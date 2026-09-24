-- PROPOSAL ONLY. Topic vocabulary and actor-topic mapping.
BEGIN;

CREATE TABLE IF NOT EXISTS topic (
    topic_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE,
    name text NOT NULL UNIQUE,
    description text,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS actor_topic (
    actor_id uuid NOT NULL REFERENCES actor(actor_id),
    topic_id uuid NOT NULL REFERENCES topic(topic_id),
    match_strength text NOT NULL CHECK (match_strength IN ('strong','moderate')),
    match_reason text NOT NULL CHECK (char_length(match_reason) BETWEEN 1 AND 1000),
    source_id uuid NOT NULL REFERENCES source(source_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (actor_id,topic_id,source_id)
);

CREATE INDEX IF NOT EXISTS ix_actor_topic_topic ON actor_topic(topic_id,actor_id);
COMMIT;
-- ROLLBACK: export mappings, then drop actor_topic and topic.

