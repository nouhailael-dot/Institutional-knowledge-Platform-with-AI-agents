-- Rollback of migration 750: recreates organization_ranking (with its guard function,
-- triggers, keys and the actor_ranking stand-in view) and query_log, exactly as they
-- were after 720. query_log comes back empty: its old rows are in the backup taken
-- before 750. Then: DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '750';
-- Roll 750 back before rolling 720 back.

BEGIN;

CREATE FUNCTION public.ghus_guard_ranking_is_university()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE category text;
BEGIN
    SELECT a.organization_category INTO category FROM organization a
     WHERE a.organization_id = NEW.organization_id;
    IF category IS DISTINCT FROM 'university_academic' THEN
        RAISE EXCEPTION
            'rankings are recorded for university organizations only; organization % is %',
            NEW.organization_id, COALESCE(category, 'unclassified');
    END IF;
    RETURN NEW;
END $function$;

CREATE TABLE public.organization_ranking (
    organization_ranking_id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    context_organization_id uuid,
    publisher text NOT NULL,
    ranking_name text NOT NULL,
    ranking_year integer NOT NULL,
    subject text,
    ranked_entity_name text NOT NULL,
    position_text text NOT NULL,
    source_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT organization_ranking_publisher_check CHECK ((publisher = ANY (ARRAY['QS'::text, 'THE'::text, 'U.S. News'::text, 'ARWU'::text]))),
    CONSTRAINT organization_ranking_ranking_year_check CHECK (((ranking_year >= 1900) AND (ranking_year <= 2200)))
);
ALTER TABLE ONLY public.organization_ranking
    ADD CONSTRAINT actor_ranking_actor_id_publisher_ranking_name_ranking_year__key UNIQUE (organization_id, publisher, ranking_name, ranking_year, subject, position_text, source_id);
ALTER TABLE ONLY public.organization_ranking
    ADD CONSTRAINT organization_ranking_pkey PRIMARY KEY (organization_ranking_id);
CREATE TRIGGER organization_ranking_append_only BEFORE DELETE OR UPDATE ON public.organization_ranking FOR EACH ROW EXECUTE FUNCTION public.ghus_reject_mutation();
CREATE TRIGGER organization_ranking_university_only BEFORE INSERT ON public.organization_ranking FOR EACH ROW EXECUTE FUNCTION public.ghus_guard_ranking_is_university();
ALTER TABLE ONLY public.organization_ranking
    ADD CONSTRAINT organization_ranking_context_organization_id_fkey FOREIGN KEY (context_organization_id) REFERENCES public.organization(organization_id);
ALTER TABLE ONLY public.organization_ranking
    ADD CONSTRAINT organization_ranking_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organization(organization_id);
ALTER TABLE ONLY public.organization_ranking
    ADD CONSTRAINT organization_ranking_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);
ALTER TABLE public.organization_ranking ENABLE ROW LEVEL SECURITY;

CREATE VIEW public.actor_ranking WITH (security_invoker = true) AS
SELECT organization_ranking_id AS actor_ranking_id,
       organization_id AS actor_id,
       context_organization_id AS context_actor_id,
       publisher,
       ranking_name,
       ranking_year,
       subject,
       ranked_entity_name,
       position_text,
       source_id,
       created_at
  FROM public.organization_ranking;
COMMENT ON VIEW public.actor_ranking IS 'Stand-in for organization_ranking until the code uses the new name (migration 720).';
REVOKE ALL ON public.actor_ranking FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE 'REVOKE ALL ON public.actor_ranking FROM anon, authenticated';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.actor_ranking TO service_role';
    END IF;
END $$;

CREATE TABLE public.query_log (
    query_id uuid DEFAULT gen_random_uuid() NOT NULL,
    asked_at timestamp with time zone DEFAULT now(),
    question text NOT NULL,
    route text,
    retrieved_ids uuid[],
    found_by jsonb,
    top_distance real,
    latency_ms integer,
    answer text,
    helpful boolean,
    route_overridden_to text,
    n_doc_passages integer DEFAULT 0 NOT NULL,
    doc_name text,
    model text,
    input_tokens integer,
    output_tokens integer,
    user_id text,
    session_id text,
    feedback text,
    feedback_reason text,
    feedback_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
COMMENT ON TABLE public.query_log IS 'RAG-owned telemetry. Stores user questions/answers; default retention target is 12 months.';
COMMENT ON COLUMN public.query_log.retrieved_ids IS 'Map entity UUIDs only. Uploaded document passages are counted in n_doc_passages, not stored here.';
ALTER TABLE ONLY public.query_log
    ADD CONSTRAINT query_log_pkey PRIMARY KEY (query_id);
CREATE INDEX query_log_asked_idx ON public.query_log USING btree (asked_at DESC);
CREATE INDEX query_log_created_at_idx ON public.query_log USING btree (created_at DESC);
CREATE INDEX query_log_feedback_idx ON public.query_log USING btree (feedback, created_at DESC);
CREATE INDEX query_log_helpful_idx ON public.query_log USING btree (helpful) WHERE (helpful IS NOT NULL);
ALTER TABLE public.query_log ENABLE ROW LEVEL SECURITY;

COMMIT;
