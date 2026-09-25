"""Pulling commitments out of ordinary writing.

Two kinds of failure are tested here, and the second matters more:

  * missing a real promise, which makes the feature useless;
  * inventing one, which makes the whole list untrustworthy. A to-do list
    with four things you never said on it is a list you stop opening.
"""

from datetime import date

from cairn import commitments

TODAY = date(2026, 3, 4)  # a Wednesday


def find(text, source="note", ref="note:1"):
    return commitments.find(text, source, ref, today=TODAY)


# ------------------------------------------------------------------- finding


def test_a_first_person_promise_is_picked_up():
    found = find("Good call. I'll send the revised quotation on Thursday.")
    assert len(found) == 1
    assert "revised quotation" in found[0].text
    assert found[0].who == "me"
    assert found[0].due == date(2026, 3, 5)


def test_something_someone_else_owes_is_marked_as_theirs():
    found = find("Anita will confirm the container booking by Friday.")
    assert found[0].who == "them"
    assert found[0].due == date(2026, 3, 6)


def test_two_clauses_in_one_line_become_two_commitments():
    """They have different dates, so collapsing them loses one."""
    found = find("I'll call the bank and I need to file the return by Friday.")
    assert len(found) == 2
    assert found[0].due is None
    assert found[1].due == date(2026, 3, 6)


def test_an_explicit_todo_marker_is_taken_at_face_value():
    found = find("Notes from the call\n- [ ] chase the freight quote\nnothing else")
    assert any("freight quote" in c.text for c in found)


def test_todo_colon_lines_are_caught():
    found = find("TODO: renew the insurance policy before the end of the month")
    assert found and found[0].due == date(2026, 3, 31)


def test_a_request_addressed_to_you_counts():
    found = find("Can you send over the packing list when you get a moment")
    assert found and found[0].who == "me"


# ------------------------------------------------------------- not inventing


def test_a_finished_action_is_not_a_commitment():
    assert find("As discussed, I have sent the catalogue already.") == []
    assert find("The invoice was sent on Monday.") == []


def test_a_question_is_not_a_commitment():
    assert find("Should I send the revised quotation on Thursday?") == []


def test_a_hypothetical_is_not_a_commitment():
    assert find("If they agree, I'll send the revised terms.") == []


def test_the_word_will_inside_another_word_is_not_a_cue():
    """Without a word boundary on both sides, 'ill' matches inside 'will',
    'skill' and 'still', and a document about skills becomes forty items."""
    text = "The skills matrix is still being filled in and the goodwill is intact."
    assert find(text) == []


def test_a_spreadsheet_row_is_not_prose():
    assert find("1200 | 340 | 8800 | 1.2 | 4.5 | 9.9 | 12 | 44") == []


def test_very_short_and_very_long_clauses_are_skipped():
    assert find("I'll go") == []
    assert find("I'll " + "and then " * 60) == []


# ------------------------------------------------------------------- storage


def test_the_same_sentence_is_never_stored_twice(conn):
    found = find("I'll send the revised quotation on Thursday.")
    assert commitments.store(conn, found) == 1
    assert commitments.store(conn, found) == 0, "reindexing must not duplicate"


def test_the_same_promise_in_two_files_is_two_things_to_check(conn):
    first = commitments.find("I'll chase the freight quote.", "document", "/a/one.md", TODAY)
    second = commitments.find("I'll chase the freight quote.", "document", "/b/two.md", TODAY)
    assert commitments.store(conn, first) == 1
    assert commitments.store(conn, second) == 1


def test_ticking_something_off_survives_a_reindex(conn):
    """The important one: re-reading the document must not resurrect it."""
    found = find("I'll send the revised quotation on Thursday.")
    commitments.store(conn, found)
    item_id = conn.execute("SELECT id FROM commitments").fetchone()["id"]
    commitments.complete(conn, item_id)

    commitments.store(conn, found)  # the file is read again
    row = conn.execute("SELECT status FROM commitments WHERE id = ?", (item_id,)).fetchone()
    assert row["status"] == "done"
    assert commitments.open_items(conn) == []


def test_dismissed_items_stay_dismissed(conn):
    found = find("Can you send over the packing list when you get a moment")
    commitments.store(conn, found)
    item_id = conn.execute("SELECT id FROM commitments").fetchone()["id"]
    commitments.dismiss(conn, item_id)
    commitments.store(conn, found)
    assert commitments.open_items(conn) == []


def test_open_items_put_the_soonest_first_and_undated_last(conn):
    commitments.store(
        conn,
        [
            commitments.Commitment("no date one here", "me", None, "note", "note:1"),
            commitments.Commitment("due later on", "me", date(2026, 4, 1), "note", "note:2"),
            commitments.Commitment("due very soon", "me", date(2026, 3, 5), "note", "note:3"),
        ],
    )
    order = [row["text"] for row in commitments.open_items(conn)]
    assert order == ["due very soon", "due later on", "no date one here"]


# ------------------------------------- what a real machine taught this module


def test_a_capitalised_word_ending_in_double_l_is_not_a_promise():
    """Found on a real disk, not in a fixture.

    Allowing a bare "ll" after a word means Call, Fill, Bill, Tell and Full
    all parse as "<someone>'ll", and a strategy report turned into forty
    phantom commitments. The apostrophe is now required.
    """
    text = (
        "Call Utkarsh this week\n"
        "Fill the biggest gap versus the competitors\n"
        "Full detail is in the prospects file\n"
        "Tell the forwarder about the delay\n"
    )
    assert find(text) == []


def test_the_real_contraction_still_works():
    assert find("Ravi'll confirm the booking on Friday")[0].who == "them"
    assert find("I'll confirm the booking on Friday")[0].who == "me"


def test_a_thought_is_not_a_promise():
    """"We should consider the northern route" is a document being a document."""
    assert find("We should consider the northern route instead") == []
    assert find("We must be careful about the tooling cost") == []


def test_markdown_and_html_wreckage_never_reaches_the_list():
    """Indexed HTML used to put &rdquo; and </p> into the to-do list."""
    assert find("## I'll send the revised figures on Thursday") == []
    assert find("| I'll send the figures | pending | 3 |") == []
    assert find("<p>I will be in touch&rdquo;, she said.</p>") == []


def test_somebody_elses_words_quoted_in_a_report_are_not_your_to_do():
    """Weekly reports summarise email threads. Every quoted line in them was
    becoming a to-do addressed to nobody."""
    assert find('He wrote *"please advise urgently"* and escalated internally') == []
    assert find('Say "we will quote by Friday" or say we do not make bags') == []


def test_a_template_waiting_to_be_filled_in_is_not_a_commitment():
    assert find("We'll dispatch a curated sample kit within [X] business days") == []
    assert find("I'll send the quote to {{buyer}} on Monday") == []


def test_a_promise_not_to_do_something_is_not_a_thing_to_do():
    assert find("Email will not tell you which of them replied") == []
    assert find("I won't be sending the revised terms this week") == []


def test_a_clause_cut_at_the_next_cue_does_not_keep_the_conjunction():
    """"I'll send the form on Tuesday and" is not how anyone writes a to-do."""
    found = find("I'll send the mandate form on Tuesday and Priya will confirm the opening.")
    assert found[0].text == "I'll send the mandate form on Tuesday"
    assert found[1].text == "Priya will confirm the opening"
