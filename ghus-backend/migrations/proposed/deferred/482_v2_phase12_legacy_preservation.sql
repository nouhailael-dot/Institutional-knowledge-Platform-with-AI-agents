-- PROPOSAL ONLY. Phase 12 legacy preservation backfill (runs after 480, before 490).
-- Applied only to isolated *_test databases until schema-owner approval.
--
-- Every legacy value that migration 500 removes gets either a destination row
-- or an explicit row in legacy_migration_record. Nothing is invented:
--   * facts reuse the actor's own legacy source row and that row's retrieved_at;
--     values without a legacy source stay in the audit record, not the ledger;
--   * state/city are normalized deterministically (same rules as
--     agents/common/geography.py, proven by tests/db/test_phase12_legacy_preservation.py);
--     unresolved locations become geocode_failed reviews, never guesses;
--   * organization_hierarchy has no relationship evidence, so every row becomes
--     a relationship_review item instead of an unsourced entity_edge.
-- Gap-fill only: no existing canonical value is overwritten. Idempotent.
BEGIN;

-- 1. Append-only record of each legacy value and where it went.
CREATE TABLE IF NOT EXISTS legacy_migration_record (
    legacy_migration_record_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    migration_batch_id text NOT NULL,
    legacy_table text NOT NULL,
    legacy_key text NOT NULL,
    legacy_field text NOT NULL,
    actor_id uuid REFERENCES actor(actor_id),
    disposition text NOT NULL CHECK (disposition IN (
        'fact','duplicate_of_fact','normalized','review','audit_only'
    )),
    destination_table text,
    destination_id uuid,
    legacy_value text,
    legacy_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (legacy_table, legacy_key, legacy_field),
    CHECK (disposition IN ('audit_only') OR destination_table IS NOT NULL)
);
DROP TRIGGER IF EXISTS legacy_migration_record_append_only ON legacy_migration_record;
CREATE TRIGGER legacy_migration_record_append_only
BEFORE UPDATE OR DELETE ON legacy_migration_record
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();

-- 2. Review kind for unsourced legacy relationships (superset of the 440 list).
ALTER TABLE review_item DROP CONSTRAINT IF EXISTS ck_review_item_kind;
ALTER TABLE review_item ADD CONSTRAINT ck_review_item_kind CHECK (review_kind IN (
    'verify_actor','category_doubt','geocode_failed','hub_needs_review',
    'hub_radius_overlap','hub_member_outside_radius','hub_center_drift','hub_proposal',
    'possible_duplicate','fact_conflict','pending_update','verify_person','verify_event',
    'identity','affiliation_change','classification','geocode','hub_assignment',
    'same_topic_overlap','new_hub','pending_human_update','relationship_review'
)) NOT VALID;

-- 3. Deterministic geography normalization (mirrors agents/common/geography.py).
CREATE TABLE IF NOT EXISTS us_state_alias (
    alias text PRIMARY KEY,
    state_code text NOT NULL REFERENCES region_state(state_code)
);
-- Generated from agents.common.geography.STATE_ALIASES (108 entries).
INSERT INTO us_state_alias(alias,state_code) VALUES
    ('ak','AK'),('al','AL'),('alabama','AL'),('alaska','AK'),('ar','AR'),('arizona','AZ'),
    ('arkansas','AR'),('az','AZ'),('ca','CA'),('california','CA'),('co','CO'),('colorado','CO'),
    ('connecticut','CT'),('ct','CT'),('d c','DC'),('dc','DC'),('de','DE'),('delaware','DE'),
    ('district columbia','DC'),('district of columbia','DC'),('fl','FL'),('florida','FL'),
    ('ga','GA'),('georgia','GA'),('hawaii','HI'),('hi','HI'),('ia','IA'),('id','ID'),
    ('idaho','ID'),('il','IL'),('illinois','IL'),('in','IN'),('indiana','IN'),('iowa','IA'),
    ('kansas','KS'),('kentucky','KY'),('ks','KS'),('ky','KY'),('la','LA'),('louisiana','LA'),
    ('ma','MA'),('maine','ME'),('maryland','MD'),('massachusetts','MA'),('md','MD'),('me','ME'),
    ('mi','MI'),('michigan','MI'),('minnesota','MN'),('mississippi','MS'),('missouri','MO'),
    ('mn','MN'),('mo','MO'),('montana','MT'),('ms','MS'),('mt','MT'),('nc','NC'),('nd','ND'),
    ('ne','NE'),('nebraska','NE'),('nevada','NV'),('new hampshire','NH'),('new jersey','NJ'),
    ('new mexico','NM'),('new york','NY'),('nh','NH'),('nj','NJ'),('nm','NM'),
    ('north carolina','NC'),('north dakota','ND'),('nv','NV'),('ny','NY'),('oh','OH'),
    ('ohio','OH'),('ok','OK'),('oklahoma','OK'),('or','OR'),('oregon','OR'),('pa','PA'),
    ('pennsylvania','PA'),('rhode island','RI'),('ri','RI'),('sc','SC'),('sd','SD'),
    ('south carolina','SC'),('south dakota','SD'),('tennessee','TN'),('texas','TX'),('tn','TN'),
    ('tx','TX'),('ut','UT'),('utah','UT'),('va','VA'),('vermont','VT'),('virginia','VA'),
    ('vt','VT'),('wa','WA'),('washington','WA'),('washington d c','DC'),('washington dc','DC'),
    ('washington district of columbia','DC'),('washington state','WA'),('west virginia','WV'),
    ('wi','WI'),('wisconsin','WI'),('wv','WV'),('wy','WY'),('wyoming','WY')
ON CONFLICT (alias) DO NOTHING;

CREATE OR REPLACE FUNCTION ghus_plain_text(value text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT btrim(regexp_replace(lower(regexp_replace(regexp_replace(
           normalize(coalesce(value,''),NFKD),
           '[̀-ͯ᪰-᫿᷀-᷿⃐-⃿︠-︯]','','g'),
         '[^A-Za-z0-9]+',' ','g')),' +',' ','g'))
$$;

CREATE OR REPLACE FUNCTION ghus_normalize_state(value text)
RETURNS text LANGUAGE sql STABLE PARALLEL SAFE AS $$
  SELECT state_code FROM us_state_alias WHERE alias=ghus_plain_text(value)
$$;

CREATE OR REPLACE FUNCTION ghus_normalize_country(value text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN ghus_plain_text(value) IN
      ('','us','usa','united states','united states of america')
    THEN 'US' ELSE btrim(coalesce(value,'')) END
$$;

CREATE OR REPLACE FUNCTION ghus_normalize_city(value text)
RETURNS text LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
  tokens text[];
  suffixes text[][] := ARRAY[
    ARRAY['consolidated','government','balance'],
    ARRAY['metropolitan','government','balance'],
    ARRAY['unified','government','balance'],
    ARRAY['urban','county','balance'],
    ARRAY['consolidated','government',NULL],
    ARRAY['metropolitan','government',NULL],
    ARRAY['unified','government',NULL],
    ARRAY['municipality',NULL,NULL],
    ARRAY['borough',NULL,NULL],
    ARRAY['village',NULL,NULL],
    ARRAY['town',NULL,NULL],
    ARRAY['city',NULL,NULL],
    ARRAY['cdp',NULL,NULL],
    ARRAY['balance',NULL,NULL]];
  suffix text[];
  n int;
  removed boolean := true;
  plain text := ghus_plain_text(value);
BEGIN
  IF plain = '' THEN RETURN ''; END IF;
  SELECT array_agg(CASE token WHEN 'st' THEN 'saint' WHEN 'ste' THEN 'sainte'
                              WHEN 'ft' THEN 'fort' WHEN 'mt' THEN 'mount' ELSE token END
                   ORDER BY ordinality)
    INTO tokens FROM unnest(string_to_array(plain,' ')) WITH ORDINALITY token;
  WHILE coalesce(array_length(tokens,1),0) > 0 AND removed LOOP
    removed := false;
    FOR i IN 1..array_length(suffixes,1) LOOP
      suffix := ARRAY(SELECT x FROM unnest(suffixes[i:i]) x WHERE x IS NOT NULL);
      n := array_length(suffix,1);
      IF array_length(tokens,1) >= n
         AND tokens[array_length(tokens,1)-n+1:array_length(tokens,1)] = suffix THEN
        tokens := tokens[1:array_length(tokens,1)-n];
        removed := true;
        EXIT;
      END IF;
    END LOOP;
  END LOOP;
  RETURN coalesce(array_to_string(tokens,' '),'');
END;
$$;

-- 4. Geography backfill for single-location actors.
CREATE TEMP TABLE phase12_geo ON COMMIT DROP AS
WITH base AS (
  SELECT a.actor_id, a.location_city, a.state, a.country, a.source_id,
         ghus_normalize_country(a.country) country_code,
         ghus_normalize_state(a.state) norm_state,
         ghus_normalize_city(a.location_city) norm_city
  FROM actor a
  WHERE coalesce(a.is_multi_location,false) = false
), candidates AS (
  SELECT b.actor_id, count(c.geoid) n_all,
         count(c.geoid) FILTER (WHERE ghus_plain_text(c.place_name)=ghus_plain_text(b.location_city)) n_exact
  FROM base b
  LEFT JOIN us_city_coord c ON c.state_code=b.norm_state AND c.normalized_city=b.norm_city
                           AND b.norm_city <> ''
  GROUP BY b.actor_id
)
SELECT b.*, rs.region_code,
  CASE
    WHEN b.country_code <> 'US' THEN 'country_not_supported'
    WHEN b.norm_city = '' THEN 'missing_city'
    WHEN b.norm_state IS NULL THEN 'unknown_state'
    WHEN k.n_all = 0 THEN 'city_not_found'
    WHEN k.n_all > 1 AND k.n_exact <> 1 THEN 'ambiguous_city'
    ELSE NULL
  END failure_reason,
  (SELECT c.geoid FROM us_city_coord c
   WHERE c.state_code=b.norm_state AND c.normalized_city=b.norm_city AND b.norm_city <> ''
     AND (k.n_all = 1 OR ghus_plain_text(c.place_name)=ghus_plain_text(b.location_city))
   ORDER BY c.geoid LIMIT 1) geoid
FROM base b
JOIN candidates k USING (actor_id)
LEFT JOIN region_state rs ON rs.state_code=b.norm_state;

UPDATE actor a
SET state_code = coalesce(a.state_code, g.norm_state),
    region_code = coalesce(a.region_code, g.region_code),
    latitude = coalesce(a.latitude, c.latitude),
    longitude = coalesce(a.longitude, c.longitude)
FROM phase12_geo g
LEFT JOIN us_city_coord c ON c.geoid = g.geoid AND g.failure_reason IS NULL
WHERE a.actor_id = g.actor_id
  AND ((a.state_code IS NULL AND g.norm_state IS NOT NULL)
    OR (a.region_code IS NULL AND g.region_code IS NOT NULL)
    OR (a.latitude IS NULL AND c.latitude IS NOT NULL));

INSERT INTO actor_location (actor_location_id,actor_id,location_name,country,state_code,
                            city,region_code,latitude,longitude,is_primary,source_id)
SELECT gen_random_uuid(), g.actor_id, NULL, 'US', g.norm_state, g.location_city,
       g.region_code, c.latitude, c.longitude, true, g.source_id
FROM phase12_geo g
JOIN us_city_coord c ON c.geoid = g.geoid
JOIN source s ON s.source_id = g.source_id
WHERE g.failure_reason IS NULL
  AND NOT EXISTS (SELECT 1 FROM actor_location l WHERE l.actor_id = g.actor_id AND l.is_primary);

-- Raw legacy state preserved for every actor that had one.
INSERT INTO legacy_migration_record(migration_batch_id,legacy_table,legacy_key,legacy_field,
    actor_id,disposition,destination_table,destination_id,legacy_value,legacy_metadata,reason)
SELECT 'phase12_legacy_preservation_2026_10','actor',a.actor_id::text,'state',a.actor_id,
       CASE WHEN g.norm_state IS NOT NULL THEN 'normalized' ELSE 'review' END,
       CASE WHEN g.norm_state IS NOT NULL THEN 'actor.state_code' ELSE 'review_item' END,
       NULL, a.state,
       jsonb_build_object('state_code',g.norm_state,'region_code',g.region_code),
       CASE WHEN g.norm_state IS NULL THEN 'state value not a recognized US state' END
FROM actor a JOIN phase12_geo g USING (actor_id)
WHERE nullif(btrim(a.state),'') IS NOT NULL
ON CONFLICT (legacy_table,legacy_key,legacy_field) DO NOTHING;

INSERT INTO review_item(review_kind,entity_type,entity_id,priority,payload,status)
SELECT 'geocode_failed','actor',g.actor_id,'normal',
       jsonb_build_object(
         'issue','geocode_failed','state','not_found','reason',g.failure_reason,
         'city',g.location_city,'legacy_state',g.state,'country',g.country,
         'state_code',g.norm_state,'normalized_city',g.norm_city,
         'migration_batch_id','phase12_legacy_preservation_2026_10'),
       'pending'
FROM phase12_geo g
JOIN actor a USING (actor_id)
WHERE g.failure_reason IS NOT NULL AND a.latitude IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM review_item r
    WHERE r.review_kind='geocode_failed' AND r.entity_id=g.actor_id
      AND r.payload->>'migration_batch_id'='phase12_legacy_preservation_2026_10');

-- 5. Legacy scalar narrative fields -> imported baseline facts (topic-null scope).
DO $facts$
DECLARE
  field text;
BEGIN
  FOREACH field IN ARRAY ARRAY['description','primary_technical_focus','technical_approach',
      'current_activities','technology_ip_notes','key_constraints','funding_summary',
      'estimated_trl','primary_lifecycle_role'] LOOP
    EXECUTE format($sql$
      WITH legacy AS (
        SELECT a.actor_id, a.%1$I::text raw_value,
               CASE WHEN %2$L='estimated_trl' THEN to_jsonb(a.%1$I) ELSE to_jsonb(a.%1$I::text) END value,
               s.source_id, s.retrieved_at, s.trust_tier
        FROM actor a
        LEFT JOIN source s ON s.source_id=a.source_id AND s.retrieved_at IS NOT NULL
        WHERE nullif(btrim(a.%1$I::text),'') IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM legacy_migration_record r
                          WHERE r.legacy_table='actor' AND r.legacy_key=a.actor_id::text
                            AND r.legacy_field=%2$L)
      ), inserted AS (
        INSERT INTO actor_fact(actor_fact_id,actor_id,topic_id,fact_type,fact_key,fact_value,
            collection_state,layer,source_id,source_origin,confidence,observed_at,retrieved_at,
            generated_by,creator_class,lifecycle_state)
        SELECT gen_random_uuid(),actor_id,NULL,'legacy_baseline',%2$L,value,'found',1,
               source_id,'imported_phase1',
               CASE WHEN trust_tier='verified' THEN 'medium' ELSE 'low' END,
               NULL,retrieved_at,'phase12_legacy_preservation_2026_10','agent','accepted'
        FROM legacy WHERE source_id IS NOT NULL
        RETURNING actor_fact_id, actor_id
      )
      INSERT INTO legacy_migration_record(migration_batch_id,legacy_table,legacy_key,
          legacy_field,actor_id,disposition,destination_table,destination_id,legacy_value,reason)
      SELECT 'phase12_legacy_preservation_2026_10','actor',l.actor_id::text,%2$L,l.actor_id,
             CASE WHEN i.actor_fact_id IS NULL THEN 'audit_only' ELSE 'fact' END,
             CASE WHEN i.actor_fact_id IS NULL THEN NULL ELSE 'actor_fact' END,
             i.actor_fact_id, l.raw_value,
             CASE WHEN i.actor_fact_id IS NULL
                  THEN 'no legacy source row; value retained only in this migration record' END
      FROM legacy l LEFT JOIN inserted i USING (actor_id)
    $sql$, field, field);
  END LOOP;
END
$facts$;

-- 6. actor_profile summaries -> imported baseline facts (one profile per actor).
DO $one_profile$ BEGIN
  IF EXISTS (SELECT 1 FROM actor_profile GROUP BY actor_id HAVING count(*) > 1) THEN
    RAISE EXCEPTION '482 expects at most one actor_profile per actor';
  END IF;
END $one_profile$;
DO $profiles$
DECLARE
  field text;
BEGIN
  FOREACH field IN ARRAY ARRAY['profile_summary','identity_summary','technical_summary',
      'lifecycle_summary','funding_summary'] LOOP
    EXECUTE format($sql$
      WITH legacy AS (
        SELECT p.actor_profile_id, p.actor_id, p.%1$I raw_value, s.source_id, s.retrieved_at,
               s.trust_tier,
               jsonb_build_object('generated_by',p.generated_by,'confidence',p.confidence,
                 'verification_status',p.verification_status,'legacy_source_id',p.source_id,
                 'created_at',p.created_at,'updated_at',p.updated_at) metadata
        FROM actor_profile p
        LEFT JOIN source s ON s.source_id=p.source_id AND s.retrieved_at IS NOT NULL
        WHERE nullif(btrim(p.%1$I),'') IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM legacy_migration_record r
                          WHERE r.legacy_table='actor_profile'
                            AND r.legacy_key=p.actor_profile_id::text AND r.legacy_field=%1$L)
      ), inserted AS (
        INSERT INTO actor_fact(actor_fact_id,actor_id,topic_id,fact_type,fact_key,fact_value,
            collection_state,layer,source_id,source_origin,confidence,observed_at,retrieved_at,
            generated_by,creator_class,lifecycle_state)
        SELECT gen_random_uuid(),actor_id,NULL,'legacy_profile',%1$L,to_jsonb(raw_value),'found',1,
               source_id,'imported_phase1',
               CASE WHEN trust_tier='verified' THEN 'medium' ELSE 'low' END,
               NULL,retrieved_at,'phase12_legacy_preservation_2026_10','agent','accepted'
        FROM legacy WHERE source_id IS NOT NULL
        RETURNING actor_fact_id, actor_id
      )
      INSERT INTO legacy_migration_record(migration_batch_id,legacy_table,legacy_key,
          legacy_field,actor_id,disposition,destination_table,destination_id,legacy_value,
          legacy_metadata,reason)
      SELECT 'phase12_legacy_preservation_2026_10','actor_profile',l.actor_profile_id::text,
             %1$L,l.actor_id,
             CASE WHEN i.actor_fact_id IS NULL THEN 'audit_only' ELSE 'fact' END,
             CASE WHEN i.actor_fact_id IS NULL THEN NULL ELSE 'actor_fact' END,
             i.actor_fact_id, l.raw_value, l.metadata,
             CASE WHEN i.actor_fact_id IS NULL
                  THEN 'no legacy source row; value retained only in this migration record' END
      FROM legacy l LEFT JOIN inserted i USING (actor_id)
    $sql$, field);
  END LOOP;
END
$profiles$;

-- 7. actor_capability_fact rows are copies of actor scalar fields. Link each one
--    to the baseline fact holding the identical value; otherwise keep it as its
--    own fact (when sourced) or in the audit record.
WITH legacy AS (
  SELECT f.actor_capability_fact_id, f.actor_id, f.fact_type, f.source_field, f.fact_value,
         replace(f.source_field,'actor.','') scalar_field,
         jsonb_build_object('fact_type',f.fact_type,'source_field',f.source_field,
           'evidence_url',f.evidence_url,'legacy_source_id',f.source_id,
           'confidence',f.confidence,'verification_status',f.verification_status,
           'generated_by',f.generated_by,'created_at',f.created_at) metadata
  FROM actor_capability_fact f
  WHERE NOT EXISTS (SELECT 1 FROM legacy_migration_record r
                    WHERE r.legacy_table='actor_capability_fact'
                      AND r.legacy_key=f.actor_capability_fact_id::text
                      AND r.legacy_field='fact_value')
)
INSERT INTO legacy_migration_record(migration_batch_id,legacy_table,legacy_key,legacy_field,
    actor_id,disposition,destination_table,destination_id,legacy_value,legacy_metadata,reason)
SELECT 'phase12_legacy_preservation_2026_10','actor_capability_fact',
       l.actor_capability_fact_id::text,'fact_value',l.actor_id,
       CASE WHEN fact.actor_fact_id IS NOT NULL THEN 'duplicate_of_fact' ELSE 'audit_only' END,
       CASE WHEN fact.actor_fact_id IS NOT NULL THEN 'actor_fact' END,
       fact.actor_fact_id, l.fact_value, l.metadata,
       CASE WHEN fact.actor_fact_id IS NULL
            THEN 'no matching sourced baseline fact; value retained only in this migration record' END
FROM legacy l
LEFT JOIN LATERAL (
  SELECT f.actor_fact_id FROM actor_fact f
  WHERE f.actor_id=l.actor_id AND f.fact_type='legacy_baseline' AND f.fact_key=l.scalar_field
    AND f.generated_by='phase12_legacy_preservation_2026_10'
    AND f.fact_value = to_jsonb(l.fact_value)
  LIMIT 1
) fact ON true;

-- 8. organization_hierarchy: no relationship evidence -> GHUS relationship review.
WITH legacy AS (
  SELECT h.parent_actor_id, h.child_actor_id, h.relationship_type, h.created_at,
         h.parent_actor_id::text||'>'||h.child_actor_id::text||'>'||h.relationship_type legacy_key
  FROM organization_hierarchy h
  WHERE NOT EXISTS (SELECT 1 FROM legacy_migration_record r
                    WHERE r.legacy_table='organization_hierarchy'
                      AND r.legacy_key=h.parent_actor_id::text||'>'||h.child_actor_id::text
                                       ||'>'||h.relationship_type
                      AND r.legacy_field='relationship')
), reviews AS (
  INSERT INTO review_item(review_kind,entity_type,entity_id,candidate_entity_id,priority,payload,status)
  SELECT 'relationship_review','actor',child_actor_id,parent_actor_id,'normal',
         jsonb_build_object(
           'issue','unsourced_legacy_relationship',
           'legacy_relationship_type',relationship_type,
           'proposed_relationship_type','unit_of',
           'subject_actor_id',child_actor_id,'object_actor_id',parent_actor_id,
           'legacy_key',legacy_key,
           'note','Legacy hierarchy row has no source. Confirm with evidence before an entity_edge is created.',
           'migration_batch_id','phase12_legacy_preservation_2026_10'),
         'pending'
  FROM legacy
  RETURNING review_item_id, payload->>'legacy_key' legacy_key
)
INSERT INTO legacy_migration_record(migration_batch_id,legacy_table,legacy_key,legacy_field,
    actor_id,disposition,destination_table,destination_id,legacy_value,legacy_metadata,reason)
SELECT 'phase12_legacy_preservation_2026_10','organization_hierarchy',l.legacy_key,'relationship',
       l.child_actor_id,'review','review_item',r.review_item_id,l.relationship_type,
       jsonb_build_object('parent_actor_id',l.parent_actor_id,'child_actor_id',l.child_actor_id,
                          'created_at',l.created_at),
       'no relationship source; GHUS review required before any entity_edge'
FROM legacy l JOIN reviews r USING (legacy_key);

COMMIT;
