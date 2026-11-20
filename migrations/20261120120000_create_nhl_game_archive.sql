-- Persistent, source-attributed NHL game results archive.
-- This table is separate from prediction snapshots and does not activate a model.
-- Do not populate this table until a source with reviewed reuse terms is selected.
create table if not exists nhl_game_archive (
    id uuid primary key default gen_random_uuid(),
    game_id text not null unique,
    season text not null check (season ~ '^[0-9]{8}$'),
    game_date date not null,
    start_time_utc timestamptz,
    home_team_id bigint,
    home_team_abbreviation text not null,
    home_team_name text,
    home_score integer check (home_score is null or home_score >= 0),
    away_team_id bigint,
    away_team_abbreviation text not null,
    away_team_name text,
    away_score integer check (away_score is null or away_score >= 0),
    game_type smallint not null check (game_type in (1, 2, 3)),
    game_state text not null,
    result_status text not null check (result_status in ('FINAL', 'NON_FINAL_REVIEW')),
    cross_team_confirmed boolean not null default false,
    observed_teams jsonb not null default '[]'::jsonb,
    training_eligible boolean not null default false,
    eligibility_reason text not null,
    source text not null default 'unverified_source',
    source_url text not null,
    source_license text,
    source_terms_status text not null default 'review_required'
        check (source_terms_status in ('review_required', 'reviewed')),
    source_attribution text not null,
    imported_at timestamptz not null default now(),
    constraint nhl_archive_distinct_teams
        check (home_team_abbreviation <> away_team_abbreviation),
    constraint nhl_archive_final_has_score
        check (
            result_status <> 'FINAL'
            or (home_score is not null and away_score is not null)
        ),
    constraint nhl_archive_training_requires_final
        check (not training_eligible or result_status = 'FINAL')
);

create index if not exists idx_nhl_archive_season_date
    on nhl_game_archive (season, game_date, game_id);
create index if not exists idx_nhl_archive_home_date
    on nhl_game_archive (home_team_abbreviation, game_date desc);
create index if not exists idx_nhl_archive_away_date
    on nhl_game_archive (away_team_abbreviation, game_date desc);
create index if not exists idx_nhl_archive_training
    on nhl_game_archive (training_eligible, game_type, game_date)
    where training_eligible = true;

alter table nhl_game_archive enable row level security;
