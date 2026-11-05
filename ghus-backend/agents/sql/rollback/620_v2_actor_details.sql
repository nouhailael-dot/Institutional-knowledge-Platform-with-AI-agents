-- Rollback for 620_v2_actor_details.sql. actor_details holds only
-- copies of actor_fact readings, so dropping it loses nothing.

BEGIN;

DROP TRIGGER IF EXISTS actor_details_follows_pointer ON actor_fact_current_pointer;
DROP FUNCTION IF EXISTS ghus_actor_details_on_pointer();
DROP FUNCTION IF EXISTS ghus_actor_details_refresh(uuid, text);
DROP TABLE IF EXISTS actor_details;

COMMIT;
