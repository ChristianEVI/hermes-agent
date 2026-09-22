# Anweisung: Evidentic Biologika-Referenzdatenbank

Stand: 2026-09-22 · Status: **abgestimmt** (alle offenen Entscheidungen geklärt)
Datenbasis: Supabase-Projekt „Sales Engine" (`tibfpnoeerzonkkxecmb`), Schema **`canonical`**

## 0. Ziel

Alle biotechnologisch relevanten Arzneimittel (ohne Vakzine, ohne Zell-/Gentherapie)
über ihre WHO-INN-Endung identifizieren, für den **EU-Markt** jede Präsentation
erfassen, mit **DE (PZN)** und **US (NDC)** verknüpfen und daraus eine
**Referenzdatenbank** mit vier Kernfeldern je Packung aufbauen:
Gesamtmenge/-volumen · Identifier (EU-MA-Nr., PZN, NDC) · Standardpreis (AEK) ·
Standard-Aliquotzahl.

## 1. Grundsatzentscheidungen

| Thema | Entscheidung |
|---|---|
| Datenmodell | **`canonical` weiterverwenden und ergänzen.** Kein Neuaufbau, keine Parallelkopie. `regbio.*` ist deprecated und wird eingefroren (Sync abschalten, separates Ticket). |
| Bezugsebene | **Eine Zeile pro Packung = pro PZN.** Verschiedene Packungsgrößen desselben Produkts sind eigene Präsentationen. |
| Regionen | EU = Leitsystem (MA-Nummer), DE = Preis + PZN, US = Pendant (NDC), nur wenn parallel im Markt. |
| Originalprodukt | Nur Präparate des Originalherstellers. Kriterium: ABDA-Spalte **„Parallelimport = Nein"**. Parallel-/Re-Importe werden nicht erfasst. |
| Biosimilars | Sind **keine** Originalprodukte, werden aber als eigene Produkte mit eigener PZN erfasst und in der Spalte `is_biosimilar` gekennzeichnet (Quelle: EMA-Medicines-Liste; `canonical.product.is_biosimilar` existiert). |
| US-Match `concentration_only` | Wird **auf der Webseite gezeigt**, mit Kennzeichnung — der Kunde soll die Originalkonzentration der Präsentation sehen. |
| Vakzine | Raus. |
| Zell-/Gentherapie (`-cel`, `-gene`) | Raus. |
| Antisense (`-rsen`) | Rein, mit Prüfvermerk (kleine intrathekale Volumina). |

## 2. Schritt 1 — WHO-INN-Stammtabelle (`canonical.inn_stem`, neu)

Einziger Ort, an dem der Scope definiert wird. Spalten: `stem`, `match_rule`
(suffix / prefix / second_word), `class`, `is_active`, `note`.

| Klasse | Stämme | Regel |
|---|---|---|
| Monoklonale Antikörper (bis 2021) | `-mab` | suffix |
| Monoklonale Antikörper (ab 2021/22) | `-tug`, `-bart`, `-mig`, `-ment` | suffix |
| ADC | mAb-Stamm **+** Payload: `vedotin`, `mafodotin`, `deruxtecan`, `govitecan`, `emtansine`, `ozogamicin`, `tesirine` … | second_word |
| Fusionsproteine | `-cept` | suffix |
| Peptide | `-tide`, `-relin` | suffix |
| siRNA | `-siran` | suffix |
| Antisense | `-rsen` | suffix, Prüfvermerk |
| Enzyme | `-ase` | suffix |
| Insuline | `insulin ` | prefix |
| Erythropoetine | `-poetin` | suffix |
| Interleukine / Zytokine | `-kin`, `interferon ` | suffix / prefix |
| Gerinnungsfaktoren | `-cog` | suffix (CBER-Lücke in openFDA prüfen) |
| Koloniestimulierende Faktoren | `-stim` | suffix |
| Wachstumsfaktoren | `-ermin` | suffix |

Ergebnis des Abgleichs wird in `canonical.molecule.core_scope_status`
(`in_scope` / `out_of_scope` / `review`) und `molecule_class_detail` geschrieben.
Beide Spalten sind heute zu >90 % leer.

## 3. Schritt 2 — EU-APIs und -Präsentationen (EMA)

### 3.1 Quellen
- **PMS API** (`https://api.pms.ema.europa.eu/public/v1/MedicinalProductDefinition/{id}/$everything`,
  Suche: `…/MedicinalProductDefinition?name=…`) — verlangt ein **SPOR-Bearer-Token**
  (OAuth2 Client-Credentials; ohne Token: HTTP 401 „APIM. Not authorized"). Ein passendes
  OAuth2-Credential existiert bereits in n8n (genutzt im Pilot-Flow „AUDIT — EMA PMS
  Präsentationen (Pilot)", Node „everything"; `regbio.stg_pms_everything`, 990 Produkte).
  Rate-Limit beachten: Pilot lief mit 8 Requests / 1,3 s.
- **EMA-Medicines-Liste** (bestehender Flow „EMA Drug List Biologics - Sync") — liefert Biosimilar-Flag und Zulassungsstatus.
- **SmPC (PDF)** — Fallback für Unit-Anzahl und Rekonstitutionsvolumen.
- SPOR-Zugänge: **PMS-Token-Credential** (vorhanden, s. o.); **SMS Industry API** (Substanz-Stammdaten) nutzbar; **UPD** ist Tierarzneimittel → irrelevant; Historic Data Registration nicht nötig. Zugangsdaten nur als n8n-Credential, nie im Chat/Repo.

### 3.2 Was PMS strukturiert liefert (Pilot-Befund)
| Feld | Status |
|---|---|
| Produkt, Marke, Darreichungsform, Route | strukturiert |
| EU-MA-Nummer **je Packung** | strukturiert (`RegulatedAuthorization`) |
| MAH | strukturiert (`holder.display`) |
| Stärke | strukturiert, **zwei Muster**: `presentationRatio` (Menge **und** Volumen je Behältnis, z. B. Mvasi 400 mg / 16 ml) oder `concentrationRatio` (nur mg/ml, Volumen fehlt) |
| Unit-Anzahl je Packung | `packaging.containedItem` nur bei ~26 % der Produkte; sonst nur `description`-Freitext (`Packaging:… Package_size:… Content:…`) → Parser + SmPC-Fallback |
| Biosimilar-Status | **nicht** in PMS (kein `legalBasis`) → EMA-Medicines-Liste |
| Rekonstitutionsvolumen | nicht in PMS → SmPC |

### 3.3 Regeln Menge/Volumen
- Lösungen: `Menge/Unit` und `Volumen/Unit` aus `presentationRatio`; bei
  `concentrationRatio` Volumen aus `description` oder SmPC ergänzen.
- **Pulver/Lyophilisate:** erfasst wird die **Wirkstoffmenge je Unit**; das
  **Rekonstitutionsvolumen** und das daraus resultierende **Endvolumen** kommen aus
  dem SmPC → Gesamtvolumen = Units × Endvolumen.
- Packung: `Gesamtmenge = Units × Menge/Unit`, `Gesamtvolumen = Units × Volumen/Unit`.
- Konzentration ist abgeleitet (Anzeigefeld), kein Erfassungsfeld.

## 4. Schritt 3 — Deutschland: PZN und Standardpreis (ABDA)

Prozess mit **Sascha** (einziger ABDA-Zugang):
1. Wir liefern ihm die Liste der relevanten **EU-MA-Produkte** (nicht alle Produkte).
2. Er filtert in der ABDA auf **Parallelimport = Nein** und gibt je verfügbarer
   deutscher Präsentation zurück: **PZN, Zulassungs-Nr. (→ Link zur EU-MA-Nr.), AEK/AEP
   (Standardpreis), Preisdatum, Anbieter**.
3. Import nach `canonical.presentation_market_code` mit `market = 'DE'`,
   `code_type = 'pzn'`, `reference_price`, `reference_price_date`,
   `reference_price_source = 'ABDA'`.

Der Preis ist ein **einmaliger Referenzwert**, freibleibend; Nachprüfung nur bei
konkretem Kundenbedarf. Das Format ist bekannt: `regbio.stg_abda_flat` (2.958 Zeilen,
Spalten `pzn`, `zulassung_nr`, `grosso` = AEK, `grosso_datum`, `anbieter`, …) —
heute noch nicht nach `canonical` geladen (0 PZN, 0 Preise in `presentation_market_code`).

## 5. Schritt 4 — USA: NDC-Pendant (openFDA)

openFDA liefert **Produkt- und Präsentationsdaten**, keine Preise:
- `drug/drugsfda` → BLA-Nummer, Sponsor, Stärke, Marketing-Status (Produktebene)
- `drug/ndc` → `product_ndc` + `packaging[]` mit `package_ndc` und Beschreibung
  („10 mL in 1 VIAL") → Füllvolumen, Unit-Anzahl; `active_ingredients.strength` → Konzentration
- `drug/label` → „How Supplied" / „Dosage Forms and Strengths" als Fallback

Gesamtmenge US = Konzentration × Füllvolumen (parsen) oder aus dem Label.
Hinweis: einige CBER-Biologika (v. a. Plasmaderivate / Gerinnungsfaktoren) fehlen in
Drugs@FDA/NDC — beim ersten Abzug prüfen.

**Match-Regel EU ↔ US** (neue Tabelle `canonical.presentation_equivalence`):

| `match_status` | Bedeutung | Webseite |
|---|---|---|
| `exact` | gleiche Konzentration **und** gleiche Menge/Volumen je Unit | als US-Pendant |
| `concentration_only` | gleiche Konzentration, andere Gesamtmenge (Cetuximab-Fall) | gezeigt, gekennzeichnet |
| `api_only` | gleicher Wirkstoff, keine passende Präsentation | intern |
| `none` | in den USA nicht im Markt | intern |

## 6. Referenzdatenbank — vier Pflichtfelder je Packung (PZN)

1. **Gesamtmenge, Gesamtvolumen** (`presentation.total_amount_value`, `fill_volume_value`; Konzentration abgeleitet)
2. **Identifier**: EU-MA-Nr., PZN, NDC (`presentation_market_code`)
3. **Standardpreis AEK** (`presentation_market_code.reference_price` für DE)
4. **Standard-Aliquote** — neue Spalten `aliquot_volume_proposed_ul`,
   `aliquot_count_proposed`, `aliquot_volume_confirmed_ul`, `aliquot_count_confirmed`,
   `aliquot_confirmed_by`, `aliquot_confirmed_at`.

Aliquot-Vorschlagslogik (System schlägt vor, Mensch bestätigt):
- Kandidaten-Volumen {20, 30, 40, 50, 100, 200, 400} µl; Tube 0,5 ml Low-Binding Eppendorf.
- Grenzen 5–400 µl; Ziel **≤ 50 Aliquote**, hartes Maximum **100**.
- Wähle das kleinste Kandidaten-Volumen mit `n = Gesamtvolumen / v ≤ 50`; sonst das kleinste mit `n ≤ 100`.
- Bestehende `canonical.aliquot_product` / `aliquot_lot` bleiben das operative System; die Vorschlagsfelder hängen an der Präsentation.

## 7. Erweiterungsplan `canonical` (Migrationen)

| Objekt | Art | Zweck |
|---|---|---|
| `canonical.inn_stem` | neue Tabelle | WHO-Stammtabelle (§2) |
| `canonical.molecule.core_scope_status`, `molecule_class_detail` | befüllen | Scope-Ergebnis |
| `canonical.presentation_equivalence` | neue Tabelle | EU↔US-Match mit `match_status` (§5) |
| `canonical.presentation` | 6 neue Spalten | Aliquot-Vorschlag/-Bestätigung (§6) |
| `canonical.presentation_market_code` | Daten laden | PZN + AEK aus ABDA (§4) |
| `canonical.presentation_package` | RLS aktivieren | einzige `canonical`-Tabelle ohne RLS |

## 8. Umsetzungsreihenfolge

1. n8n **„TEST — EMA PMS Public API Strukturtest"** (`aD0u5lDXIrN2mDMs`): OAuth2-Credential am HTTP-Node auswählen, ausführen → bestätigt Datenform.
2. `inn_stem` anlegen, Scope-Abgleich über `canonical.molecule` laufen lassen, Review der `review`-Fälle.
3. n8n-**Import-Flow PMS → `canonical`** (Produkt, Präsentation, MA-Nr., Stärke; Parser für `description`; SmPC-Fallback-Queue).
4. Liste der EU-MA-Produkte an Sascha → ABDA-Rücklauf (PZN, AEK) → Load nach `presentation_market_code`.
5. openFDA-Abgleich → `presentation_equivalence`.
6. Aliquot-Vorschläge berechnen → manuelle Bestätigung.
7. Webseiten-Export.
