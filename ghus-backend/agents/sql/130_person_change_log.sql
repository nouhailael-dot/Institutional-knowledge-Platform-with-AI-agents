-- Human-approved person affiliation changes with source-level provenance.
-- Emit only; AGENTS.md prohibits running migrations from the agent session.

CREATE TABLE IF NOT EXISTS person_change_log (
    person_change_id uuid PRIMARY KEY,
    person_id uuid NOT NULL REFERENCES person(person_id),
    field_name varchar(80) NOT NULL,
    previous_value text NOT NULL,
    new_value text NOT NULL,
    source_url text NOT NULL,
    changed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_person_change_log_field
        CHECK (field_name = 'affiliation'),
    CONSTRAINT ck_person_change_log_value_changed
        CHECK (previous_value <> new_value)
);

CREATE INDEX IF NOT EXISTS ix_person_change_log_person_changed
    ON person_change_log (person_id, changed_at DESC);
