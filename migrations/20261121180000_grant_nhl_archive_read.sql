-- Ensure the Render service role can read the reviewed NHL archive.
-- RLS remains enabled; Supabase service_role bypasses RLS by design.
grant usage on schema public to service_role;
grant select on table public.nhl_game_archive to service_role;
