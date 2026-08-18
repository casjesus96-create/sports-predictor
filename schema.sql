create table if not exists prediction_snapshots (
id uuid primary key default gen_random_uuid(),
event_id text not null,
sport text not null default 'baseball',
league text not null default 'MLB',
model_version text not null,
created_at timestamptz not null default now(),
data_cutoff timestamptz not null default now(),
home_probability numeric(8,6) not null check(home_probability between 0 and 1),
away_probability numeric(8,6) not null check(away_probability between 0 and 1),
confidence text not null,
data_quality integer not null check(data_quality between 0 and 100),
features jsonb not null default '{}'::jsonb,
result_status text not null default 'PENDING',
actual_winner text,
settled_at timestamptz
);
create index if not exists idx_prediction_event on prediction_snapshots(event_id);
create index if not exists idx_prediction_created on prediction_snapshots(created_at desc);
