-- Person rubric evidence and deterministic identity outcomes. Emit only; do not run automatically.

ALTER TABLE search_candidate
    ADD COLUMN IF NOT EXISTS identity_outcome text;

ALTER TABLE person_review_queue
    ADD COLUMN IF NOT EXISTS review_kind text NOT NULL DEFAULT 'identity',
    ADD COLUMN IF NOT EXISTS rubric jsonb,
    ADD COLUMN IF NOT EXISTS score_breakdown jsonb,
    ADD COLUMN IF NOT EXISTS rerank_position integer,
    ADD COLUMN IF NOT EXISTS rerank_reason text,
    ADD COLUMN IF NOT EXISTS identity_outcome text;

ALTER TABLE person_review_queue
    DROP CONSTRAINT IF EXISTS ck_person_review_queue_review_kind;

ALTER TABLE person_review_queue
    ADD CONSTRAINT ck_person_review_queue_review_kind
    CHECK (review_kind IN ('identity', 'rubric_band', 'profile_404'));

CREATE INDEX IF NOT EXISTS ix_person_review_queue_rubric_band
    ON person_review_queue (status, created_at)
    WHERE review_kind = 'rubric_band';

-- The canonical person and actor_person tables cannot carry provenance for all
-- five permitted discovery fields. This agent-owned row records the exact
-- affiliation/profile facts and their source in the same transaction as create.
CREATE TABLE IF NOT EXISTS person_discovery_profile (
    person_discovery_profile_id uuid PRIMARY KEY,
    person_id uuid NOT NULL REFERENCES person(person_id),
    actor_id uuid NOT NULL REFERENCES actor(actor_id),
    role varchar(120) NOT NULL,
    research_area text,
    public_profile_url text,
    source_id uuid NOT NULL REFERENCES source(source_id),
    source_url text NOT NULL,
    fetched_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_person_discovery_profile_source
    ON person_discovery_profile (person_id, actor_id, role, source_id);

CREATE INDEX IF NOT EXISTS ix_person_discovery_profile_reverify
    ON person_discovery_profile (person_id, fetched_at DESC)
    WHERE public_profile_url IS NOT NULL;
