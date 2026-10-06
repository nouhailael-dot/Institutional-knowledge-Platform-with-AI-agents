-- TEST-ONLY. Executed solely by scripts/phase12_cutover_rehearsal.py against
-- ghus_v2_phase12_rehearsal_test. Stand-ins for GHUS decisions that do not exist
-- yet; they must never be applied to a real database. %(who)s is the label.

-- Aggregates: GHUS chooses between network parent and legacy collection.
-- The rehearsal stands in the network-parent option.
WITH aggregate AS (
  SELECT review_item_id, entity_id FROM review_item
  WHERE review_kind='category_doubt' AND status='pending'
    AND payload->>'is_true_aggregate'='true'
), decided AS (
  INSERT INTO review_item_decision(review_item_id,decision,decided_by,reason,decided_at)
  SELECT review_item_id,'resolve',%(who)s,'actor_category=association_network',now()
  FROM aggregate RETURNING review_item_id
), resolved AS (
  UPDATE review_item SET status='resolved'
  WHERE review_item_id IN (SELECT review_item_id FROM decided) RETURNING entity_id
)
UPDATE actor SET actor_category='association_network', category_needs_review=false,
       category_note=%(who)s
WHERE actor_id IN (SELECT entity_id FROM resolved);

-- "Mining Hubs" has no sector, members or location. Stand in a topic and the
-- centroid of the other MINING hub centers so 405 can be exercised.
UPDATE hub h SET topic_id=t.topic_id,
       center_city='TEST-ONLY', center_latitude=c.lat, center_longitude=c.lon,
       center_method='test_only_rehearsal', center_method_version='test_only',
       center_computed_at=now(), radius_miles=200, center_frozen=false
FROM topic t,
     (SELECT avg(center_latitude) lat, avg(center_longitude) lon FROM hub h2
      JOIN topic t2 ON t2.topic_id=h2.topic_id WHERE t2.code='MINING') c
WHERE t.code='MINING' AND h.topic_id IS NULL;
