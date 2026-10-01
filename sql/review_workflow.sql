-- Human review admission workflow.
-- EMIT ONLY. Do not run automatically; a database owner must review and apply it.

CREATE TABLE IF NOT EXISTS proposed_hub (
    proposed_hub_id uuid PRIMARY KEY,
    name varchar(255) NOT NULL,
    primary_city varchar(120),
    state varchar(80),
    country varchar(80),
    rationale text NOT NULL,
    source_table varchar(40) NOT NULL,
    source_row_id uuid NOT NULL,
    proposed_by varchar(120) NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'rejected')),
    reviewed_by varchar(120),
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_proposed_hub_source UNIQUE (source_table, source_row_id, name)
);

CREATE TABLE IF NOT EXISTS review_admission_decision (
    review_admission_decision_id uuid PRIMARY KEY,
    idempotency_key varchar(200) NOT NULL UNIQUE,
    entity_type varchar(20) NOT NULL
        CHECK (entity_type IN ('actor', 'event', 'person')),
    source_table varchar(40) NOT NULL
        CHECK (source_table IN ('search_candidate', 'event_review_queue', 'person_review_queue')),
    source_row_id uuid NOT NULL,
    decision_kind varchar(30) NOT NULL
        CHECK (decision_kind IN ('same_existing', 'new', 'reject', 'defer')),
    target_entity_id uuid,
    edited_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    hub_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    proposed_hub_id uuid REFERENCES proposed_hub(proposed_hub_id),
    reviewer varchar(120) NOT NULL,
    rejection_reason text,
    rejection_reason_other text,
    notes text,
    outcome jsonb NOT NULL,
    decided_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_review_admission_target
        CHECK (decision_kind <> 'same_existing' OR target_entity_id IS NOT NULL),
    CONSTRAINT ck_review_admission_rejection_reason
        CHECK (
            (decision_kind <> 'reject' AND rejection_reason IS NULL AND rejection_reason_other IS NULL)
            OR
            (decision_kind = 'reject' AND rejection_reason IN (
                'Not relevant to GHUS sectors',
                'Not an organisation / event / person page',
                'Duplicate of an existing record',
                'Outside target geography',
                'Past event with no useful participants',
                'Insufficient evidence on the page',
                'Other'
            ) AND (rejection_reason <> 'Other' OR btrim(rejection_reason_other) <> ''))
        )
);

CREATE INDEX IF NOT EXISTS ix_review_admission_source
    ON review_admission_decision (source_table, source_row_id, decided_at DESC);

ALTER TABLE search_candidate
    ADD COLUMN IF NOT EXISTS review_status varchar(20) NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS review_updated_at timestamptz;

ALTER TABLE search_candidate
    DROP CONSTRAINT IF EXISTS search_candidate_review_status_check;
ALTER TABLE search_candidate
    ADD CONSTRAINT search_candidate_review_status_check
    CHECK (review_status IN ('pending', 'approved', 'rejected', 'deferred', 'superseded'));

ALTER TABLE event_review_queue
    ADD COLUMN IF NOT EXISTS notes text;
ALTER TABLE event_review_queue
    DROP CONSTRAINT IF EXISTS event_review_queue_status_check;
ALTER TABLE event_review_queue
    ADD CONSTRAINT event_review_queue_status_check
    CHECK (status IN ('pending', 'approved', 'rejected', 'deferred', 'superseded'));

ALTER TABLE person_review_queue
    DROP CONSTRAINT IF EXISTS person_review_queue_status_check;
ALTER TABLE person_review_queue
    ADD CONSTRAINT person_review_queue_status_check
    CHECK (status IN ('pending', 'approved', 'rejected', 'deferred', 'superseded'));

CREATE INDEX IF NOT EXISTS ix_search_candidate_review_status
    ON search_candidate (review_status, created_at);
