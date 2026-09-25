"""Folding email into the same index as everything else.

A message becomes a row like any file, under a `gmail:<id>` path, so one
search box covers your disk and your mail and one commitment radar reads
both. That uniformity is the point: a separate "email view" would mean
remembering which half of your working life a thing was in, which is the
problem this tool exists to remove.

Only the fields a person searches by are stored - sender, subject, date and
the body text. Attachments, headers and routing information are not.
"""

from __future__ import annotations

import time

from cairn import commitments
from cairn.extract import chunk, sanitise
from cairn.permissions import Permission, Permissions


def sync(conn, limit: int = 200, query: str = "newer_than:90d") -> dict:
    """Read recent mail into the index and lift commitments out of it."""
    Permissions.load().require(Permission.GMAIL_READ)
    from cairn.connectors import google

    messages = google.recent_messages(limit=limit, query=query)
    added = 0
    found = 0
    for message in messages:
        path = f"gmail:{message['id']}"
        text = sanitise(
            f"From: {message['sender']}\nTo: {message['to']}\n"
            f"Subject: {message['subject']}\nDate: {message['date']}\n\n{message['body']}"
        )
        if not text.strip():
            continue
        pieces = chunk(text)
        conn.execute("DELETE FROM chunks WHERE path = ?", (path,))
        conn.executemany(
            "INSERT INTO chunks(path, ord, body) VALUES (?, ?, ?)",
            [(path, i, piece) for i, piece in enumerate(pieces)],
        )
        conn.execute(
            "INSERT INTO files(path, name, folder, kind, size, mtime, passages, indexed_at) "
            "VALUES (?, ?, 'Email', 'email', ?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET name=excluded.name, mtime=excluded.mtime, "
            "passages=excluded.passages, indexed_at=excluded.indexed_at",
            (
                path,
                message["subject"] or "(no subject)",
                len(text),
                time.time(),
                len(pieces),
                time.time(),
            ),
        )
        added += 1

        # Only YOUR promises are lifted from mail you sent; from mail you
        # received, only what the sender committed to. Treating an incoming
        # marketing email's "we will be in touch" as your own to-do is how a
        # commitment list becomes noise.
        found += commitments.store(
            conn, commitments.find(message["body"][:20000], "email", path, limit=5)
        )
    conn.commit()
    return {"messages": added, "commitments": found}
