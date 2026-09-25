"""The one screen worth reading first thing.

A brief is only useful if it is short and if everything on it is actionable,
so this returns four small lists rather than a dashboard: what is late, what
is due today, what you are waiting on from other people, and what changed on
disk since you last looked.

Nothing here is generated text. Every line is a row you can click through to
its source, which is the difference between a summary you trust and one you
skim past.
"""

from __future__ import annotations

from datetime import date, timedelta

from cairn import commitments
from cairn.db import stats as db_stats
from cairn.indexer import recent_files


def _bucket(items: list[dict], today: date) -> dict:
    """Five buckets, and "later" is a separate one from "undated".

    Lumping a date three months out in with the dateless ones was wrong in a
    way that showed: the screen said NO DATE above a row reading "Apr 13".
    """
    overdue, due_today, soon, later, undated = [], [], [], [], []
    horizon = today + timedelta(days=7)
    for item in items:
        raw = item.get("due")
        if not raw:
            undated.append(item)
            continue
        try:
            due = date.fromisoformat(raw)
        except ValueError:
            undated.append(item)
            continue
        if due < today:
            overdue.append(item)
        elif due == today:
            due_today.append(item)
        elif due <= horizon:
            soon.append(item)
        else:
            later.append(item)
    return {
        "overdue": overdue,
        "today": due_today,
        "soon": soon,
        "later": later,
        "undated": undated,
    }


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def build(conn, today: date | None = None, changed_days: int = 3) -> dict:
    today = today or date.today()
    mine = commitments.open_items(conn, who="me", limit=300)
    theirs = commitments.open_items(conn, who="them", limit=100)
    buckets = _bucket(mine, today)

    counts = db_stats(conn)
    changed = recent_files(conn, days=changed_days, limit=12)

    # The single line worth putting at the top. Ordered by what actually
    # needs a decision now, not by what is most numerous.
    if buckets["overdue"]:
        number = len(buckets["overdue"])
        headline = (
            "One thing is past its date."
            if number == 1
            else f"{number} things are past their dates."
        )
    elif buckets["today"]:
        number = len(buckets["today"])
        headline = "One thing is due today." if number == 1 else f"{number} things are due today."
    elif theirs:
        headline = f"Nothing due today. You are waiting on {_count(len(theirs), 'thing')}."
    elif buckets["soon"]:
        headline = f"Nothing due today. {_count(len(buckets['soon']), 'thing')} this week."
    elif counts["files"] == 0:
        headline = "Nothing indexed yet - pick a folder and Cairn will read it."
    else:
        headline = "Nothing due. Clear."

    return {
        "date": today.isoformat(),
        "headline": headline,
        "overdue": buckets["overdue"],
        "due_today": buckets["today"],
        "due_soon": buckets["soon"],
        "due_later": buckets["later"],
        "undated": buckets["undated"][:10],
        "waiting_on": theirs,
        "changed_files": changed,
        "stats": counts,
    }


def as_text(brief: dict) -> str:
    """The same brief for a terminal, because not everyone wants a browser."""
    lines = [f"  {brief['headline']}", ""]

    def block(title: str, items: list[dict], show_due: bool = True) -> None:
        if not items:
            return
        lines.append(f"{title} ({len(items)})")
        for item in items[:10]:
            due = f"  [{item['due']}]" if show_due and item.get("due") else ""
            lines.append(f"  - {item['text'][:92]}{due}")
        if len(items) > 10:
            lines.append(f"  ... and {len(items) - 10} more")
        lines.append("")

    block("OVERDUE", brief["overdue"])
    block("DUE TODAY", brief["due_today"])
    block("THIS WEEK", brief["due_soon"])
    block("LATER", brief["due_later"])
    block("WAITING ON OTHERS", brief["waiting_on"])
    block("NO DATE", brief["undated"], show_due=False)

    if brief["changed_files"]:
        lines.append(f"CHANGED RECENTLY ({len(brief['changed_files'])})")
        for item in brief["changed_files"][:6]:
            lines.append(f"  - {item['name']}")
        lines.append("")

    counts = brief["stats"]
    lines.append(
        f"{counts['files']:,} files / {counts['passages']:,} passages indexed"
        + (f"  (last swept {counts['last_index']})" if counts["last_index"] else "")
    )
    return "\n".join(lines)
