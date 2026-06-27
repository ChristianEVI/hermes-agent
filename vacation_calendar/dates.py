"""Date helpers: working-day counting and blackout-period overlap.

Working days are Monday–Friday. Public holidays are intentionally out of scope
for this first version (a company of <10 people typically reconciles the few
regional holidays manually, and DATEV holds the authoritative holiday calendar);
the :func:`working_days` signature leaves room to pass an explicit holiday set
later.
"""

from __future__ import annotations

import datetime as _dt
from typing import Iterable


def parse(d: str | _dt.date) -> _dt.date:
    if isinstance(d, _dt.date):
        return d
    return _dt.date.fromisoformat(d)


def daterange(start: _dt.date, end: _dt.date) -> Iterable[_dt.date]:
    cur = start
    while cur <= end:
        yield cur
        cur += _dt.timedelta(days=1)


def working_days(
    start: str | _dt.date,
    end: str | _dt.date,
    holidays: Iterable[str | _dt.date] | None = None,
) -> int:
    """Count Mon–Fri days in the inclusive range, excluding any ``holidays``."""
    start_d, end_d = parse(start), parse(end)
    if end_d < start_d:
        raise ValueError("end_date must not be before start_date")
    holiday_set = {parse(h) for h in (holidays or [])}
    return sum(
        1
        for day in daterange(start_d, end_d)
        if day.weekday() < 5 and day not in holiday_set
    )


def overlaps(a_start: str | _dt.date, a_end: str | _dt.date,
             b_start: str | _dt.date, b_end: str | _dt.date) -> bool:
    a0, a1 = parse(a_start), parse(a_end)
    b0, b1 = parse(b_start), parse(b_end)
    return a0 <= b1 and b0 <= a1
