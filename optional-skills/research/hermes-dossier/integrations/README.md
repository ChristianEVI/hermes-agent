# Hermes Dossier — App Integration

`hermesDossier.ts` is a drop-in TypeScript client for reading the Hermes Dossier
module from an application (e.g. the Sales Engine app).

## Where the data lives
The module is a set of namespaced tables inside the **Sales Engine** Supabase
project:

| Table | Contents |
|-------|----------|
| `hermes_molecules` | identity + VH/VL sequences + provenance |
| `hermes_insilico_results` | full in-silico payload (per-chain metrics, liabilities) |
| `hermes_dossiers` | RUO dossier: version, status, verdict summary |

```
Project URL : https://tibfpnoeerzonkkxecmb.supabase.co
Dashboard   : https://supabase.com/dashboard/project/tibfpnoeerzonkkxecmb
```

## Usage
```bash
npm i @supabase/supabase-js
```
```ts
import { createHermesDossierClient } from "./hermesDossier";

const hd = createHermesDossierClient(); // reads SUPABASE_URL / SUPABASE_SERVICE_KEY

const tras  = await hd.getByName("Trastuzumab");
const risky = await hd.list({ verdict: "ELEVATED_RISK", limit: 20 });
const scan  = await hd.getInsilico("PUBREF-CETUXIMAB"); // full liability payload
```

## Access (RLS)
The `hermes_*` tables have Row-Level Security **enabled with no policies**, so
reads are blocked by default. Choose one:

- **Server-side (recommended):** use the `service_role` key (Dashboard → Settings
  → API). It bypasses RLS. Never expose it in the browser.
- **Public read policy:** add a `SELECT` policy for the `anon` role if the data
  may be read with the publishable key (then it is publicly readable).

## Provenance / disclaimer
All sequences are public reference sequences (Thera-SAbDab / DrugBank). Dossiers
are **Research Use Only** in-silico analyses — not GMP/GLP records.
