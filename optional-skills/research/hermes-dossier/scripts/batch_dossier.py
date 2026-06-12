#!/usr/bin/env python3
"""
batch_dossier.py — "Data on stock" engine. Run the in-silico developability scan
+ dossier build across an entire antibody catalogue in one pass.

Pure standard library. Reuses seq_liability_scan.py and dossier_build.py.

Input: a CSV catalogue (one antibody per row). Recognised columns (case-insensitive,
extras ignored):
    external_ref, name, vh, vl, hc, lc, provenance, storage_temp_c
At least `name` (or `external_ref`) and one sequence column are required.

Usage:
    python3 batch_dossier.py --catalogue catalogue.csv --out-dir dossiers/
    python3 batch_dossier.py --catalogue catalogue.csv --out-dir dossiers/ --push

Outputs, per molecule, into --out-dir:
    <external_ref>.md   <external_ref>.json
And a portfolio index:
    index.json, index.csv   (ranked by risk → your sellable inventory map)

--push additionally writes each dossier to Supabase (requires SUPABASE_URL /
SUPABASE_SERVICE_KEY env; see supabase_push.py).
"""
import os
import re
import sys
import csv
import json
import argparse
import importlib.util

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(mod):
    spec = importlib.util.spec_from_file_location(mod, os.path.join(_HERE, f"{mod}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


scan_mod = _load("seq_liability_scan")
dossier_mod = _load("dossier_build")

VERDICT_RANK = {"ELEVATED_RISK": 0, "MODERATE_RISK": 1, "LOW_RISK": 2}


def _slug(s):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s) or "molecule"


def process_row(row):
    """Scan + build a dossier for one catalogue row. Returns (dossier, index_entry)."""
    name = (row.get("name") or row.get("external_ref") or "antibody").strip()
    ext = (row.get("external_ref") or name).strip()

    chains = []
    for label in ("vh", "vl", "hc", "lc"):
        seq = (row.get(label) or "").strip()
        if seq:
            chains.append((label.upper(), seq, None))
    if not chains:
        return None, {"external_ref": ext, "name": name, "error": "no sequence"}

    chain_records = [scan_mod.scan_sequence(s, lbl, cdr) for (lbl, s, cdr) in chains]
    scan = {
        "molecule": name, "modality": "antibody", "status": "RUO",
        "method_version": scan_mod.METHOD_VERSION,
        "chains": chain_records,
        "aggregate": scan_mod.aggregate(chain_records, name),
    }
    meta = {
        "external_ref": ext,
        "provenance": (row.get("provenance") or "").strip() or None,
        "storage_temp": (row.get("storage_temp_c") or "").strip() or None,
    }
    markdown = dossier_mod.build_markdown(scan, meta)
    dossier = dossier_mod.build_payload(scan, meta, markdown)

    agg = scan["aggregate"]
    entry = {
        "external_ref": ext, "name": name,
        "verdict": agg["verdict"],
        "total_liability_count": agg["total_liability_count"],
        "total_high_severity_count": agg["total_high_severity_count"],
        "flags": agg["developability_flags"],
    }
    return dossier, entry


def _read_catalogue(path):
    text = sys.stdin.read() if path == "-" else open(path, newline="").read()
    reader = csv.DictReader(text.splitlines())
    rows = []
    for raw in reader:
        rows.append({(k or "").strip().lower(): v for k, v in raw.items()})
    return rows


def main():
    ap = argparse.ArgumentParser(description="Batch in-silico dossier generation")
    ap.add_argument("--catalogue", required=True, help="CSV catalogue path, or '-'")
    ap.add_argument("--out-dir", required=True, help="Directory for dossiers + index")
    ap.add_argument("--push", action="store_true", help="Also push each dossier to Supabase")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    rows = _read_catalogue(args.catalogue)

    index, errors = [], []
    pusher = _load("supabase_push") if args.push else None

    for row in rows:
        dossier, entry = process_row(row)
        if dossier is None:
            errors.append(entry)
            print(f"  SKIP {entry['external_ref']}: {entry['error']}", file=sys.stderr)
            continue
        base = os.path.join(args.out_dir, _slug(entry["external_ref"]))
        with open(base + ".md", "w") as f:
            f.write(dossier["markdown"])
        with open(base + ".json", "w") as f:
            json.dump(dossier, f, indent=2)
        if pusher:
            try:
                pusher.push(dossier)
                entry["pushed"] = True
            except SystemExit as e:
                entry["pushed"] = False
                print(f"  push failed for {entry['external_ref']}: {e}", file=sys.stderr)
        index.append(entry)

    # Portfolio index ranked by risk (your sellable-inventory map)
    index.sort(key=lambda e: (VERDICT_RANK.get(e["verdict"], 9),
                              -e["total_high_severity_count"]))
    with open(os.path.join(args.out_dir, "index.json"), "w") as f:
        json.dump({"molecules": index, "errors": errors}, f, indent=2)
    with open(os.path.join(args.out_dir, "index.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["external_ref", "name", "verdict", "liabilities",
                    "high_severity", "flags"])
        for e in index:
            w.writerow([e["external_ref"], e["name"], e["verdict"],
                        e["total_liability_count"], e["total_high_severity_count"],
                        "|".join(e["flags"])])

    print(f"Done: {len(index)} dossiers written to {args.out_dir} "
          f"({len(errors)} skipped). Portfolio index: index.csv / index.json")


if __name__ == "__main__":
    main()
