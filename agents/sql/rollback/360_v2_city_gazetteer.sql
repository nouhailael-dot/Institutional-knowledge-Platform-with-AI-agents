-- PROPOSAL ONLY. Exact rollback for 360_v2_city_gazetteer.sql.
BEGIN;
DROP TABLE IF EXISTS us_city_coord;
COMMIT;
