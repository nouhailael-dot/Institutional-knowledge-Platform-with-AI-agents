BEGIN;
DROP TRIGGER IF EXISTS actor_ranking_append_only ON actor_ranking;
DROP TABLE IF EXISTS actor_ranking;
COMMIT;
