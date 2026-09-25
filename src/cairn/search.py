"""Searching what has been indexed.

The input is whatever a person typed, which means it will eventually contain
a quote mark, a colon, a stray parenthesis, or the word AND. FTS5 treats all
of those as syntax and raises on the malformed ones, so nothing typed is
passed through as a query. Every term is quoted and the query is rebuilt -
the user gets a result instead of an error, always.

One SQLite constraint shapes this file: once a second table is in scope,
FTS5 rejects MATCH, snippet() and bm25() against the virtual table under
either its alias or its bare name. So the match runs against `chunks` alone
and the file metadata is fetched in a second query. It looks redundant. It
is the only thing that works.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Words that would otherwise be read as FTS5 operators.
_OPERATORS = {"and", "or", "not", "near"}
_TERM = re.compile(r'"[^"]+"|\S+')

# Dropped only when a whole question is being turned into a query. Requiring
# every word of "what did we agree on the delivery terms" to appear is why
# natural-language questions used to find nothing at all.
_STOPWORDS = frozenset(
    """a an the of in on at to for from by with and or is are was were be been being
    do does did what which who whom whose when where why how i me my we our you your
    it its this that these those there here can could shall should will would may
    might must about into over under again then than as if so not no yes please
    tell show find get give any some all""".split()
)


@dataclass
class Hit:
    path: str
    name: str
    folder: str
    kind: str
    mtime: float
    snippet: str
    score: float
    passages: int


def build_query(text: str, join: str = "AND", drop_stopwords: bool = False) -> str:
    """Turn typed text into an FTS5 expression that cannot be malformed.

    A quoted "exact phrase" stays a phrase. A trailing * stays a prefix
    search, because people expect `invoic*` to work. Everything else becomes
    a quoted term, and the terms are ANDed - matching every word is what
    people mean when they type several.
    """
    terms: list[str] = []
    for raw in _TERM.findall(text or ""):
        if raw.startswith('"') and raw.endswith('"') and len(raw) > 2:
            inner = raw[1:-1].replace('"', "")
            if inner.strip():
                terms.append(f'"{inner.strip()}"')
            continue
        prefix = raw.endswith("*")
        cleaned = re.sub(r"[^\w\-À-ɏ]+", " ", raw.rstrip("*"), flags=re.UNICODE).strip()
        if not cleaned:
            continue
        for word in cleaned.split():
            if len(word) < 2 and not word.isdigit():
                continue
            if drop_stopwords and word.lower() in _STOPWORDS:
                continue
            if word.lower() in _OPERATORS:
                terms.append(f'"{word}"')
            elif prefix:
                terms.append(f'"{word}"*')
            else:
                terms.append(f'"{word}"')
    return f" {join} ".join(terms)


def _match(conn, query: str, limit: int) -> list:
    try:
        return conn.execute(
            "SELECT path, "
            "       snippet(chunks, 2, '<mark>', '</mark>', ' ... ', 18) AS snip, "
            "       bm25(chunks) AS score "
            "FROM chunks WHERE chunks MATCH ? ORDER BY score LIMIT ?",
            (query, limit),
        ).fetchall()
    except Exception:
        # A query that still offends FTS5 must degrade to no results, never
        # to a stack trace in the user's face.
        return []


def search(conn, text: str, limit: int = 30, kind: str = "") -> list[Hit]:
    """Best passage per file, best files first."""
    query = build_query(text)
    if not query:
        return []

    # Over-fetch: several passages of one file will often outrank a single
    # passage of another, and we want variety in the file list.
    rows = _match(conn, query, limit * 8)
    if not rows and " AND " in query:
        # Every word being required is right when someone types two words and
        # wrong when they type a sentence. Rather than guess which they meant,
        # try the strict reading first and relax only when it finds nothing -
        # so a precise search stays precise and a wordy one still works.
        rows = _match(conn, build_query(text, join="OR", drop_stopwords=True), limit * 8)
    if not rows:
        return []

    best: dict[str, tuple[float, str]] = {}
    for row in rows:
        current = best.get(row["path"])
        if current is None or row["score"] < current[0]:
            best[row["path"]] = (row["score"], row["snip"])

    paths = list(best)[: limit * 2]
    placeholders = ",".join("?" for _ in paths)
    meta = {
        row["path"]: row
        for row in conn.execute(
            f"SELECT path, name, folder, kind, mtime, passages FROM files WHERE path IN ({placeholders})",
            paths,
        )
    }

    hits: list[Hit] = []
    for path in paths:
        info = meta.get(path)
        if info is None:
            continue  # indexed passage whose file row is gone; skip quietly
        if kind and info["kind"] != kind:
            continue
        score, snip = best[path]
        hits.append(
            Hit(
                path=path,
                name=info["name"],
                folder=info["folder"],
                kind=info["kind"],
                mtime=info["mtime"],
                snippet=snip,
                score=score,
                passages=info["passages"],
            )
        )
    hits.sort(key=lambda h: h.score)
    return hits[:limit]


def passages_for(conn, path: str, text: str = "", limit: int = 8) -> list[str]:
    """The matching passages inside one file - the 'show me where' view."""
    query = build_query(text)
    if query:
        try:
            rows = conn.execute(
                "SELECT body FROM chunks WHERE chunks MATCH ? AND path = ? "
                "ORDER BY bm25(chunks) LIMIT ?",
                (query, path, limit),
            ).fetchall()
            if rows:
                return [r["body"] for r in rows]
        except Exception:
            pass
    rows = conn.execute(
        "SELECT body FROM chunks WHERE path = ? ORDER BY ord LIMIT ?", (path, limit)
    ).fetchall()
    return [r["body"] for r in rows]


def context_for_question(conn, question: str, budget_chars: int = 6000) -> list[dict]:
    """Passages to hand a model when answering over the user's own documents.

    Capped by characters rather than by count so one enormous passage cannot
    crowd out five useful ones, and drawn from several files so the answer is
    not a summary of whichever document happened to rank first.
    """
    # A question is mostly filler. "what did we agree on the delivery terms"
    # shares only two useful words with the document that answers it, so the
    # stopwords go, and if requiring the rest finds nothing they are ORed -
    # ranking then decides, which is what you want when answering.
    def run(expression: str) -> list:
        if not expression:
            return []
        try:
            return conn.execute(
                "SELECT path, body, bm25(chunks) AS score FROM chunks "
                "WHERE chunks MATCH ? ORDER BY score LIMIT 40",
                (expression,),
            ).fetchall()
        except Exception:
            return []

    rows = run(build_query(question, drop_stopwords=True))
    if not rows:
        rows = run(build_query(question, join="OR", drop_stopwords=True))
    if not rows:
        return []

    picked: list[dict] = []
    used = 0
    per_file: dict[str, int] = {}
    for row in rows:
        if per_file.get(row["path"], 0) >= 2:
            continue
        body = row["body"]
        if used + len(body) > budget_chars:
            continue
        per_file[row["path"]] = per_file.get(row["path"], 0) + 1
        picked.append({"path": row["path"], "body": body})
        used += len(body)
        if used >= budget_chars * 0.9:
            break
    return picked
