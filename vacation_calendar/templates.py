"""HTML rendering for the vacation-calendar dashboard.

Plain server-rendered HTML with a little embedded CSS — no build step, no JS
framework. The request workflow is drawn graphically in :func:`workflow_graphic`
using styled boxes and arrows, with the current status highlighted.
"""

from __future__ import annotations

import html
import sqlite3
from typing import Sequence

from . import workflow
from .entitlements import Balance

STATUS_CLASS = {
    "pending": "st-pending",
    "approved": "st-approved",
    "rejected": "st-rejected",
    "cancelled": "st-cancelled",
}
STATUS_LABEL = workflow.LABELS

KIND_LABEL = {"vacation": "Urlaub", "ko": "K.O.-Tag"}


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


CSS = """
:root{--bg:#0f1115;--card:#181b22;--line:#2a2f3a;--fg:#e6e8ee;--muted:#9aa3b2;
--accent:#5b8cff;--green:#3fb96a;--red:#e5564b;--amber:#e0a52e;--grey:#6b7280;}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);
color:var(--fg);font-size:15px;line-height:1.5}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
header{background:#13161c;border-bottom:1px solid var(--line);padding:0 20px}
header .bar{display:flex;align-items:center;gap:20px;max-width:1100px;margin:0 auto;height:56px}
header .brand{font-weight:700;letter-spacing:.04em}
nav a{color:var(--muted);padding:6px 2px;font-size:14px}
nav a.active{color:var(--fg);border-bottom:2px solid var(--accent)}
.spacer{flex:1}
main{max-width:1100px;margin:24px auto;padding:0 20px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:24px 0 10px}
.muted{color:var(--muted)}
.cards{display:flex;gap:14px;flex-wrap:wrap;margin:14px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;min-width:150px}
.card .big{font-size:26px;font-weight:700}
.card .lbl{color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.04em}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);font-size:14px}
th{color:var(--muted);font-weight:600;text-transform:uppercase;font-size:12px;letter-spacing:.04em}
tr:last-child td{border-bottom:none}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600}
.st-pending{background:rgba(224,165,46,.15);color:var(--amber)}
.st-approved{background:rgba(63,185,106,.15);color:var(--green)}
.st-rejected{background:rgba(229,86,75,.15);color:var(--red)}
.st-cancelled{background:rgba(107,114,128,.2);color:var(--grey)}
form.inline{display:inline}
input,select,textarea{background:#0e1015;border:1px solid var(--line);color:var(--fg);
border-radius:7px;padding:8px 10px;font-size:14px;font-family:inherit}
textarea{width:100%}
label{display:block;font-size:13px;color:var(--muted);margin:8px 0 3px}
button{background:var(--accent);color:#fff;border:0;border-radius:7px;padding:8px 14px;
font-size:14px;font-weight:600;cursor:pointer}
button.ghost{background:transparent;border:1px solid var(--line);color:var(--fg)}
button.danger{background:var(--red)}button.ok{background:var(--green)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:24px}
.box{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:14px 0}
.flash{padding:10px 14px;border-radius:8px;margin:12px 0}
.flash.err{background:rgba(229,86,75,.12);color:#ffb4ac;border:1px solid rgba(229,86,75,.4)}
.flash.ok{background:rgba(63,185,106,.12);color:#aef0c4;border:1px solid rgba(63,185,106,.4)}
/* workflow graphic */
.flow{display:flex;align-items:center;gap:0;flex-wrap:wrap;margin:8px 0}
.flow .node{border:2px solid var(--line);border-radius:9px;padding:8px 12px;font-size:13px;
font-weight:600;color:var(--muted);background:#0e1015;white-space:nowrap}
.flow .node.active{color:#fff;box-shadow:0 0 0 2px rgba(91,140,255,.25)}
.flow .node.active.pending{border-color:var(--amber);color:var(--amber)}
.flow .node.active.approved{border-color:var(--green);color:var(--green)}
.flow .node.active.rejected{border-color:var(--red);color:var(--red)}
.flow .node.active.cancelled{border-color:var(--grey);color:#cbd2dd}
.flow .arrow{color:var(--muted);padding:0 10px;font-size:18px}
.legend{font-size:12px;color:var(--muted);margin-top:6px}
.right{text-align:right}
"""


def page(title: str, body: str, *, actor: sqlite3.Row | None, active: str = "") -> str:
    nav = ""
    if actor is not None:
        items = [("/", "Dashboard")]
        if actor["role"] in ("manager", "admin"):
            items.append(("/team", "Team"))
        if actor["role"] == "admin":
            items += [("/admin", "Verwaltung"), ("/datev", "DATEV"), ("/audit", "Audit")]
        links = "".join(
            f'<a href="{esc(href)}" class="{"active" if active == href else ""}">{esc(label)}</a>'
            for href, label in items
        )
        nav = (
            f'<nav>{links}</nav><div class="spacer"></div>'
            f'<span class="muted">{esc(actor["name"])} · {esc(actor["role"])}</span>'
            f'<a href="/logout">Abmelden</a>'
        )
    header = (
        '<header><div class="bar"><span class="brand">🌴 Urlaubskalender</span>'
        f'{nav}</div></header>'
    )
    return (
        f"<!doctype html><html lang=de><head><meta charset=utf-8>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{esc(title)}</title><style>{CSS}</style></head><body>"
        f"{header}<main>{body}</main></body></html>"
    )


def flash(message: str, kind: str = "ok") -> str:
    if not message:
        return ""
    return f'<div class="flash {esc(kind)}">{esc(message)}</div>'


def login_page(error: str = "") -> str:
    body = (
        "<h1>Anmeldung</h1>"
        '<p class="muted">Urlaubskalender mit Audit-Trail</p>'
        f"{flash(error, 'err') if error else ''}"
        '<form method=post action="/login" class=box style="max-width:360px">'
        "<label>E-Mail</label><input name=email type=email required autofocus style=width:100%>"
        "<label>Passwort</label><input name=password type=password required style=width:100%>"
        '<div style="margin-top:14px"><button type=submit>Anmelden</button></div>'
        '<p class="legend">Demo: chef@example.com · manager@example.com · '
        'erik@example.com — Passwort: passwort</p>'
        "</form>"
    )
    return page("Anmeldung", body, actor=None)


def workflow_graphic(current: str) -> str:
    """Render the request workflow as a highlighted flow diagram."""
    order = ["pending", "approved", "rejected", "cancelled"]
    nodes = []
    for i, state in enumerate(order):
        active = "active" if state == current else ""
        nodes.append(
            f'<div class="node {active} {state}">{esc(STATUS_LABEL[state])}</div>'
        )
        if i == 0:
            nodes.append('<span class="arrow">→</span>')
    flow = (
        '<div class="flow">'
        f'{nodes[0]}{nodes[1]}'
        '<div style="display:flex;flex-direction:column;gap:6px">'
        f'{nodes[2]}{nodes[3]}{nodes[4]}'
        "</div></div>"
    )
    return (
        f"{flow}"
        '<div class="legend">Schemaablauf: Beantragt → Genehmigt / Abgelehnt; '
        "der Mitarbeiter kann einen offenen Antrag zurückziehen.</div>"
    )


def badge(status: str) -> str:
    return f'<span class="badge {STATUS_CLASS.get(status, "")}">{esc(STATUS_LABEL.get(status, status))}</span>'


def balance_cards(bal: Balance) -> str:
    def card(label, value, sub=""):
        sub_html = f'<div class="muted" style="font-size:12px">{esc(sub)}</div>' if sub else ""
        shown = value if isinstance(value, str) else _num(value)
        return (
            f'<div class="card"><div class="lbl">{esc(label)}</div>'
            f'<div class="big">{esc(shown)}</div>{sub_html}</div>'
        )

    return (
        '<div class="cards">'
        + card("Gesamturlaub", bal.total, f"{_num(bal.annual_days)} Jahresurlaub + {_num(bal.carryover_days)} Vorjahr")
        + card("Resturlaub", bal.remaining, f"{_num(bal.approved)} genommen")
        + card("Resturlaub Vorjahr", bal.carryover_days, "aus dem vergangenen Jahr")
        + card("Offen/Beantragt", bal.pending, "noch nicht entschieden")
        + card("K.O.-Tage", f"{_num(bal.ko_remaining)} / {bal.ko_total}", "verfügbar / gesamt")
        + "</div>"
    )


def _num(value) -> str:
    f = float(value)
    return str(int(f)) if f.is_integer() else f"{f:.1f}"


def requests_table(rows: Sequence[sqlite3.Row], *, actor: sqlite3.Row,
                   show_employee: bool, deciders: bool = False) -> str:
    if not rows:
        return '<p class="muted">Keine Anträge.</p>'
    head = "<tr>"
    if show_employee:
        head += "<th>Mitarbeiter</th>"
    head += ("<th>Art</th><th>Von</th><th>Bis</th><th>Tage</th><th>Status</th>"
             "<th>Notiz</th><th></th></tr>")
    body_rows = []
    for r in rows:
        cells = ""
        if show_employee:
            cells += f"<td>{esc(r['employee_name'])}</td>"
        cells += (
            f"<td>{esc(KIND_LABEL.get(r['kind'], r['kind']))}</td>"
            f"<td>{esc(r['start_date'])}</td><td>{esc(r['end_date'])}</td>"
            f"<td>{_num(r['days'])}</td><td>{badge(r['status'])}</td>"
            f"<td class=muted>{esc(r['note'])}</td>"
        )
        cells += f"<td class=right>{_action_buttons(r, actor)}</td>"
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table>{head}{''.join(body_rows)}</table>"


def _action_buttons(r: sqlite3.Row, actor: sqlite3.Row) -> str:
    if r["status"] != "pending" and r["status"] != "approved":
        return ""
    buttons = []
    is_owner = r["employee_id"] == actor["id"]
    is_decider = actor["role"] == "admin" or (
        actor["role"] == "manager" and not is_owner
    )
    # The precise decider check is enforced server-side; here we only decide
    # which buttons to show.
    if r["status"] == "pending":
        if is_decider and not is_owner:
            buttons.append(_decide_form(r["id"], "approve", "Genehmigen", "ok"))
            buttons.append(_decide_form(r["id"], "reject", "Ablehnen", "danger"))
        if is_owner:
            buttons.append(_decide_form(r["id"], "cancel", "Zurückziehen", "ghost"))
    elif r["status"] == "approved":
        if is_decider and not is_owner:
            buttons.append(_decide_form(r["id"], "revoke", "Widerrufen", "ghost"))
    return " ".join(buttons)


def _decide_form(req_id: int, action: str, label: str, cls: str) -> str:
    return (
        f'<form class=inline method=post action="/requests/{req_id}/decide">'
        f'<input type=hidden name=action value="{esc(action)}">'
        f'<button class="{esc(cls)}" type=submit>{esc(label)}</button></form>'
    )


def request_form(kind_default: str = "vacation") -> str:
    return (
        '<form method=post action="/requests" class=box style="max-width:480px">'
        "<h2 style=margin-top:0>Neuen Antrag stellen</h2>"
        "<label>Art</label>"
        "<select name=kind>"
        f"<option value=vacation {'selected' if kind_default=='vacation' else ''}>Urlaub</option>"
        f"<option value=ko {'selected' if kind_default=='ko' else ''}>K.O.-Tag</option>"
        "</select>"
        '<div class=grid2><div><label>Von</label>'
        "<input type=date name=start_date required style=width:100%></div>"
        "<div><label>Bis</label>"
        "<input type=date name=end_date required style=width:100%></div></div>"
        "<label>Notiz (optional)</label><input name=note style=width:100%>"
        '<div style="margin-top:12px"><button type=submit>Antrag absenden</button></div>'
        "</form>"
    )


def dashboard(*, actor, bal, own_requests, pending_decisions, year) -> str:
    body = [
        f"<h1>Hallo {esc(actor['name'])}</h1>",
        f'<p class="muted">Ihre Urlaubsübersicht {esc(year)} '
        f"(Personalnr. {esc(actor['personnel_no'])})</p>",
        balance_cards(bal),
        "<h2>Antrags-Workflow</h2>",
        '<div class="box">' + workflow_graphic(_latest_status(own_requests)) + "</div>",
        "<div class=grid2><div>",
        "<h2>Meine Anträge</h2>",
        requests_table(own_requests, actor=actor, show_employee=False),
        "</div><div>",
        request_form(),
        "</div></div>",
    ]
    if pending_decisions:
        body += [
            "<h2>Zu genehmigen (Ihr Team)</h2>",
            requests_table(pending_decisions, actor=actor, show_employee=True, deciders=True),
        ]
    return "".join(body)


def _latest_status(rows: Sequence[sqlite3.Row]) -> str:
    return rows[0]["status"] if rows else "pending"


def team_page(*, actor, members) -> str:
    """members: list of dicts {employee, balance}."""
    rows = []
    for m in members:
        e, b = m["employee"], m["balance"]
        rows.append(
            f"<tr><td>{esc(e['name'])}</td><td>{esc(e['personnel_no'])}</td>"
            f"<td>{_num(b.total)}</td><td>{_num(b.remaining)}</td>"
            f"<td>{_num(b.pending)}</td><td>{_num(b.carryover_days)}</td>"
            f"<td>{_num(b.ko_remaining)}/{b.ko_total}</td></tr>"
        )
    table = (
        "<table><tr><th>Mitarbeiter</th><th>Personalnr.</th><th>Gesamt</th>"
        "<th>Resturlaub</th><th>Offen</th><th>Vorjahr</th><th>K.O.</th></tr>"
        f"{''.join(rows)}</table>"
    )
    return f"<h1>Team-Übersicht</h1><p class=muted>Salden Ihrer Mitarbeiter.</p>{table}"
