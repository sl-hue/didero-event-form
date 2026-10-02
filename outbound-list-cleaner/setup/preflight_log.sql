-- Team log of the skill's requirements check: one row per run, whoever runs it.
-- Run once in the Supabase project (SQL editor, or via Claude with your OK).
create table if not exists public.preflight_runs (
  id            bigint generated always as identity primary key,
  received_at   timestamptz not null default now(),
  run_id        uuid not null unique,
  checked_at    timestamptz not null,
  user_label    text check (char_length(user_label) <= 200),
  device        text check (char_length(device) <= 64),
  os            text check (char_length(os) <= 200),
  skill_version text check (char_length(skill_version) <= 50),
  list_type     text check (char_length(list_type) <= 50),
  passed        boolean not null,
  failed        jsonb not null default '[]'::jsonb,
  checks        jsonb not null check (pg_column_size(checks) < 20000)
);

-- The skill only ever ADDS rows. Its key (the publishable / anon key) can insert,
-- and can't read, change or delete anything. You see every row in the Supabase dashboard.
alter table public.preflight_runs enable row level security;
revoke all on public.preflight_runs from anon, authenticated;
grant insert on public.preflight_runs to anon;
drop policy if exists "skill can add runs" on public.preflight_runs;
create policy "skill can add runs" on public.preflight_runs for insert to anon with check (true);

-- Easy reading in the dashboard: newest first, one line per run.
create or replace view public.preflight_summary with (security_invoker = true) as
  select checked_at, user_label, device, list_type, skill_version, passed, failed
  from public.preflight_runs order by checked_at desc;
revoke all on public.preflight_summary from anon, authenticated;
