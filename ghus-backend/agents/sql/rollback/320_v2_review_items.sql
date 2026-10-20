BEGIN;
DROP TRIGGER IF EXISTS review_item_decision_append_only ON review_item_decision;
DROP TABLE IF EXISTS review_item_decision;
DROP TABLE IF EXISTS review_item;
COMMIT;
