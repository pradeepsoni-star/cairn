"""Reading a date out of ordinary writing, in code rather than by asking a model.

This is done deterministically on purpose. Language models are confidently
wrong about dates - they will cheerfully tell you next Tuesday is the 14th
when it is the 16th - and a to-do with the wrong date is worse than no date
at all, because you stop checking. Everything here is a rule you can read,
test and argue with.

Weekday handling is the part people disagree about, so it is stated plainly:
a bare weekday name means the NEXT one, and "Friday" said on a Friday means
a week today, not this morning. Saying "today" is how you mean today.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2,
    "wed": 2, "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4,
    "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}

_ORDINAL = r"(?:st|nd|rd|th)?"


def _clamp(year: int, month: int, day: int) -> date | None:
    """A date, or None if the writing said something like 31 February."""
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _next_weekday(today: date, target: int, *, skip_today: bool = True) -> date:
    ahead = (target - today.weekday()) % 7
    if ahead == 0 and skip_today:
        ahead = 7
    return today + timedelta(days=ahead)


def _end_of_month(today: date) -> date:
    if today.month == 12:
        return date(today.year, 12, 31)
    return date(today.year, today.month + 1, 1) - timedelta(days=1)


def parse_due(text: str, today: date | None = None, day_first: bool = True) -> date | None:
    """The due date a phrase points at, or None if it names no date.

    `day_first` decides only the genuinely ambiguous numeric case - 03/04 -
    where nothing in the text itself can settle it. Anything that can be
    settled (13/04, 2026-04-13, "13 April") ignores the flag entirely.
    """
    if not text:
        return None
    today = today or date.today()
    lowered = text.lower()

    # --- explicit calendar dates, most specific first ------------------------

    iso = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lowered)
    if iso:
        found = _clamp(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        if found:
            return found

    # A slash is only ever a date separator. A full stop is not: "v2.4",
    # "section 3.1" and "3.4 million" are all decimals, and reading them as
    # dates put phantom deadlines on a third of one test corpus. So a dotted
    # date is accepted only when it carries a year, which no decimal does.
    numeric = re.search(
        r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b|\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b",
        lowered,
    )
    if numeric:
        slashed = numeric.group(1) is not None
        first = int(numeric.group(1) if slashed else numeric.group(4))
        second = int(numeric.group(2) if slashed else numeric.group(5))
        year_text = numeric.group(3) if slashed else numeric.group(6)
        if year_text:
            year = int(year_text)
            year += 2000 if year < 100 else 0
        else:
            year = today.year
        if first > 12 and second <= 12:
            day, month = first, second
        elif second > 12 and first <= 12:
            day, month = second, first
        else:
            day, month = (first, second) if day_first else (second, first)
        found = _clamp(year, month, day)
        # A bare "3/4" that has already gone by means next year's, the way a
        # person writing it in December and meaning January would expect.
        if found and not year_text and found < today:
            found = _clamp(year + 1, month, day)
        if found:
            return found

    named = re.search(
        rf"\b(\d{{1,2}}){_ORDINAL}\s+({'|'.join(MONTHS)})\b"
        rf"|\b({'|'.join(MONTHS)})\s+(\d{{1,2}}){_ORDINAL}\b",
        lowered,
    )
    if named:
        if named.group(1):
            day, month = int(named.group(1)), MONTHS[named.group(2)]
        else:
            day, month = int(named.group(4)), MONTHS[named.group(3)]
        year_hint = re.search(r"\b(20\d{2})\b", lowered)
        year = int(year_hint.group(1)) if year_hint else today.year
        found = _clamp(year, month, day)
        if found and not year_hint and found < today:
            found = _clamp(year + 1, month, day)
        if found:
            return found

    # --- relative phrases ----------------------------------------------------

    if re.search(r"\b(today|tonight|this evening|eod|end of day|by cob|cob)\b", lowered):
        return today
    # Longest phrase first: "day after tomorrow" contains "tomorrow", and
    # testing the short one first quietly loses a day.
    if re.search(r"\bday after tomorrow\b", lowered):
        return today + timedelta(days=2)
    if re.search(r"\btomorrow\b|\btmrw\b|\btmr\b", lowered):
        return today + timedelta(days=1)
    if re.search(r"\byesterday\b", lowered):
        return today - timedelta(days=1)

    span = re.search(r"\bin (\d{1,3}|a|an|two|three|four|five|six|seven) (day|week|month)s?\b", lowered)
    if span:
        words = {"a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
        count = words.get(span.group(1), 0) or int(span.group(1) or 0)
        unit = span.group(2)
        if unit == "day":
            return today + timedelta(days=count)
        if unit == "week":
            return today + timedelta(weeks=count)
        return today + timedelta(days=30 * count)

    if re.search(r"\b(end of (the )?month|month end)\b", lowered):
        return _end_of_month(today)
    if re.search(r"\b(end of (the )?week|week end|by the weekend)\b", lowered):
        return _next_weekday(today, 4, skip_today=False)
    if re.search(r"\bnext month\b", lowered):
        return today + timedelta(days=30)

    weekday = re.search(rf"\b(next|this|coming)?\s*({'|'.join(WEEKDAYS)})\b", lowered)
    if weekday:
        target = WEEKDAYS[weekday.group(2)]
        found = _next_weekday(today, target)
        if (weekday.group(1) or "").strip() == "next" and (target - today.weekday()) % 7 != 0:
            # "next Friday" said on a Monday means the Friday of next week,
            # not this one - the commonest source of a missed handover.
            found += timedelta(days=7)
        return found

    if re.search(r"\bnext week\b", lowered):
        return _next_weekday(today, 0)
    if re.search(r"\bthis week\b", lowered):
        return _next_weekday(today, 4, skip_today=False)

    return None


def humanise(due: date | None, today: date | None = None) -> str:
    """How a person would say it: 'today', 'in 3 days', '12 days overdue'."""
    if due is None:
        return "no date"
    today = today or date.today()
    days = (due - today).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days == -1:
        return "yesterday"
    if days < 0:
        return f"{abs(days)} days overdue"
    if days < 7:
        return f"in {days} days"
    if days < 14:
        return "next week"
    # The year matters once it is not this one. "13 Apr" for a date that
    # rolled into next year reads as a date already gone.
    if due.year != today.year:
        return due.strftime("%d %b %Y")
    return due.strftime("%d %b")
