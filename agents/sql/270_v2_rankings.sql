-- PROPOSAL ONLY. Rankings are university-only and attributed to the published subject.
BEGIN;

CREATE TABLE IF NOT EXISTS actor_ranking (
    actor_ranking_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id uuid NOT NULL REFERENCES actor(actor_id),
    context_actor_id uuid REFERENCES actor(actor_id),
    publisher text NOT NULL CHECK (publisher IN ('QS','THE','U.S. News','ARWU')),
    ranking_name text NOT NULL,
    ranking_year integer NOT NULL CHECK (ranking_year BETWEEN 1900 AND 2200),
    subject text,
    ranked_entity_name text NOT NULL,
    position_text text NOT NULL,
    source_id uuid NOT NULL REFERENCES source(source_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (actor_id,publisher,ranking_name,ranking_year,subject,position_text,source_id)
);

DROP TRIGGER IF EXISTS actor_ranking_append_only ON actor_ranking;
CREATE TRIGGER actor_ranking_append_only BEFORE UPDATE OR DELETE ON actor_ranking
FOR EACH ROW EXECUTE FUNCTION ghus_reject_mutation();
COMMIT;
-- ROLLBACK: export rankings, drop trigger/table.

