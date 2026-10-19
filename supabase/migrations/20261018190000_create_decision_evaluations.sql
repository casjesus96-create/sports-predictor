-- Persistent audit trail for Centro de Decisión evaluations.
-- Evaluations are tied to immutable official prediction snapshots when available.
create table if not exists public.decision_evaluations (
    id uuid primary key default gen_random_uuid(),
    prediction_snapshot_id uuid null references public.prediction_snapshots(id) on delete set null,
    event_id text null,
    sport text not null check (sport in ('MLB', 'NFL', 'NBA', 'TENNIS')),
    model_version text null,
    selected_side text not null check (selected_side in ('home', 'away', 'manual')),
    selected_team text null,
    opponent_team text null,
    model_probability double precision not null check (model_probability > 0 and model_probability < 1),
    decimal_odds double precision not null check (decimal_odds > 1 and decimal_odds <= 1000),
    data_quality integer not null check (data_quality between 0 and 100),
    risk_signals jsonb not null default '[]'::jsonb,
    classification text not null,
    expected_value_percent double precision not null,
    evaluation jsonb not null,
    evaluated_at timestamptz not null default now()
);

create index if not exists decision_evaluations_evaluated_at_idx
    on public.decision_evaluations (evaluated_at desc);
create index if not exists decision_evaluations_snapshot_id_idx
    on public.decision_evaluations (prediction_snapshot_id);

alter table public.decision_evaluations enable row level security;
revoke all on public.decision_evaluations from anon, authenticated;
grant all on public.decision_evaluations to service_role;
