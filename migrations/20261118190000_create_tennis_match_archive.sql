-- Separate, source-attributed tennis results archive.
-- Valuebetennis publishes these results under CC BY 4.0; attribution is
-- retained on every row. This table is not a prediction or snapshot table.
create table if not exists tennis_match_archive (
    id uuid primary key default gen_random_uuid(),
    source_match_id text not null unique,
    source text not null default 'Valuebetennis',
    source_url text not null,
    source_license text not null default 'CC BY 4.0',
    source_attribution text not null,
    league text not null check (league in ('ATP', 'WTA')),
    match_date date not null,
    match_datetime_utc timestamptz,
    tournament text not null,
    tournament_id text,
    category text not null default 'Unknown',
    surface text check (surface in ('Hard', 'Clay', 'Grass', 'Carpet', 'Other')),
    round_code smallint check (round_code is null or round_code >= 0),
    player1_id text not null,
    player1_name text not null,
    player1_name_key text not null,
    player2_id text not null,
    player2_name text not null,
    player2_name_key text not null,
    winner_id text not null,
    score text,
    duration_minutes integer check (duration_minutes is null or duration_minutes >= 0),
    imported_at timestamptz not null default now(),
    constraint tennis_archive_distinct_players check (player1_id <> player2_id),
    constraint tennis_archive_winner_is_participant check (winner_id in (player1_id, player2_id))
);

create index if not exists idx_tennis_archive_league_date
    on tennis_match_archive (league, match_date desc);
create index if not exists idx_tennis_archive_player1_date
    on tennis_match_archive (league, player1_id, match_date desc);
create index if not exists idx_tennis_archive_player2_date
    on tennis_match_archive (league, player2_id, match_date desc);
create index if not exists idx_tennis_archive_tournament_date
    on tennis_match_archive (league, tournament_id, match_date desc);

-- The backend sync uses the Supabase service role; no public client policy is
-- added. Keep the archive inaccessible to anonymous direct table reads.
alter table tennis_match_archive enable row level security;

create index if not exists idx_tennis_archive_player1_name_key_date
    on tennis_match_archive (league, player1_name_key, match_date desc);
create index if not exists idx_tennis_archive_player2_name_key_date
    on tennis_match_archive (league, player2_name_key, match_date desc);
