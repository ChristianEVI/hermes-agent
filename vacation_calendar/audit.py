"""Tamper-evident, append-only audit trail.

Every state change is recorded as a row in ``audit_log``. Rows form a hash
chain: each entry's ``entry_hash`` is ``sha256(prev_hash || canonical_payload)``
where ``prev_hash`` is the previous row's ``entry_hash`` (the genesis row uses
64 zeros). Because each hash commits to the entire history before it, deleting
or editing any past row breaks the chain and :func:`verify_chain` detects it.

The ``audit_log`` table additionally has triggers that forbid UPDATE/DELETE, so
tampering requires going around the application entirely — and even then the
chain check still catches it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from . import clock as _t  # local time helper (see clock.py)

GENESIS_HASH = "0" * 64


def _canonical(payload: dict) -> str:
    """Deterministic JSON encoding so the hash is reproducible."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_entry(prev_hash: str, payload: dict) -> str:
    data = (prev_hash + _canonical(payload)).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _last_hash(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["entry_hash"] if row else GENESIS_HASH


def record(
    conn: sqlite3.Connection,
    *,
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    actor_id: int | None = None,
    actor_name: str = "system",
    details: dict | None = None,
    ts: str | None = None,
) -> str:
    """Append an entry to the audit log and return its ``entry_hash``.

    ``action`` is a short verb like ``request.approve`` or ``entitlement.set``.
    ``details`` is any JSON-serialisable dict with the relevant context.
    """
    details = details or {}
    ts = ts or _t.now_iso()
    prev_hash = _last_hash(conn)
    payload = {
        "ts": ts,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "action": action,
        "entity_type": entity_type,
        "entity_id": None if entity_id is None else str(entity_id),
        "details": details,
    }
    entry_hash = _hash_entry(prev_hash, payload)
    conn.execute(
        """
        INSERT INTO audit_log
            (ts, actor_id, actor_name, action, entity_type, entity_id,
             details, prev_hash, entry_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts,
            actor_id,
            actor_name,
            action,
            entity_type,
            payload["entity_id"],
            _canonical(details),
            prev_hash,
            entry_hash,
        ),
    )
    return entry_hash


@dataclass(frozen=True)
class ChainResult:
    ok: bool
    checked: int
    broken_at: int | None = None
    reason: str = ""


def verify_chain(conn: sqlite3.Connection) -> ChainResult:
    """Walk the audit log and confirm the hash chain is intact.

    Returns :class:`ChainResult` with ``ok=False`` and the offending row id if a
    link does not validate (indicating insertion, deletion or modification).
    """
    rows = conn.execute(
        """
        SELECT id, ts, actor_id, actor_name, action, entity_type, entity_id,
               details, prev_hash, entry_hash
        FROM audit_log ORDER BY id ASC
        """
    ).fetchall()

    expected_prev = GENESIS_HASH
    checked = 0
    for row in rows:
        if row["prev_hash"] != expected_prev:
            return ChainResult(False, checked, row["id"], "prev_hash mismatch")
        payload = {
            "ts": row["ts"],
            "actor_id": row["actor_id"],
            "actor_name": row["actor_name"],
            "action": row["action"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "details": json.loads(row["details"]),
        }
        recomputed = _hash_entry(row["prev_hash"], payload)
        if recomputed != row["entry_hash"]:
            return ChainResult(False, checked, row["id"], "entry_hash mismatch")
        expected_prev = row["entry_hash"]
        checked += 1

    return ChainResult(True, checked)


def entries(conn: sqlite3.Connection, limit: int = 200) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
