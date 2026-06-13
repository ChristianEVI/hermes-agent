/**
 * hermesDossier.ts — drop-in client for the Hermes Dossier module.
 *
 * The Hermes Dossier module lives inside the "Sales Engine" Supabase project
 * as three namespaced tables: hermes_molecules, hermes_insilico_results,
 * hermes_dossiers. This file wraps the Supabase queries so an app can read the
 * in-silico antibody developability data without writing any SQL.
 *
 * Install:   npm i @supabase/supabase-js
 *
 * Auth (RLS is enabled on the tables):
 *   - Recommended: server-side with the service_role key (bypasses RLS).
 *       SUPABASE_URL=https://tibfpnoeerzonkkxecmb.supabase.co
 *       SUPABASE_SERVICE_KEY=<service_role key from Dashboard -> Settings -> API>
 *   - Or pass { url, key } explicitly, or hand in your own SupabaseClient.
 *
 * Quick start:
 *   import { createHermesDossierClient } from "./hermesDossier";
 *   const hd = createHermesDossierClient();
 *   const tras = await hd.getByName("Trastuzumab");
 *   const risky = await hd.list({ verdict: "ELEVATED_RISK", limit: 20 });
 */
import { createClient, SupabaseClient } from "@supabase/supabase-js";

export type Verdict = "LOW_RISK" | "MODERATE_RISK" | "ELEVATED_RISK";

export interface DossierSummary {
  verdict: Verdict;
  total_liability_count: number;
  total_high_severity_count: number;
  developability_flags: string[];
}

export interface Molecule {
  external_ref: string;
  name: string;
  modality: string;
  vh_seq: string | null;
  vl_seq: string | null;
  provenance: string | null;
}

export interface DossierRecord {
  molecule: Molecule;
  version: string;
  status: string;        // "RUO"
  summary: DossierSummary;
}

/** Default = the Sales Engine project that hosts the hermes_* module. */
const DEFAULT_URL = "https://tibfpnoeerzonkkxecmb.supabase.co";

const SELECT =
  "version, status, summary, " +
  "hermes_molecules!inner(external_ref, name, modality, vh_seq, vl_seq, provenance)";

export interface HermesDossierClient {
  /** Portfolio, optionally filtered by verdict. */
  list(params?: { verdict?: Verdict; limit?: number }): Promise<DossierRecord[]>;
  /** One dossier by ERP/external reference, e.g. "PUBREF-TRASTUZUMAB". */
  getByRef(externalRef: string): Promise<DossierRecord | null>;
  /** Dossiers whose molecule name matches (case-insensitive substring). */
  getByName(name: string): Promise<DossierRecord[]>;
  /** Full in-silico payload (per-chain metrics + liabilities) for one molecule. */
  getInsilico(externalRef: string): Promise<unknown | null>;
  /** Escape hatch: the underlying SupabaseClient. */
  raw: SupabaseClient;
}

export function createHermesDossierClient(opts?: {
  url?: string;
  key?: string;
  client?: SupabaseClient;
}): HermesDossierClient {
  const url = opts?.url ?? process.env.SUPABASE_URL ?? DEFAULT_URL;
  const key =
    opts?.key ?? process.env.SUPABASE_SERVICE_KEY ?? process.env.SUPABASE_KEY;
  if (!opts?.client && !key) {
    throw new Error(
      "Hermes Dossier: missing Supabase key. Set SUPABASE_SERVICE_KEY " +
        "(server-side) or pass { key }.",
    );
  }
  const supabase = opts?.client ?? createClient(url, key as string);

  const map = (row: any): DossierRecord => {
    const m = row.hermes_molecules;
    return {
      molecule: {
        external_ref: m.external_ref,
        name: m.name,
        modality: m.modality,
        vh_seq: m.vh_seq,
        vl_seq: m.vl_seq,
        provenance: m.provenance,
      },
      version: row.version,
      status: row.status,
      summary: row.summary as DossierSummary,
    };
  };

  return {
    async list(params = {}) {
      let q = supabase.from("hermes_dossiers").select(SELECT);
      if (params.verdict) q = q.eq("summary->>verdict", params.verdict);
      const { data, error } = await q.limit(params.limit ?? 100);
      if (error) throw error;
      return (data ?? []).map(map);
    },

    async getByRef(externalRef) {
      const { data, error } = await supabase
        .from("hermes_dossiers")
        .select(SELECT)
        .eq("hermes_molecules.external_ref", externalRef)
        .maybeSingle();
      if (error) throw error;
      return data ? map(data) : null;
    },

    async getByName(name) {
      const { data, error } = await supabase
        .from("hermes_dossiers")
        .select(SELECT)
        .ilike("hermes_molecules.name", `%${name}%`);
      if (error) throw error;
      return (data ?? []).map(map);
    },

    async getInsilico(externalRef) {
      const { data, error } = await supabase
        .from("hermes_insilico_results")
        .select("payload, hermes_molecules!inner(external_ref)")
        .eq("hermes_molecules.external_ref", externalRef)
        .maybeSingle();
      if (error) throw error;
      return data ? (data as any).payload : null;
    },

    raw: supabase,
  };
}
