"""Finding the promises buried in your own writing.

Most things people forget were never on a to-do list. They were a sentence in
the middle of a meeting note - "I'll send the revised figures on Thursday" -
written down and then scrolled past. Cairn reads the documents it has
already indexed, and your notes, and pulls those sentences out.

Three design choices, each the result of the obvious approach failing:

* Rules, not a model. A model asked to "find the commitments" invents them,
  and a to-do list you did not write is a list you stop trusting after a
  week. Every item Cairn shows you can be traced to the exact sentence it
  came from, which is why `source_ref` is not optional.

* Cue words need a word boundary on BOTH sides. Without the trailing one,
  "ill" matches inside "will", "skill" and "still", and a document about
  skills becomes forty commitments.

* Clauses are split at every cue, not at sentence ends. "I'll call the bank
  and I need to file the return by Friday" is two commitments with different
  owners of attention, and only the second has a date.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date

from cairn.dates import parse_due

# The contracted form ALWAYS needs its apostrophe. Allowing a bare "ll" after
# a word looks harmless and is not: every capitalised word ending in a double
# L then matches - Call, Fill, Bill, Tell, Full - and on a real machine that
# turned a strategy report into forty phantom commitments. This is the same
# trap as "ill" inside "will", one level further in.
_LL = r"(?:'|’)\s*ll"

# Something the writer took on themselves. "should" and "must" are absent on
# purpose: "we should consider the northern route" is a thought, not a promise,
# and documents are full of them.
_MINE = rf"(?:i|we)\s*(?:{_LL}|\s*(?:m|am|are)\s+going to|\s*will|\s*need to|\s*have to|\s*shall|\s*intend to|\s*plan to)"
# Something asked of the writer.
_ASKED = r"(?:can you|could you|would you|please|remind me to|don'?t forget to|make sure (?:you |to )?)"
# Something someone else took on - the waiting-on list.
_THEIRS = rf"(?:he|she|they|[A-Z][a-z]+)\s*(?:{_LL}|\s*will|\s*is going to|\s*are going to|\s*agreed to|\s*promised to)"

# Explicit markers people already use in documents.
_MARKER = r"(?:^|\n)\s*(?:[-*]\s*\[\s\]|todo\s*:|to-do\s*:|action\s*:|action item\s*:|next step\s*:|next steps\s*:|follow[- ]?up\s*:|ar\s*:)"

CUE = re.compile(rf"\b(?:{_MINE}|{_ASKED})\b", re.IGNORECASE)
CUE_THEIRS = re.compile(rf"\b{_THEIRS}\b")
MARKER = re.compile(_MARKER, re.IGNORECASE)

# Anything already finished is not a commitment. "I'll" cannot be past tense,
# but "I need to have sent" and "I will have finished" both are, and a note
# that says "as discussed, I sent the file" must not become a to-do.
_ALREADY_DONE = re.compile(
    r"\b(?:already (?:sent|done|shared|filed|paid|called)|have (?:sent|done|shared|filed|paid)"
    r"|has been (?:sent|done|shared|filed|paid)|was (?:sent|done|shared|filed|paid))\b",
    re.IGNORECASE,
)

# A question about a commitment is not a commitment.
_HYPOTHETICAL = re.compile(
    r"\b(?:if|unless|whether|in case|would have|might|maybe|perhaps|hypothetically)\b",
    re.IGNORECASE,
)

# A promise NOT to do something is not a thing to do.
_NEGATED = re.compile(r"\b(?:will not|won'?t|will never|never going to)\b|’ll never\b", re.IGNORECASE)

# Somebody else's words, quoted inside your document. Reports that summarise
# an email thread are full of these, and every one became a to-do addressed
# to nobody. Any double quote inside the clause is enough of a signal - a
# genuine promise of your own rarely contains one.
_QUOTED = re.compile(r'["“”]')

# A template rather than a commitment: "We'll dispatch a sample kit within
# [X] business days" is boilerplate waiting to be filled in.
_PLACEHOLDER = re.compile(r"\[[A-Za-z0-9 _-]{1,20}\]|\{\{?[a-z_]+\}?\}|<[a-z_]+>", re.IGNORECASE)

# Lines that are structure rather than sentences. Markdown headings, table
# rows and leftover markup all read as prose to a regex and as gibberish to a
# person looking at their to-do list.
_NOT_PROSE = re.compile(r"^#{1,6}\s|^\s*\|.*\|\s*$|</?[a-z][^>]*>|&[a-z]{2,8};|^\s*\d+\s*\|")

MIN_WORDS = 3
MAX_WORDS = 45


@dataclass(frozen=True)
class Commitment:
    text: str
    who: str  # "me" - something you owe; "them" - something you are waiting for
    due: date | None
    source: str  # "note", "document"
    source_ref: str  # note id, or the file path the sentence came from

    @property
    def fingerprint(self) -> str:
        """Stable across reindexes so the same sentence is never listed twice.

        Deliberately includes the source: the same promise made in two
        different documents is two things to check, not one.
        """
        seed = f"{self.source_ref}|{re.sub(r'[^a-z0-9]+', ' ', self.text.lower()).strip()}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _tidy(clause: str) -> str:
    clause = re.sub(r"\s+", " ", clause).strip(" \t-*•.,;:")
    # A clause that was cut at the NEXT cue keeps the conjunction that joined
    # them - "I'll send the form on Tuesday and" - and one that starts after a
    # cut keeps the one that began it. Both ends are trimmed.
    clause = re.sub(r"^(?:and|but|so|then|also|plus)\s+", "", clause, flags=re.IGNORECASE)
    clause = re.sub(r"\s+(?:and|but|so|then|also|plus|,)\s*$", "", clause, flags=re.IGNORECASE)
    return clause.strip(" \t-*•.,;:")


def _usable(clause: str) -> bool:
    words = clause.split()
    if not (MIN_WORDS <= len(words) <= MAX_WORDS):
        return False
    if clause.endswith("?"):
        return False
    if _ALREADY_DONE.search(clause) or _HYPOTHETICAL.search(clause):
        return False
    if _NOT_PROSE.search(clause) or _NEGATED.search(clause):
        return False
    if _QUOTED.search(clause) or _PLACEHOLDER.search(clause):
        return False
    # A clause of mostly punctuation or numbers came out of a spreadsheet row.
    letters = sum(c.isalpha() for c in clause)
    return letters >= len(clause) * 0.5


def _split_at_cues(line: str) -> list[str]:
    """Break a line into one clause per cue, each starting at its cue."""
    positions = [m.start() for m in CUE.finditer(line)]
    positions += [m.start() for m in CUE_THEIRS.finditer(line)]
    if not positions:
        return []
    positions = sorted(set(positions))
    bounds = positions + [len(line)]
    return [line[bounds[i] : bounds[i + 1]] for i in range(len(positions))]


def find(
    text: str,
    source: str,
    source_ref: str,
    today: date | None = None,
    limit: int = 40,
) -> list[Commitment]:
    """Every commitment in a piece of text, in the order they were written."""
    if not text:
        return []
    found: list[Commitment] = []
    seen: set[str] = set()

    # Explicit markers first: a line the writer already flagged as an action
    # is taken at face value, cue words or not.
    for match in MARKER.finditer(text):
        tail = text[match.end() :].split("\n", 1)[0]
        clause = _tidy(tail)
        if _usable(clause):
            item = Commitment(clause, "me", parse_due(clause, today), source, source_ref)
            if item.fingerprint not in seen:
                seen.add(item.fingerprint)
                found.append(item)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if len(line) < 12 or len(line) > 1500:
            continue
        # Structure is a property of the LINE, not of the clause. A clause
        # that begins at its cue has already discarded the "##" or the leading
        # "|" by the time anything looks at it, so the check has to happen
        # here, before the line is taken apart.
        if _NOT_PROSE.search(line):
            continue
        # Work sentence by sentence, not line by line. A condition attached to
        # a promise usually sits BEFORE the cue - "If they agree, I'll send
        # the revised terms" - so a clause that starts at the cue has already
        # thrown the condition away by the time it is examined.
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            if _HYPOTHETICAL.search(sentence) or _ALREADY_DONE.search(sentence):
                continue
            for clause in _split_at_cues(sentence):
                tidy = _tidy(clause)
                if not _usable(tidy):
                    continue
                who = "them" if CUE_THEIRS.match(clause.strip()) else "me"
                item = Commitment(tidy, who, parse_due(tidy, today), source, source_ref)
                if item.fingerprint in seen:
                    continue
                seen.add(item.fingerprint)
                found.append(item)
                if len(found) >= limit:
                    return found
    return found


# ------------------------------------------------------------------- storage


def store(conn, items: list[Commitment]) -> int:
    """Save new commitments. Returns how many were genuinely new.

    An existing row is left exactly as it is: if you have already ticked
    something off, reindexing the document it came from must not resurrect it.
    """
    import time

    added = 0
    for item in items:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO commitments "
            "(text, who, due, source, source_ref, status, created_at, fingerprint) "
            "VALUES (?, ?, ?, ?, ?, 'open', ?, ?)",
            (
                item.text,
                item.who,
                item.due.isoformat() if item.due else None,
                item.source,
                item.source_ref,
                time.time(),
                item.fingerprint,
            ),
        )
        added += cursor.rowcount or 0
    return added


def open_items(conn, who: str = "", limit: int = 200) -> list[dict]:
    """Open commitments, soonest first, undated last."""
    query = (
        "SELECT * FROM commitments WHERE status = 'open' "
        + ("AND who = ? " if who else "")
        + "ORDER BY (due IS NULL), due ASC, created_at DESC LIMIT ?"
    )
    params = (who, limit) if who else (limit,)
    return [dict(row) for row in conn.execute(query, params)]


def complete(conn, item_id: int, done: bool = True) -> None:
    import time

    conn.execute(
        "UPDATE commitments SET status = ?, done_at = ? WHERE id = ?",
        ("done" if done else "open", time.time() if done else None, item_id),
    )


def dismiss(conn, item_id: int) -> None:
    """Not a real commitment. Kept as a row so re-scanning cannot bring it back."""
    conn.execute("UPDATE commitments SET status = 'dismissed' WHERE id = ?", (item_id,))
