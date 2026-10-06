-- PROPOSAL ONLY. Stable read surface for applications across the V2 cutover.
-- Exposes final V2 names before migration 500 runs; the view follows 500's
-- column renames (location_city -> city, alternate_names -> alt_names) and does
-- not reference any column 500 drops. Narrative fields come from the imported
-- baseline facts written by 482, so they survive the column drop.
BEGIN;
CREATE OR REPLACE VIEW actor_read AS
SELECT a.actor_id, a.name, a.slug, a.actor_category, a.category_type, a.category_note,
       a.category_needs_review, a.description, a.website, a.website_domain,
       a.location_city AS city, a.state_code, a.region_code, a.country,
       a.latitude, a.longitude, a.is_multi_location, a.status, a.source_origin,
       a.source_id, a.merged_into_actor_id, a.alternate_names AS alt_names,
       a.created_at, a.updated_at,
       f.primary_technical_focus, f.technical_approach, f.current_activities,
       f.technology_ip_notes, f.key_constraints, f.funding_summary,
       f.estimated_trl::smallint AS estimated_trl, f.primary_lifecycle_role
FROM actor a
LEFT JOIN LATERAL (
    SELECT max(fact_value #>> '{}') FILTER (WHERE fact_key='primary_technical_focus') primary_technical_focus,
           max(fact_value #>> '{}') FILTER (WHERE fact_key='technical_approach') technical_approach,
           max(fact_value #>> '{}') FILTER (WHERE fact_key='current_activities') current_activities,
           max(fact_value #>> '{}') FILTER (WHERE fact_key='technology_ip_notes') technology_ip_notes,
           max(fact_value #>> '{}') FILTER (WHERE fact_key='key_constraints') key_constraints,
           max(fact_value #>> '{}') FILTER (WHERE fact_key='funding_summary') funding_summary,
           max(fact_value #>> '{}') FILTER (WHERE fact_key='estimated_trl') estimated_trl,
           max(fact_value #>> '{}') FILTER (WHERE fact_key='primary_lifecycle_role') primary_lifecycle_role
    FROM actor_fact
    WHERE actor_fact.actor_id = a.actor_id AND fact_type = 'legacy_baseline'
) f ON true;
COMMENT ON VIEW actor_read IS
    'Architecture V2 application read surface; stable across migration 500.';
COMMIT;
