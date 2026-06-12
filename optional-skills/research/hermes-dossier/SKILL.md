---
name: hermes-dossier
description: >
  Generate standardised, sellable in-silico developability dossiers for
  therapeutic antibodies (Research-Use-Only). Scan VH/VL or full HC/LC sequences
  for liability hotspots (deamidation, isomerization, oxidation, N-glycosylation,
  unpaired cysteine), compute biophysical properties (pI, net charge, GRAVY,
  extinction coefficient, MW), assemble a standardised Markdown/JSON dossier, and
  persist it to Supabase for delivery to early drug developers. Use for antibody
  developability triage, "data-on-stock" catalogue characterisation, and building
  a proprietary RUO data product. No GMP required.
version: 1.0.0
author: hermes-agent
license: MIT
metadata:
  hermes:
    tags: [science, biologics, antibody, developability, research]
prerequisites:
  commands: [python3]
---

# Hermes Dossier — In-silico Antibody Developability

You are an expert in antibody developability and biologics characterisation. This
skill generates a standardised, **Research-Use-Only (RUO)** "Hermes Dossier" from
an antibody sequence — entirely in-silico, no wet lab, no GMP.

## Regulatory framing (state this when asked)

- **GMP is NOT required.** GMP governs the manufacture of patient-bound product,
  not the generation of research data. Selling characterisation data / dossiers /
  simulations to early developers is an **RUO** activity.
- Non-GMP samples **cannot** be retroactively GMP-certified — and they don't need
  to be for a data product. What matters is **data integrity (ALCOA+)**,
  documented sample provenance & cold-chain (already captured in the ERP), and —
  for the wet-lab Phase 2 — **ISO 17025** accreditation of the analytics.
- The defensible IP is the **dataset** (EU sui-generis database right), the
  **methods**, and trained models — never the molecule itself.

## Core workflows

### 1 — In-silico liability & developability scan

Scan a heavy/light variable sequence (or full chains). Outputs structured JSON:
per-chain liabilities, pI, net charge @pH7.4, GRAVY, E280, MW, and a
TAP-/Jain-oriented developability verdict.

```bash
python3 scripts/seq_liability_scan.py \
  --name "mAb-123" \
  --vh "EVQLVESGGG..." \
  --vl "DIQMTQSPSS..." \
  --cdr-vh "27-38,56-65,105-117" \
  --cdr-vl "24-34,50-56,89-97" \
  > scan.json
```

Provide `--cdr-vh/--cdr-vl` ranges to flag CDR-resident liabilities (highest risk).
Without them, the `in_cdr` field is `—` (unknown). Accepts `--fasta <file|->` too.

### 2 — Assemble the standardised dossier

```bash
python3 scripts/dossier_build.py --scan scan.json \
  --external-ref "ERP-00123" \
  --provenance "Wholesale lot L-2021-009" \
  --storage-temp -75 \
  --out-md dossier.md --out-json dossier.json
```

Produces a Markdown dossier (sections: Identity & Provenance → In-silico
Fingerprint → Sequence-Liability Map → Wet-lab panel placeholder → Methods & Data
Integrity + RUO disclaimer) and a machine-readable JSON payload. See
`references/DOSSIER_TEMPLATE.md` for the format.

### 3 — Batch the whole catalogue ("data on stock")

Characterise an entire antibody catalogue in one pass — this is the core
data-asset engine. Input is a CSV (one antibody per row; columns
`external_ref, name, vh, vl, hc, lc, provenance, storage_temp_c`).

```bash
python3 scripts/batch_dossier.py --catalogue catalogue.csv --out-dir dossiers/
# add --push to also write every dossier to Supabase
```

Writes `<external_ref>.md` + `.json` per molecule plus a **portfolio index**
(`index.csv` / `index.json`) ranked by developability risk — your sellable
inventory map. Accepts `--catalogue -` to stream a CSV from stdin.

### 4 — Persist to Supabase (delivery layer)

Apply the schema once (`references/SCHEMA.sql`) via the Supabase MCP
`apply_migration` tool, then push:

```bash
export SUPABASE_URL="https://<project-ref>.supabase.co"
export SUPABASE_SERVICE_KEY="<service-role-key>"   # server-side only
python3 scripts/supabase_push.py --dossier dossier.json
```

In an interactive Hermes session you can instead use the Supabase MCP tools
(`mcp__Supabase__execute_sql` / `apply_migration`) directly — no env keys needed.

## Reasoning guidelines

1. **State raw values first** — MW, pI, net charge, GRAVY, E280 per chain.
2. **Map liabilities** — list motif, position, severity; prioritise CDR-resident
   ones (deamidation NG, isomerization DG, CDR Met/Trp oxidation).
3. **Give the verdict** — LOW / MODERATE / ELEVATED risk with the driving flags.
4. **Recommend** — engineering options (e.g. NG→NG mutation, Met→Leu) and which
   Phase-2 wet-lab assays would confirm (nanoDSF, AC-SINS, HIC, SEC).
5. **Stamp method version** — every dossier carries `method_version` for ALCOA+
   reproducibility. Always include the RUO disclaimer.

See `references/DEVELOPABILITY_REFERENCE.md` for liability tables, thresholds, the
Jain biophysical panel, and the GMP/GLP/ISO-17025/RUO distinctions.

## Important notes

- All scripts are Python-stdlib only; no RDKit/Biopython required.
- The scan is deterministic and reproducible — same sequence → same dossier.
- MVP scope: in-silico, antibodies. Peptides and wet-lab assay ingestion are Phase 2.
- This is an RUO research aid, not a regulatory or clinical document.
