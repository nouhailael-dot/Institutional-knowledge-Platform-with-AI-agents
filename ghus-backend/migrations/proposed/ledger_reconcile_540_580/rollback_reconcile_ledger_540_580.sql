-- Undo reconcile_ledger_540_580.sql: remove exactly the five rows it added.
--
-- Usage: psql ... -v reconciled_at='<applied_at printed by the reconciliation>'
--
-- Deletes a row only if its id, checksum AND applied_at all match, and only if
-- all five match: one reconciliation, written in one transaction. Anything
-- else (a row recorded by someone else, a partial set) is refused and left for
-- a person to look at. With none of the five present it does nothing, so it is
-- safe to rerun. The schema is not touched (the reconciliation never touched it).
--
-- This is NOT a rollback of migrations 540-580 themselves: their own scripts in
-- agents/sql/rollback/ would drop columns and tables that live requests use, and
-- are not part of this change.

\set ON_ERROR_STOP on
\if :{?reconciled_at}
\else
\warn 'rollback needs -v reconciled_at=<applied_at printed by the reconciliation>'
DO $$ BEGIN RAISE EXCEPTION 'reconciled_at not given; nothing done'; END $$;
\endif

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
SET LOCAL search_path = pg_catalog, public;
SET LOCAL application_name = 'ghus_ledger_reconcile_540_580_rollback';
SELECT set_config('ghus.reconciled_at', :'reconciled_at', true);

DO $$
DECLARE
    stamp   timestamptz := current_setting('ghus.reconciled_at')::timestamptz;
    ours    integer;
    others  integer;
    deleted integer;
BEGIN
    SELECT count(*) FILTER (WHERE (migration_id, source_sha256) IN (
                ('540', '8a6f1dbec788694c2eca45b9e5f10b363da6a74197e40a60eaf8ac48805d6907'),
                ('550', '56dc21550fd74771915b84794a29068081f5eff367810409ad2cf95885d0e46d'),
                ('560', 'd52c855edf804b319cf77ca4f5919d76462d0436e4a884455467e8bd0e566c4a'),
                ('570', 'ee0f192baf82ca0649fe2edc4516f41a518f4deaa6a8696b3505250ffeb01190'),
                ('580', '63d7419e7b9511e12e7e339745bff3903c72f3ff13b55bd078aadb3f467b5f11'))
                AND applied_at = stamp),
           count(*)
      INTO ours, others
    FROM public.architecture_v2_migration_ledger
    WHERE migration_id IN ('540', '550', '560', '570', '580');
    others := others - ours;

    IF ours = 0 AND others = 0 THEN
        RAISE NOTICE 'nothing to roll back: no 540-580 ledger row exists';
        RETURN;
    END IF;
    IF others > 0 OR ours <> 5 THEN
        RAISE EXCEPTION 'rollback refused: % row(s) match this reconciliation (% expected), % other 540-580 row(s) exist',
            ours, 5, others;
    END IF;

    DELETE FROM public.architecture_v2_migration_ledger
    WHERE (migration_id, source_sha256) IN (
            ('540', '8a6f1dbec788694c2eca45b9e5f10b363da6a74197e40a60eaf8ac48805d6907'),
            ('550', '56dc21550fd74771915b84794a29068081f5eff367810409ad2cf95885d0e46d'),
            ('560', 'd52c855edf804b319cf77ca4f5919d76462d0436e4a884455467e8bd0e566c4a'),
            ('570', 'ee0f192baf82ca0649fe2edc4516f41a518f4deaa6a8696b3505250ffeb01190'),
            ('580', '63d7419e7b9511e12e7e339745bff3903c72f3ff13b55bd078aadb3f467b5f11'))
      AND applied_at = stamp;
    GET DIAGNOSTICS deleted = ROW_COUNT;
    IF deleted <> 5 THEN
        RAISE EXCEPTION 'rollback failed: % row(s) deleted, 5 expected', deleted;
    END IF;
    RAISE NOTICE 'rolled back: 5 ledger rows of the % reconciliation removed', stamp;
END $$;

SELECT count(*) AS ledger_rows,
       count(*) FILTER (WHERE migration_id IN ('540', '550', '560', '570', '580')) AS rows_540_580
FROM public.architecture_v2_migration_ledger;

COMMIT;
