"""Business-logic orchestration layer.

Everything the web layer (or a script, or a test) needs goes through
:class:`Service`. It enforces role-based visibility, validates requests against
blackout periods and balances, drives the workflow state machine and writes an
audit entry for every state change.

Roles
-----
* ``employee`` — sees only their own data; may create and cancel their own
  requests.
* ``manager``  — additionally sees and decides on requests from direct reports
  (``employee.manager_id == manager.id``).
* ``admin``    — the "Chef": manages employees, entitlements, K.O. days and
  blackout periods, decides on any request, and reads the audit log.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import audit, auth, clock, dates, db, workflow
from .entitlements import Balance, balance


class ServiceError(Exception):
    """Base class for expected, user-facing errors."""


class PermissionDenied(ServiceError):
    pass


class ValidationError(ServiceError):
    pass


class NotFound(ServiceError):
    pass


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


class Service:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ------------------------------------------------------------------ #
    # Employees
    # ------------------------------------------------------------------ #
    def get_employee(self, employee_id: int) -> sqlite3.Row:
        row = db.fetchone(self.conn, "SELECT * FROM employees WHERE id = ?", (employee_id,))
        if row is None:
            raise NotFound(f"Mitarbeiter {employee_id} nicht gefunden.")
        return row

    def get_employee_by_email(self, email: str) -> sqlite3.Row | None:
        return db.fetchone(self.conn, "SELECT * FROM employees WHERE email = ?", (email,))

    def list_employees(self, actor: sqlite3.Row) -> list[sqlite3.Row]:
        if actor["role"] == "admin":
            return db.fetchall(self.conn, "SELECT * FROM employees ORDER BY name")
        if actor["role"] == "manager":
            return db.fetchall(
                self.conn,
                "SELECT * FROM employees WHERE id = ? OR manager_id = ? ORDER BY name",
                (actor["id"], actor["id"]),
            )
        return [self.get_employee(actor["id"])]

    def create_employee(
        self,
        actor: sqlite3.Row,
        *,
        personnel_no: str,
        name: str,
        email: str,
        password: str,
        role: str = "employee",
        manager_id: int | None = None,
    ) -> int:
        self._require_admin(actor)
        if role not in ("employee", "manager", "admin"):
            raise ValidationError(f"Ungültige Rolle: {role}")
        try:
            cur = self.conn.execute(
                """
                INSERT INTO employees
                    (personnel_no, name, email, role, manager_id, password_hash, active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (personnel_no, name, email, role, manager_id,
                 auth.hash_password(password), clock.now_iso()),
            )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"Personalnummer oder E-Mail bereits vergeben ({exc}).")
        emp_id = int(cur.lastrowid)
        audit.record(
            self.conn, action="employee.create", entity_type="employee",
            entity_id=emp_id, actor_id=actor["id"], actor_name=actor["name"],
            details={"name": name, "email": email, "role": role, "manager_id": manager_id},
        )
        return emp_id

    # ------------------------------------------------------------------ #
    # Entitlements (Jahresurlaub, Resturlaub Vorjahr, K.O.-Tage)
    # ------------------------------------------------------------------ #
    def set_entitlement(
        self,
        actor: sqlite3.Row,
        *,
        employee_id: int,
        year: int,
        annual_days: float,
        carryover_days: float = 0.0,
        ko_days: int = 0,
    ) -> None:
        self._require_admin(actor)
        self.get_employee(employee_id)  # existence check
        if annual_days < 0 or carryover_days < 0 or ko_days < 0:
            raise ValidationError("Urlaubstage dürfen nicht negativ sein.")
        self.conn.execute(
            """
            INSERT INTO entitlements (employee_id, year, annual_days, carryover_days, ko_days)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(employee_id, year) DO UPDATE SET
                annual_days = excluded.annual_days,
                carryover_days = excluded.carryover_days,
                ko_days = excluded.ko_days
            """,
            (employee_id, year, annual_days, carryover_days, ko_days),
        )
        audit.record(
            self.conn, action="entitlement.set", entity_type="entitlement",
            entity_id=f"{employee_id}:{year}", actor_id=actor["id"], actor_name=actor["name"],
            details={"employee_id": employee_id, "year": year, "annual_days": annual_days,
                     "carryover_days": carryover_days, "ko_days": ko_days},
        )

    def set_ko_days(self, actor: sqlite3.Row, *, employee_id: int, year: int, ko_days: int) -> None:
        """Convenience: set only the K.O.-day contingent, preserving leave."""
        self._require_admin(actor)
        ent = db.fetchone(
            self.conn, "SELECT * FROM entitlements WHERE employee_id = ? AND year = ?",
            (employee_id, year),
        )
        annual = float(ent["annual_days"]) if ent else 0.0
        carry = float(ent["carryover_days"]) if ent else 0.0
        self.set_entitlement(
            actor, employee_id=employee_id, year=year,
            annual_days=annual, carryover_days=carry, ko_days=ko_days,
        )

    # ------------------------------------------------------------------ #
    # Blackout periods (Sperrzeiten)
    # ------------------------------------------------------------------ #
    def add_blackout(self, actor: sqlite3.Row, *, year: int, start_date: str,
                     end_date: str, reason: str = "") -> int:
        self._require_admin(actor)
        if dates.parse(end_date) < dates.parse(start_date):
            raise ValidationError("Enddatum liegt vor Startdatum.")
        cur = self.conn.execute(
            "INSERT INTO blackout_periods (year, start_date, end_date, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (year, start_date, end_date, reason, clock.now_iso()),
        )
        bid = int(cur.lastrowid)
        audit.record(
            self.conn, action="blackout.add", entity_type="blackout", entity_id=bid,
            actor_id=actor["id"], actor_name=actor["name"],
            details={"year": year, "start_date": start_date, "end_date": end_date, "reason": reason},
        )
        return bid

    def delete_blackout(self, actor: sqlite3.Row, blackout_id: int) -> None:
        self._require_admin(actor)
        row = db.fetchone(self.conn, "SELECT * FROM blackout_periods WHERE id = ?", (blackout_id,))
        if row is None:
            raise NotFound("Sperrzeit nicht gefunden.")
        self.conn.execute("DELETE FROM blackout_periods WHERE id = ?", (blackout_id,))
        audit.record(
            self.conn, action="blackout.delete", entity_type="blackout", entity_id=blackout_id,
            actor_id=actor["id"], actor_name=actor["name"], details=dict(row),
        )

    def list_blackouts(self, year: int | None = None) -> list[sqlite3.Row]:
        if year is None:
            return db.fetchall(self.conn, "SELECT * FROM blackout_periods ORDER BY start_date")
        return db.fetchall(
            self.conn, "SELECT * FROM blackout_periods WHERE year = ? ORDER BY start_date", (year,)
        )

    def _blackout_conflict(self, start_date: str, end_date: str) -> sqlite3.Row | None:
        for bp in self.list_blackouts(dates.parse(start_date).year):
            if dates.overlaps(start_date, end_date, bp["start_date"], bp["end_date"]):
                return bp
        return None

    # ------------------------------------------------------------------ #
    # Requests / workflow
    # ------------------------------------------------------------------ #
    def create_request(
        self,
        actor: sqlite3.Row,
        *,
        employee_id: int | None = None,
        kind: str = "vacation",
        start_date: str,
        end_date: str,
        note: str = "",
    ) -> int:
        employee_id = employee_id or actor["id"]
        # Employees may only file for themselves; admins may file for anyone.
        if employee_id != actor["id"] and actor["role"] != "admin":
            raise PermissionDenied("Sie dürfen nur eigene Anträge stellen.")
        if kind not in ("vacation", "ko"):
            raise ValidationError(f"Unbekannte Antragsart: {kind}")

        emp = self.get_employee(employee_id)
        days = dates.working_days(start_date, end_date)
        if days <= 0:
            raise ValidationError("Der Zeitraum enthält keine Arbeitstage (Mo–Fr).")

        year = dates.parse(start_date).year
        if dates.parse(end_date).year != year:
            raise ValidationError("Anträge über den Jahreswechsel bitte getrennt stellen.")

        if kind == "vacation":
            conflict = self._blackout_conflict(start_date, end_date)
            if conflict is not None:
                raise ValidationError(
                    f"Zeitraum überschneidet sich mit einer Sperrzeit "
                    f"({conflict['start_date']}–{conflict['end_date']}: {conflict['reason']})."
                )

        # Balance check (counts approved + pending so two open requests can't
        # both consume the same days).
        bal = balance(self.conn, employee_id, year)
        if kind == "vacation":
            if days > bal.remaining_if_all_approved:
                raise ValidationError(
                    f"Nicht genügend Resturlaub: angefragt {days}, "
                    f"verfügbar {bal.remaining_if_all_approved}."
                )
        else:  # ko
            if days > (bal.ko_remaining - bal.ko_pending):
                raise ValidationError(
                    f"Nicht genügend K.O.-Tage: angefragt {days}, "
                    f"verfügbar {bal.ko_remaining - bal.ko_pending}."
                )

        cur = self.conn.execute(
            """
            INSERT INTO requests
                (employee_id, kind, start_date, end_date, days, status, note, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (employee_id, kind, start_date, end_date, days, note, clock.now_iso()),
        )
        req_id = int(cur.lastrowid)
        audit.record(
            self.conn, action="request.create", entity_type="request", entity_id=req_id,
            actor_id=actor["id"], actor_name=actor["name"],
            details={"employee_id": employee_id, "employee": emp["name"], "kind": kind,
                     "start_date": start_date, "end_date": end_date, "days": days, "note": note},
        )
        return req_id

    def get_request(self, request_id: int) -> sqlite3.Row:
        row = db.fetchone(self.conn, "SELECT * FROM requests WHERE id = ?", (request_id,))
        if row is None:
            raise NotFound(f"Antrag {request_id} nicht gefunden.")
        return row

    def decide_request(
        self,
        actor: sqlite3.Row,
        *,
        request_id: int,
        action: str,
        decision_note: str = "",
    ) -> str:
        """Apply a workflow action (approve/reject/revoke/cancel). Returns new state."""
        req = self.get_request(request_id)
        emp = self.get_employee(req["employee_id"])

        # Determine the actor's role *relative to this request*.
        if actor["id"] == emp["id"]:
            actor_kind = "employee"
        elif self._is_decider(actor, emp):
            actor_kind = "decider"
        else:
            raise PermissionDenied("Sie sind für diesen Antrag nicht zuständig.")

        if not workflow.role_may(action, actor_kind):
            raise PermissionDenied(
                f"Ihre Rolle darf die Aktion '{action}' nicht ausführen."
            )

        new_state = workflow.next_state(action, req["status"])

        self.conn.execute(
            """
            UPDATE requests
            SET status = ?, decided_by = ?, decided_at = ?, decision_note = ?
            WHERE id = ?
            """,
            (new_state, actor["id"], clock.now_iso(), decision_note, request_id),
        )
        audit.record(
            self.conn, action=f"request.{action}", entity_type="request", entity_id=request_id,
            actor_id=actor["id"], actor_name=actor["name"],
            details={"employee_id": emp["id"], "employee": emp["name"],
                     "from": req["status"], "to": new_state, "action": action,
                     "decision_note": decision_note},
        )
        return new_state

    def list_requests(
        self,
        actor: sqlite3.Row,
        *,
        employee_id: int | None = None,
        status: str | None = None,
    ) -> list[sqlite3.Row]:
        """Return requests visible to ``actor`` (own / team / all)."""
        clauses: list[str] = []
        params: list[Any] = []

        if actor["role"] == "admin":
            pass
        elif actor["role"] == "manager":
            clauses.append("(r.employee_id = ? OR e.manager_id = ?)")
            params += [actor["id"], actor["id"]]
        else:
            clauses.append("r.employee_id = ?")
            params.append(actor["id"])

        if employee_id is not None:
            if not self.can_view(actor, employee_id):
                raise PermissionDenied("Kein Zugriff auf diesen Mitarbeiter.")
            clauses.append("r.employee_id = ?")
            params.append(employee_id)
        if status is not None:
            clauses.append("r.status = ?")
            params.append(status)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return db.fetchall(
            self.conn,
            f"""
            SELECT r.*, e.name AS employee_name, e.personnel_no AS personnel_no
            FROM requests r JOIN employees e ON e.id = r.employee_id
            {where}
            ORDER BY r.created_at DESC
            """,
            params,
        )

    def pending_for_decider(self, actor: sqlite3.Row) -> list[sqlite3.Row]:
        """Open requests this actor can decide on (their reports, or all for admin)."""
        rows = self.list_requests(actor, status="pending")
        return [r for r in rows if r["employee_id"] != actor["id"]]

    # ------------------------------------------------------------------ #
    # Balances (visibility-checked)
    # ------------------------------------------------------------------ #
    def get_balance(self, actor: sqlite3.Row, employee_id: int, year: int) -> Balance:
        if not self.can_view(actor, employee_id):
            raise PermissionDenied("Kein Zugriff auf diese Urlaubsdaten.")
        return balance(self.conn, employee_id, year)

    # ------------------------------------------------------------------ #
    # Audit
    # ------------------------------------------------------------------ #
    def audit_entries(self, actor: sqlite3.Row, limit: int = 200) -> list[sqlite3.Row]:
        self._require_admin(actor)
        return audit.entries(self.conn, limit)

    def verify_audit(self, actor: sqlite3.Row):
        self._require_admin(actor)
        return audit.verify_chain(self.conn)

    # ------------------------------------------------------------------ #
    # Visibility / role helpers
    # ------------------------------------------------------------------ #
    def can_view(self, actor: sqlite3.Row, employee_id: int) -> bool:
        if actor["id"] == employee_id or actor["role"] == "admin":
            return True
        if actor["role"] == "manager":
            target = self.get_employee(employee_id)
            return target["manager_id"] == actor["id"]
        return False

    def _is_decider(self, actor: sqlite3.Row, employee: sqlite3.Row) -> bool:
        if actor["role"] == "admin":
            return True
        return actor["role"] == "manager" and employee["manager_id"] == actor["id"]

    def _require_admin(self, actor: sqlite3.Row) -> None:
        if actor["role"] != "admin":
            raise PermissionDenied("Diese Aktion ist Administratoren vorbehalten.")
