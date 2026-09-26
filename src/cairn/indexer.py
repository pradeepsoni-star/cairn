"""Building and keeping the index up to date.

The sweep is incremental and interruptible. Interruptible matters: the first
run over a real machine can take a while, people close laptops, and an index
that is only valid if the sweep finished is an index that is rarely valid.
Every file is committed as it is done, so stopping halfway leaves a smaller
index rather than a broken one.

Deletions are handled by comparing the set of paths on disk with the set in
the database at the end of a full sweep - but only for the roots that were
actually swept. Getting that wrong is how an indexer silently empties itself
when someone unplugs an external drive.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from cairn import commitments, extract
from cairn.config import Settings
from cairn.db import set_meta
from cairn.permissions import Permission, Permissions, record

# Formats where a sentence is likely to be a sentence. Pulling commitments out
# of a spreadsheet produces noise, so those are indexed for search but not
# scanned for promises.
PROSE_KINDS = frozenset({"md", "markdown", "txt", "docx", "pdf", "rtf", "rst", "epub", "html", "htm"})

MAX_COMMITMENTS_PER_FILE = 8

# Small on purpose. The work is IO and C-parser bound rather than pure Python,
# so a handful of threads captures most of the gain; going wider mostly makes
# a laptop's fan loud and starves whatever else the person is doing.
WORKERS = min(8, (os.cpu_count() or 4))
# How many files are read before the results are written. Bounds memory on a
# huge folder, and bounds how long Stop takes to be felt.
BATCH = 64


@dataclass
class Progress:
    scanned: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    unreadable: int = 0
    passages: int = 0
    commitments: int = 0
    current: str = ""
    started: float = field(default_factory=time.time)
    finished: bool = False
    error: str = ""

    @property
    def elapsed(self) -> float:
        return time.time() - self.started

    def as_dict(self) -> dict:
        data = {
            k: v for k, v in self.__dict__.items() if k not in {"started"}
        }
        data["elapsed"] = round(self.elapsed, 1)
        return data


def _forget_passages(conn, paths: list[str]) -> None:
    """Remove the passages of these files, in ONE pass.

    FTS5 has no index on `path` - it is an UNINDEXED column, which means
    exactly what it says - so every `DELETE ... WHERE path = ?` is a full scan
    of the whole table. Measured: 7 ms at 2,000 passages, 75 ms at 20,000,
    and 1,285 ms at 120,000. Doing one per file made the first scan quadratic
    and turned 5,100 files into eighteen minutes.

    One DELETE for a whole batch is still one scan, but one scan for sixty-four
    files instead of sixty-four scans.
    """
    if not paths:
        return
    placeholders = ",".join("?" for _ in paths)
    conn.execute(f"DELETE FROM chunks WHERE path IN ({placeholders})", paths)


def _store_file(conn, path: Path, info, passages: list[str]) -> None:
    conn.executemany(
        "INSERT INTO chunks(path, ord, body) VALUES (?, ?, ?)",
        [(str(path), i, body) for i, body in enumerate(passages)],
    )
    conn.execute(
        "INSERT INTO files(path, name, folder, kind, size, mtime, passages, indexed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(path) DO UPDATE SET "
        "name=excluded.name, folder=excluded.folder, kind=excluded.kind, "
        "size=excluded.size, mtime=excluded.mtime, passages=excluded.passages, "
        "indexed_at=excluded.indexed_at",
        (
            str(path),
            path.name,
            str(path.parent),
            extract.kind_of(path),
            info.st_size,
            info.st_mtime,
            len(passages),
            time.time(),
        ),
    )


def reindex(
    conn,
    settings: Settings | None = None,
    on_progress: Callable[[Progress], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    full: bool = False,
) -> Progress:
    """Bring the index in line with what is on disk.

    `full` re-reads every file even if its timestamp says it has not changed -
    the repair option, for when a reader has been fixed or a format newly
    supported.
    """
    settings = settings or Settings.load()
    progress = Progress()

    # Checked here, at the moment files are about to be opened, rather than
    # when indexing was configured. Permission revoked a minute ago stops the
    # sweep that starts now.
    permissions = Permissions.load()
    if not permissions.allowed(Permission.READ_FOLDERS):
        progress.finished = True
        progress.error = (
            "Cairn has not been allowed to read your folders. Grant it under "
            "Permissions and this will work."
        )
        return progress

    roots = settings.folder_paths()
    if not roots:
        progress.finished = True
        progress.error = "No folders chosen yet."
        return progress
    record(Permission.READ_FOLDERS, "scan started", ", ".join(str(r) for r in roots))

    known = {
        row["path"]: (row["mtime"], row["size"])
        for row in conn.execute("SELECT path, mtime, size FROM files")
    }
    excludes = frozenset(e.strip().lower() for e in settings.exclude if e.strip())
    max_bytes = settings.max_file_mb * 1024 * 1024
    seen: set[str] = set()

    def prepare(path: Path, info) -> dict | None:
        """Read and chunk one file. Runs on a worker thread.

        Touches no database and no shared state - everything it learns comes
        back in the returned dict and is applied by the one thread that owns
        the connection. SQLite has a single writer, and a worker pool that
        writes is a worker pool that corrupts.
        """
        try:
            text = extract.extract(path)
        except (extract.Unreadable, OSError):
            return None
        passages = extract.chunk(text)
        if not passages:
            return None
        promises = []
        if (
            settings.scan_documents_for_commitments
            and settings.has("commitments")
            and extract.kind_of(path) in PROSE_KINDS
        ):
            promises = commitments.find(
                text[:200_000], "document", str(path), limit=MAX_COMMITMENTS_PER_FILE
            )
        return {"path": path, "info": info, "passages": passages, "promises": promises}

    def apply(prepared: dict, previous) -> None:
        """Write one prepared file. Only ever called on the calling thread."""
        _store_file(conn, prepared["path"], prepared["info"], prepared["passages"])
        _ = previous
        progress.passages += len(prepared["passages"])
        if previous:
            progress.updated += 1
        else:
            progress.added += 1
        if prepared["promises"]:
            progress.commitments += commitments.store(conn, prepared["promises"])

    # Reading and chunking is the slow part and every file is independent, so
    # it is done on a small pool. Measured on 5,100 files this is where all
    # the time went - the writes themselves are trivial by comparison.
    #
    # Threads rather than processes: most of the cost is inside the C parsers
    # (pypdf, openpyxl) and in file IO, both of which release the GIL, while
    # processes would add pickling, startup cost, and a PyInstaller problem
    # for the packaged build.
    #
    # Work goes through in small batches rather than all at once so that
    # memory stays bounded on a folder with 50,000 files in it, and so that
    # Stop still takes effect within a second or two.
    batch: list[tuple[Path, object, object]] = []

    def drain() -> None:
        if not batch:
            return
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            results = list(pool.map(lambda item: prepare(item[0], item[1]), batch))
        # Only files we have seen before have passages to clear, and on a
        # first scan that is none of them - which is what removes the cost
        # from the case where it hurt most.
        stale = [
            str(prepared["path"])
            for (_p, _i, previous), prepared in zip(batch, results, strict=True)
            if prepared is not None and previous
        ]
        _forget_passages(conn, stale)

        for (_path, _info, previous), prepared in zip(batch, results, strict=True):
            if prepared is None:
                progress.unreadable += 1
                continue
            apply(prepared, previous)
        conn.commit()
        batch.clear()
        if on_progress:
            on_progress(progress)

    for path, info in extract.walk(roots, max_bytes, excludes):
        if should_stop and should_stop():
            break
        key = str(path)
        seen.add(key)
        progress.scanned += 1
        progress.current = path.name

        previous = known.get(key)
        if not full and previous and abs(previous[0] - info.st_mtime) < 1 and previous[1] == info.st_size:
            progress.unchanged += 1
            if on_progress and progress.scanned % 200 == 0:
                on_progress(progress)
            continue

        batch.append((path, info, previous))
        if len(batch) >= BATCH:
            drain()

    drain()

    # Only prune when the sweep actually completed. A cancelled sweep has not
    # seen the whole disk, and deleting everything it missed would be a
    # spectacular way to lose an index.
    stopped_early = bool(should_stop and should_stop())
    if not stopped_early:
        root_strings = [str(r) for r in roots]
        for key in known:
            if key in seen:
                continue
            if not any(key.startswith(root) for root in root_strings):
                continue  # belongs to a root not swept this time
            if Path(key).exists():
                continue  # unreadable now, but still there: keep what we have
            conn.execute("DELETE FROM chunks WHERE path = ?", (key,))
            conn.execute("DELETE FROM files WHERE path = ?", (key,))
            progress.removed += 1
        set_meta(conn, "last_index", time.strftime("%Y-%m-%d %H:%M"))
    record(
        Permission.READ_FOLDERS,
        "scan finished" if not stopped_early else "scan stopped",
        f"{progress.scanned} files read, {progress.added + progress.updated} indexed",
    )

    conn.commit()
    progress.finished = True
    progress.current = ""
    if on_progress:
        on_progress(progress)
    return progress


def recent_files(conn, days: int = 3, limit: int = 25) -> list[dict]:
    """What has changed lately - the 'where was I' question, answered."""
    cutoff = time.time() - days * 86400
    return [
        dict(row)
        for row in conn.execute(
            "SELECT path, name, folder, kind, mtime FROM files "
            "WHERE mtime > ? ORDER BY mtime DESC LIMIT ?",
            (cutoff, limit),
        )
    ]
