-- Immutable audit snapshots for cross-sport best-play recommendations.
-- No mutable status fields: outcomes are derived from the linked prediction snapshot.
create table if not exists public.best_play_recommendations (
    id uuid primary key default gen_random_uuid(),
    prediction_snapshot_id uuid not null references public.prediction_snapshots(id) on delete restrict,
    event_id text not null,
    sport text not null check (sport in ('MLB', 'NBA', 'NFL')),
    model_version text not null,
    selected_side text not null check (selected_side in ('home', 'away')),
    selected_team text not null,
    opponent_team text not null,
    market_key text not null check (market_key = 'h2h'),
    market_label text not null,
    model_probability double precision not null check (model_probability > 0 and model_probability < 1),
    decimal_odds double precision not null check (decimal_odds > 1 and decimal_odds <= 1000),
    fair_odds double precision not null check (fair_odds > 1),
    implied_probability double precision not null check (implied_probability > 0 and implied_probability < 1),
    edge_percentage_points double precision not null,
    expected_value_percent double precision not null,
    data_quality integer not null check (data_quality between 0 and 100),
    ranking_score double precision null check (ranking_score between 0 and 100),
    classification text not null,
    odds_source text not null check (odds_source in ('automatic', 'manual')),
    bookmaker text not null,
    odds_observed_at timestamptz null,
    model_snapshot_created_at timestamptz not null,
    recommendation_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists best_play_recommendations_created_at_idx
    on public.best_play_recommendations (created_at desc);
create index if not exists best_play_recommendations_day_rank_idx
    on public.best_play_recommendations (created_at desc, ranking_score desc);
create index if not exists best_play_recommendations_snapshot_idx
    on public.best_play_recommendations (prediction_snapshot_id);

create or replace function public.prevent_best_play_recommendation_mutation()
returns trigger
language plpgsql
as $$
begin
    raise exception 'best_play_recommendations is append-only; UPDATE and DELETE are prohibited';
end;
$$;

drop trigger if exists best_play_recommendations_immutable on public.best_play_recommendations;
create trigger best_play_recommendations_immutable
before update or delete on public.best_play_recommendations
for each row execute function public.prevent_best_play_recommendation_mutation();

alter table public.best_play_recommendations enable row level security;
revoke all on public.best_play_recommendations from anon, authenticated;
grant select, insert on public.best_play_recommendations to service_role;
