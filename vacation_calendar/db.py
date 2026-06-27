"""SQLite schema, connection helpers and migrations for the vacation calendar.

The whole module is intentionally backed by a single SQLite file so it can run
on a $5 VPS without any external services. Foreign keys are enabled and the
audit log is append-only (enforced both by convention in the service layer and
by a trigger that forbids UPDATE/DELETE).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

# Schema version — bump when ``SCHEMA`` changes and add a migration.
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    personnel_no  TEXT    NOT NULL UNIQUE,          -- DATEV Personalnummer
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    role          TEXT    NOT NULL DEFAULT 'employee'
                          CHECK (role IN ('employee', 'manager', 'admin')),
    manager_id    INTEGER REFERENCES employees(id),
    password_hash TEXT    NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL
);

-- One entitlement row per employee per year.
CREATE TABLE IF NOT EXISTS entitlements (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id    INTEGER NOT NULL REFERENCES employees(id),
    year           INTEGER NOT NULL,
    annual_days    REAL    NOT NULL DEFAULT 0,   -- Jahresurlaub
    carryover_days REAL    NOT NULL DEFAULT 0,   -- Resturlaub aus Vorjahr
    ko_days        INTEGER NOT NULL DEFAULT 0,   -- K.O.-Tage (Kontingent)
    UNIQUE (employee_id, year)
);

-- Company-wide blackout periods (Sperrzeiten) during which vacation is blocked.
CREATE TABLE IF NOT EXISTS blackout_periods (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    year       INTEGER NOT NULL,
    start_date TEXT    NOT NULL,                 -- ISO yyyy-mm-dd inclusive
    end_date   TEXT    NOT NULL,                 -- ISO yyyy-mm-dd inclusive
    reason     TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL
);

-- Absence requests: vacation (Urlaub) or K.O. days.
CREATE TABLE IF NOT EXISTS requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    kind        TEXT    NOT NULL CHECK (kind IN ('vacation', 'ko')),
    start_date  TEXT    NOT NULL,
    end_date    TEXT    NOT NULL,
    days        REAL    NOT NULL,                -- counted working days
    status      TEXT    NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    note        TEXT    NOT NULL DEFAULT '',
    decided_by  INTEGER REFERENCES employees(id),
    decided_at  TEXT,
    decision_note TEXT  NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL
);

-- Append-only, hash-chained audit trail.
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    actor_id    INTEGER,
    actor_name  TEXT    NOT NULL DEFAULT 'system',
    action      TEXT    NOT NULL,
    entity_type TEXT    NOT NULL,
    entity_id   TEXT,
    details     TEXT    NOT NULL DEFAULT '{}',   -- canonical JSON
    prev_hash   TEXT    NOT NULL,
    entry_hash  TEXT    NOT NULL UNIQUE
);

-- Web sessions (signed cookie also carries the id, this is the server side).
CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT    PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    created_at  TEXT    NOT NULL,
    expires_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_requests_emp  ON requests(employee_id);
CREATE INDEX IF NOT EXISTS idx_requests_stat ON requests(status);
CREATE INDEX IF NOT EXISTS idx_ent_emp_year  ON entitlements(employee_id, year);

-- Make the audit log genuinely append-only: reject any UPDATE or DELETE.
CREATE TRIGGER IF NOT EXISTS audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a connection with sensible defaults (FK on, Row factory)."""
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the schema (idempotent) and record the schema version."""
    conn.executescript(SCHEMA)
    cur = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'")
    row = cur.fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )


def fetchone(conn: sqlite3.Connection, sql: str, params: Iterable = ()) -> sqlite3.Row | None:
    return conn.execute(sql, tuple(params)).fetchone()


def fetchall(conn: sqlite3.Connection, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
    return conn.execute(sql, tuple(params)).fetchall()
