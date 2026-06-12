#!/usr/bin/env python3
"""
supabase_push.py — Persist a Hermes Dossier (dossier_build.py JSON output) into
Supabase via the PostgREST REST API. Stdlib only.

Credentials are read from the environment:
    SUPABASE_URL          e.g. https://<project-ref>.supabase.co
    SUPABASE_SERVICE_KEY  service-role key (server-side only — never ship to clients)

Writes are idempotent on molecules.external_ref (upsert via Prefer:resolution).

Usage:
    python3 supabase_push.py --dossier dossier.json
    python3 dossier_build.py ... --out-json - | python3 supabase_push.py --dossier -

Requires the schema from references/SCHEMA.sql (tables: molecules, insilico_results,
dossiers). For interactive Hermes sessions you can equivalently use the Supabase
MCP tools (execute_sql / apply_migration) instead of this script.
"""
import os
import sys
import json
import argparse
import urllib.request
import urllib.error


def _env(name):
    val = os.environ.get(name)
    if not val:
        sys.exit(f"Missing required environment variable: {name}")
    return val.rstrip("/")


def _request(base, key, path, payload, prefer):
    url = f"{base}/rest/v1/{path}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode()
            return json.loads(body) if body else []
    except urllib.error.HTTPError as e:
        sys.exit(f"Supabase error {e.code} on {path}: {e.read().decode()[:500]}")
    except urllib.error.URLError as e:
        sys.exit(f"Network error reaching Supabase: {e}")


def push(dossier):
    base = _env("SUPABASE_URL")
    if not base.startswith("http"):
        base = f"https://{base}.supabase.co"
    key = _env("SUPABASE_SERVICE_KEY")

    ins = dossier["insilico"]
    identity = dossier.get("identity", {})

    # 1. Upsert molecule (idempotent on external_ref)
    chains = {c["name"]: c for c in ins["chains"]}
    molecule = {
        "external_ref": identity.get("external_ref") or dossier["molecule"],
        "name": dossier["molecule"],
        "modality": dossier["modality"],
        "provenance": identity.get("provenance"),
        "storage_temp_c": _num(identity.get("storage_temp_c")),
    }
    mol = _request(base, key, "molecules?on_conflict=external_ref",
                   molecule, "resolution=merge-duplicates,return=representation")
    molecule_id = mol[0]["id"]

    # 2. Insert in-silico results
    _request(base, key, "insilico_results", {
        "molecule_id": molecule_id,
        "payload": ins,
        "method_version": ins.get("method_version"),
    }, "return=minimal")

    # 3. Insert dossier
    _request(base, key, "dossiers", {
        "molecule_id": molecule_id,
        "version": dossier["dossier_version"],
        "status": dossier.get("status", "RUO"),
        "summary": dossier["summary"],
        "markdown": dossier["markdown"],
        "payload": dossier,
    }, "return=minimal")

    return molecule_id


def _num(v):
    if v in (None, "", "—"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser(description="Push a Hermes Dossier to Supabase")
    ap.add_argument("--dossier", required=True, help="Dossier JSON path, or '-' for stdin")
    args = ap.parse_args()
    text = sys.stdin.read() if args.dossier == "-" else open(args.dossier).read()
    dossier = json.loads(text)
    molecule_id = push(dossier)
    print(f"OK — persisted molecule_id={molecule_id} "
          f"({dossier['molecule']}) to Supabase.")


if __name__ == "__main__":
    main()
