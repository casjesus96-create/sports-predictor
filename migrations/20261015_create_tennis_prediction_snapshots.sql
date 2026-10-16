-- Tennis prediction snapshots are separate from team-sport snapshots because
-- tennis is player-vs-player and does not have home/away teams.
create table if not exists tennis_prediction_snapshots (
    id uuid primary key default gen_random_uuid(),
    event_id text not null,
    match_id text not null,
    league text not null check (league in ('ATP', 'WTA')),
    tournament text,
    round text,
    player1_id text,
    player1_name text not null,
    player2_id text,
    player2_name text not null,
    model_version text not null,
    created_at timestamptz not null default now(),
    data_cutoff timestamptz not null,
    player1_probability numeric(8,6) not null check (player1_probability between 0 and 1),
    player2_probability numeric(8,6) not null check (player2_probability between 0 and 1),
    player1_rating numeric(10,2) not null,
    player2_rating numeric(10,2) not null,
    historical_matches_used integer not null default 0 check (historical_matches_used >= 0),
    features jsonb not null default '{}'::jsonb,
    result_status text not null default 'PENDING'
        check (result_status in ('PENDING', 'CORRECT', 'INCORRECT', 'VOID')),
    actual_winner_id text,
    actual_winner_name text,
    settled_at timestamptz,
    constraint tennis_snapshot_probability_sum
        check (abs((player1_probability + player2_probability) - 1.0) <= 0.00001)
);
create index if not exists idx_tennis_snapshot_event on tennis_prediction_snapshots(event_id);
create index if not exists idx_tennis_snapshot_created on tennis_prediction_snapshots(created_at desc);
create index if not exists idx_tennis_snapshot_pending on tennis_prediction_snapshots(result_status)
    where result_status = 'PENDING';

-- A match has one immutable snapshot per model version. A repeated request
-- returns the original row rather than overwriting the pre-match probabilities.
create unique index if not exists uq_tennis_snapshot_match_model
    on tennis_prediction_snapshots(league, match_id, model_version);
