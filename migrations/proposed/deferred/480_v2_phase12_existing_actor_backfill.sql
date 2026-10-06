-- PROPOSAL ONLY. Phase 12 existing-canonical actor backfill.
-- This file is applied only to the isolated migration proof until schema-owner approval.
BEGIN;

DO $migration$
DECLARE
  legacy_column text;
BEGIN
  SELECT CASE WHEN EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='actor' AND column_name='actor_type'
  ) THEN 'actor_type' ELSE 'actor_category' END INTO legacy_column;
  EXECUTE format($sql$
    INSERT INTO actor_category_migration_audit(
      actor_id,migration_batch_id,legacy_category,legacy_category_raw,
      mapped_category,mapping_status,
      prior_status,prior_source_origin,prior_category_note,prior_category_needs_review
    )
    SELECT actor_id,'phase12_existing_canonical_2026_10',%1$I,actor_type_raw,
      ghus_phase12_legacy_category(%1$I),
      CASE WHEN ghus_phase12_legacy_category(%1$I) IS NULL
           THEN 'requires_review' ELSE 'mapped' END,
      status,source_origin,category_note,category_needs_review
    FROM actor
    ON CONFLICT(actor_id) DO NOTHING
  $sql$, legacy_column);
END
$migration$;

UPDATE actor a
SET actor_category=audit.mapped_category,
    category_needs_review=CASE
      WHEN audit.mapping_status='requires_review' THEN true
      ELSE COALESCE(a.category_needs_review,false)
    END,
    category_note=CASE
      WHEN audit.mapping_status='requires_review'
      THEN COALESCE(NULLIF(btrim(a.category_note),''),
           'Legacy actor category requires explicit GHUS reclassification.')
      ELSE a.category_note
    END,
    source_origin='imported_phase1'
FROM actor_category_migration_audit audit
WHERE audit.actor_id=a.actor_id
  AND audit.migration_batch_id='phase12_existing_canonical_2026_10';

INSERT INTO actor_verification_event(
    actor_id,topic_id,decision,decided_by,decided_at,reason,
    decision_origin,migration_batch_id
)
SELECT audit.actor_id,NULL,'verified',NULL,NULL,
       'Existing canonical GHUS actor at the Architecture V2 migration baseline.',
       'existing_canonical_migration',audit.migration_batch_id
FROM actor_category_migration_audit audit
WHERE audit.migration_batch_id='phase12_existing_canonical_2026_10'
  AND NOT EXISTS (
    SELECT 1 FROM actor_verification_event event
    WHERE event.actor_id=audit.actor_id
      AND event.decision_origin='existing_canonical_migration'
  );

INSERT INTO review_item(
    review_kind,entity_type,entity_id,priority,payload,status
)
SELECT 'category_doubt','actor',audit.actor_id,'normal',
       jsonb_build_object(
         'issue','unmappable_legacy_actor_category',
         'legacy_category',audit.legacy_category,
         'migration_batch_id',audit.migration_batch_id,
         'category_type_pending_enrichment',true
       ),'pending'
FROM actor_category_migration_audit audit
WHERE audit.migration_batch_id='phase12_existing_canonical_2026_10'
  AND audit.mapping_status='requires_review'
  AND NOT EXISTS (
    SELECT 1 FROM review_item item
    WHERE item.review_kind='category_doubt'
      AND item.entity_type='actor'
      AND item.entity_id=audit.actor_id
      AND item.payload->>'migration_batch_id'=audit.migration_batch_id
  );

COMMIT;
