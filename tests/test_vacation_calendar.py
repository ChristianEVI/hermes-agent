"""Tests for the vacation_calendar module — pure stdlib (unittest).

Run with either::

    python -m unittest tests.test_vacation_calendar
    python -m pytest tests/test_vacation_calendar.py    # also works
"""

from __future__ import annotations

import datetime as dt
import unittest

from vacation_calendar import audit, clock, datev, dates, db, seed, workflow
from vacation_calendar.service import (
    NotFound,
    PermissionDenied,
    Service,
    ValidationError,
)


def _frozen(year=2026):
    clock.set_now(lambda: dt.datetime(year, 6, 1, 9, 0, 0, tzinfo=dt.timezone.utc))


class Base(unittest.TestCase):
    def setUp(self):
        _frozen()
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        seed.seed(self.conn, year=2026)
        self.svc = Service(self.conn)
        self.chef = self.svc.get_employee_by_email("chef@example.com")
        self.mgr = self.svc.get_employee_by_email("manager@example.com")
        self.erik = self.svc.get_employee_by_email("erik@example.com")
        self.nina = self.svc.get_employee_by_email("nina@example.com")

    def tearDown(self):
        self.conn.close()
        clock.set_now(lambda: dt.datetime.now(dt.timezone.utc))


class TestWorkingDays(unittest.TestCase):
    def test_mon_fri(self):
        self.assertEqual(dates.working_days("2026-07-06", "2026-07-10"), 5)

    def test_excludes_weekend(self):
        self.assertEqual(dates.working_days("2026-07-04", "2026-07-05"), 0)
        self.assertEqual(dates.working_days("2026-07-03", "2026-07-06"), 2)

    def test_holidays(self):
        self.assertEqual(
            dates.working_days("2026-07-06", "2026-07-10", holidays=["2026-07-08"]), 4
        )

    def test_end_before_start(self):
        with self.assertRaises(ValueError):
            dates.working_days("2026-07-10", "2026-07-06")


class TestBalances(Base):
    def test_total_is_annual_plus_carry(self):
        bal = self.svc.get_balance(self.erik, self.erik["id"], 2026)
        self.assertEqual(bal.annual_days, 30)
        self.assertEqual(bal.carryover_days, 4)
        self.assertEqual(bal.total, 34)
        self.assertEqual(bal.remaining, 34)

    def test_remaining_after_approval(self):
        rid = self.svc.create_request(
            self.erik, start_date="2026-07-06", end_date="2026-07-10"
        )
        bal = self.svc.get_balance(self.erik, self.erik["id"], 2026)
        self.assertEqual(bal.pending, 5)
        self.assertEqual(bal.remaining, 34)  # not yet approved
        self.svc.decide_request(self.mgr, request_id=rid, action="approve")
        bal = self.svc.get_balance(self.erik, self.erik["id"], 2026)
        self.assertEqual(bal.approved, 5)
        self.assertEqual(bal.remaining, 29)

    def test_insufficient_balance_blocked(self):
        with self.assertRaises(ValidationError):
            # 30+4 = 34 days available; ask for a huge range
            self.svc.create_request(
                self.erik, start_date="2026-01-05", end_date="2026-12-31"
            )


class TestVisibility(Base):
    def test_employee_sees_only_own(self):
        with self.assertRaises(PermissionDenied):
            self.svc.get_balance(self.erik, self.chef["id"], 2026)
        # own is fine
        self.svc.get_balance(self.erik, self.erik["id"], 2026)

    def test_manager_sees_reports(self):
        # erik reports to manager
        self.assertTrue(self.svc.can_view(self.mgr, self.erik["id"]))
        # nina reports to chef, not manager
        self.assertFalse(self.svc.can_view(self.mgr, self.nina["id"]))

    def test_admin_sees_all(self):
        self.assertTrue(self.svc.can_view(self.chef, self.erik["id"]))
        self.assertTrue(self.svc.can_view(self.chef, self.nina["id"]))

    def test_employee_list_is_self_only(self):
        rows = self.svc.list_employees(self.erik)
        self.assertEqual([r["id"] for r in rows], [self.erik["id"]])


class TestWorkflow(Base):
    def test_transitions(self):
        self.assertEqual(workflow.next_state("approve", "pending"), "approved")
        self.assertEqual(workflow.next_state("reject", "pending"), "rejected")
        with self.assertRaises(workflow.WorkflowError):
            workflow.next_state("approve", "approved")

    def test_owner_cannot_approve(self):
        rid = self.svc.create_request(
            self.erik, start_date="2026-07-06", end_date="2026-07-10"
        )
        with self.assertRaises(PermissionDenied):
            self.svc.decide_request(self.erik, request_id=rid, action="approve")

    def test_owner_can_cancel(self):
        rid = self.svc.create_request(
            self.erik, start_date="2026-07-06", end_date="2026-07-10"
        )
        st = self.svc.decide_request(self.erik, request_id=rid, action="cancel")
        self.assertEqual(st, "cancelled")

    def test_foreign_manager_cannot_decide(self):
        # nina reports to chef; manager must not be able to approve her request
        rid = self.svc.create_request(
            self.nina, start_date="2026-07-06", end_date="2026-07-10"
        )
        with self.assertRaises(PermissionDenied):
            self.svc.decide_request(self.mgr, request_id=rid, action="approve")
        # chef (admin) can
        st = self.svc.decide_request(self.chef, request_id=rid, action="approve")
        self.assertEqual(st, "approved")

    def test_revoke_after_approve(self):
        rid = self.svc.create_request(
            self.erik, start_date="2026-07-06", end_date="2026-07-10"
        )
        self.svc.decide_request(self.mgr, request_id=rid, action="approve")
        st = self.svc.decide_request(self.mgr, request_id=rid, action="revoke")
        self.assertEqual(st, "rejected")


class TestBlackoutAndKO(Base):
    def test_blackout_blocks_vacation(self):
        with self.assertRaises(ValidationError):
            self.svc.create_request(
                self.erik, start_date="2026-12-23", end_date="2026-12-24"
            )

    def test_ko_days_separate_from_vacation(self):
        bal = self.svc.get_balance(self.erik, self.erik["id"], 2026)
        self.assertEqual(bal.ko_total, 2)
        rid = self.svc.create_request(
            self.erik, kind="ko", start_date="2026-08-03", end_date="2026-08-03"
        )
        self.svc.decide_request(self.mgr, request_id=rid, action="approve")
        bal = self.svc.get_balance(self.erik, self.erik["id"], 2026)
        self.assertEqual(bal.ko_remaining, 1)
        # vacation balance untouched by KO
        self.assertEqual(bal.remaining, 34)

    def test_ko_overdraw_blocked(self):
        # only 2 KO days; ask for a 3-working-day KO span
        with self.assertRaises(ValidationError):
            self.svc.create_request(
                self.erik, kind="ko", start_date="2026-08-03", end_date="2026-08-05"
            )

    def test_admin_sets_ko_days(self):
        self.svc.set_ko_days(self.chef, employee_id=self.erik["id"], year=2026, ko_days=5)
        bal = self.svc.get_balance(self.erik, self.erik["id"], 2026)
        self.assertEqual(bal.ko_total, 5)
        # non-admin cannot
        with self.assertRaises(PermissionDenied):
            self.svc.set_ko_days(self.mgr, employee_id=self.erik["id"], year=2026, ko_days=9)


class TestAdminOnly(Base):
    def test_non_admin_cannot_set_entitlement(self):
        with self.assertRaises(PermissionDenied):
            self.svc.set_entitlement(
                self.mgr, employee_id=self.erik["id"], year=2026, annual_days=40
            )

    def test_create_employee_and_login_role(self):
        emp_id = self.svc.create_employee(
            self.chef, personnel_no="0099", name="Test Person",
            email="test@example.com", password="geheim", role="employee",
            manager_id=self.mgr["id"],
        )
        self.assertIsInstance(emp_id, int)
        # duplicate personnel_no rejected
        with self.assertRaises(ValidationError):
            self.svc.create_employee(
                self.chef, personnel_no="0099", name="Dup",
                email="dup@example.com", password="x",
            )


class TestAudit(Base):
    def test_chain_intact_after_operations(self):
        rid = self.svc.create_request(
            self.erik, start_date="2026-07-06", end_date="2026-07-10"
        )
        self.svc.decide_request(self.mgr, request_id=rid, action="approve")
        result = self.svc.verify_audit(self.chef)
        self.assertTrue(result.ok)
        self.assertGreater(result.checked, 0)

    def test_tamper_is_detected(self):
        # Drop the append-only trigger to simulate an attacker with raw DB access.
        self.conn.executescript("DROP TRIGGER audit_log_no_update;")
        self.conn.execute("UPDATE audit_log SET details='{\"x\":1}' WHERE id=1")
        result = audit.verify_chain(self.conn)
        self.assertFalse(result.ok)
        self.assertEqual(result.broken_at, 1)

    def test_append_only_trigger_blocks_update(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE audit_log SET action='x' WHERE id=1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM audit_log WHERE id=1")

    def test_audit_read_is_admin_only(self):
        with self.assertRaises(PermissionDenied):
            self.svc.audit_entries(self.erik)


class TestDatev(Base):
    def _approve_vacation(self):
        rid = self.svc.create_request(
            self.erik, start_date="2026-07-06", end_date="2026-07-10"
        )
        self.svc.decide_request(self.mgr, request_id=rid, action="approve")

    def test_export_csv_roundtrip(self):
        self._approve_vacation()
        csv_text = datev.export_csv(self.conn, 2026)
        self.assertIn("Personalnummer;", csv_text)
        self.assertIn("0003;Erik Entwickler;U;2026-07-06;2026-07-10;5", csv_text)
        rows = datev.parse_csv(csv_text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].days, 5)

    def test_reconcile_clean(self):
        self._approve_vacation()
        rows = datev.parse_csv(datev.export_csv(self.conn, 2026))
        result = datev.reconcile(self.conn, 2026, rows)
        self.assertTrue(result.is_clean)

    def test_reconcile_detects_differences(self):
        self._approve_vacation()
        # DATEV file is empty -> the approved absence is only in the calendar
        result = datev.reconcile(self.conn, 2026, [])
        self.assertFalse(result.is_clean)
        self.assertEqual(len(result.only_in_calendar), 1)
        self.assertEqual(len(result.only_in_datev), 0)

    def test_reconcile_detects_day_mismatch(self):
        self._approve_vacation()
        rows = datev.parse_csv(datev.export_csv(self.conn, 2026))
        tampered = [
            datev.AbsenceRow(
                personnel_no=rows[0].personnel_no, name=rows[0].name,
                absence_key=rows[0].absence_key, start_date=rows[0].start_date,
                end_date=rows[0].end_date, days=3, kind=rows[0].kind,
                status=rows[0].status,
            )
        ]
        result = datev.reconcile(self.conn, 2026, tampered)
        self.assertEqual(len(result.day_mismatches), 1)


if __name__ == "__main__":
    unittest.main()
