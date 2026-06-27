"""Single, overridable time source so business logic and tests stay deterministic."""

from __future__ import annotations

import datetime as _dt
from typing import Callable

# Tests can monkeypatch this to freeze time.
_now_fn: Callable[[], _dt.datetime] = lambda: _dt.datetime.now(_dt.timezone.utc)


def set_now(fn: Callable[[], _dt.datetime]) -> None:
    global _now_fn
    _now_fn = fn


def now() -> _dt.datetime:
    return _now_fn()


def now_iso() -> str:
    return now().replace(microsecond=0).isoformat()


def today() -> _dt.date:
    return now().date()


def current_year() -> int:
    return today().year
