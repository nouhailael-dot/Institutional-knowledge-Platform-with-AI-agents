-- Rollback for 621_v2_actor_details_all_readings.sql: stop following topic-less
-- readings. The function stays in its 621 form (a superset of 620's); roll back
-- 620 as well to remove actor_details entirely.

BEGIN;

DROP TRIGGER IF EXISTS actor_details_follows_topicless_fact ON actor_fact;
DROP FUNCTION IF EXISTS ghus_actor_details_on_topicless_fact();

COMMIT;
