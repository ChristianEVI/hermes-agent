# Evidentic OS – Modulare Architektur (Designdokument)

**Status:** Entwurf v1.0 · **Sprache:** Deutsch · **Zielgruppe:** Architektur, Entwicklung, QA/Validierung

Dieses Dokument beschreibt, wie das „Evidentic OS" – eine Plattform mit ERP, CRM,
Versand (DHL/FedEx), SecurPharm-Anbindung, GDP-konformer Beschaffung (§ 52a AMG)
und Manufacturing – als **modulares, plugin-fähiges System** gebaut wird, das

1. von menschlichen Entwicklern jederzeit verstanden, geändert und erweitert werden kann,
2. AI-agentisches Arbeiten (Coding-Agents, User-Interaction-Agents) als *zusätzlichen*
   Zugriffsweg unterstützt – niemals als einzigen,
3. nach anerkannten Standards (GAMP 5, EU-GMP Annex 11, GDP-Leitlinien) qualitäts-
   geprüft und **validierbar** ist.

---

## 1. Leitentscheidung: Modularer Monolith mit Plugin-Kernel

**Empfehlung:** Kein Microservice-Zoo zum Start, sondern ein **modularer Monolith**
(eine deploybare Anwendung) mit einem kleinen **Kernel** und streng getrennten
Modulen, die wie Plugins registriert, aktiviert und deaktiviert werden.
Microservices lassen sich später pro Modul herauslösen, weil die Modulgrenzen von
Anfang an wie Servicegrenzen geschnitten sind (eigenes Schema, eigene API, eigene Events).

Das ist genau das Modell, das Odoo, Django (Apps) und Tryton seit Jahren erfolgreich
fahren – und es ist mit Python hervorragend umsetzbar.

```
┌────────────────────────────────────────────────────────────────┐
│                        Evidentic OS                            │
│                                                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐  │
│  │   ERP    │ │   CRM    │ │ Versand  │ │ Beschaffung      │  │
│  │  Modul   │ │  Modul   │ │ DHL/FedEx│ │ (§52a AMG / GDP) │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────────┬─────────┘  │
│  ┌────┴─────┐ ┌────┴─────────┐ ┌┴────────────────┴─────────┐  │
│  │SecurPharm│ │Manufacturing │ │  weitere Module (Plugins) │  │
│  └────┬─────┘ └────┬─────────┘ └┬──────────────────────────┘  │
│       │            │            │                              │
│  ═════╪════════════╪════════════╪═══ Modul-API / Event-Bus ═══ │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ KERNEL: Modul-Registry · Lifecycle · Event-Bus ·         │ │
│  │ AuthN/AuthZ · Audit-Trail · Migrationen · Konfiguration  │ │
│  └──────────────────────────────────────────────────────────┘ │
└───────────────┬───────────────────────────┬────────────────────┘
                │                           │
        ┌───────┴────────┐          ┌───────┴───────────────────┐
        │  PostgreSQL    │          │  AI-Access-Layer          │
        │  (1 DB, ein    │          │  (MCP-Server, REST/       │
        │  Schema pro    │          │  PostgREST, Supabase-     │
        │  Modul)        │          │  Dienste optional)        │
        └────────────────┘          └───────────────────────────┘
```

**Kernprinzip:** Der Kernel weiß nichts über Fachlichkeit. Module wissen nichts
voneinander – sie kommunizieren nur über deklarierte Verträge (Interfaces + Events).

---

## 2. Antwort auf Frage 1: Plugin-Architektur in Python – ja, und so geht sie

Ja, das ist möglich und in Python sogar ein etabliertes Muster. Der „Metacode",
den Sie beschreiben, besteht aus vier Bausteinen:

### 2.1 Modul-Manifest (deklarative Selbstbeschreibung)

Jedes Modul liefert ein maschinen- **und** menschenlesbares Manifest mit:

```toml
# modules/procurement/module.toml
[module]
name          = "procurement"
version       = "1.4.2"          # SemVer, Pflicht
display_name  = "Beschaffung (GDP / §52a AMG)"
description   = "Lieferantenqualifizierung, Bestellwesen, GDP-Dokumentation"

[module.dependencies]
requires  = ["core", "erp>=2.0,<3.0"]   # harte Abhängigkeiten
optional  = ["securpharm"]              # weiche Abhängigkeiten (Feature-Erweiterung)

[module.database]
schema     = "procurement"              # eigenes PostgreSQL-Schema
migrations = "migrations/"              # Alembic-Migrationskette nur für dieses Schema

[module.provides]                       # Verträge, die dieses Modul anbietet
interfaces = ["evidentic.procurement.SupplierQualificationService"]
events     = ["procurement.order.created", "procurement.supplier.qualified"]

[module.consumes]                       # Verträge, die es von anderen nutzt
interfaces = ["evidentic.erp.ArticleService"]
events     = ["erp.article.updated"]

[module.compliance]                     # für die Validierung (siehe Kap. 6)
gxp_class      = "GAMP5-Cat5"           # kundenspezifische Software
regulations    = ["EU-GDP 2013/C 343/01", "AMG §52a", "AMWHV"]
audit_trail    = true
e_signatures   = ["supplier_qualification_approval"]
```

### 2.2 Verträge statt Direktzugriff (Interfaces + Events)

Module importieren **niemals** Code oder Tabellen anderer Module. Sie nutzen:

- **Interfaces** – in Python als `typing.Protocol` oder `abc.ABC` definiert,
  mit Pydantic-Modellen als Datenverträgen. Die Interface-Definitionen leben in
  einem schlanken, stabilen Paket `evidentic-contracts`, das unabhängig versioniert wird.
- **Events** – asynchrone Domänenereignisse über einen Event-Bus
  (In-Process zum Start; via *Transactional Outbox* in PostgreSQL persistiert,
  später ausbaubar auf NATS/RabbitMQ ohne Modul-Änderung).

```python
# evidentic_contracts/erp.py  – stabiler Vertrag, streng versioniert
from typing import Protocol
from pydantic import BaseModel

class ArticleDTO(BaseModel):
    article_id: str
    name: str
    pzn: str | None          # Pharmazentralnummer
    requires_cold_chain: bool

class ArticleService(Protocol):
    def get_article(self, article_id: str) -> ArticleDTO: ...
    def search_by_pzn(self, pzn: str) -> list[ArticleDTO]: ...
```

Warum das die Langzeit-Wartbarkeit sichert: Ein Modul kann nach Monaten oder Jahren
komplett neu geschrieben werden, solange es dieselben Verträge erfüllt. Der Rest des
Systems merkt davon nichts. Vertragsänderungen laufen über SemVer
(Major-Version = Breaking Change) und werden durch Contract-Tests in der CI erzwungen.

### 2.3 Modul-Registry und Lifecycle (aktivieren/deaktivieren)

Der Kernel führt eine Registry (Tabelle `core.modules`) mit Zustand pro Modul:
`installed → active → inactive → uninstalled`. Jedes Modul implementiert
Lifecycle-Hooks:

```python
class EvidenticModule(ABC):
    manifest: ModuleManifest

    def on_install(self, ctx): ...     # Schema anlegen, Migrationen bis HEAD fahren
    def on_activate(self, ctx): ...    # Services registrieren, Event-Handler abonnieren
    def on_deactivate(self, ctx): ...  # Services deregistrieren, sauber abmelden
    def on_uninstall(self, ctx): ...   # optional: Schema archivieren (nie löschen, GxP!)
    def health_check(self) -> Health: ...
```

Die Entdeckung der Module erfolgt über **Python Entry Points**
(`importlib.metadata`), das Standard-Plugin-Verfahren von Python – dasselbe
Prinzip, mit dem z. B. pytest seine Plugins findet:

```toml
# pyproject.toml des Moduls
[project.entry-points."evidentic.modules"]
procurement = "evidentic_procurement.module:ProcurementModule"
```

### 2.4 Kontrollierte Degradation statt Fehler-Kaskade

Ihre Sorge „dann funktionieren Teile der Datenbank nicht mehr" wird architektonisch
entschärft:

- **Abhängigkeits-Auflösung:** Der Kernel berechnet beim Aktivieren/Deaktivieren den
  Abhängigkeitsgraphen (topologische Sortierung). Ein Modul, dessen harte Abhängigkeit
  deaktiviert wird, wird mit deaktiviert – oder die Deaktivierung wird verweigert.
  Es gibt keinen halb-kaputten Zustand.
- **Weiche Abhängigkeiten degradieren sauber:** Ist z. B. `securpharm` deaktiviert,
  blendet die Beschaffung die Verifikationsfunktion aus und protokolliert dies –
  statt mit Fehlern zu laufen.
- **Daten bleiben immer erhalten:** Deaktivieren rührt das Schema nicht an. Die Daten
  eines inaktiven Moduls sind lesbar (Reporting, Audit), nur die Geschäftslogik ruht.
  In einem GxP-Umfeld werden Schemata ohnehin nie gelöscht, sondern archiviert.
- **Jedes Modul hat eine eigene Migrationskette** (Alembic mit `version_locations`
  pro Modul, ein Alembic-Branch pro Schema). Modul-Updates migrieren nur ihr
  eigenes Schema. Fremde Schemata sind per DB-Rolle nicht einmal beschreibbar.

---

## 3. Antwort auf Frage 2: Wie die modulare Bauweise konkret aussieht

### 3.1 Datenbankseite: ein PostgreSQL-Cluster, ein Schema pro Modul

| Regel | Umsetzung |
|---|---|
| Modul-Isolation | Jedes Modul erhält ein eigenes Schema (`erp`, `crm`, `shipping`, `securpharm`, `procurement`, `manufacturing`, `core`) |
| Keine Fremdzugriffe | Keine Foreign Keys über Schemagrenzen. Referenzen auf fremde Entitäten nur über stabile IDs + Events/Interfaces |
| Zugriffsschutz | Eine DB-Rolle pro Modul; `GRANT` nur auf das eigene Schema. Cross-Schema-Zugriff ist damit technisch unmöglich, nicht nur verboten |
| Audit-Trail | Zentraler, append-only Audit-Mechanismus (`core.audit_log`, Trigger-basiert): wer, was, wann, alter/neuer Wert – Annex-11-konform |
| Historie | Temporale Tabellen (Valid-Time) für GxP-relevante Stammdaten (Lieferantenstatus, Chargen) |

Warum **eine** Datenbank statt vieler: Backup/Restore, Point-in-Time-Recovery und
Validierung bleiben beherrschbar; Konsistenz für den Audit-Trail ist transaktional.
Die Schema-Trennung gibt trotzdem die Option, einzelne Module später auf eigene
Datenbanken/Services auszulagern.

### 3.2 Anwendungsseite: Schichten in jedem Modul gleich

Jedes Modul folgt derselben inneren Struktur (hexagonale Architektur / Ports & Adapters):

```
modules/shipping/
├── module.toml               # Manifest (siehe 2.1)
├── pyproject.toml            # eigenständiges Python-Paket
├── src/evidentic_shipping/
│   ├── module.py             # Lifecycle-Hooks
│   ├── domain/               # Geschäftslogik, KEINE Framework-Imports
│   ├── application/          # Use-Cases, Event-Handler
│   ├── adapters/
│   │   ├── db/               # SQLAlchemy-Repositories (nur Schema `shipping`)
│   │   ├── api/              # FastAPI-Router: /api/shipping/...
│   │   ├── dhl/              # DHL-Middleware (Carrier-Adapter)
│   │   └── fedex/            # FedEx-Middleware (gleicher Carrier-Port!)
│   └── contracts_impl.py     # Implementierung der angebotenen Interfaces
├── migrations/               # Alembic, nur Schema `shipping`
├── tests/                    # Unit-, Contract- und Integrationstests
└── docs/                     # Modulspezifikation → fließt in die Validierung ein
```

Die DHL/FedEx-Middleware ist dabei selbst ein Mini-Plugin-System: ein
`CarrierPort`-Interface, DHL und FedEx als austauschbare Adapter. Ein dritter
Carrier ist später ein neues Adapterpaket, keine Änderung am Versandmodul.

### 3.3 AI-Access-Layer: AI als weiterer Client, nie als Sonderweg

Das System exponiert **eine** wohldefinierte API-Fläche, die von drei Clients
gleichberechtigt genutzt wird: Web-UI, klassische Integrationen und AI-Agents.

- **MCP-Server** (Model Context Protocol): Der Kernel generiert aus den
  Modul-Manifesten und OpenAPI-Definitionen automatisch MCP-Tools
  (`erp_search_article`, `shipping_create_label`, `securpharm_verify_pack` …).
  Neues Modul aktiviert → Tools erscheinen; Modul deaktiviert → Tools verschwinden.
- **REST/OpenAPI** pro Modul (FastAPI), automatisch dokumentiert.
- **Supabase (optional, selbst gehostet):** Supabase ist „nur" Postgres plus
  Dienste (Auth, PostgREST, Realtime). Es kann als Realtime-/Auth-Schicht dienen.
  Für den GxP-Kern gilt aber: Geschäftslogik läuft in den Modulen, nicht in
  Datenbank-nahen Auto-APIs – sonst umgeht man Audit-Trail und Berechtigungslogik.
  Empfehlung: PostgREST/Supabase höchstens lesend für Dashboards/AI-Kontext,
  jede Schreiboperation durch die Modul-Use-Cases.

**Entscheidend:** AI-Agents besitzen eigene Service-Accounts mit denselben
Rollen-/Rechteprüfungen und demselben Audit-Trail wie Menschen. Jede AI-Aktion ist
im Audit-Log als solche gekennzeichnet. Es gibt keinen Code-Pfad, den nur eine AI
kennt oder nutzen kann.

---

## 4. Antwort auf Frage 3: Wo liegen die Module, und wie arbeiten Coder daran?

**Die Module sind ganz normaler Quellcode in einem Git-Repository.** Es gibt keine
Kompilierung in ein Black-Box-Format, keine nur-generierten Artefakte, keine
Laufzeit, die Code versteckt.

### 4.1 Ablage: Monorepo mit Paketen

```
evidentic-os/                      # EIN Git-Repository (Monorepo)
├── kernel/                        # Plugin-Kernel, Event-Bus, Auth, Audit
├── contracts/                     # evidentic-contracts (stabile Interfaces/DTOs)
├── modules/
│   ├── erp/
│   ├── crm/
│   ├── shipping/
│   ├── securpharm/
│   ├── procurement/
│   └── manufacturing/
├── ai/                            # MCP-Server, Agent-Konfiguration, Prompts
├── deploy/                        # Docker/Compose/K8s, Umgebungsdefinitionen
├── validation/                    # URS, FS, Risikoanalysen, Traceability (Kap. 6)
└── docs/
```

Ein Monorepo (mit `uv workspaces` oder vergleichbar) ist für ein Team die richtige
Wahl: atomare Änderungen über Modulgrenzen, eine CI, eine Versionshistorie.
Reife Module können später als eigene Pakete in eine interne Registry
(z. B. privates PyPI) ausgelagert und versioniert bezogen werden – das Manifest-
und Entry-Point-Modell funktioniert in beiden Welten identisch.

### 4.2 Garantien gegen „nur noch die AI versteht das System"

Diese Sorge ist berechtigt – und sie wird durch **Prozess- und Architekturregeln**
ausgeschlossen, nicht durch Hoffnung:

1. **Alles ist Code im Git.** Kein zur Laufzeit generierter, nirgends eingecheckter
   Code. Was die AI schreibt, landet als normaler Commit/Pull-Request im Repo.
2. **Human-Review ist Pflicht.** Jeder Merge (auch von AI-Agents) durchläuft
   Pull-Request-Review durch einen Menschen. In GxP-Kontexten ist das ohnehin
   Bestandteil der Change-Control (siehe Kap. 6).
3. **Lesbarkeit als CI-Gate:** Typisierung (mypy/pyright strict), Linting (ruff),
   Docstring-Pflicht auf öffentlichen Verträgen, Komplexitätslimits. Code, den ein
   Mensch nicht prüfen kann, kommt nicht durch die Pipeline – egal wer ihn schrieb.
4. **Dokumentation lebt neben dem Code:** Jedes Modul hat `docs/` mit
   Fachspezifikation und Architektur-Entscheidungen (ADRs). `AGENTS.md`/`CLAUDE.md`
   im Repo machen dieselbe Doku auch für Coding-Agents nutzbar – ein Dokument,
   zwei Leserschaften.
5. **Tests als ausführbare Spezifikation:** Contract-Tests definieren das
   Verhalten der Modulgrenzen. Ein Entwickler, der in zwei Jahren ein Modul
   austauscht, hat eine präzise, ausführbare Definition dessen, was es tun muss.
6. **Standard-Werkzeuge, kein Eigenbau-Framework:** Python, FastAPI, SQLAlchemy,
   Alembic, Pydantic, pytest – alles, was ein durchschnittlicher Python-Entwickler
   kennt. Der „Metacode" (Kernel) ist bewusst klein (< einige tausend Zeilen) und
   selbst vollständig dokumentiert und getestet.

Ergebnis: Ein Coder klont das Repo, liest das Manifest und die Verträge eines
Moduls, startet die lokale Umgebung (`docker compose up`) und kann jedes Modul
verstehen, ändern, testen und ersetzen – mit oder ohne AI-Unterstützung.

---

## 5. Kommunikationsmuster zwischen Modulen (Referenz)

| Bedarf | Muster | Beispiel |
|---|---|---|
| Synchrone Abfrage | Interface-Aufruf über Registry | Beschaffung fragt ERP: `ArticleService.get_article()` |
| Zustandsänderung mitteilen | Domain-Event über Outbox/Event-Bus | `shipping.parcel.delivered` → CRM aktualisiert Kundenhistorie |
| Langlaufende Prozesse | Saga/Prozess-Manager im Kernel | Wareneingang: Beschaffung → SecurPharm-Verifikation → ERP-Buchung |
| Externe Systeme | Adapter-Ports pro Modul | DHL-/FedEx-Adapter, SecurPharm-Gateway (NGDA-Anbindung) |
| AI-Zugriff | MCP-Tools, generiert aus Manifest + OpenAPI | Agent bucht Versandlabel über dieselbe Use-Case-Schicht wie die UI |

---

## 6. Qualitätssicherung und Validierung: der Standard, der das System höherwertig macht

Für pharmazeutischen Großhandel/Herstellung ist der maßgebliche Rahmen:

| Standard | Relevanz für Evidentic OS |
|---|---|
| **GAMP 5 (2. Ausgabe, 2022)** | Leitfaden für die Validierung computergestützter Systeme; risikobasierter Ansatz; ausdrücklich offen für agile Entwicklung und kritische Bewertung von AI-generierten Artefakten |
| **EU-GMP Annex 11** (+ EU-GDP-Leitlinien 2013/C 343/01, Kap. 3.3) | Anforderungen an computergestützte Systeme: Audit-Trail, Zugriffskontrolle, Datenintegrität, Lieferantenbewertung |
| **§ 52a AMG / AMWHV** | Großhandelserlaubnis; das Beschaffungsmodul muss die GDP-Prozesse (Lieferantenqualifizierung, Temperaturführung, Rückrufe, Dokumentation) nachweisbar abbilden |
| **Delegierte VO (EU) 2016/161** | SecurPharm: Verifizierung/Ausbuchung von Packungen, Anbindung an den deutschen NMVS-Hub (NGDA/securPharm e.V.) |
| **ALCOA+** | Datenintegritätsprinzipien: zuordenbar, lesbar, zeitgleich, original, korrekt + vollständig, konsistent, dauerhaft, verfügbar |
| Optional: **ISO 9001 / ISO/IEC 25010** | QM-System bzw. Software-Qualitätsmerkmale als übergeordnete Klammer |

### 6.1 Validierung modul-scharf statt monolithisch

Der größte praktische Gewinn der Plugin-Architektur: **Validierung pro Modul.**

- Jedes Modul trägt seine Compliance-Metadaten im Manifest (GAMP-Kategorie,
  betroffene Regularien, ob Audit-Trail/E-Signaturen nötig sind).
- Pro Modul existiert eine eigene Validierungsakte in `validation/<modul>/`:
  - **URS** (User Requirements Specification) – fachliche Anforderungen
  - **FS/DS** (Funktions-/Designspezifikation) – generiert zum Teil aus
    Manifest, OpenAPI und Vertragsdefinitionen (Single Source of Truth: der Code)
  - **Risikoanalyse** (z. B. FMEA) – bestimmt Testtiefe
  - **Traceability-Matrix** – Anforderung → Spezifikation → Test → Testergebnis;
    automatisiert gepflegt, indem Tests Anforderungs-IDs referenzieren
    (`@pytest.mark.req("URS-PROC-012")`) und die CI die Matrix generiert
  - **IQ/OQ/PQ**-Protokolle – IQ/OQ weitgehend automatisiert (Installations- und
    Funktionstests aus der Pipeline mit signierten Reports), PQ im Betrieb
- **Wird ein Modul ausgetauscht oder aktualisiert, wird nur dieses Modul
  (plus Regressionstest der Verträge) revalidiert** – nicht das Gesamtsystem.
  Genau dafür braucht man die harten Modulgrenzen aus Kap. 2/3.

### 6.2 Technische Compliance-Bausteine (systemweit, im Kernel)

- **Audit-Trail:** zentral, append-only, manipulationsgeschützt (Hash-Verkettung),
  mit Zeitstempel, Benutzer-/Agent-Identität, Vorher-/Nachher-Werten. Kein Modul
  kann ihn umgehen, weil Schreiboperationen nur über die Use-Case-Schicht laufen.
- **Elektronische Signaturen** für definierte Freigabeschritte
  (z. B. Lieferantenfreigabe), Annex-11-/Part-11-konform (Bedeutung, Datum, Identität).
- **Zugriffskontrolle:** rollenbasiert, pro Modul deklariert, zentral durchgesetzt;
  AI-Agents als eigene, einschränkbare Identitäten.
- **Change Control:** Git + Pull-Request + CI **ist** der technische Teil der
  Change-Control-Akte. Release-Artefakte sind reproduzierbar gebaut, versioniert
  und signiert; die Modul-Registry protokolliert jede Aktivierung/Deaktivierung
  und jedes Versions-Update im Audit-Trail.
- **Backup/Restore & Archivierung:** dokumentierte, getestete Verfahren
  (PITR auf PostgreSQL); Aufbewahrungsfristen nach AMG/AMWHV.

### 6.3 AI im validierten System

GAMP 5 (2. Ausgabe) erlaubt ausdrücklich moderne, toolgestützte Entwicklung.
Praktisch heißt das: AI darf Code, Tests und Doku **erzeugen**, aber die
**Verifikation bleibt beim Menschen und bei der validierten Pipeline** –
Review-Pflicht, Testabdeckung, Traceability. Für AI-Funktionen *im Betrieb*
(z. B. Agent legt Bestellvorschläge an) gilt: Der Agent arbeitet über validierte
Use-Cases mit eigener Identität; GxP-kritische Entscheidungen erfordern
menschliche Freigabe (Human-in-the-Loop), die als E-Signatur dokumentiert wird.

---

## 7. Umsetzungsfahrplan (Vorschlag)

| Phase | Inhalt | Ergebnis |
|---|---|---|
| 0 | Kernel + Contracts + Modul-Skelett („walking skeleton"): Registry, Lifecycle, Event-Bus, Audit-Trail, ein Demo-Modul | Plugin-Mechanik beweisbar; CI mit Lint/Typing/Tests |
| 1 | ERP-Kern (Artikel, Chargen, Lager) + CRM-Basis | Erste fachliche Module auf der Mechanik |
| 2 | Versandmodul mit Carrier-Port (DHL zuerst, FedEx als zweiter Adapter) | Beweis der Austauschbarkeit auf Adapter-Ebene |
| 3 | Beschaffung (GDP/§52a) + SecurPharm-Gateway | GxP-kritische Module inkl. Validierungsakten |
| 4 | Manufacturing + AI-Access-Layer (MCP-Server, Agent-Rollen) | Vollausbau; PQ im Pilotbetrieb |

Jede Phase liefert lauffähige Software plus die zugehörigen Validierungsdokumente –
Validierung ist Teil der Definition-of-Done, kein nachgelagertes Projekt.

---

## 8. Zusammenfassung der Antworten

1. **Plugin-Architektur:** Ja – über Modul-Manifeste, Python Entry Points,
   Lifecycle-Hooks und einen kleinen Kernel. Aktivieren/Deaktivieren ist ein
   verwalteter Zustandsübergang mit Abhängigkeitsprüfung; Daten bleiben erhalten,
   fehlende weiche Abhängigkeiten degradieren kontrolliert statt zu crashen.
2. **Modulare Bauweise:** Modularer Monolith; ein PostgreSQL-Schema und eine
   DB-Rolle pro Modul; Kommunikation ausschließlich über versionierte Interfaces
   und Events; hexagonale Struktur in jedem Modul; Carrier/Behörden-Anbindungen
   als austauschbare Adapter.
3. **Zugriff für Coder:** Alle Module sind normaler Python-Quellcode in einem
   Git-Monorepo mit Standard-Werkzeugen. Human-Review, Typisierung, Tests und
   Doku-Pflicht sind CI-Gates. AI-Agents arbeiten über dieselben APIs und
   denselben Review-Prozess – ein System, das nur eine AI versteht oder
   kontrolliert, ist damit strukturell ausgeschlossen.
4. **Validierung:** GAMP 5 + Annex 11 + GDP als Rahmen; Compliance-Metadaten im
   Modul-Manifest; Validierungsakte und Traceability-Matrix pro Modul, weitgehend
   aus Code/Tests generiert; Audit-Trail und E-Signaturen im Kernel. Der modulare
   Schnitt macht Revalidierung nach Modultausch klein und bezahlbar – das ist der
   messbare Mehrwert („höherwertig") der Architektur.
