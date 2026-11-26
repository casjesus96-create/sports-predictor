-- Repair only recognized French surface labels currently misclassified as Other.
-- Raw surface_detail, match identity, dates, results and import metadata remain untouched.
begin;

update public.tennis_match_archive
set surface = case lower(btrim(surface_detail))
    when 'dur' then 'Hard'
    when 'dur intérieur' then 'Hard'
    when 'dur intÃ©rieur' then 'Hard'
    when 'terre battue' then 'Clay'
    when 'gazon' then 'Grass'
    when 'moquette intérieur' then 'Carpet'
    when 'moquette intÃ©rieur' then 'Carpet'
end
where surface = 'Other'
  and lower(btrim(surface_detail)) in (
      'dur',
      'dur intérieur',
      'dur intÃ©rieur',
      'terre battue',
      'gazon',
      'moquette intérieur',
      'moquette intÃ©rieur'
  );

-- Fail the migration rather than silently leave a recognized label misclassified.
do $$
begin
    if exists (
        select 1
        from public.tennis_match_archive
        where surface = 'Other'
          and lower(btrim(surface_detail)) in (
              'dur',
              'dur intérieur',
              'dur intÃ©rieur',
              'terre battue',
              'gazon',
              'moquette intérieur',
              'moquette intÃ©rieur'
          )
    ) then
        raise exception 'Recognized tennis surface labels remain classified as Other';
    end if;
end
$$;

commit;
