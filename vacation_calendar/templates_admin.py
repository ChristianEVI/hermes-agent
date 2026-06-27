"""Admin-only pages: employee/entitlement/blackout management, audit log, DATEV."""

from __future__ import annotations

from typing import Sequence

from .templates import _num, esc


def admin_page(*, employees, blackouts, year, managers) -> str:
    emp_rows = []
    mgr_options = "".join(
        f'<option value="{e["id"]}">{esc(e["name"])}</option>' for e in managers
    )
    for e in employees:
        emp_rows.append(
            f"<tr><td>{esc(e['personnel_no'])}</td><td>{esc(e['name'])}</td>"
            f"<td>{esc(e['email'])}</td><td>{esc(e['role'])}</td>"
            f"<td>{esc(e['ent_annual'])}</td><td>{esc(e['ent_carry'])}</td>"
            f"<td>{esc(e['ent_ko'])}</td>"
            f"<td>{_entitlement_form(e, year)}</td></tr>"
        )
    emp_table = (
        "<table><tr><th>Pers.Nr</th><th>Name</th><th>E-Mail</th><th>Rolle</th>"
        f"<th>Jahresurlaub {esc(year)}</th><th>Vorjahr</th><th>K.O.</th>"
        f"<th>Bearbeiten</th></tr>{''.join(emp_rows)}</table>"
    )

    bo_rows = []
    for b in blackouts:
        bo_rows.append(
            f"<tr><td>{esc(b['start_date'])}</td><td>{esc(b['end_date'])}</td>"
            f"<td>{esc(b['reason'])}</td><td class=right>"
            f'<form class=inline method=post action="/admin/blackout/{b["id"]}/delete">'
            f'<button class=danger type=submit>Löschen</button></form></td></tr>'
        )
    bo_table = (
        "<table><tr><th>Von</th><th>Bis</th><th>Grund</th><th></th></tr>"
        f"{''.join(bo_rows) if bo_rows else '<tr><td colspan=4 class=muted>Keine Sperrzeiten.</td></tr>'}</table>"
    )

    new_employee = (
        '<form method=post action="/admin/employee" class=box>'
        "<h2 style=margin-top:0>Mitarbeiter anlegen</h2>"
        "<div class=grid2>"
        "<div><label>Personalnummer</label><input name=personnel_no required style=width:100%></div>"
        "<div><label>Name</label><input name=name required style=width:100%></div>"
        "<div><label>E-Mail</label><input name=email type=email required style=width:100%></div>"
        "<div><label>Passwort</label><input name=password required style=width:100%></div>"
        "<div><label>Rolle</label><select name=role style=width:100%>"
        "<option value=employee>employee</option><option value=manager>manager</option>"
        "<option value=admin>admin</option></select></div>"
        f"<div><label>Vorgesetzte/r</label><select name=manager_id style=width:100%>"
        f"<option value=''>— keine/r —</option>{mgr_options}</select></div>"
        "</div><div style=margin-top:12px><button type=submit>Anlegen</button></div></form>"
    )

    new_blackout = (
        '<form method=post action="/admin/blackout" class=box>'
        "<h2 style=margin-top:0>Sperrzeit (Sperrzeit) eintragen</h2>"
        "<div class=grid2>"
        "<div><label>Von</label><input type=date name=start_date required style=width:100%></div>"
        "<div><label>Bis</label><input type=date name=end_date required style=width:100%></div>"
        "</div><label>Grund</label><input name=reason style=width:100%>"
        "<div style=margin-top:12px><button type=submit>Eintragen</button></div></form>"
    )

    return (
        f"<h1>Verwaltung</h1><p class=muted>Urlaubstage, K.O.-Tage und Sperrzeiten "
        f"für {esc(year)}.</p>"
        f"<h2>Mitarbeiter & Urlaubstage</h2>{emp_table}{new_employee}"
        f"<h2>Sperrzeiten</h2>{bo_table}{new_blackout}"
    )


def _entitlement_form(e, year) -> str:
    return (
        f'<form class=inline method=post action="/admin/entitlement">'
        f'<input type=hidden name=employee_id value="{e["id"]}">'
        f'<input type=hidden name=year value="{esc(year)}">'
        f'<input name=annual_days value="{esc(e["ent_annual"])}" size=3 title="Jahresurlaub">'
        f'<input name=carryover_days value="{esc(e["ent_carry"])}" size=3 title="Resturlaub Vorjahr">'
        f'<input name=ko_days value="{esc(e["ent_ko"])}" size=2 title="K.O.-Tage">'
        f'<button type=submit>Speichern</button></form>'
    )


def audit_page(*, entries, chain) -> str:
    status = (
        f'<div class="flash ok">Audit-Kette intakt — {chain.checked} Einträge geprüft.</div>'
        if chain.ok
        else f'<div class="flash err">MANIPULATION ERKANNT bei Eintrag '
        f'#{esc(chain.broken_at)} ({esc(chain.reason)}).</div>'
    )
    rows = []
    for a in entries:
        rows.append(
            f"<tr><td>{esc(a['id'])}</td><td class=muted>{esc(a['ts'])}</td>"
            f"<td>{esc(a['actor_name'])}</td><td>{esc(a['action'])}</td>"
            f"<td>{esc(a['entity_type'])}/{esc(a['entity_id'])}</td>"
            f"<td class=muted style='font-size:12px;max-width:340px'>{esc(a['details'])}</td>"
            f"<td class=muted style='font-family:monospace;font-size:11px'>{esc(a['entry_hash'][:12])}…</td></tr>"
        )
    table = (
        "<table><tr><th>#</th><th>Zeit</th><th>Akteur</th><th>Aktion</th>"
        "<th>Objekt</th><th>Details</th><th>Hash</th></tr>"
        f"{''.join(rows)}</table>"
    )
    return (
        f"<h1>Audit-Trail</h1>"
        f"<p class=muted>Revisionssicheres, append-only Protokoll mit "
        f"SHA-256-Hashkette. Jede Änderung ist nachvollziehbar.</p>{status}{table}"
    )


def datev_page(*, year, reconcile_html: str = "") -> str:
    return (
        f"<h1>DATEV-Abgleich</h1>"
        f"<p class=muted>Export der Fehlzeiten (Urlaub & K.O.-Tage) im "
        f"DATEV-kompatiblen CSV-Format und Abgleich gegen eine DATEV-Datei.</p>"
        f'<div class=box><h2 style=margin-top:0>Export {esc(year)}</h2>'
        f"<p class=muted>Genehmigte Abwesenheiten als CSV "
        f"(Personalnummer; Nachname; Abwesenheitsschlüssel; Von; Bis; Tage; Art; Status).</p>"
        f'<a href="/datev/export.csv?year={esc(year)}"><button>CSV herunterladen</button></a></div>'
        f'<form method=post action="/datev/reconcile" class=box>'
        f"<h2 style=margin-top:0>Abgleich</h2>"
        f"<label>DATEV-CSV einfügen</label>"
        f"<textarea name=csv rows=8 placeholder='Personalnummer;Nachname;...'></textarea>"
        f"<input type=hidden name=year value='{esc(year)}'>"
        f"<div style=margin-top:12px><button type=submit>Abgleichen</button></div></form>"
        f"{reconcile_html}"
    )


def reconcile_result_html(result) -> str:
    def rows(items, fmt):
        return "".join(fmt(i) for i in items) or '<tr><td colspan=5 class=muted>—</td></tr>'

    cls = "ok" if result.is_clean else "err"
    summary = (
        f'<div class="flash {cls}">Abgleich abgeschlossen: '
        f"{len(result.in_both)} übereinstimmend, "
        f"{len(result.only_in_calendar)} nur im Kalender, "
        f"{len(result.only_in_datev)} nur in DATEV, "
        f"{len(result.day_mismatches)} Tage-Abweichungen.</div>"
    )

    def cal_row(r):
        return (f"<tr><td>{esc(r.personnel_no)}</td><td>{esc(r.name)}</td>"
                f"<td>{esc(r.start_date)}</td><td>{esc(r.end_date)}</td>"
                f"<td>{_num(r.days)}</td></tr>")

    def mismatch_row(pair):
        c, d = pair
        return (f"<tr><td>{esc(c.personnel_no)}</td><td>{esc(c.name)}</td>"
                f"<td>{esc(c.start_date)}</td><td>{esc(c.end_date)}</td>"
                f"<td>Kalender {_num(c.days)} ≠ DATEV {_num(d.days)}</td></tr>")

    head = "<tr><th>Pers.Nr</th><th>Name</th><th>Von</th><th>Bis</th><th>Tage</th></tr>"
    return (
        f"{summary}"
        f"<h2>Nur im Kalender (fehlt in DATEV)</h2>"
        f"<table>{head}{rows(result.only_in_calendar, cal_row)}</table>"
        f"<h2>Nur in DATEV (fehlt im Kalender)</h2>"
        f"<table>{head}{rows(result.only_in_datev, cal_row)}</table>"
        f"<h2>Abweichende Tage</h2>"
        f"<table>{head}{rows(result.day_mismatches, mismatch_row)}</table>"
    )
