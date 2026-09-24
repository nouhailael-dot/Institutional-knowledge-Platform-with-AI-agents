BEGIN;
DROP VIEW IF EXISTS actor_fact_current;
DROP TRIGGER IF EXISTS fact_resolution_append_only ON fact_resolution;
DROP TRIGGER IF EXISTS actor_fact_append_only ON actor_fact;
DROP TABLE IF EXISTS fact_resolution;
DROP TABLE IF EXISTS actor_fact;
COMMIT;
