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

### 3.2 Was PMS strukturiert liefert (verifiziert 2026-09-22, Test-Flow `aD0u5lDXIrN2mDMs`)

| Feld | Status | Quelle im FHIR-Bundle |
|---|---|---|
| Produkt, Marke, Darreichungsform | strukturiert | `MedicinalProductDefinition.name.part` (Codes 220000000002/4/5) |
| EU-MA-Nummer **je Packung** | strukturiert | `RegulatedAuthorization.identifier` mit `subject = PackagedProductDefinition/{id}` |
| Basis-MA-Nr. + Verfahrensnummer | strukturiert | `RegulatedAuthorization` mit `subject = MedicinalProductDefinition`, **nur `EU/1/…`** wählen (Orphan-Designationen `EU/3/…` hängen am selben Subject) |
| MAH | strukturiert | `RegulatedAuthorization.holder.display` |
| Menge je Unit | strukturiert | `Ingredient.substance.strength[].presentationRatio` (Achtung: `strength` liegt **unter `substance`**), Ingredient mit `for = ManufacturedItemDefinition` → z. B. 20 mg / 1 pre-filled syringe |
| Volumen je Unit / Konzentration | strukturiert, produktweit | Ingredient mit `for = AdministrableProductDefinition` → 20 mg / 0,4 ml (`amount_and_volume`) oder 114,3 mg / 1 ml (`concentration_only`) |
| Units je Packung | strukturiert (neuere Datensätze) | `PackagedProductDefinition.containedItemQuantity` (Wert + Unit-Typ-Code); sonst `description` („Package_size:1 …", „Pack size of 1 vial", „IN A VIAL" → 1) |
| Packungsspezifisches Volumen | Freitext | `description` „Content:0.4 mL (50 mg/mL)" — **hat Vorrang** vor dem produktweiten Ratio (Amgevita: /001 = 0,4 ml, /010 = 0,2 ml bei gleichem Produkt) |
| Pulver: rekonstituierte Konzentration | strukturiert | APD-Ratio (Adcetris 5 mg/ml) → Rekonstitutionsvolumen ableitbar = Menge / Konzentration (50 mg / 5 = 10 ml); gegen SmPC verifizieren |
| Biosimilar-Status | **nicht** in PMS | EMA-Medicines-Liste (`canonical.product.is_biosimilar`) |

Mehrere PMS-IDs je Produkt: `6000…` = EU-Ebene (Basis-Nr., Packungen, ggf. Orphan), `7000…` = nationale/sprachliche Varianten derselben MA-Nummer → **`6000…` bevorzugen**, Schlüssel = MA-Nummer der Packung.

Coverage per Namenssuche im Pilot: 141/151 EU-Produkte (93 %). Fehlend u. a. Advate, Idelvion (Gerinnungsfaktoren), Naglazyme, Nexviadyme, Strensiq (Enzyme), Kineret, Blincyto, Gazyvaro, Vyvgart, Silapo → Import-Flow braucht **EU-MA-Nummer als Fallback-Schlüssel**.

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

## 7. Umgesetzt in `canonical` (Migrationen, 2026-09-22)

| Objekt | Status | Zweck |
|---|---|---|
| `canonical.inn_stem` (28 Zeilen, RLS an) | ✅ angelegt + befüllt | WHO-Stammtabelle (§2); `effect` = include / review / exclude |
| `canonical.inn_stem_hits(inn)`, `inn_scope_status(inn)` | ✅ | Wort-basierter Suffix/Präfix/Zweitwort-Abgleich |
| `canonical.regulatory_molecule.scope_status / scope_class` | ✅ befüllt | 353 in_scope · 11 review · 1.367 out_of_scope |
| `canonical.classify_molecule_scope()` | ✅ | setzt `molecule.core_scope_status` (193 in_scope, 2 review, 19 out) — manuelle Werte bleiben |
| `canonical.stem_class_to_detail()` | ✅ | mappt Stamm-Klasse auf den CHECK-Katalog von `molecule_class_detail` |
| `canonical.v_pms_import_candidates` + RPC `public.pms_import_candidates` | ✅ | **561 Kandidaten** (EU, Scope, nicht withdrawn, keine ATMP; 162 Biosimilars, 10 review = Antisense) |
| `canonical.presentation_equivalence` (RLS an) | ✅ angelegt | EU↔US-Match-Status (§5) |
| `canonical.presentation` +18 Spalten | ✅ | `units_per_pack`, `amount_per_unit_*`, `reconstituted_volume_per_unit_ml`, `pms_*`, `field_sources`, `needs_review`, `manual_locked`, 6 Aliquot-Spalten |
| `canonical.propose_aliquots()` / `_fallback()` | ✅ | Regel n ≤ 50, sonst ≤ 100; 20–400 µl |
| `public.canonical_upsert_pms_extract(run_id, payload)` | ✅ angelegt, Batch-Test ausstehend | Upsert Produkt/Präsentation/Market-Code, respektiert `manual_locked` |

Offen (bewusst nicht angefasst): RLS auf `canonical.presentation_package`.

## 7a. n8n-Flows

| Flow | ID | Zweck |
|---|---|---|
| TEST — EMA PMS Public API Strukturtest | `aD0u5lDXIrN2mDMs` | verifizierte Extraktion (4 Produkte) + Suchschlüssel-Test |
| **EMA PMS → canonical Import** | `IHDoKwgYA2PpDhoj` | Kandidaten (RPC) → Namenssuche → 6000…-Filter → `$everything` → Extraktion → `pms_stage` → Upsert; Batch über `Parameter`-Node (limit/offset) |

Credentials (einmalig in der UI anhängen): „EMA PMS Public API (OAuth2)" an `PMS Suche Name` + `PMS $everything`; „Supabase account FDA EMA" an `Kandidaten`, `Stage RPC`, `Upsert canonical`.

Suchschlüssel-Befund: Namenssuche findet alle 10 zuvor fehlenden Produkte (Contains-Suche, bis 44 Treffer); `RegulatedAuthorization?identifier=` ist in der Public API **nicht exponiert** (404). Definitiver Join = Verfahrensnummer `EMEA/H/C/…` (`regulatory_product.ema_nr` ↔ `RegulatedAuthorization.case.identifier`).

## 7b. Extraktions- und Import-Regeln (verifiziert an 10 Produkten / 170 Packungen, 2026-09-22)

| Regel | Umsetzung |
|---|---|
| **Primäreinheit je Produkt** | `IU`, wenn irgendein PMS-Verhältnis IU liefert (Epoetine, Insuline, Faktoren); sonst Masse, `mg`/`mcg`/`g` auf **mg** normalisiert. Einheiten werden nie gemischt; Zweiteinheiten landen in `secondary_strengths`. |
| **Menge je Unit** | Summe der Fertigeinheiten-Verhältnisse (`Ingredient for ManufacturedItemDefinition`) in der Primäreinheit — Insulin-Mischungen (Actraphane 30: 210 IU + 90 IU = 300 IU/Pen) werden summiert; verschiedene Substanz-Codes → `needs_review` „Kombination". |
| **Volumen je Unit** | Packungsbeschreibung (`Content: x mL`, `… OF 0.3 ML`, `CONTAINING 3 ML`, `3 mL per Pen`, `N x V ml`) hat Vorrang vor dem produktweiten APD-Verhältnis. |
| **Units je Packung** | `containedItemQuantity`, sonst Beschreibung (`Package_size:N`, `Pack size of N`, Zahlwörter „FIVE PRE-FILLED SYRINGE(S)", `IN A VIAL` → 1). |
| **Pulver** | Menge je Vial + rekonstituierte Konzentration (APD) → Rekonstitutionsvolumen = Menge / Konzentration; `total_volume_basis = reconstituted_derived`, SmPC-Prüfvermerk. |
| **Dedupe** | Mehrere PMS-Datensätze (`6000…`, Sprach-/Länder-Varianten) je MA-Nummer → der vollständigste (Score aus Units, Menge, Volumen, Struktur) gewinnt. Im Test: 264 Duplikate → 170 eindeutige Packungen. |
| **Join** | Nur Bundles, deren Verfahrensnummer (`EMEA/H/C/…`) zum Kandidaten passt, werden geschrieben. |
| **Schutz kuratierter Daten** | 775 vorbestehende EU-Präsentationen sind `manual_locked`: bestehende Werte bleiben, NULL-Felder werden aufgefüllt. Sperre per SQL aufhebbar. |
| **Aliquot-Vorschlag** | kleinstes Volumen aus {20…400 µl} mit n ≤ 50, sonst ≤ 100; wenn selbst 400 µl > 100 ergibt → 100 × 400 µl (`capped_100`). Bestätigte Werte werden nie überschrieben. |
| **Batching** | Import läuft selbst-fortsetzend in 100er-Batches (`pms_import_candidates(p_exclude_run_id)`), um n8n-Speicher zu schonen (~10 `$everything`-Bundles je Kandidat). |

## 8. Umsetzungsreihenfolge

1. ✅ Strukturtest verifiziert.
2. ✅ `inn_stem` + Scope-Abgleich (561 Kandidaten); Review-Fälle = 10 Antisense-Produkte.
3. ✅ Import-Flow `IHDoKwgYA2PpDhoj` batch-getestet (10 Produkte → 170 Packungen, 0 Fehler). Vollabzug: Flow wiederholt starten, bis `Summary.candidates == 0`; danach `needs_review`-Queue (SmPC) abarbeiten.
4. Liste der EU-MA-Produkte an Sascha → ABDA-Rücklauf (PZN, AEK) → Load nach `presentation_market_code`.
5. openFDA-Abgleich → `presentation_equivalence`.
6. Aliquot-Vorschläge berechnen → manuelle Bestätigung.
7. Webseiten-Export.
