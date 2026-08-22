-- Prompt D: event review queue for same-date fuzzy event title matches.
-- Do not run automatically; this file is emitted for a human migration step.

CREATE TABLE IF NOT EXISTS event_review_queue (
    event_review_id uuid PRIMARY KEY,
    staged_record_id uuid NOT NULL REFERENCES staged_record(staged_record_id) ON DELETE CASCADE,
    candidate_event_id uuid NOT NULL REFERENCES event(event_id),
    similarity_score numeric(6, 5) NOT NULL,
    staged_title text NOT NULL,
    candidate_title text NOT NULL,
    shared_start_date date NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'superseded')),
    reviewer text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (staged_record_id, candidate_event_id)
);

CREATE INDEX IF NOT EXISTS ix_event_review_queue_status
    ON event_review_queue (status, created_at);
