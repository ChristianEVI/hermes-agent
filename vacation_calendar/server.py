"""Standard-library HTTP server tying the vacation calendar together.

No web framework — just ``http.server`` with a small regex router, signed
session cookies and server-rendered HTML. Run with::

    python -m vacation_calendar            # serves on http://127.0.0.1:8770

The database (and demo data, if empty) is created on first start.
"""

from __future__ import annotations

import re
import secrets
import sqlite3
import urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import auth, clock, datev, db, seed, templates
from . import templates_admin as ta
from .service import NotFound, PermissionDenied, Service, ServiceError, ValidationError

COOKIE_NAME = "vc_session"


def _get_secret(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = 'cookie_secret'").fetchone()
    if row:
        return row["value"]
    secret = secrets.token_hex(32)
    conn.execute("INSERT INTO meta (key, value) VALUES ('cookie_secret', ?)", (secret,))
    return secret


class Handler(BaseHTTPRequestHandler):
    server_version = "VacationCalendar/0.1"

    # -- plumbing ---------------------------------------------------------- #
    @property
    def conn(self) -> sqlite3.Connection:
        return self.server.conn  # type: ignore[attr-defined]

    @property
    def secret(self) -> str:
        return self.server.secret  # type: ignore[attr-defined]

    def log_message(self, *args):  # quieter logging
        if self.server.verbose:  # type: ignore[attr-defined]
            super().log_message(*args)

    def _actor(self) -> sqlite3.Row | None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        if COOKIE_NAME not in cookie:
            return None
        token = auth.unsign(self.secret, cookie[COOKIE_NAME].value)
        if not token:
            return None
        return auth.lookup_session(self.conn, token)

    def _form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        parsed = urllib.parse.parse_qs(raw, keep_blank_values=True)
        return {k: v[0] for k, v in parsed.items()}

    def _query(self) -> dict[str, str]:
        q = urllib.parse.urlparse(self.path).query
        parsed = urllib.parse.parse_qs(q, keep_blank_values=True)
        return {k: v[0] for k, v in parsed.items()}

    def _send_html(self, body: str, status: int = 200):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str, *, msg: str = "", err: str = ""):
        params = {}
        if msg:
            params["msg"] = msg
        if err:
            params["err"] = err
        if params:
            sep = "&" if "?" in location else "?"
            location = location + sep + urllib.parse.urlencode(params)
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def _set_session_cookie(self, token: str):
        signed = auth.sign(self.secret, token)
        cookie = SimpleCookie()
        cookie[COOKIE_NAME] = signed
        cookie[COOKIE_NAME]["path"] = "/"
        cookie[COOKIE_NAME]["httponly"] = True
        cookie[COOKIE_NAME]["samesite"] = "Lax"
        self.send_header("Set-Cookie", cookie[COOKIE_NAME].OutputString())

    # -- routing ----------------------------------------------------------- #
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            self._route_get(path)
        except ServiceError as exc:
            status = 403 if isinstance(exc, PermissionDenied) else (
                404 if isinstance(exc, NotFound) else 400)
            self._send_html(templates.page("Fehler", templates.flash(str(exc), "err"),
                                           actor=self._actor()), status=status)
        except BrokenPipeError:
            pass

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            self._route_post(path)
        except ServiceError as exc:
            ref = self.headers.get("Referer", "/")
            self._redirect(ref, err=str(exc))

    # -- GET routes -------------------------------------------------------- #
    def _route_get(self, path: str):
        if path == "/login":
            return self._send_html(templates.login_page(self._query().get("err", "")))
        if path == "/logout":
            return self._logout()

        actor = self._actor()
        if actor is None:
            return self._redirect("/login")

        q = self._query()
        flash = templates.flash(q.get("msg", ""), "ok") + templates.flash(q.get("err", ""), "err")

        if path == "/":
            return self._dashboard(actor, flash)
        if path == "/team":
            return self._team(actor, flash)
        if path == "/admin":
            return self._admin(actor, flash)
        if path == "/audit":
            return self._audit(actor, flash)
        if path == "/datev":
            return self._datev(actor, flash)
        if path == "/datev/export.csv":
            return self._datev_export(actor)

        return self._send_html(templates.page("Nicht gefunden",
                               "<h1>404</h1>", actor=actor), status=404)

    # -- POST routes ------------------------------------------------------- #
    def _route_post(self, path: str):
        if path == "/login":
            return self._login()

        actor = self._actor()
        if actor is None:
            return self._redirect("/login")
        svc = Service(self.conn)
        form = self._form()

        m = re.fullmatch(r"/requests/(\d+)/decide", path)
        if m:
            return self._decide(svc, actor, int(m.group(1)), form)
        if path == "/requests":
            return self._create_request(svc, actor, form)
        if path == "/admin/entitlement":
            return self._set_entitlement(svc, actor, form)
        if path == "/admin/blackout":
            return self._add_blackout(svc, actor, form)
        m = re.fullmatch(r"/admin/blackout/(\d+)/delete", path)
        if m:
            svc.delete_blackout(actor, int(m.group(1)))
            return self._redirect("/admin", msg="Sperrzeit gelöscht.")
        if path == "/admin/employee":
            return self._create_employee(svc, actor, form)
        if path == "/datev/reconcile":
            return self._datev_reconcile(actor, form)

        return self._redirect("/", err="Unbekannte Aktion.")

    # -- handlers ---------------------------------------------------------- #
    def _login(self):
        form = self._form()
        svc = Service(self.conn)
        emp = svc.get_employee_by_email(form.get("email", "").strip().lower())
        if emp is None or not emp["active"] or not auth.verify_password(
            form.get("password", ""), emp["password_hash"]
        ):
            return self._redirect("/login", err="E-Mail oder Passwort falsch.")
        token = auth.create_session(self.conn, emp["id"])
        self.send_response(303)
        self.send_header("Location", "/")
        self._set_session_cookie(token)
        self.end_headers()

    def _logout(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        if COOKIE_NAME in cookie:
            token = auth.unsign(self.secret, cookie[COOKIE_NAME].value)
            if token:
                auth.destroy_session(self.conn, token)
        self._redirect("/login")

    def _dashboard(self, actor, flash):
        svc = Service(self.conn)
        year = int(self._query().get("year", clock.current_year()))
        bal = svc.get_balance(actor, actor["id"], year)
        own = svc.list_requests(actor, employee_id=actor["id"])
        pending = svc.pending_for_decider(actor) if actor["role"] in ("manager", "admin") else []
        body = flash + templates.dashboard(
            actor=actor, bal=bal, own_requests=own,
            pending_decisions=pending, year=year,
        )
        self._send_html(templates.page("Dashboard", body, actor=actor, active="/"))

    def _team(self, actor, flash):
        if actor["role"] not in ("manager", "admin"):
            raise PermissionDenied("Kein Zugriff.")
        svc = Service(self.conn)
        year = clock.current_year()
        members = []
        for e in svc.list_employees(actor):
            if e["id"] == actor["id"]:
                continue
            members.append({"employee": e, "balance": svc.get_balance(actor, e["id"], year)})
        body = flash + templates.team_page(actor=actor, members=members)
        self._send_html(templates.page("Team", body, actor=actor, active="/team"))

    def _admin(self, actor, flash):
        svc = Service(self.conn)
        if actor["role"] != "admin":
            raise PermissionDenied("Kein Zugriff.")
        year = clock.current_year()
        employees = []
        for e in svc.list_employees(actor):
            ent = db.fetchone(
                self.conn, "SELECT * FROM entitlements WHERE employee_id = ? AND year = ?",
                (e["id"], year),
            )
            employees.append({
                **dict(e),
                "ent_annual": ent["annual_days"] if ent else 0,
                "ent_carry": ent["carryover_days"] if ent else 0,
                "ent_ko": ent["ko_days"] if ent else 0,
            })
        managers = [e for e in svc.list_employees(actor) if e["role"] in ("manager", "admin")]
        blackouts = svc.list_blackouts(year)
        body = flash + ta.admin_page(employees=employees, blackouts=blackouts,
                                      year=year, managers=managers)
        self._send_html(templates.page("Verwaltung", body, actor=actor, active="/admin"))

    def _audit(self, actor, flash):
        svc = Service(self.conn)
        entries = svc.audit_entries(actor)
        chain = svc.verify_audit(actor)
        body = flash + ta.audit_page(entries=entries, chain=chain)
        self._send_html(templates.page("Audit", body, actor=actor, active="/audit"))

    def _datev(self, actor, flash, reconcile_html=""):
        if actor["role"] != "admin":
            raise PermissionDenied("Kein Zugriff.")
        year = int(self._query().get("year", clock.current_year()))
        body = flash + ta.datev_page(year=year, reconcile_html=reconcile_html)
        self._send_html(templates.page("DATEV", body, actor=actor, active="/datev"))

    def _datev_export(self, actor):
        if actor["role"] != "admin":
            raise PermissionDenied("Kein Zugriff.")
        year = int(self._query().get("year", clock.current_year()))
        csv_text = datev.export_csv(self.conn, year)
        data = csv_text.encode("utf-8-sig")  # BOM so Excel/DATEV detect UTF-8
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         f'attachment; filename="datev_fehlzeiten_{year}.csv"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _datev_reconcile(self, actor, form):
        if actor["role"] != "admin":
            raise PermissionDenied("Kein Zugriff.")
        year = int(form.get("year", clock.current_year()))
        rows = datev.parse_csv(form.get("csv", ""))
        result = datev.reconcile(self.conn, year, rows)
        self._datev(actor, "", reconcile_html=ta.reconcile_result_html(result))

    def _create_request(self, svc, actor, form):
        svc.create_request(
            actor, kind=form.get("kind", "vacation"),
            start_date=form["start_date"], end_date=form["end_date"],
            note=form.get("note", ""),
        )
        self._redirect("/", msg="Antrag eingereicht.")

    def _decide(self, svc, actor, request_id, form):
        action = form.get("action", "")
        new_state = svc.decide_request(actor, request_id=request_id, action=action,
                                       decision_note=form.get("decision_note", ""))
        self._redirect(self.headers.get("Referer", "/"),
                       msg=f"Antrag aktualisiert: {new_state}.")

    def _set_entitlement(self, svc, actor, form):
        svc.set_entitlement(
            actor, employee_id=int(form["employee_id"]), year=int(form["year"]),
            annual_days=float(form["annual_days"]),
            carryover_days=float(form["carryover_days"]),
            ko_days=int(form["ko_days"]),
        )
        self._redirect("/admin", msg="Urlaubstage gespeichert.")

    def _add_blackout(self, svc, actor, form):
        year = int(form.get("start_date", "0-0")[:4] or clock.current_year())
        svc.add_blackout(actor, year=year, start_date=form["start_date"],
                         end_date=form["end_date"], reason=form.get("reason", ""))
        self._redirect("/admin", msg="Sperrzeit eingetragen.")

    def _create_employee(self, svc, actor, form):
        manager_id = form.get("manager_id") or None
        svc.create_employee(
            actor, personnel_no=form["personnel_no"], name=form["name"],
            email=form["email"].strip().lower(), password=form["password"],
            role=form.get("role", "employee"),
            manager_id=int(manager_id) if manager_id else None,
        )
        self._redirect("/admin", msg="Mitarbeiter angelegt.")


def build_server(db_path: str, host: str = "127.0.0.1", port: int = 8770,
                 *, verbose: bool = False) -> ThreadingHTTPServer:
    conn = db.connect(db_path)
    db.init_db(conn)
    if conn.execute("SELECT COUNT(*) AS n FROM employees").fetchone()["n"] == 0:
        seed.seed(conn)
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.conn = conn          # type: ignore[attr-defined]
    httpd.secret = _get_secret(conn)  # type: ignore[attr-defined]
    httpd.verbose = verbose    # type: ignore[attr-defined]
    return httpd


def serve(db_path: str = "vacation_calendar.db", host: str = "127.0.0.1",
          port: int = 8770, *, verbose: bool = False) -> None:
    httpd = build_server(db_path, host, port, verbose=verbose)
    print(f"Urlaubskalender läuft auf http://{host}:{port}  (DB: {db_path})")
    print("Demo-Login: chef@example.com / passwort")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
