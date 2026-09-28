-- Additive split: new views preserve legacy actor_type and verification_status.
BEGIN;
CREATE OR REPLACE VIEW actor_v1_compat AS
SELECT
    a.actor_id, a.name, a.slug, a.actor_type, a.actor_type_raw, a.description,
    a.website, a.location_city, a.state, a.country, a.source_id,
    a.verification_status, a.confidence, a.created_at, a.updated_at
FROM actor a;

CREATE OR REPLACE VIEW staged_record_agent3_compat AS
SELECT sr.*,
    COALESCE(sr.normalized_payload->>'actor_category', sr.normalized_payload->>'actor_type')
        AS actor_type
FROM staged_record sr;

CREATE OR REPLACE VIEW actor_profile_current AS
SELECT
    a.actor_id, a.name, a.actor_category, a.category_type, a.description,
    a.website, a.website_domain, a.location_city, a.state_code, a.region_code,
    a.record_status, a.source_origin, f.topic_id,
    jsonb_object_agg(f.fact_key,f.fact_value)
        FILTER (WHERE f.collection_state='found') AS current_facts
FROM actor a
LEFT JOIN actor_fact_current f ON f.actor_id=a.actor_id
GROUP BY a.actor_id,f.topic_id;

COMMENT ON VIEW actor_v1_compat IS
    'Temporary legacy reader. actor_type and verification_status remain canonical during the additive period.';
COMMENT ON VIEW staged_record_agent3_compat IS
    'Temporary Agent 3 compatibility alias allowed by Architecture V2.';
COMMIT;
