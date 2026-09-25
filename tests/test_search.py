"""Search.

The query builder gets most of the attention because it is the part exposed
directly to whatever a person types, and FTS5 raises on syntax it dislikes.
A search box that can be made to throw is a search box that will be made to
throw, usually by someone pasting a filename with a quote in it.
"""

import pytest

from cairn.search import build_query, search


def test_ordinary_words_are_anded():
    assert build_query("invoice march") == '"invoice" AND "march"'


def test_a_quoted_phrase_stays_a_phrase():
    assert build_query('"packing list" urgent') == '"packing list" AND "urgent"'


def test_a_trailing_star_stays_a_prefix_search():
    assert build_query("invoic*") == '"invoic"*'


@pytest.mark.parametrize(
    "typed",
    ['broken " quote', "trailing (", "NOT AND OR", "a:b:c", "*", '""', "-- drop", "^&$#@!"],
)
def test_no_input_can_produce_a_malformed_query(conn, typed):
    """Whatever is typed, the search returns results or nothing - never an error."""
    assert search(conn, typed) == []


def test_operator_words_are_neutralised():
    """Typing 'cats and dogs' means the words, not the boolean."""
    assert build_query("cats and dogs") == '"cats" AND "and" AND "dogs"'


def test_accented_words_survive():
    assert build_query("café münchen") == '"café" AND "münchen"'


def test_an_empty_query_finds_nothing_rather_than_everything(conn):
    assert search(conn, "") == []
    assert search(conn, "   ") == []


# ------------------------------------------------------------------ results


def _add(conn, path, name, body):
    import time

    conn.execute(
        "INSERT INTO files(path, name, folder, kind, size, mtime, passages, indexed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
        (path, name, "/work", path.rsplit(".", 1)[-1], len(body), time.time(), time.time()),
    )
    conn.execute("INSERT INTO chunks(path, ord, body) VALUES (?, 0, ?)", (path, body))
    conn.commit()


def test_finds_a_word_inside_a_file(conn):
    _add(conn, "/work/a.md", "a.md", "The northern warehouse packaging redesign is called Falcon.")
    hits = search(conn, "falcon")
    assert len(hits) == 1
    assert hits[0].name == "a.md"
    assert "<mark>" in hits[0].snippet


def test_one_result_per_file_not_per_passage(conn):
    for ordinal in range(4):
        conn.execute(
            "INSERT INTO chunks(path, ord, body) VALUES ('/work/b.md', ?, 'freight freight freight')",
            (ordinal,),
        )
    _add(conn, "/work/b.md", "b.md", "freight quote")
    assert len([h for h in search(conn, "freight") if h.path == "/work/b.md"]) == 1


def test_a_passage_whose_file_row_is_gone_is_skipped_quietly(conn):
    """Half-finished sweeps happen. They must not surface a hit with no file."""
    conn.execute("INSERT INTO chunks(path, ord, body) VALUES ('/gone.md', 0, 'orphan text')")
    conn.commit()
    assert search(conn, "orphan") == []


def test_kind_filter(conn):
    _add(conn, "/work/c.md", "c.md", "shipping terms agreed")
    _add(conn, "/work/d.txt", "d.txt", "shipping terms agreed")
    assert [h.name for h in search(conn, "shipping", kind="txt")] == ["d.txt"]


def test_a_wordy_search_still_finds_something(conn):
    """Requiring every word is right for two words and wrong for a sentence.

    Strict first, relaxed only when strict finds nothing - so a precise
    search stays precise and a typed-out question still works.
    """
    _add(conn, "/work/e.md", "e.md", "Delivery terms agreed as DAP Rotterdam.")
    assert search(conn, "delivery terms") , "the precise search must work"
    assert search(conn, "what did we agree on the delivery terms"), "so must the wordy one"


def test_a_precise_search_is_not_loosened_when_it_matches(conn):
    _add(conn, "/work/g.md", "g.md", "freight quote for the northern route")
    _add(conn, "/work/h.md", "h.md", "freight only, no quote yet")
    names = {hit.name for hit in search(conn, "freight quote northern")}
    assert names == {"g.md"}, "a search that matches must not be relaxed"


def test_context_for_a_question_spreads_across_files(conn):
    from cairn.search import context_for_question

    for index in range(5):
        _add(conn, f"/work/f{index}.md", f"f{index}.md", "delivery terms were agreed as DAP")
    picked = context_for_question(conn, "delivery terms")
    assert len({p["path"] for p in picked}) > 1, "one document must not crowd out the rest"
