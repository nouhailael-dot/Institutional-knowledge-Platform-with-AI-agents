-- PROPOSAL ONLY. Supersedes the contract of frozen proposal 250 without editing it.
-- Deploy 250 + 300 + 420 as one additive V2 package before application writers.
-- Applied alone after 250 has received writes, the CHECK replacement is breaking;
-- rollout must first prove that no deprecated connected_to_strategic_entity rows exist.
BEGIN;

CREATE TABLE IF NOT EXISTS entity_edge_type_definition (
    relationship_type text PRIMARY KEY,
    subject_types text[] NOT NULL,
    object_types text[] NOT NULL,
    establishes_actor_family boolean NOT NULL DEFAULT false,
    definition text NOT NULL,
    CHECK (cardinality(subject_types) > 0 AND cardinality(object_types) > 0)
);

INSERT INTO entity_edge_type_definition
    (relationship_type,subject_types,object_types,establishes_actor_family,definition)
VALUES
    ('unit_of',ARRAY['actor'],ARRAY['actor'],true,'Actor is an organizational unit of actor.'),
    ('operated_by',ARRAY['actor'],ARRAY['actor'],true,'Actor or facility is operated by actor.'),
    ('affiliated_with',ARRAY['person'],ARRAY['actor'],false,'Person has a sourced professional affiliation.'),
    ('member_of',ARRAY['actor'],ARRAY['actor'],false,'Actor is a member; this is not ownership.'),
    ('portfolio_of',ARRAY['actor'],ARRAY['actor'],false,'Startup is in an accelerator or investor portfolio; this is not ownership.'),
    ('spinout_of',ARRAY['actor'],ARRAY['actor'],false,'Actor spun out of another actor.'),
    ('funded_by',ARRAY['actor'],ARRAY['actor'],false,'Actor received funding from another actor.'),
    ('collaborates_with',ARRAY['actor'],ARRAY['actor'],false,'Actors have a sourced collaboration.'),
    ('organizes',ARRAY['actor'],ARRAY['event'],false,'Actor organizes an event.'),
    ('participates_in',ARRAY['actor','person'],ARRAY['event'],false,'Actor or person participates in an event.'),
    ('connected_to_um6p_ocp',ARRAY['actor','person','event'],ARRAY['strategic_entity'],false,'Sourced connection to an allowlisted UM6P/OCP/INNOVX entity.')
ON CONFLICT (relationship_type) DO UPDATE SET
    subject_types=EXCLUDED.subject_types,
    object_types=EXCLUDED.object_types,
    establishes_actor_family=EXCLUDED.establishes_actor_family,
    definition=EXCLUDED.definition;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM entity_edge
        WHERE relationship_type='connected_to_strategic_entity'
    ) THEN
        RAISE EXCEPTION '420 refuses deprecated connected_to_strategic_entity rows; resolve rollout explicitly';
    END IF;
END $$;

ALTER TABLE entity_edge DROP CONSTRAINT IF EXISTS entity_edge_relationship_type_check;
ALTER TABLE entity_edge ADD CONSTRAINT entity_edge_relationship_type_check CHECK (
    relationship_type IN (
        'unit_of','operated_by','affiliated_with','member_of','portfolio_of',
        'spinout_of','funded_by','collaborates_with','organizes','participates_in',
        'connected_to_um6p_ocp'
    )
);

CREATE OR REPLACE FUNCTION ghus_validate_entity_edge()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    allowed_subjects text[];
    allowed_objects text[];
    endpoint_exists boolean;
BEGIN
    SELECT subject_types,object_types INTO allowed_subjects,allowed_objects
    FROM entity_edge_type_definition
    WHERE relationship_type=NEW.relationship_type;
    IF allowed_subjects IS NULL
       OR NOT NEW.subject_type=ANY(allowed_subjects)
       OR NOT NEW.object_type=ANY(allowed_objects) THEN
        RAISE EXCEPTION 'invalid endpoint pair % -> % for %',
            NEW.subject_type,NEW.object_type,NEW.relationship_type;
    END IF;

    IF NEW.subject_type='actor' THEN
        SELECT EXISTS(SELECT 1 FROM actor WHERE actor_id=NEW.subject_id) INTO endpoint_exists;
    ELSIF NEW.subject_type='person' THEN
        SELECT EXISTS(SELECT 1 FROM person WHERE person_id=NEW.subject_id) INTO endpoint_exists;
    ELSIF NEW.subject_type='event' THEN
        SELECT EXISTS(SELECT 1 FROM event WHERE event_id=NEW.subject_id) INTO endpoint_exists;
    ELSE
        SELECT EXISTS(SELECT 1 FROM strategic_entity WHERE strategic_entity_id=NEW.subject_id) INTO endpoint_exists;
    END IF;
    IF NOT endpoint_exists THEN
        RAISE EXCEPTION 'missing % subject endpoint %',NEW.subject_type,NEW.subject_id;
    END IF;

    IF NEW.object_type='actor' THEN
        SELECT EXISTS(SELECT 1 FROM actor WHERE actor_id=NEW.object_id) INTO endpoint_exists;
    ELSIF NEW.object_type='person' THEN
        SELECT EXISTS(SELECT 1 FROM person WHERE person_id=NEW.object_id) INTO endpoint_exists;
    ELSIF NEW.object_type='event' THEN
        SELECT EXISTS(SELECT 1 FROM event WHERE event_id=NEW.object_id) INTO endpoint_exists;
    ELSE
        SELECT EXISTS(SELECT 1 FROM strategic_entity WHERE strategic_entity_id=NEW.object_id) INTO endpoint_exists;
    END IF;
    IF NOT endpoint_exists THEN
        RAISE EXCEPTION 'missing % object endpoint %',NEW.object_type,NEW.object_id;
    END IF;
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION ghus_prevent_actor_family_cycle()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE cycle_found boolean;
BEGIN
    IF NEW.relationship_type NOT IN ('unit_of','operated_by') THEN
        RETURN NEW;
    END IF;
    WITH RECURSIVE ancestors(actor_id,path) AS (
        SELECT NEW.object_id,ARRAY[NEW.object_id]
        UNION ALL
        SELECT edge.object_id,ancestors.path || edge.object_id
        FROM ancestors
        JOIN entity_edge edge
          ON edge.subject_type='actor' AND edge.object_type='actor'
         AND edge.subject_id=ancestors.actor_id
         AND edge.relationship_type IN ('unit_of','operated_by')
        WHERE NOT edge.object_id=ANY(ancestors.path)
    )
    SELECT EXISTS(SELECT 1 FROM ancestors WHERE actor_id=NEW.subject_id)
    INTO cycle_found;
    IF cycle_found THEN
        RAISE EXCEPTION 'actor family cycle refused for % -> %',NEW.subject_id,NEW.object_id;
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS entity_edge_validate ON entity_edge;
CREATE TRIGGER entity_edge_validate
BEFORE INSERT ON entity_edge FOR EACH ROW EXECUTE FUNCTION ghus_validate_entity_edge();

DROP TRIGGER IF EXISTS entity_edge_prevent_family_cycle ON entity_edge;
CREATE TRIGGER entity_edge_prevent_family_cycle
BEFORE INSERT ON entity_edge FOR EACH ROW EXECUTE FUNCTION ghus_prevent_actor_family_cycle();

CREATE UNIQUE INDEX IF NOT EXISTS uq_entity_edge_identity
ON entity_edge(subject_type,subject_id,relationship_type,object_type,object_id,
               COALESCE(topic_id,'00000000-0000-0000-0000-000000000000'::uuid),source_id);

CREATE OR REPLACE VIEW actor_descendants AS
SELECT root_actor_id,descendant_actor_id,depth,path
FROM actor_descendant_edge;

COMMIT;
