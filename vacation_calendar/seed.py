"""Seed a fresh database with a small demo company (<10 employees).

Run via ``python -m vacation_calendar.seed <db-path>`` or it is invoked
automatically by the server when the database is empty. Default password for
every demo account is ``passwort`` (change it in production!).
"""

from __future__ import annotations

import sqlite3
import sys

from . import audit, auth, clock, db

DEMO_PASSWORD = "passwort"


def seed(conn: sqlite3.Connection, *, year: int | None = None) -> None:
    year = year or clock.current_year()
    prev = year - 1
    now = clock.now_iso()

    def add_employee(personnel_no, name, email, role, manager_id):
        cur = conn.execute(
            """
            INSERT INTO employees
                (personnel_no, name, email, role, manager_id, password_hash, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (personnel_no, name, email, role, manager_id,
             auth.hash_password(DEMO_PASSWORD), now),
        )
        emp_id = int(cur.lastrowid)
        audit.record(conn, action="employee.create", entity_type="employee",
                     entity_id=emp_id, actor_name="seed",
                     details={"name": name, "role": role})
        return emp_id

    def set_ent(emp_id, annual, carry, ko):
        conn.execute(
            "INSERT INTO entitlements (employee_id, year, annual_days, carryover_days, ko_days) "
            "VALUES (?, ?, ?, ?, ?)",
            (emp_id, year, annual, carry, ko),
        )
        audit.record(conn, action="entitlement.set", entity_type="entitlement",
                     entity_id=f"{emp_id}:{year}", actor_name="seed",
                     details={"annual_days": annual, "carryover_days": carry, "ko_days": ko})

    # Chef / admin
    chef = add_employee("0001", "Christian Chef", "chef@example.com", "admin", None)
    # Manager / Vorgesetzte
    manager = add_employee("0002", "Maria Manager", "manager@example.com", "manager", chef)
    # Employees reporting to the manager
    e1 = add_employee("0003", "Erik Entwickler", "erik@example.com", "employee", manager)
    e2 = add_employee("0004", "Sara Sachbearbeiterin", "sara@example.com", "employee", manager)
    e3 = add_employee("0005", "Tom Techniker", "tom@example.com", "employee", manager)
    # One employee reporting directly to the Chef
    e4 = add_employee("0006", "Nina Neuzugang", "nina@example.com", "employee", chef)

    # Entitlements for the current year: 30 annual days, some carryover, K.O. days
    set_ent(chef, 30, 0, 2)
    set_ent(manager, 30, 5, 2)
    set_ent(e1, 30, 4, 2)
    set_ent(e2, 28, 2, 2)
    set_ent(e3, 30, 0, 2)
    set_ent(e4, 30, 0, 1)
    _ = prev  # carryover values represent the Resturlaub aus dem Vorjahr

    # A blackout period (Sperrzeit) — e.g. year-end inventory week.
    conn.execute(
        "INSERT INTO blackout_periods (year, start_date, end_date, reason, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (year, f"{year}-12-22", f"{year}-12-31", "Jahresend-Inventur / Betriebsruhe", now),
    )
    audit.record(conn, action="blackout.add", entity_type="blackout", actor_name="seed",
                 details={"reason": "Jahresend-Inventur", "year": year})


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m vacation_calendar.seed <db-path>", file=sys.stderr)
        return 2
    conn = db.connect(argv[0])
    db.init_db(conn)
    existing = conn.execute("SELECT COUNT(*) AS n FROM employees").fetchone()["n"]
    if existing:
        print(f"Datenbank enthält bereits {existing} Mitarbeiter — übersprungen.")
        return 0
    seed(conn)
    print("Demo-Daten angelegt. Login z.B. chef@example.com / passwort")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
