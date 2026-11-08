-- Fix the PL/pgSQL output-variable/column collision reported as SQLSTATE 42702.
-- Keep the existing RPC signature and response shape. Procedural values use v_ names;
-- unqualified source_key occurrences in SQL statements refer to target table columns.
create or replace function public.ingest_app_finalized_football_match(
    p_match jsonb,
    p_external_match_id text
)
returns table(status text, source_key text)
language plpgsql
security definer
set search_path = public
as $$
#variable_conflict use_column
declare
    v_source_key text;
    v_competition text;
    v_match_date date;
    v_home_key text;
    v_away_key text;
    v_home_score integer;
    v_away_score integer;
    v_existing record;
    v_existing_key text;
    v_candidate_count integer := 0;
    v_inserted_key text;
    v_status text;
    v_result_hash text;
begin
    if p_match is null
       or coalesce(p_match->>'source', '') <> 'APP_FINALIZED'
       or coalesce(p_match->>'source_url', '') = ''
       or coalesce(p_match->>'status', 'FINISHED') <> 'FINISHED'
       or coalesce(p_external_match_id, '') = ''
       or coalesce(p_match->>'source_key', '') = ''
       or coalesce(p_match->>'competition_code', '') not in ('PL', 'PD', 'SA', 'BL1', 'FL1')
       or coalesce(p_match->>'home_team', '') = ''
       or coalesce(p_match->>'away_team', '') = ''
       or coalesce(p_match->>'home_team_key', '') = ''
       or coalesce(p_match->>'away_team_key', '') = ''
       or coalesce(p_match->>'season', '') !~ '^[0-9]{4}$'
       or coalesce(p_match->>'match_date', '') !~ '^\d{4}-\d{2}-\d{2}$'
       or coalesce(p_match->>'home_score', '') !~ '^\d{1,2}$'
       or coalesce(p_match->>'away_score', '') !~ '^\d{1,2}$' then
        raise exception 'Invalid app-finalized football match payload';
    end if;

    v_source_key := p_match->>'source_key';
    v_competition := p_match->>'competition_code';
    v_match_date := (p_match->>'match_date')::date;
    v_home_key := p_match->>'home_team_key';
    v_away_key := p_match->>'away_team_key';
    v_home_score := (p_match->>'home_score')::integer;
    v_away_score := (p_match->>'away_score')::integer;

    if v_match_date > current_date
       or v_match_date < date '1990-01-01'
       or v_home_score < 0 or v_home_score > 30
       or v_away_score < 0 or v_away_score > 30
       or v_home_key = v_away_key then
        raise exception 'App-finalized football match failed integrity checks';
    end if;

    v_result_hash := md5(concat_ws('|', v_competition, v_match_date::text,
        v_home_key, v_away_key, v_home_score::text, v_away_score::text));

    select * into v_existing
      from public.football_match_archive
     where football_match_archive.source_key = v_source_key
     for update;

    if found then
        v_existing_key := v_existing.source_key;
        if v_existing.competition_code = v_competition
           and v_existing.home_team_key = v_home_key
           and v_existing.away_team_key = v_away_key
           and abs(v_existing.match_date - v_match_date) <= 1
           and v_existing.home_score = v_home_score
           and v_existing.away_score = v_away_score then
            v_status := 'ALREADY_PRESENT';
        else
            v_status := 'CONFLICT';
        end if;
    else
        -- Catch a one-day UTC/local-date discrepancy before inserting a second row.
        select count(*), min(a.source_key)
          into v_candidate_count, v_existing_key
          from public.football_match_archive a
         where a.competition_code = v_competition
           and a.home_team_key = v_home_key
           and a.away_team_key = v_away_key
           and a.match_date between v_match_date - 1 and v_match_date + 1;

        if v_candidate_count > 1 then
            v_status := 'CONFLICT';
        elsif v_candidate_count = 1 then
            select * into v_existing
              from public.football_match_archive
             where football_match_archive.source_key = v_existing_key
             for update;
            if v_existing.home_score = v_home_score
               and v_existing.away_score = v_away_score then
                v_status := 'ALREADY_PRESENT';
            else
                v_status := 'CONFLICT';
            end if;
        else
            insert into public.football_match_archive (
                source_key, source, source_url, competition_code, competition_name,
                season, match_date, home_team, home_team_key, away_team, away_team_key,
                home_score, away_score, result
            ) values (
                v_source_key, 'APP_FINALIZED', p_match->>'source_url',
                v_competition, p_match->>'competition_name', p_match->>'season',
                v_match_date, p_match->>'home_team', v_home_key,
                p_match->>'away_team', v_away_key, v_home_score, v_away_score,
                case when v_home_score > v_away_score then 'H'
                     when v_home_score < v_away_score then 'A' else 'D' end
            )
            on conflict (source_key) do nothing
            returning football_match_archive.source_key into v_inserted_key;

            if v_inserted_key is not null then
                v_existing_key := v_inserted_key;
                v_status := 'INSERTED';
            else
                -- A concurrent importer won the unique-key race; compare, never overwrite.
                select * into v_existing
                  from public.football_match_archive
                 where football_match_archive.source_key = v_source_key
                 for update;
                v_existing_key := v_source_key;
                if found
                   and v_existing.competition_code = v_competition
                   and v_existing.home_team_key = v_home_key
                   and v_existing.away_team_key = v_away_key
                   and v_existing.home_score = v_home_score
                   and v_existing.away_score = v_away_score then
                    v_status := 'ALREADY_PRESENT';
                else
                    v_status := 'CONFLICT';
                end if;
            end if;
        end if;
    end if;

    insert into public.football_archive_ingestion_events (
        source_key, ingestion_source, external_match_id, competition_code,
        event_status, result_hash, payload
    ) values (
        coalesce(v_existing_key, v_source_key), 'APP_FINALIZED', p_external_match_id,
        v_competition, v_status, v_result_hash, p_match
    )
    on conflict on constraint football_archive_ingestion_event_unique do nothing;

    return query select v_status, coalesce(v_existing_key, v_source_key);
end;
$$;

revoke all on function public.ingest_app_finalized_football_match(jsonb, text) from public, anon, authenticated;
grant execute on function public.ingest_app_finalized_football_match(jsonb, text) to service_role;
