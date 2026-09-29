-- DEFERRED; NO RUNNER. P7 + P15 -> P12.
UPDATE proposed_hub SET proposal_kind = 'legacy_review' WHERE proposal_kind IS NULL;
ALTER TABLE proposed_hub
    ALTER COLUMN proposal_kind SET DEFAULT 'legacy_review',
    ALTER COLUMN proposal_kind SET NOT NULL;
ALTER TABLE proposed_hub ADD CONSTRAINT fk_proposed_hub_topic
    FOREIGN KEY (topic_id) REFERENCES topic(topic_id) NOT VALID;
ALTER TABLE proposed_hub ADD CONSTRAINT fk_proposed_hub_final_hub
    FOREIGN KEY (final_hub_id) REFERENCES hub(hub_id) NOT VALID;
ALTER TABLE proposed_hub ADD CONSTRAINT ck_proposed_hub_kind
    CHECK (proposal_kind IN ('legacy_review','deterministic_cluster')) NOT VALID;
ALTER TABLE proposed_hub ADD CONSTRAINT ck_proposed_hub_radius
    CHECK (radius_miles IS NULL OR (radius_miles > 0 AND radius_miles <= 200)) NOT VALID;
ALTER TABLE proposed_hub ADD CONSTRAINT ck_proposed_hub_core
    CHECK (core_radius_miles IS NULL OR core_radius_miles = 50) NOT VALID;
ALTER TABLE proposed_hub ADD CONSTRAINT ck_proposed_hub_counts CHECK (
    proposal_kind <> 'deterministic_cluster'
    OR (independent_family_count >= 10 AND category_count >= 5
        AND topic_id IS NOT NULL AND membership_fingerprint IS NOT NULL)
) NOT VALID;
