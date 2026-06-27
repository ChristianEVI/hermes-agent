# Urlaubskalender mit Audit-Trail

Ein schlankes Urlaubsverwaltungs-Modul für Firmen mit **< 10 Mitarbeitern** —
komplett auf der Python-Standardbibliothek (`http.server` + `sqlite3`) gebaut,
**ohne externe Abhängigkeiten** und ohne Build-Schritt. Läuft auf einem $5-VPS
genauso wie lokal.

```bash
python -m vacation_calendar            # http://127.0.0.1:8770
# Demo-Login: chef@example.com / passwort
```

Beim ersten Start wird die SQLite-Datenbank angelegt und mit einer kleinen
Demo-Firma befüllt (Chef, eine Vorgesetzte, vier Mitarbeitende).

## Erfüllte Anforderungen

| # | Anforderung | Umsetzung |
|---|-------------|-----------|
| 1a | Jahresurlaubstage je Mitarbeiter eintragbar | Admin-Verwaltung → `entitlements.annual_days` |
| 1b | Jeder sieht nur seine eigenen Urlaubstage | Rollen-/Sichtbarkeitsprüfung in `service.py` (`can_view`) |
| 1c | Anzeige Gesamturlaub / Resturlaub / Resturlaub Vorjahr | Dashboard-Karten, `entitlements.balance()` |
| 1d | Sperrzeiten eintragbar | `blackout_periods`, Verwaltung + Blockierung bei Antrag |
| 2a | Zusätzlicher „K.O.-Tag" (bezahlt, kein Urlaub) | eigene Antragsart `kind='ko'`, separat von Urlaub geführt |
| 2b | Admin trägt Anzahl K.O.-Tage individuell ein | `set_ko_days()` / Verwaltung |
| 3a | Grafischer Schemaablauf mit Statusanzeigen | `templates.workflow_graphic()` (Pending → Approved/Not Approved/Cancelled) |
| 3b | Vorgesetzte/Chef genehmigen/ablehnen im Dashboard | Genehmigen/Ablehnen-Buttons, `decide_request()` |
| 4a | Abgleich mit DATEV-Personalmanagement | `datev.py`: CSV-Export, -Import und Abgleich (Reconcile) |
| ✚ | Audit-Trail | append-only, SHA-256-Hashkette, Manipulationserkennung |

## Architektur

```
vacation_calendar/
├── __main__.py        # python -m vacation_calendar  (CLI/Server-Start)
├── server.py          # http.server-Router, Sessions, Seiten
├── templates.py       # HTML (Dashboard, grafischer Workflow, Tabellen)
├── templates_admin.py # Admin-, Audit- und DATEV-Seiten
├── service.py         # Geschäftslogik + Rollen/Rechte + Audit-Verknüpfung
├── workflow.py        # Antrags-State-Machine (Pending/Approved/…)
├── entitlements.py    # Saldenberechnung (Gesamt/Rest/Vorjahr/K.O.)
├── dates.py           # Arbeitstage (Mo–Fr), Sperrzeiten-Überlappung
├── datev.py           # DATEV-CSV-Export/-Import + Abgleich
├── audit.py           # append-only, hash-chained Audit-Trail
├── auth.py            # PBKDF2-Passwörter + signierte Session-Cookies
├── db.py              # SQLite-Schema, Append-only-Trigger
├── seed.py            # Demo-Daten
└── clock.py           # überschreibbare Zeitquelle (für Tests)
```

## Rollen

* **employee** – sieht nur eigene Daten; stellt eigene Anträge, kann offene
  Anträge zurückziehen.
* **manager** (Vorgesetzte/r) – sieht zusätzlich die direkt zugeordneten
  Mitarbeitenden und genehmigt/lehnt deren Anträge ab.
* **admin** (Chef) – verwaltet Mitarbeitende, Urlaubstage, K.O.-Tage und
  Sperrzeiten, entscheidet über alle Anträge und liest den Audit-Trail.

## Antrags-Workflow

```
                 ┌─ approve ─▶ Genehmigt (Approved)
 Beantragt ──────┼─ reject  ─▶ Abgelehnt (Not Approved) ◀─ revoke ─ Genehmigt
 (Pending)       └─ cancel  ─▶ Zurückgezogen (Cancelled)
```

Die erlaubten Übergänge sind in `workflow.TRANSITIONS` zentral definiert und
werden im Dashboard grafisch dargestellt (aktueller Status hervorgehoben).

## Audit-Trail (revisionssicher)

Jede Zustandsänderung wird append-only protokolliert. Die Einträge bilden eine
**Hashkette**: `entry_hash = SHA256(prev_hash ‖ kanonische_nutzdaten)`. Dadurch
verändert jede nachträgliche Manipulation alle nachfolgenden Hashes —
`audit.verify_chain()` erkennt das und nennt den betroffenen Eintrag.
Zusätzlich verbieten SQLite-Trigger `UPDATE`/`DELETE` auf `audit_log`.

## DATEV-Abgleich

`datev.py` exportiert genehmigte Fehlzeiten (Urlaub + K.O.-Tage) als
DATEV-kompatibles, semikolon-getrenntes CSV:

```
Personalnummer;Nachname;Abwesenheitsschluessel;Datum_von;Datum_bis;Tage;Art;Status
```

Der Abwesenheitsschlüssel ist konfigurierbar (`DEFAULT_ABSENCE_KEYS`), da die
konkreten DATEV-Schlüssel je Mandant in *Lohn und Gehalt* / *LODAS*
unterschiedlich konfiguriert sind. `reconcile()` vergleicht eine importierte
DATEV-Datei mit dem Kalender und zeigt Abweichungen (nur im Kalender / nur in
DATEV / abweichende Tage). Sobald API-Zugangsdaten (Berater-/Mandantennummer,
DATEVconnect) vorliegen, ist `export_rows()` die einzige Stelle, an der ein
echter Client angebunden werden muss.

## Tests

```bash
python -m unittest tests.test_vacation_calendar
```

30 Tests decken Saldenberechnung, Sichtbarkeit/Rollen, Workflow-Übergänge,
Sperrzeiten, K.O.-Tage, DATEV-Export/Abgleich und die Audit-Hashkette
(inkl. Manipulationserkennung) ab.

## Hinweise für den Produktivbetrieb

* Demo-Passwörter (`passwort`) vor dem Einsatz ändern; hinter einen
  TLS-Terminierungs-Proxy stellen (Cookies sind `HttpOnly`/`SameSite=Lax`).
* Feiertage werden in dieser Version bewusst nicht modelliert (DATEV hält den
  maßgeblichen Feiertagskalender); `dates.working_days()` akzeptiert bereits
  eine Feiertagsliste zur späteren Erweiterung.
