-- Architecture V2 - remove four tables that were never used.
--
-- Decision (2026-11-04, platform owner): organize the database in the simplest
-- way. Audit of the shared database on 4 Nov 2026 (86 tables): these four
-- are empty, no running code reads or writes them, and nothing depends on
-- them except each other:
--
--   funding_source            0 rows  V1 plan, never built. Funding is kept
--                                     as sourced actor facts (funding_signal).
--   hub_funding               0 rows  V1 plan, never built (depends only on
--                                     funding_source).
--   hub_sector_strength       0 rows  V1 computed cache, never computed.
--                                     hub_sector (migration 520) replaced it.
--   person_verification_event 0 rows  Superseded: person decisions are kept
--                                     in record_verification and
--                                     review_item_decision.
--
-- Every other empty table stays: it is part of the Architecture V2 design
-- (tests/db/test_architecture_v2_schema.py) or running code uses it.
--
-- The migration refuses to run if any of the four holds a row, so no data can
-- be lost. ORDERING: after 600.
-- ROLLBACK: agents/sql/rollback/610_v2_drop_unused_tables.sql (recreates the
-- exact definitions read from the shared database on 4 Nov 2026).
-- Local isolated test databases first. Production needs the platform owner's
-- approval, a fresh backup and a ledger entry.

BEGIN;

DO $$
DECLARE
    t text;
    n bigint;
BEGIN
    FOREACH t IN ARRAY ARRAY['hub_funding', 'funding_source', 'hub_sector_strength',
                             'person_verification_event'] LOOP
        IF to_regclass('public.' || t) IS NOT NULL THEN
            EXECUTE format('SELECT count(*) FROM public.%I', t) INTO n;
            IF n > 0 THEN
                RAISE EXCEPTION '610: % holds % rows; nothing dropped', t, n;
            END IF;
        END IF;
    END LOOP;
END
$$;

DROP TABLE IF EXISTS public.hub_funding;
DROP TABLE IF EXISTS public.funding_source;
DROP TABLE IF EXISTS public.hub_sector_strength;
DROP TABLE IF EXISTS public.person_verification_event;

COMMIT;
