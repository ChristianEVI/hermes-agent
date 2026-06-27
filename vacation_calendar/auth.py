"""Password hashing and signed session tokens — standard library only.

Passwords use PBKDF2-HMAC-SHA256 with a per-password random salt. Session
cookies are signed with an HMAC keyed by a server secret so a client cannot
forge them; the token is also stored server-side in the ``sessions`` table and
can be revoked.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3

from . import clock as _t

_PBKDF2_ROUNDS = 200_000


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, dk_hex = stored.split("$")
        assert algo == "pbkdf2_sha256"
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(dk.hex(), dk_hex)
    except (ValueError, AssertionError):
        return False


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #
def create_session(conn: sqlite3.Connection, employee_id: int, *, ttl_hours: int = 12) -> str:
    token = secrets.token_urlsafe(32)
    now = _t.now()
    expires = now + _t_delta(ttl_hours)
    conn.execute(
        "INSERT INTO sessions (token, employee_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, employee_id, now.replace(microsecond=0).isoformat(),
         expires.replace(microsecond=0).isoformat()),
    )
    return token


def _t_delta(hours: int):
    import datetime as _dt

    return _dt.timedelta(hours=hours)


def lookup_session(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    if not token:
        return None
    row = conn.execute(
        """
        SELECT s.employee_id, s.expires_at, e.*
        FROM sessions s JOIN employees e ON e.id = s.employee_id
        WHERE s.token = ?
        """,
        (token,),
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] < _t.now_iso():
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        return None
    return row


def destroy_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


# --------------------------------------------------------------------------- #
# Cookie signing
# --------------------------------------------------------------------------- #
def sign(secret: str, value: str) -> str:
    mac = hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{mac}"


def unsign(secret: str, signed: str) -> str | None:
    if not signed or "." not in signed:
        return None
    value, _, mac = signed.rpartition(".")
    expected = hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(mac, expected):
        return value
    return None
