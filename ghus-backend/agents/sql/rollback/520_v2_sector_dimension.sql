-- ROLLBACK for agents/sql/520_v2_sector_dimension.sql.
-- Local ghus_v2_*_test databases only.
--
-- Refuses to run once any sector link carries real data, because dropping these
-- tables would destroy sourced evidence. Export and migrate the rows first if
-- they are genuinely to be removed.

BEGIN;

DO $$
DECLARE linked integer;
BEGIN
    SELECT (SELECT count(*) FROM actor_sector)
         + (SELECT count(*) FROM event_sector)
         + (SELECT count(*) FROM hub_sector)
      INTO linked;
    IF linked <> 0 THEN
        RAISE EXCEPTION
            'refusing to roll back: % sourced sector link row(s) exist. Export them first.',
            linked;
    END IF;
END $$;

DROP TRIGGER IF EXISTS hub_sector_append_only ON hub_sector;
DROP TRIGGER IF EXISTS actor_sector_append_only ON actor_sector;
DROP FUNCTION IF EXISTS ghus_guard_sector_link_append_only();

DROP TABLE IF EXISTS hub_sector;
DROP TABLE IF EXISTS event_sector;
DROP TABLE IF EXISTS actor_sector;
DROP TABLE IF EXISTS sector;

COMMIT;
