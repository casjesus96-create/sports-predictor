from pathlib import Path


def test_app_finalized_ingestion_migration_resolves_source_key_column_ambiguity():
    migration = (
        Path(__file__).resolve().parents[1]
        / "supabase"
        / "migrations"
        / "20261108183000_fix_app_finalized_source_key_ambiguity.sql"
    ).read_text(encoding="utf-8")

    assert "returns table(status text, source_key text)" in migration.lower()
    assert "as $$\n#variable_conflict use_column\ndeclare" in migration.lower()
    assert "on conflict (source_key) do nothing" in migration.lower()
    assert "return query select v_status, coalesce(v_existing_key, v_source_key)" in migration.lower()
    assert "grant execute on function public.ingest_app_finalized_football_match(jsonb, text) to service_role" in migration.lower()
