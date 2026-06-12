#!/usr/bin/env python3
"""
dossier_build.py — Assemble a standardised "Hermes Dossier" (Markdown + JSON)
from an in-silico scan (seq_liability_scan.py output) plus identity / provenance
metadata.

Pure standard library. RUO (Research-Use-Only) product — not a GMP document.

Usage:
    python3 seq_liability_scan.py --name mAb-123 --vh ... --vl ... > scan.json
    python3 dossier_build.py --scan scan.json \
        --external-ref ERP-00123 --provenance "Wholesale lot L-2021-009" \
        --storage-temp -75 --out-md dossier.md --out-json dossier.json

If --scan is '-' the scan JSON is read from stdin. With no --out-* the Markdown
is printed to stdout.
"""
import sys
import json
import argparse
import datetime

DOSSIER_VERSION = "1.0.0"

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _fmt_liability_rows(chain):
    rows = []
    for m in sorted(chain["liabilities"],
                    key=lambda x: (SEVERITY_ORDER.get(x["severity"], 9), x["position"])):
        cdr = "—" if m["in_cdr"] is None else ("yes" if m["in_cdr"] else "no")
        rows.append(f"| {chain['name']} | {m['position']} | {m['motif']} | "
                    f"{m['label']} | {m['severity']} | {cdr} |")
    return rows


def build_markdown(scan, meta):
    agg = scan["aggregate"]
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = []
    lines.append(f"# Hermes Dossier — {scan['molecule']}")
    lines.append("")
    lines.append(f"**Status:** {scan['status']} (Research Use Only) · "
                 f"**Modality:** {scan['modality']} · "
                 f"**Dossier version:** {DOSSIER_VERSION} · "
                 f"**Generated:** {now}")
    lines.append("")

    # --- 1. Identity & provenance ---
    lines.append("## 1. Identity & Provenance")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Molecule | {scan['molecule']} |")
    lines.append(f"| External / ERP reference | {meta.get('external_ref', '—')} |")
    lines.append(f"| Modality | {scan['modality']} |")
    lines.append(f"| Provenance | {meta.get('provenance', '—')} |")
    lines.append(f"| Storage temperature (°C) | {meta.get('storage_temp', '—')} |")
    lines.append(f"| Chains analysed | {', '.join(agg['chains'])} |")
    lines.append("")

    # --- 2. In-silico developability fingerprint ---
    lines.append("## 2. In-silico Developability Fingerprint")
    lines.append("")
    lines.append(f"**Aggregate verdict: `{agg['verdict']}`** · "
                 f"Total liabilities: {agg['total_liability_count']} "
                 f"(high-severity: {agg['total_high_severity_count']}) · "
                 f"Fv MW: {agg['total_fv_mw_da']} Da")
    if agg["developability_flags"]:
        lines.append("")
        lines.append("Flags: " + ", ".join(f"`{f}`" for f in agg["developability_flags"]))
    lines.append("")
    lines.append("| Chain | Length | MW (Da) | pI | Net charge @pH7.4 | GRAVY | "
                 "Aromatic frac. | E280 (cystines) | Liabilities (high) |")
    lines.append("|-------|--------|---------|----|-------------------|-------|"
                 "----------------|-----------------|--------------------|")
    for c in scan["chains"]:
        lines.append(
            f"| {c['name']} | {c['length']} | {c['molecular_weight_da']} | "
            f"{c['isoelectric_point']} | {c['net_charge_ph7.4']} | "
            f"{c['gravy_hydropathy']} | {c['aromatic_fraction']} | "
            f"{c['extinction']['e280_cystines']} | "
            f"{c['liability_count']} ({c['high_severity_count']}) |")
    lines.append("")

    # --- 3. Sequence-liability map ---
    lines.append("## 3. Sequence-Liability Map")
    lines.append("")
    lines.append("| Chain | Position | Motif | Liability | Severity | In CDR |")
    lines.append("|-------|----------|-------|-----------|----------|--------|")
    any_row = False
    for c in scan["chains"]:
        for row in _fmt_liability_rows(c):
            lines.append(row)
            any_row = True
    if not any_row:
        lines.append("| — | — | — | No sequence liabilities detected | — | — |")
    lines.append("")
    lines.append("> *In CDR* is `—` when CDR boundaries were not supplied. Provide "
                 "`--cdr-vh/--cdr-vl` to the scan to prioritise CDR-resident liabilities.")
    lines.append("")

    # --- 4. Wet-lab panel (Phase 2 placeholder) ---
    lines.append("## 4. Biophysical Panel (Wet-Lab — Phase 2)")
    lines.append("")
    lines.append("The following Jain-style developability assays are **not yet "
                 "populated** in this RUO dossier and are available as a Phase-2 "
                 "add-on (ISO 17025 analytics):")
    lines.append("")
    lines.append("| Assay | Reads out | Status |")
    lines.append("|-------|-----------|--------|")
    for assay, readout in [
        ("nanoDSF (Tm/Tagg)", "thermal / conformational stability"),
        ("DLS (kD, Tagg)", "colloidal stability, aggregation onset"),
        ("SEC", "% monomer / aggregate / fragment"),
        ("AC-SINS", "self-association → viscosity risk"),
        ("HIC", "hydrophobicity / clearance proxy"),
        ("icIEF", "charge variants / pI"),
    ]:
        lines.append(f"| {assay} | {readout} | _pending_ |")
    lines.append("")

    # --- 5. Methods & data integrity ---
    lines.append("## 5. Methods & Data Integrity")
    lines.append("")
    lines.append(f"- **Method version:** `{scan.get('method_version', 'n/a')}` "
                 f"(deterministic, reproducible).")
    lines.append("- pI / net charge: Henderson-Hasselbalch over EMBOSS pKa values.")
    lines.append("- Hydrophobicity: Kyte & Doolittle GRAVY.")
    lines.append("- Extinction coefficient: Pace et al. (1995).")
    lines.append("- Liability motifs: deamidation, isomerization, oxidation, "
                 "N-glycosylation, glycation, unpaired cysteine, N-terminal pyroglutamate.")
    lines.append("")
    lines.append("> **RUO disclaimer:** This dossier is generated for research use "
                 "only from in-silico sequence analysis. It is **not** a GMP/GLP "
                 "record and does not constitute a regulatory submission. Samples "
                 "were characterised under documented cold-chain custody (non-GMP).")
    lines.append("")
    return "\n".join(lines)


def build_payload(scan, meta, markdown):
    return {
        "dossier_version": DOSSIER_VERSION,
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": scan.get("status", "RUO"),
        "molecule": scan["molecule"],
        "modality": scan["modality"],
        "identity": {
            "external_ref": meta.get("external_ref"),
            "provenance": meta.get("provenance"),
            "storage_temp_c": meta.get("storage_temp"),
        },
        "insilico": scan,
        "summary": {
            "verdict": scan["aggregate"]["verdict"],
            "total_liability_count": scan["aggregate"]["total_liability_count"],
            "total_high_severity_count": scan["aggregate"]["total_high_severity_count"],
            "developability_flags": scan["aggregate"]["developability_flags"],
        },
        "markdown": markdown,
    }


def main():
    ap = argparse.ArgumentParser(description="Assemble a Hermes Dossier from a scan")
    ap.add_argument("--scan", required=True, help="Scan JSON path, or '-' for stdin")
    ap.add_argument("--external-ref", help="ERP / catalogue reference")
    ap.add_argument("--provenance", help="Provenance note (lot, source)")
    ap.add_argument("--storage-temp", help="Storage temperature in °C")
    ap.add_argument("--out-md", help="Write Markdown dossier to this path")
    ap.add_argument("--out-json", help="Write JSON dossier to this path")
    args = ap.parse_args()

    text = sys.stdin.read() if args.scan == "-" else open(args.scan).read()
    scan = json.loads(text)
    meta = {
        "external_ref": args.external_ref,
        "provenance": args.provenance,
        "storage_temp": args.storage_temp,
    }

    markdown = build_markdown(scan, meta)
    payload = build_payload(scan, meta, markdown)

    if args.out_md:
        with open(args.out_md, "w") as f:
            f.write(markdown)
    if args.out_json:
        with open(args.out_json, "w") as f:
            json.dump(payload, f, indent=2)
    if not args.out_md and not args.out_json:
        print(markdown)
    else:
        wrote = [p for p in (args.out_md, args.out_json) if p]
        print("Wrote: " + ", ".join(wrote), file=sys.stderr)


if __name__ == "__main__":
    main()
