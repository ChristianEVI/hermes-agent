# Regulatory Biologics Supabase Sync — Flow-Dokumentation

n8n-Workflow-ID: `QcgMfNovIO4QedBL` · Instanz: `n8n.srv919552.hstgr.cloud`
Trigger: täglich 07:20 (Schedule) + Manual Trigger.

Dieser Sync liest die kuratierten FDA- und EMA-Biologika-Listen aus SharePoint,
parst je Präsentation die Stärke-/Messwert-Angaben, schreibt alles über die
Supabase-RPC `regbio_import` relational in das Schema `regbio` und verschickt zum
Abschluss eine Summary-Mail an `christian.schmitz@evidentic.com`.

## 1. Was an der E-Mail verbessert wurde

Der `Summary`-Node erzeugt jetzt eine strukturierte, auf einen Blick lesbare Mail
statt zweier Fließtext-Absätze:

- **Status-Banner** oben: grün „Sync erfolgreich“, grau „keine Änderungen“ oder
  rot „Sync mit Fehler“.
- **Ergebnis-Zeile**: `X neu · Y aktualisiert · Z fehlen jetzt · R zur Prüfung`.
- **Kennzahlen-Tabelle** FDA / EMA / Gesamt mit den Spalten Gesehen, Neu,
  Aktualisiert, Fehlt jetzt, Presentations, Messwerte, z. Prüfung.
- **Review-Hinweis** (gelb) nur wenn geparste Messwerte `needs_review = true` haben.
- **Fehler-Box** (rot) wenn ein Import keine gültige RPC-Antwort liefert — inkl.
  Fehlermeldung. Vorher wurde bei Fehlern nur „?“ angezeigt.
- **Betreff** transportiert das Ergebnis: `RegBio Sync: 3 neu, 1008 akt., 1 fehlend, 37 Review`
  bzw. `[FEHLER] …`.
- Der bisherige Footer mit Flow-Quelle/Link bleibt erhalten.

Robustheit: Zahlen werden defensiv aus der RPC-Antwort gelesen; fehlt `run_id`/`seen`,
wird die Quelle als fehlgeschlagen behandelt (die beiden Import-Nodes stehen auf
`onError: continueRegularOutput`, damit die Mail auch bei einem Fehler verschickt wird).

## 2. Vorläufer-Flows (was die gelesenen Listen füllt)

Dieser Flow liest nur — er befüllt die SharePoint-Listen **nicht** selbst. Das
erledigen zwei getrennte, vorgelagerte Flows:

| Vorläufer-Flow | n8n-ID | Zeit | Schreibt nach |
|---|---|---|---|
| FDA Biologics openFDA Daily Sync | `u512LLhVYlTHglb0` | 07:10 | SharePoint-Liste „FDA Drug List Biologics“ (`9e205e2a-…`) |
| EMA Drug List Biologics - Sync | `OdGa78DdESytjw3b` | 07:00 | SharePoint-Liste „EMA Drug List Biologics“ (`47f79227-…`) |

Zeitliche Staffelung: EMA 07:00 → FDA 07:10 → dieser Sync 07:20. Es besteht keine
technische n8n-Verkettung (kein „Execute Workflow“), die Kopplung erfolgt allein
über die SharePoint-Listen und die Uhrzeiten.

## 3. Nachfolger-Flows (wird das Ergebnis weiterverwendet?)

Nein. `regbio_import` schreibt in das Schema `regbio`, und diese Tabellen sind seit
2026-07-12 (Phase-6-Audit) in Supabase als **DEPRECATED** markiert:

> „verwaistes Parallel-Regulatory-Biologika-Modell, dupliziert canonical EMA/FDA,
> wird von KEINER serving/public-View oder -Function konsumiert. canonical ist die
> einzige Wahrheit. Entscheidung: einfrieren; Edge-Function-Befüllung stoppen.“

Kein anderer Flow und keine serving-View liest aktuell aus den von diesem Sync
befüllten `regbio.*`-Tabellen. Das Ergebnis löst also nichts weiter aus — außer der
Summary-Mail. (Andere Biologika-Flows wie „Biologika-LinkedIn“ hängen an separaten
Quellen/Queues, nicht an diesem Import.)

## 4. Welche Postgres-Tabellen gefüllt werden

`public.regbio_import(p_source, p_payload)` (SECURITY DEFINER, `search_path = regbio, public`)
schreibt pro Lauf in folgende Tabellen des Schemas `regbio`:

| Tabelle | Operation | Inhalt |
|---|---|---|
| `regbio.import_runs` | insert + update | ein Lauf-Datensatz (Status, Zähler, Fehler) |
| `regbio.source_records` | upsert | Roh-Datensatz je Produkt (per `source_record_key`) |
| `regbio.apis` | upsert | Wirkstoffe/INN (per `normalized_name`) |
| `regbio.drugs` | upsert | Produkt/Marke (FDA: `fda_application_number`+Brand, EMA: `ema_product_number`+Brand) |
| `regbio.drug_apis` | delete + insert | Verknüpfung Produkt ↔ Wirkstoff |
| `regbio.drug_source_xrefs` | upsert | Quellen-Cross-Reference je Produkt |
| `regbio.presentations` | upsert | Darreichungen/Packungen (nur FDA liefert welche; EMA-Payload = leer) |
| `regbio.presentation_source_xrefs` | upsert | Quellen-Cross-Reference je Präsentation |
| `regbio.presentation_measurements` | delete + insert | geparste Mess-/Stärkewerte inkl. `needs_review` |
| `regbio.sources` | update | `last_imported_at` der Quelle |

Zusätzlich setzt die Funktion am Ende `status = 'missing_in_latest_source_run'` für
`regbio.drugs` und `regbio.source_records`, die im aktuellen Lauf nicht mehr gesehen
wurden (→ Spalte „Fehlt jetzt“ in der Mail).

Nicht von diesem Flow beschrieben (aktive Staging-/Provenienz-Objekte laut Audit):
`regbio.stg_abda_flat`, `regbio.stg_pms_*`, `regbio.aliquot_presentation_link_log`, `*_log`.

## Hinweise zum Deployment

- Die Änderung am `Summary`-Node ist als neue Workflow-Version gespeichert, aber
  **noch nicht publiziert**. Die aktive (laufende) Version ist unverändert.
- Beim Speichern über die n8n-MCP-Schnittstelle gingen die Credential-Zuordnungen
  der fünf HTTP-Request-Nodes verloren (MCP kann die geteilten Credentials nicht
  automatisch zuordnen). Vor dem Publizieren müssen in der n8n-UI wieder gesetzt
  werden:
  - Read FDA List / Read EMA List / Send Email (Graph): OAuth2 „Graph SharePoint - EMA Biologics“
  - Import FDA / Import EMA: Supabase „Supabase account FDA EMA“
- Optionaler Sicherheitshinweis (Supabase-Advisor): alle `regbio.*`-Tabellen haben
  RLS deaktiviert.
