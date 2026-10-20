-- Prompt E2: review-only queue for discovered public professional person records.
-- Do not run automatically; this file is emitted for a human migration step.

CREATE TABLE IF NOT EXISTS person_review_queue (
    person_review_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    staged_record_id uuid NOT NULL REFERENCES staged_record(staged_record_id) ON DELETE CASCADE,
    source_id uuid NOT NULL REFERENCES source(source_id),
    candidate_person_id uuid REFERENCES person(person_id),
    score numeric(4, 3),
    staged_name text NOT NULL,
    affiliation text,
    role text,
    public_profile_url text,
    research_area text,
    candidate_name text,
    source_url text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'superseded')),
    reviewer text,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_person_review_candidate
    ON person_review_queue (staged_record_id, candidate_person_id)
    WHERE candidate_person_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_person_review_no_candidate
    ON person_review_queue (staged_record_id)
    WHERE candidate_person_id IS NULL;

CREATE INDEX IF NOT EXISTS ix_person_review_queue_status
    ON person_review_queue (status, created_at);
