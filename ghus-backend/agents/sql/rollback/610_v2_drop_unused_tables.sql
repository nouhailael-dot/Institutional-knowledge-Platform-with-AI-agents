-- Rollback for 610_v2_drop_unused_tables.sql: recreates the four tables
-- exactly as the shared database defined them on 4 Nov 2026 (all were empty).

BEGIN;

CREATE TABLE IF NOT EXISTS public.funding_source (
    funding_source_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    category character varying(40),
    description text,
    CONSTRAINT funding_source_pkey PRIMARY KEY (funding_source_id),
    CONSTRAINT funding_source_name_key UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS public.hub_funding (
    hub_id uuid NOT NULL REFERENCES public.hub(hub_id),
    funding_source_id uuid NOT NULL REFERENCES public.funding_source(funding_source_id),
    narrative text,
    source_id uuid REFERENCES public.source(source_id),
    CONSTRAINT hub_funding_pkey PRIMARY KEY (hub_id, funding_source_id)
);

CREATE TABLE IF NOT EXISTS public.hub_sector_strength (
    hub_id uuid NOT NULL REFERENCES public.hub(hub_id),
    sector_id uuid NOT NULL REFERENCES public.sector(sector_id),
    strength_score numeric(5,2),
    actor_count integer,
    top_actor_ids uuid[],
    narrative_summary text,
    last_computed timestamp without time zone,
    CONSTRAINT hub_sector_strength_pkey PRIMARY KEY (hub_id, sector_id)
);

CREATE TABLE IF NOT EXISTS public.person_verification_event (
    person_verification_event_id uuid DEFAULT gen_random_uuid() NOT NULL,
    person_id uuid NOT NULL REFERENCES public.person(person_id),
    decision text NOT NULL CHECK (decision IN ('verified', 'rejected')),
    decided_by text,
    decided_at timestamp with time zone,
    reason text,
    rejection_reason text,
    source_id uuid REFERENCES public.source(source_id),
    decision_origin text NOT NULL,
    migration_batch_id uuid,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT person_verification_event_pkey PRIMARY KEY (person_verification_event_id),
    CONSTRAINT ck_person_verification_origin CHECK (
        (decision_origin = 'ghus_review' AND NULLIF(btrim(decided_by), '') IS NOT NULL
         AND decided_at IS NOT NULL AND migration_batch_id IS NULL)
        OR (decision_origin <> 'ghus_review' AND migration_batch_id IS NOT NULL)),
    CONSTRAINT ck_person_verification_rejection CHECK (
        decision <> 'rejected' OR NULLIF(btrim(rejection_reason), '') IS NOT NULL)
);

DROP TRIGGER IF EXISTS person_verification_event_append_only ON public.person_verification_event;
CREATE TRIGGER person_verification_event_append_only
    BEFORE DELETE OR UPDATE ON public.person_verification_event
    FOR EACH ROW EXECUTE FUNCTION public.ghus_guard_no_delete();

ALTER TABLE public.funding_source ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.hub_funding ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.hub_sector_strength ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.person_verification_event ENABLE ROW LEVEL SECURITY;

COMMIT;
