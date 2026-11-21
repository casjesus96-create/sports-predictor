-- Store season-reviewed canonical franchise identity separately from provider team IDs.
-- This does not define historical mappings; the importer must supply reviewed mappings.
alter table nhl_game_archive
    add column if not exists home_team_canonical_key text,
    add column if not exists away_team_canonical_key text;

create index if not exists idx_nhl_archive_home_canonical_date
    on nhl_game_archive (home_team_canonical_key, game_date desc)
    where home_team_canonical_key is not null;

create index if not exists idx_nhl_archive_away_canonical_date
    on nhl_game_archive (away_team_canonical_key, game_date desc)
    where away_team_canonical_key is not null;

comment on column nhl_game_archive.home_team_canonical_key is
    'Season-reviewed canonical franchise identity; distinct from source team ID and abbreviation.';
comment on column nhl_game_archive.away_team_canonical_key is
    'Season-reviewed canonical franchise identity; distinct from source team ID and abbreviation.';
