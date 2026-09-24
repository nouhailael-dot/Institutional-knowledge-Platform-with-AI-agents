BEGIN;
DROP TRIGGER IF EXISTS actor_strategic_connection_check_append_only ON actor_strategic_connection_check;
DROP TABLE IF EXISTS actor_strategic_connection_check;
DROP TABLE IF EXISTS strategic_entity;
COMMIT;
