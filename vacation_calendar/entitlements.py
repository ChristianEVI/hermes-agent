"""Leave-balance calculations (Gesamturlaub / Resturlaub / Resturlaub Vorjahr).

Definitions used throughout the module, for a given employee and year:

* ``annual_days``   — this year's statutory/contractual entitlement (Jahresurlaub)
* ``carryover_days`` — remaining days carried over from the previous year
                       (Resturlaub aus dem Vorjahr)
* ``total``         — Gesamturlaub = annual_days + carryover_days
* ``approved``      — working days of *approved* vacation in the year
* ``pending``       — working days of *pending* vacation in the year
* ``remaining``     — Resturlaub = total - approved
* ``remaining_if_all_approved`` — total - approved - pending (what's left if
                      every open request is granted)

K.O. days are tracked separately from vacation (they are paid stay-at-home days,
not regular leave): ``ko_total`` / ``ko_approved`` / ``ko_pending`` / ``ko_remaining``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Balance:
    employee_id: int
    year: int
    annual_days: float
    carryover_days: float
    total: float
    approved: float
    pending: float
    remaining: float
    remaining_if_all_approved: float
    ko_total: int
    ko_approved: float
    ko_pending: float
    ko_remaining: float

    def as_dict(self) -> dict:
        return asdict(self)


def _sum_days(conn: sqlite3.Connection, employee_id: int, year: int,
              kind: str, status: str) -> float:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(days), 0) AS s
        FROM requests
        WHERE employee_id = ? AND kind = ? AND status = ?
          AND strftime('%Y', start_date) = ?
        """,
        (employee_id, kind, status, str(year)),
    ).fetchone()
    return float(row["s"])


def get_entitlement(conn: sqlite3.Connection, employee_id: int, year: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM entitlements WHERE employee_id = ? AND year = ?",
        (employee_id, year),
    ).fetchone()


def balance(conn: sqlite3.Connection, employee_id: int, year: int) -> Balance:
    ent = get_entitlement(conn, employee_id, year)
    annual = float(ent["annual_days"]) if ent else 0.0
    carry = float(ent["carryover_days"]) if ent else 0.0
    ko_total = int(ent["ko_days"]) if ent else 0

    approved = _sum_days(conn, employee_id, year, "vacation", "approved")
    pending = _sum_days(conn, employee_id, year, "vacation", "pending")
    ko_approved = _sum_days(conn, employee_id, year, "ko", "approved")
    ko_pending = _sum_days(conn, employee_id, year, "ko", "pending")

    total = annual + carry
    return Balance(
        employee_id=employee_id,
        year=year,
        annual_days=annual,
        carryover_days=carry,
        total=total,
        approved=approved,
        pending=pending,
        remaining=total - approved,
        remaining_if_all_approved=total - approved - pending,
        ko_total=ko_total,
        ko_approved=ko_approved,
        ko_pending=ko_pending,
        ko_remaining=ko_total - ko_approved,
    )
