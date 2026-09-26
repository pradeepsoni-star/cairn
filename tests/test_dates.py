"""Date reading.

These are the tests that stop a to-do quietly acquiring the wrong date, which
is the failure that makes someone stop trusting the list altogether. Every
case is pinned to a fixed "today" so the suite means the same thing in June
as it does in December.
"""

from datetime import date

import pytest

from cairn.dates import humanise, parse_due

# A Wednesday, chosen so "Friday" and "next Friday" differ visibly.
TODAY = date(2026, 3, 4)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("send it today", date(2026, 3, 4)),
        ("by end of day", date(2026, 3, 4)),
        ("tonight", date(2026, 3, 4)),
        ("tomorrow morning", date(2026, 3, 5)),
        ("day after tomorrow", date(2026, 3, 6)),
        ("in 3 days", date(2026, 3, 7)),
        ("in two weeks", date(2026, 3, 18)),
        ("end of the month", date(2026, 3, 31)),
    ],
)
def test_relative_phrases(text, expected):
    assert parse_due(text, TODAY) == expected


def test_a_bare_weekday_means_the_next_one():
    assert parse_due("call them on Friday", TODAY) == date(2026, 3, 6)


def test_next_weekday_skips_a_week():
    """The single commonest way a handover date slips."""
    assert parse_due("next Friday", TODAY) == date(2026, 3, 13)


def test_the_same_weekday_as_today_means_a_week_today():
    assert parse_due("Wednesday", TODAY) == date(2026, 3, 11)


def test_today_is_how_you_say_today():
    assert parse_due("today", TODAY) == TODAY


@pytest.mark.parametrize(
    "text,expected",
    [
        ("due 2026-04-13", date(2026, 4, 13)),
        ("due 13 April", date(2026, 4, 13)),
        ("due April 13", date(2026, 4, 13)),
        ("due 13th April 2027", date(2027, 4, 13)),
        ("by 13/04", date(2026, 4, 13)),
        ("by 13.04.2026", date(2026, 4, 13)),
    ],
)
def test_explicit_dates(text, expected):
    assert parse_due(text, TODAY) == expected


def test_an_unambiguous_numeric_date_ignores_the_day_first_flag():
    """13/04 can only be a day and a month, whichever convention you use."""
    assert parse_due("13/04", TODAY, day_first=False) == date(2026, 4, 13)
    assert parse_due("04/13", TODAY, day_first=True) == date(2026, 4, 13)


def test_an_ambiguous_numeric_date_follows_the_flag():
    assert parse_due("03/04", TODAY, day_first=True) == date(2026, 4, 3)
    assert parse_due("03/04", TODAY, day_first=False) == date(2026, 3, 4)


def test_a_date_that_has_passed_rolls_to_next_year():
    """Writing '2 January' in December means the coming January."""
    december = date(2026, 12, 20)
    assert parse_due("pay on 2 January", december) == date(2027, 1, 2)


def test_impossible_dates_are_not_invented():
    assert parse_due("31 February", TODAY) is None


def test_text_with_no_date_gets_none():
    assert parse_due("send the revised figures", TODAY) is None
    assert parse_due("", TODAY) is None


@pytest.mark.parametrize(
    "text",
    ["upgrade to v2.40 soon", "see section 3.1", "revenue was 3.4 million", "a 2.5 hour call"],
)
def test_a_decimal_is_not_a_date(text):
    """The one that mattered: dotted numbers put phantom deadlines everywhere.

    A dotted date is only read as one when it carries a year, because no
    version number or decimal ever does.
    """
    assert parse_due(text, TODAY) is None


@pytest.mark.parametrize(
    "due,expected",
    [
        (date(2026, 3, 4), "today"),
        (date(2026, 3, 5), "tomorrow"),
        (date(2026, 3, 3), "yesterday"),
        (date(2026, 2, 25), "7 days overdue"),
        (date(2026, 3, 7), "in 3 days"),
        (None, "no date"),
    ],
)
def test_humanise(due, expected):
    assert humanise(due, TODAY) == expected


@pytest.mark.parametrize("offset", range(7))
def test_next_weekday_is_right_on_every_day_of_the_week(offset):
    """The arithmetic version broke at the end of the week, and broke silently.

    "next Friday" used to be computed as "the next Friday, plus seven days".
    Said on a Saturday the coming Friday is ALREADY next week, so that landed
    two Fridays out - a whole week late, on exactly the kind of promise people
    make on a Friday afternoon about the following week.

    It now means that weekday in the following calendar week, counted from
    next Monday, which is what people mean whichever day they say it.
    """
    from datetime import timedelta

    said_on = date(2026, 9, 21) + timedelta(days=offset)   # Mon 21 .. Sun 27 Sep
    assert parse_due("next Friday", said_on) == date(2026, 10, 2)
    assert parse_due("next Monday", said_on) == date(2026, 9, 28)


def test_a_bare_weekday_still_means_the_coming_one():
    """Only "next" changed. "Friday" keeps meaning the next Friday there is."""
    assert parse_due("Friday", date(2026, 9, 23)) == date(2026, 9, 25)   # Wednesday
    assert parse_due("Friday", date(2026, 9, 26)) == date(2026, 10, 2)   # Saturday
