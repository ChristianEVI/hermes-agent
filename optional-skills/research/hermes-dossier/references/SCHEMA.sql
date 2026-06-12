-- Hermes Dossier — minimal Supabase/Postgres schema (MVP: in-silico, antibodies)
-- Apply via Supabase MCP `apply_migration` or the SQL editor.
-- Phase-2 extension points are noted inline.

create table if not exists molecules (
    id              uuid primary key default gen_random_uuid(),
    external_ref    text unique not null,            -- ERP / catalogue id
    name            text not null,
    modality        text not null default 'antibody',
    vh_seq          text,
    vl_seq          text,
    hc_seq          text,
    lc_seq          text,
    provenance      text,                            -- wholesale lot / source note
    storage_temp_c  numeric,                         -- documented cold-chain temp
    created_at      timestamptz not null default now()
);
create index if not exists idx_molecules_external_ref on molecules (external_ref);

create table if not exists insilico_results (
    id              uuid primary key default gen_random_uuid(),
    molecule_id     uuid not null references molecules (id) on delete cascade,
    payload         jsonb not null,                  -- full seq_liability_scan.py output
    method_version  text,
    computed_at     timestamptz not null default now()
);
create index if not exists idx_insilico_molecule on insilico_results (molecule_id);

create table if not exists dossiers (
    id              uuid primary key default gen_random_uuid(),
    molecule_id     uuid not null references molecules (id) on delete cascade,
    version         text not null,
    status          text not null default 'RUO',     -- Research Use Only
    summary         jsonb,
    markdown        text,
    payload         jsonb,
    created_at      timestamptz not null default now()
);
create index if not exists idx_dossiers_molecule on dossiers (molecule_id);

-- Lock down by default: RLS enabled with no policies. The service_role key
-- (used by supabase_push.py) bypasses RLS, so server-side writes keep working;
-- anon / authenticated get no access until Phase-2 tenant policies are added.
alter table molecules enable row level security;
alter table insilico_results enable row level security;
alter table dossiers enable row level security;

-- Phase 2 (NOT enabled in MVP):
--   * characterization_results (wet-lab Jain panel: nanoDSF/DLS/SEC/AC-SINS/HIC/icIEF)
--   * storage_conditions (full cold-chain history from ERP)
--   * Row-Level Security policies for multi-tenant external customer delivery
--     e.g.  alter table dossiers enable row level security;
--           create policy tenant_read on dossiers for select using (...);
