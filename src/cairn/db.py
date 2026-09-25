"""The single SQLite file behind everything.

Two things are worth knowing before changing anything here.

1. The full-text index and your own data live in the same file but never
   depend on each other. Rebuilding the index cannot lose a note or a
   commitment, because nothing in `notes` or `commitments` is derived from
   `chunks`. That separation is deliberate: reindexing is the operation a
   user is most likely to run when something looks wrong, and it must be
   the safest one available.

2. FTS5 is used through a plain contentless-style virtual table rather than
   an external-content one. External content is faster to store but couples
   the index to a rowid in another table, and a half-finished index sweep
   then leaves the two out of step in a way that is hard to detect. Disk is
   cheap; a search that silently returns nothing is not.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from cairn.config import db_path

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path       TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    folder     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    size       INTEGER NOT NULL,
    mtime      REAL NOT NULL,
    passages   INTEGER NOT NULL DEFAULT 0,
    indexed_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS files_mtime ON files(mtime DESC);
CREATE INDEX IF NOT EXISTS files_kind  ON files(kind);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
    path UNINDEXED,
    ord  UNINDEXED,
    body,
    tokenize = 'porter unicode61'
);

CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    body       TEXT NOT NULL,
    created_at REAL NOT NULL,
    pinned     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS notes_created ON notes(created_at DESC);

CREATE TABLE IF NOT EXISTS commitments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    who         TEXT NOT NULL DEFAULT 'me',
    due         TEXT,
    source      TEXT NOT NULL,
    source_ref  TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  REAL NOT NULL,
    done_at     REAL,
    fingerprint TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS commitments_status ON commitments(status, due);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the database, creating it on first use.

    WAL keeps a long indexing pass from blocking a search, which is the whole
    point of indexing in the background. The busy timeout is generous because
    an index sweep over tens of thousands of files does hold the write lock
    in bursts, and a search that waits a moment beats one that raises.
    """
    target = path or db_path()
    conn = sqlite3.connect(str(target), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn


@contextmanager
def session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def stats(conn: sqlite3.Connection) -> dict:
    files = conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
    passages = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
    by_kind = {
        row["kind"]: row["n"]
        for row in conn.execute(
            "SELECT kind, COUNT(*) AS n FROM files GROUP BY kind ORDER BY n DESC"
        )
    }
    open_items = conn.execute(
        "SELECT COUNT(*) AS n FROM commitments WHERE status = 'open'"
    ).fetchone()["n"]
    notes = conn.execute("SELECT COUNT(*) AS n FROM notes").fetchone()["n"]
    return {
        "files": files,
        "passages": passages,
        "by_kind": by_kind,
        "open_commitments": open_items,
        "notes": notes,
        "last_index": get_meta(conn, "last_index", ""),
    }
