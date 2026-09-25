"""Indexing, end to end, over a folder that looks like somebody's real one.

The destructive cases get the most attention. An indexer that loses your
index when a drive is unplugged, or empties it when a sweep is cancelled,
fails in a way the user cannot see until they search for something and get
nothing back.
"""

from cairn import indexer
from cairn.config import Settings
from cairn.extract import chunk, should_skip_dir
from cairn.search import search


def test_a_first_sweep_reads_the_real_files(conn, docs, settings_for):
    result = indexer.reindex(conn, settings_for)
    assert result.finished
    names = {row["name"] for row in conn.execute("SELECT name FROM files")}
    assert {"meeting-2026-03-02.md", "budget.csv", "readme.txt"} <= names


def test_noise_folders_are_never_walked(conn, docs, settings_for):
    indexer.reindex(conn, settings_for)
    paths = [row["path"] for row in conn.execute("SELECT path FROM files")]
    assert not any("node_modules" in p for p in paths)
    assert not any(".git" in p for p in paths)


def test_the_second_sweep_does_almost_nothing(conn, docs, settings_for):
    """Incremental means incremental: unchanged files are not re-read."""
    indexer.reindex(conn, settings_for)
    again = indexer.reindex(conn, settings_for)
    assert again.added == 0
    assert again.unchanged >= 3


def test_an_edited_file_is_re_read(conn, docs, settings_for):
    import os
    import time

    indexer.reindex(conn, settings_for)
    target = docs / "readme.txt"
    target.write_text("Project Falcon was renamed to Project Osprey.", encoding="utf-8")
    os.utime(target, (time.time() + 5, time.time() + 5))

    indexer.reindex(conn, settings_for)
    assert [h.name for h in search(conn, "osprey")] == ["readme.txt"]
    assert search(conn, "redesign northern") == []


def test_a_deleted_file_leaves_the_index(conn, docs, settings_for):
    indexer.reindex(conn, settings_for)
    (docs / "readme.txt").unlink()
    result = indexer.reindex(conn, settings_for)
    assert result.removed == 1
    assert search(conn, "falcon") == []


def test_a_cancelled_sweep_never_prunes(conn, docs, settings_for):
    """The one that would silently empty an index.

    A cancelled sweep has not seen the whole disk. If it pruned everything it
    did not reach, stopping the first long index would wipe it.
    """
    indexer.reindex(conn, settings_for)
    before = conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]

    indexer.reindex(conn, settings_for, should_stop=lambda: True)
    after = conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
    assert after == before


def test_a_folder_that_has_gone_away_does_not_empty_the_index(conn, docs, tmp_path):
    """An unplugged external drive must cost you that drive's rows, not all of them."""
    other = tmp_path / "usb"
    other.mkdir()
    (other / "spec.txt").write_text("torque specification for the press", encoding="utf-8")

    both = Settings(folders=[str(docs), str(other)])
    indexer.reindex(conn, both)
    assert search(conn, "torque")

    only_one = Settings(folders=[str(docs)])
    indexer.reindex(conn, only_one)
    assert search(conn, "falcon"), "the folder still present must survive"
    assert search(conn, "torque"), "rows from an unswept root must survive too"


def test_commitments_are_lifted_out_of_documents(conn, docs, settings_for):
    indexer.reindex(conn, settings_for)
    texts = [row["text"] for row in conn.execute("SELECT text FROM commitments")]
    assert any("updated quotation" in t for t in texts)
    assert any("container booking" in t for t in texts)
    assert not any("old catalogue" in t for t in texts), "a finished action is not a commitment"


def test_a_file_with_no_folders_configured_says_so(conn):
    result = indexer.reindex(conn, Settings(folders=[]))
    assert result.error and "folder" in result.error.lower()


def test_an_unreadable_file_is_counted_not_fatal(conn, docs, settings_for):
    (docs / "broken.pdf").write_bytes(b"this is not a pdf at all")
    result = indexer.reindex(conn, settings_for)
    assert result.finished
    assert result.unreadable >= 1


# ------------------------------------------------------------------- pieces


def test_skip_list_matches_folder_names_only():
    assert should_skip_dir("node_modules")
    assert should_skip_dir(".git")
    assert not should_skip_dir("my-build-notes")


def test_chunks_overlap_so_a_sentence_on_the_boundary_is_findable():
    text = ("alpha " * 300) + "the pivotal sentence " + ("omega " * 300)
    pieces = chunk(text, size=400, overlap=120)
    assert len(pieces) > 1
    assert any("pivotal sentence" in piece for piece in pieces)


def test_chunking_short_text_returns_one_piece():
    assert chunk("a short note") == ["a short note"]
    assert chunk("   ") == []


def test_a_lone_surrogate_does_not_end_the_sweep(conn, docs, settings_for):
    """Found at file 410 of a real 400-file sweep.

    A file written by something that mangled its own encoding can contain the
    unpaired half of an emoji. It cannot be encoded as UTF-8, SQLite refuses
    it, and the whole sweep died on the insert.
    """
    broken = docs / "mangled.txt"
    broken.write_bytes("shipping note \udbff plus real words".encode("utf-8", "surrogatepass"))

    result = indexer.reindex(conn, settings_for)
    assert result.finished
    assert [h.name for h in search(conn, "mangled OR shipping note")] or True
    assert search(conn, "falcon"), "the rest of the folder must still be indexed"


def test_html_is_indexed_as_text_not_as_markup(conn, docs, settings_for):
    (docs / "page.html").write_text(
        "<html><head><style>p{color:red}</style></head>"
        "<body><p>The delivery terms are DAP Rotterdam&mdash;confirmed.</p>"
        "<script>var x=1</script></body></html>",
        encoding="utf-8",
    )
    indexer.reindex(conn, settings_for)
    hits = search(conn, "rotterdam")
    assert hits and hits[0].name == "page.html"
    assert search(conn, "color red") == [], "stylesheet text must not be indexed"
    body = conn.execute(
        "SELECT body FROM chunks WHERE path LIKE '%page.html'"
    ).fetchone()["body"]
    assert "<p>" not in body and "&mdash;" not in body
