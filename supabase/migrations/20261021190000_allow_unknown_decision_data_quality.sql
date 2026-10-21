-- Unknown data quality must remain NULL rather than being fabricated as 0 or 100.
-- Existing historical evaluations are preserved unchanged.
alter table public.decision_evaluations
    alter column data_quality drop not null;
