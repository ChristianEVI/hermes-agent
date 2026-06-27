"""Urlaubskalender mit Audit-Trail — vacation calendar with an audit trail.

A small, dependency-free vacation-management module for companies with fewer
than ~10 employees. Built entirely on the Python standard library
(``http.server`` + ``sqlite3``) so it runs and tests anywhere without an
install step.

Features
--------
* Per-employee annual leave (Jahresurlaub), carry-over from the previous year
  (Resturlaub Vorjahr) and remaining balance (Resturlaub).
* Each employee only sees their own data; managers see and decide on their
  team's requests; an admin manages entitlements, K.O. days and blackout
  periods.
* "K.O. days" — extra paid stay-at-home days that are *not* regular vacation,
  with an admin-configurable count per employee.
* A request workflow (Pending -> Approved / Not Approved / Cancelled) rendered
  graphically in the dashboard.
* Blackout periods (Sperrzeiten) that block vacation requests.
* A tamper-evident, append-only, hash-chained audit trail.
* A DATEV-compatible absence CSV export / import / reconcile interface.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
