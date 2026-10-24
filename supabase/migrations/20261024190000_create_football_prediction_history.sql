-- Durable, immutable pre-match football predictions and idempotent official settlement.
create table if not exists public.football_prediction_snapshots (
    id uuid primary key default gen_random_uuid(),
    provider_match_id bigint not null,
    competition_code text not null,
    kickoff_at timestamptz,
    home_team text not null,
    away_team text not null,
    model_version text not null,
    home_probability double precision,
    draw_probability double precision,
    away_probability double precision,
    expected_goals jsonb not null default '{}'::jsonb,
    prediction_payload jsonb not null,
    data_cutoff_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    result_status text not null default 'PENDING'
        check (result_status in ('PENDING', 'SETTLED', 'CANCELLED')),
    actual_home_score integer,
    actual_away_score integer,
    actual_outcome text check (actual_outcome in ('HOME', 'DRAW', 'AWAY')),
    result_source text,
    settled_at timestamptz,
    constraint football_snapshot_match_model_unique unique (provider_match_id, model_version),
    constraint football_scores_nonnegative check (
        (actual_home_score is null or actual_home_score >= 0) and
        (actual_away_score is null or actual_away_score >= 0)
    )
);
create index if not exists football_snapshots_created_idx
    on public.football_prediction_snapshots (created_at desc);
create index if not exists football_snapshots_status_idx
    on public.football_prediction_snapshots (result_status, kickoff_at);
alter table public.football_prediction_snapshots enable row level security;
revoke all on public.football_prediction_snapshots from anon, authenticated;
grant all on public.football_prediction_snapshots to service_role;
