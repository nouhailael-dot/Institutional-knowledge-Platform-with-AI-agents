"""Event dates: what a date found on the web means, from one place.

Sources often give only part of a date ("2026-02", "2026", "Spring 2027"). Each
date is read as the range of days it could be, so a past month is past and the
current year is unconfirmed, instead of keeping the model's guess. The status is
always computed from the dates (asked for on 27 Oct 2026, after a past event was
shown as upcoming).

Pure Python - no LLM calls, no cost.
"""
import re
from datetime import date, timedelta

UPCOMING, PAST, UNCONFIRMED = "upcoming", "past", "date unconfirmed"

_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")


def date_range(value):
    """(first, last, exact) for an ISO day, a month ("2026-02"), a bare year, or
    free text naming years ("Spring 2027"); None when no date can be read.
    `exact` is True only for a whole day."""
    text = str(value or "").strip()
    if _DAY.match(text):
        try:
            day = date.fromisoformat(text[:10])
            return day, day, True
        except ValueError:
            return None
    month = _MONTH.match(text)
    if month:
        year, number = int(month[1]), int(month[2])
        if not 1 <= number <= 12:
            return None
        following = date(year + number // 12, number % 12 + 1, 1)
        return date(year, number, 1), following - timedelta(days=1), False
    years = [int(y) for y in _YEAR.findall(text)]
    if years:
        return date(min(years), 1, 1), date(max(years), 12, 31), False
    return None


def event_span(start, end=None):
    """(first, last, exact) for an edition from its first and last day. An end
    date before the start, or one that cannot be read, is ignored."""
    first = date_range(start)
    if first is None:
        return None
    last = date_range(end)
    if last is None or last[1] < first[0]:
        return first
    return first[0], last[1], first[2] and last[2]


def date_status(start, end=None, today=None):
    """Upcoming, past or date unconfirmed, from the dates alone. An event on
    right now counts as upcoming; a partial date that includes today (this
    month, this year) is unconfirmed."""
    span = event_span(start, end)
    if span is None:
        return UNCONFIRMED
    first, last, exact = span
    today = today or date.today()
    if first >= today:
        return UPCOMING
    if last < today:
        return PAST
    return UPCOMING if exact else UNCONFIRMED


def same_edition(a, b, slack_days=14):
    """Whether two records' dates can be the same edition: the ranges overlap,
    or are within `slack_days` (sources often disagree by a day or two). A
    record without a date can belong to any edition."""
    left = event_span(a.get("next_date"), a.get("end_date"))
    right = event_span(b.get("next_date"), b.get("end_date"))
    if left is None or right is None:
        return True
    gap = max(left[0], right[0]) - min(left[1], right[1])
    return gap.days <= slack_days


def _us(day):
    return day.strftime("%m/%d/%Y")


def dates_text(start, end=None):
    """The edition's dates the way the platform shows them: "11/16/2026",
    "11/16/2026 – 11/19/2026", "02/2026", "2026 (exact date not found)".
    Anything else is shown as given."""
    text = str(start or "").strip()
    span = event_span(start, end)
    if span is None:
        return text
    first, last, exact = span
    if _DAY.match(text):
        end_range = date_range(end)
        if end_range and end_range[2] and last > first:
            return f"{_us(first)} – {_us(last)}"
        return _us(first)
    if _MONTH.match(text):
        return first.strftime("%m/%Y")
    if re.fullmatch(r"\d{4}", text):
        return f"{text} (exact date not found)"
    return text
