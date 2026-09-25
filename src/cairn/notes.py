"""Quick capture.

A note is typed, saved, scanned for commitments and made searchable in one
step. The scan happens on the way in rather than on a schedule, because the
moment you write "call the accountant on Tuesday" is the moment you want it
to have become a thing with a date on it.

Notes are stored as rows and mirrored into the search index under a
`note:<id>` path, so one search box covers both your files and your own
jottings. The mirror is kept in step by every write going through here.
"""

from __future__ import annotations

import time

from cairn import commitments


def _index_note(conn, note_id: int, body: str) -> None:
    from cairn.extract import chunk

    path = f"note:{note_id}"
    conn.execute("DELETE FROM chunks WHERE path = ?", (path,))
    conn.executemany(
        "INSERT INTO chunks(path, ord, body) VALUES (?, ?, ?)",
        [(path, i, piece) for i, piece in enumerate(chunk(body))],
    )
    first_line = (body.strip().splitlines() or [""])[0][:80] or "note"
    conn.execute(
        "INSERT INTO files(path, name, folder, kind, size, mtime, passages, indexed_at) "
        "VALUES (?, ?, 'Notes', 'note', ?, ?, 1, ?) "
        "ON CONFLICT(path) DO UPDATE SET name=excluded.name, size=excluded.size, "
        "mtime=excluded.mtime, indexed_at=excluded.indexed_at",
        (path, first_line, len(body), time.time(), time.time()),
    )


def add(conn, body: str) -> dict:
    """Save a note. Returns the note and any commitments it produced."""
    body = body.strip()
    if not body:
        raise ValueError("An empty note is not a note.")

    # A note whose text is identical to one already saved is a double-click or
    # a double paste, not a second meeting. Saving it again would duplicate
    # every commitment in it, because the new note has a new id and so a new
    # fingerprint - which is exactly right across two FILES and exactly wrong
    # across two copies of the same note.
    existing = conn.execute(
        "SELECT id FROM notes WHERE body = ? ORDER BY created_at DESC LIMIT 1", (body,)
    ).fetchone()
    if existing:
        return {"id": existing["id"], "body": body, "duplicate": True,
                "commitments_found": 0, "commitments": []}

    cursor = conn.execute(
        "INSERT INTO notes(body, created_at) VALUES (?, ?)", (body, time.time())
    )
    note_id = int(cursor.lastrowid)
    _index_note(conn, note_id, body)
    found = commitments.find(body, "note", f"note:{note_id}")
    added = commitments.store(conn, found)
    conn.commit()
    return {
        "id": note_id,
        "body": body,
        "duplicate": False,
        "commitments_found": added,
        "commitments": [
            {"text": c.text, "due": c.due.isoformat() if c.due else None, "who": c.who}
            for c in found
        ],
    }


def recent(conn, limit: int = 50) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT id, body, created_at, pinned FROM notes "
            "ORDER BY pinned DESC, created_at DESC LIMIT ?",
            (limit,),
        )
    ]


def delete(conn, note_id: int) -> None:
    conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    conn.execute("DELETE FROM chunks WHERE path = ?", (f"note:{note_id}",))
    conn.execute("DELETE FROM files WHERE path = ?", (f"note:{note_id}",))
    # Commitments keep their own copy of the text on purpose. Deleting the
    # note you captured a promise in does not cancel the promise.
    conn.commit()


def pin(conn, note_id: int, pinned: bool = True) -> None:
    conn.execute("UPDATE notes SET pinned = ? WHERE id = ?", (1 if pinned else 0, note_id))
    conn.commit()
