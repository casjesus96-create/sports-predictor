-- Persist external provider quota cooldowns across Render restarts.
-- Access is restricted to the backend service role; no public policy is created.
create table if not exists public.provider_quota_state (
    provider text primary key,
    state jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

alter table public.provider_quota_state enable row level security;
revoke all on table public.provider_quota_state from anon, authenticated;
grant all on table public.provider_quota_state to service_role;
