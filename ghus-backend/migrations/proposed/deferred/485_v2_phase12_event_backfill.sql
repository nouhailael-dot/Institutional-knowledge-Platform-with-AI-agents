-- PROPOSAL ONLY. Phase 12 existing-event backfill (GHUS decision 2026-10-06:
-- existing canonical events start Verified, like existing actors).
-- Gap-fill only; nothing is overwritten or invented:
--   * record_status 'verified' and source_origin 'imported_phase1' (policy, recorded
--     in legacy_migration_record);
--   * start_date copies the legacy next_date; date_status is derived from it
--     (upcoming / past) or 'unconfirmed' when there is no date;
--   * a legacy host_actor_id becomes an 'organizes' edge on the event's own source.
-- event_topic and event_claim stay empty: both need collection provenance the
-- legacy rows do not have; Light Pull fills them. Idempotent.
BEGIN;

INSERT INTO legacy_migration_record(migration_batch_id,legacy_table,legacy_key,legacy_field,
    disposition,destination_table,legacy_value,legacy_metadata,reason)
SELECT 'phase12_event_backfill_2026_10','event',e.event_id::text,'record_status',
       'normalized','event.record_status',e.record_status,
       jsonb_build_object('policy','existing canonical event starts verified',
                          'decided_by','GHUS (approved by Ismail Sabbar, 2026-10-06)'),
       NULL
FROM event e
WHERE e.record_status IS NULL
ON CONFLICT (legacy_table,legacy_key,legacy_field) DO NOTHING;

UPDATE event
SET record_status = COALESCE(record_status, 'verified'),
    source_origin = COALESCE(source_origin, 'imported_phase1'),
    start_date = COALESCE(start_date, next_date),
    date_status = COALESCE(date_status, CASE
        WHEN next_date IS NULL THEN 'unconfirmed'
        WHEN next_date >= current_date THEN 'upcoming'
        ELSE 'past' END)
WHERE record_status IS NULL OR source_origin IS NULL
   OR (start_date IS NULL AND next_date IS NOT NULL) OR date_status IS NULL;

INSERT INTO entity_edge(subject_type,subject_id,relationship_type,object_type,object_id,
                        topic_id,source_id,confidence)
SELECT 'actor',e.host_actor_id,'organizes','event',e.event_id,NULL,e.source_id,'medium'
FROM event e
WHERE e.host_actor_id IS NOT NULL AND e.source_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM entity_edge x
    WHERE x.subject_type='actor' AND x.subject_id=e.host_actor_id
      AND x.relationship_type='organizes' AND x.object_type='event'
      AND x.object_id=e.event_id);

COMMIT;
