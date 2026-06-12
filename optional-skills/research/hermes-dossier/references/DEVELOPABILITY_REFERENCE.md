# Antibody Developability Reference

Knowledge base for the `hermes-dossier` skill. Covers sequence liabilities, the
in-silico metrics, the wet-lab biophysical panel (Phase 2), and the regulatory
framing (RUO vs GMP/GLP/ISO 17025).

## 1. Sequence-liability motifs

| Liability | Motif | Severity | Mechanism / risk |
|-----------|-------|----------|------------------|
| Asn deamidation | `N[GSTHN]` (NG worst) | high | Asn→Asp/isoAsp; potency & charge change |
| Asp isomerization | `D[GSTHD]` (DG worst) | high | iso-Asp formation; stability/potency loss |
| Met oxidation | `M` | medium | Oxidation, esp. solvent-exposed / CDR or Fc |
| Trp oxidation | `W` | medium | Oxidation; can ablate binding if in CDR |
| N-glycosylation | `N[^P][ST]` | medium | Sequon occupancy → heterogeneity |
| Lys glycation | `K[ED]` | low | Non-enzymatic glycation |
| Unpaired cysteine | odd Cys count | high | Free thiol → mispairing/aggregation |
| N-terminal pyroGlu | leading `Q`/`E` | low | N-terminal charge heterogeneity |

CDR-resident liabilities matter most — they directly threaten binding. Supply CDR
ranges to the scan (`--cdr-vh/--cdr-vl`) to flag them.

## 2. In-silico metrics & methods

- **pI / net charge** — Henderson-Hasselbalch over EMBOSS pKa values
  (D 3.9, E 4.1, C 8.5, Y 10.1, H 6.5, K 10.8, R 12.5; N-term 8.6, C-term 3.6).
  Extreme pI or high net charge correlates with poor solubility / PK.
- **GRAVY** — Kyte & Doolittle hydropathy average; higher = more hydrophobic =
  higher aggregation / non-specific binding risk.
- **Extinction coefficient @280 nm** — Pace et al. 1995
  (Trp 5500, Tyr 1490, cystine 125 M⁻¹cm⁻¹); reported reduced & oxidised forms.
- **MW** — sum of average residue masses + 1 water.

Verdict heuristic (sequence-derivable subset of TAP/Jain): `ELEVATED_RISK` if an
unpaired cysteine or ≥6 high-severity liabilities; `MODERATE_RISK` if ≥3 high or
any flag; else `LOW_RISK`.

## 3. Wet-lab biophysical panel (Phase 2 — ISO 17025)

The Jain et al. (PNAS 2017) developability fingerprint — the industry benchmark.
Best effort/value order:

| Tier | Assay | Reads out |
|------|-------|-----------|
| 1 | nanoDSF | Tm, Tonset, Tagg (thermal/conformational stability) |
| 1 | DLS | Rh, polydispersity, Tagg, kD (colloidal stability) |
| 1 | SEC | % monomer / aggregate / fragment |
| 1 | AC-SINS | self-association → viscosity / aggregation risk |
| 2 | HIC | hydrophobicity (clearance/PK proxy) |
| 2 | icIEF | charge variants, pI |
| 2 | SPR/BLI | affinity & kinetics (KD, kon, koff) |
| 3 | intact/subunit MS, peptide mapping | identity, PTMs, glycans |

These require physical sample but **still no GMP** — they are RUO analytics.

## 4. Regulatory framing

- **GMP** — manufacture of patient-bound product. **Not** required for a data
  product. Cannot be applied retroactively to wholesale-sourced, non-GMP samples.
- **GLP** — only if data feeds regulatory non-clinical safety submissions.
- **ISO 17025** — testing-lab accreditation; the credibility lever for the wet-lab
  (Phase 2) analytics business.
- **ALCOA+ / data integrity** — the real differentiator for selling trustworthy
  data: Attributable, Legible, Contemporaneous, Original, Accurate (+ Complete,
  Consistent, Enduring, Available). The dossier's stamped `method_version`,
  provenance and documented cold-chain serve this.
- **IP** — defensible via the EU sui-generis **database right** (protects the
  investment in the dataset), trade-secret protection, the methods, and trained
  models. The molecule itself is not owned and need not be.

> Always present generated dossiers as **Research Use Only**. They are not GMP/GLP
> records and do not constitute regulatory submissions.
