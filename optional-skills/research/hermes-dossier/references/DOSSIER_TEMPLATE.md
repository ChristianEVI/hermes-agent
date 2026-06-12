# Hermes Dossier — Output Format

The standardised RUO dossier produced by `scripts/dossier_build.py`. Rendered as
**Markdown** (human-readable, sellable) and **JSON** (machine-readable payload).
Both are deterministic from the scan + identity metadata.

## Markdown sections

1. **Header** — molecule name, `RUO` status, modality, dossier version, UTC timestamp.
2. **Identity & Provenance** — molecule, ERP/external reference, provenance note,
   documented storage temperature, chains analysed.
3. **In-silico Developability Fingerprint** — aggregate verdict
   (`LOW`/`MODERATE`/`ELEVATED_RISK`), total/high liability counts, Fv MW, flags,
   and a per-chain table (length, MW, pI, net charge @pH7.4, GRAVY, aromatic
   fraction, E280, liability counts).
4. **Sequence-Liability Map** — per-motif table: chain, position, motif, liability
   label, severity, in-CDR flag (sorted by severity then position).
5. **Biophysical Panel (Wet-Lab — Phase 2)** — placeholder table of the Jain panel
   assays (nanoDSF/DLS/SEC/AC-SINS/HIC/icIEF), all `pending` in the in-silico MVP.
6. **Methods & Data Integrity** — method version, computation methods, and the RUO
   disclaimer.

## JSON payload (top-level keys)

```
dossier_version, generated_utc, status, molecule, modality,
identity { external_ref, provenance, storage_temp_c },
insilico { ...full seq_liability_scan.py output... },
summary { verdict, total_liability_count, total_high_severity_count,
          developability_flags },
markdown   # the rendered Markdown string
```

This JSON maps directly onto the Supabase tables in `SCHEMA.sql`:
`molecules` (identity), `insilico_results.payload` (insilico), `dossiers`
(version/status/summary/markdown/payload).
