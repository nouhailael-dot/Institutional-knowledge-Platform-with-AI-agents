BEGIN;
DROP FUNCTION IF EXISTS ghus_pre_cutover_data_loss_audit();
DROP TABLE IF EXISTS architecture_v2_cutover_baseline;
COMMIT;
