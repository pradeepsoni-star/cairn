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

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from cairn import commitments, extract
from cairn.config import Settings
from cairn.db import set_meta

# Formats where a sentence is likely to be a sentence. Pulling commitments out
# of a spreadsheet produces noise, so those are indexed for search but not
# scanned for promises.
PROSE_KINDS = frozenset({"md", "markdown", "txt", "docx", "pdf", "rtf", "rst", "epub", "html", "htm"})

MAX_COMMITMENTS_PER_FILE = 8


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


def _store_file(conn, path: Path, info, passages: list[str]) -> None:
    conn.execute("DELETE FROM chunks WHERE path = ?", (str(path),))
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
    roots = settings.folder_paths()
    if not roots:
        progress.finished = True
        progress.error = "No folders chosen yet."
        return progress

    known = {
        row["path"]: (row["mtime"], row["size"])
        for row in conn.execute("SELECT path, mtime, size FROM files")
    }
    excludes = frozenset(e.strip().lower() for e in settings.exclude if e.strip())
    max_bytes = settings.max_file_mb * 1024 * 1024
    seen: set[str] = set()

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
            if on_progress and progress.scanned % 50 == 0:
                on_progress(progress)
            continue

        try:
            text = extract.extract(path)
        except extract.Unreadable:
            progress.unreadable += 1
            continue
        except OSError:
            progress.unreadable += 1
            continue

        passages = extract.chunk(text)
        if not passages:
            progress.unreadable += 1
            continue

        _store_file(conn, path, info, passages)
        progress.passages += len(passages)
        progress.updated += 1 if previous else 0
        progress.added += 0 if previous else 1

        if settings.scan_documents_for_commitments and extract.kind_of(path) in PROSE_KINDS:
            found = commitments.find(
                text[:200_000], "document", key, limit=MAX_COMMITMENTS_PER_FILE
            )
            progress.commitments += commitments.store(conn, found)

        conn.commit()
        if on_progress and progress.scanned % 10 == 0:
            on_progress(progress)

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
