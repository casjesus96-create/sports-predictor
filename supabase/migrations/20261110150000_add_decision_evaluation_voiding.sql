-- Soft-void support for accidental Decision Center evaluations.
-- Preserve the original values and keep a reasoned audit trail.
alter table public.decision_evaluations
    add column if not exists status text not null default 'ACTIVE'
        check (status in ('ACTIVE', 'VOIDED')),
    add column if not exists voided_at timestamptz null,
    add column if not exists void_reason text null;

create index if not exists decision_evaluations_status_evaluated_at_idx
    on public.decision_evaluations (status, evaluated_at desc);

alter table public.decision_evaluations
    drop constraint if exists decision_evaluations_void_metadata_check;

alter table public.decision_evaluations
    add constraint decision_evaluations_void_metadata_check
    check (
        (status = 'ACTIVE' and voided_at is null and void_reason is null)
        or
        (status = 'VOIDED' and voided_at is not null and length(trim(void_reason)) >= 3)
    );
