BEGIN;
DROP TRIGGER IF EXISTS contact_collection_authorization_append_only ON contact_collection_authorization;
DROP TABLE IF EXISTS contact_collection_authorization;
DROP TABLE IF EXISTS person_topic;
COMMIT;
