"""Starting over.

Every piece of software eventually gets into a state its owner cannot explain
and does not want. Without a way back, the only remedy is knowing that the
answer is a hidden folder under AppData - which nobody outside this file
knows, and no ordinary person will ever find.

This module found its own reason to exist: a leftover `setup_complete: true`
from testing meant a freshly downloaded copy skipped its welcome screen, and
working out why took a terminal and a JSON file. That is precisely the wall a
person with no terminal hits and does not get past.

Two rules, because this is the one destructive thing Cairn can do to itself.

1. **It always backs up first.** The database is copied through SQLite's own
   backup API rather than by copying the file, so it works while Cairn is
   running and cannot capture a half-written page. Settings and permissions
   are copied beside it. Nothing is removed until the copy exists.

2. **There are two different intentions and they are separate.** "Let me
   choose my settings again" and "forget everything you know about me" are
   not the same wish, and a product that does the second when asked for the
   first has destroyed work nobody asked it to destroy.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

from cairn.config import Settings, data_dir, settings_path
from cairn.permissions import Permissions, record


def backup_dir(stamp: str | None = None) -> Path:
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    return data_dir() / "backups" / stamp


def _copy_everything(conn) -> Path:
    """Snapshot the database and the two settings files. Returns the folder."""
    target_dir = backup_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    # SQLite's own backup, not a file copy: safe while the database is open,
    # and it cannot catch a page mid-write.
    target = sqlite3.connect(str(target_dir / "cairn.db"))
    try:
        with target:
            conn.backup(target)
    finally:
        target.close()

    for path in (settings_path(), Permissions._path()):
        if path.exists():
            shutil.copy2(path, target_dir / path.name)
    return target_dir


def start_over(conn, erase_everything: bool = False) -> dict:
    """Reset Cairn. Returns what happened and where the backup went.

    `erase_everything=False` is the common case: run setup again, keep your
    notes, your commitments and your index. `True` is the nuclear option, and
    even that leaves a restorable copy behind.
    """
    saved_to = _copy_everything(conn)

    if not erase_everything:
        settings = Settings.load()
        settings.setup_complete = False
        settings.save()
        record("reset", "setup reopened", f"backup at {saved_to}")
        return {
            "scope": "setup",
            "backup": str(saved_to),
            "message": "Setup will run again. Nothing you had was removed.",
        }

    counts = {
        name: conn.execute(f"SELECT COUNT(*) AS n FROM {name}").fetchone()["n"]
        for name in ("files", "notes", "commitments")
    }
    for table in ("chunks", "files", "notes", "commitments", "meta"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()

    # Written, not deleted: an absent permissions file and a file granting
    # nothing mean the same thing to `load()`, and writing it makes the reset
    # visible to anyone inspecting the folder afterwards.
    Permissions().save()
    Settings().save()

    record(
        "reset",
        "ERASED",
        f"{counts['files']} indexed item(s), {counts['notes']} note(s), "
        f"{counts['commitments']} commitment(s); backup at {saved_to}",
    )
    return {
        "scope": "all",
        "backup": str(saved_to),
        "removed": counts,
        "message": "Everything was removed. A restorable copy is in the backup folder.",
    }


def list_backups() -> list[dict]:
    """Backups, newest first, so a reset is visibly undoable."""
    root = data_dir() / "backups"
    if not root.is_dir():
        return []
    found = []
    for entry in sorted(root.iterdir(), reverse=True):
        database = entry / "cairn.db"
        if entry.is_dir() and database.exists():
            found.append(
                {
                    "name": entry.name,
                    "path": str(entry),
                    "size_mb": round(database.stat().st_size / 1048576, 1),
                    "when": time.strftime(
                        "%Y-%m-%d %H:%M", time.localtime(database.stat().st_mtime)
                    ),
                }
            )
    return found
