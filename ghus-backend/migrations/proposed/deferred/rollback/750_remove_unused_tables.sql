-- Rollback of migration 750: recreates every table, view and function it removed, exactly as
-- they were on Supabase on 24 Nov 2026 (taken with pg_dump --schema-only from the live database).
-- The tables come back empty: the rows of organization_evaluation, event_scoring and query_log
-- are in the backup taken before 750. Afterwards:
--   1. run ../../unused_tables_750/restore_migration_snapshot.sql (the 710 and 720 rollback data);
--   2. DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '750';
-- Roll 750 back before rolling back 720 or 710.

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

--
-- PostgreSQL database dump
--

-- Dumped from database version 17.6
-- Dumped by pg_dump version 17.5

--
-- Name: migration_snapshot; Type: TABLE; Schema: compass; Owner: -
--

CREATE TABLE compass.migration_snapshot (
    migration_id text NOT NULL,
    object_name text NOT NULL,
    definition text NOT NULL,
    taken_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: organization_evaluation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organization_evaluation (
    organization_evaluation_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    evaluation_context character varying(120) NOT NULL,
    context_entity_type character varying(40) NOT NULL,
    context_entity_id uuid NOT NULL,
    score numeric(5,3),
    evaluation_summary text,
    evidence_summary text,
    source_id uuid,
    verification_status character varying(30),
    confidence numeric(3,2),
    generated_by character varying(80),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);

--
-- Name: actor_evaluation; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.actor_evaluation WITH (security_invoker='true') AS
 SELECT organization_evaluation_id AS actor_evaluation_id,
    organization_id AS actor_id,
    evaluation_context,
    context_entity_type,
    context_entity_id,
    score,
    evaluation_summary,
    evidence_summary,
    source_id,
    verification_status,
    confidence,
    generated_by,
    created_at,
    updated_at
   FROM public.organization_evaluation;

--
-- Name: VIEW actor_evaluation; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.actor_evaluation IS 'Stand-in for organization_evaluation until the code uses the new name (migration 720).';

--
-- Name: organization_ranking; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: actor_ranking; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.actor_ranking WITH (security_invoker='true') AS
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

--
-- Name: VIEW actor_ranking; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.actor_ranking IS 'Stand-in for organization_ranking until the code uses the new name (migration 720).';

--
-- Name: canonical_write_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.canonical_write_audit (
    canonical_write_audit_id uuid DEFAULT gen_random_uuid() NOT NULL,
    writer_module text NOT NULL,
    operation text NOT NULL,
    entity_type text NOT NULL,
    entity_id uuid,
    collection_run_id uuid,
    dry_run boolean DEFAULT true NOT NULL,
    actor_fact_id uuid,
    entity_edge_id uuid,
    source_id uuid,
    payload_hash text NOT NULL,
    performed_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT canonical_write_audit_check CHECK ((dry_run OR (source_id IS NOT NULL))),
    CONSTRAINT canonical_write_audit_operation_check CHECK ((operation = ANY (ARRAY['create_actor'::text, 'append_fact'::text, 'append_edge'::text, 'append_verification'::text, 'create_review_item'::text]))),
    CONSTRAINT canonical_write_audit_writer_module_check CHECK ((writer_module = ANY (ARRAY['agents.discovery.promote'::text, 'agents.enrichment.decisions'::text])))
);

--
-- Name: contact_collection_authorization; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.contact_collection_authorization (
    authorization_id uuid DEFAULT gen_random_uuid() NOT NULL,
    person_id uuid,
    requested_by text NOT NULL,
    request_text text NOT NULL,
    official_public_only boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT contact_collection_authorization_official_public_only_check CHECK (official_public_only)
);

--
-- Name: event_scoring; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event_scoring (
    event_scoring_id uuid NOT NULL,
    event_id uuid NOT NULL,
    longevity_description text,
    recognition_description text,
    scale_description text,
    audience_profile_description text,
    organizer_credibility_description text,
    geographic_reach_description text,
    longevity_score smallint,
    recognition_score smallint,
    scale_score smallint,
    audience_profile_score smallint,
    organizer_profile_score smallint,
    geographic_reach_score smallint,
    total_score smallint,
    tier character varying(20),
    tier_raw character varying(120),
    scoring_methodology_version character varying(20),
    source_id uuid,
    scored_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);

--
-- Name: fetched_document; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fetched_document (
    fetched_document_id uuid DEFAULT gen_random_uuid() NOT NULL,
    collection_run_id uuid NOT NULL,
    url text NOT NULL,
    canonical_url text NOT NULL,
    content_hash text NOT NULL,
    page_role text NOT NULL,
    source_id uuid NOT NULL,
    fetched_at timestamp with time zone NOT NULL,
    CONSTRAINT fetched_document_page_role_check CHECK ((page_role = ANY (ARRAY['homepage'::text, 'topic'::text, 'search_result'::text, 'uploaded'::text, 'other'::text])))
);

--
-- Name: query_log; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: TABLE query_log; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.query_log IS 'RAG-owned telemetry. Stores user questions/answers; default retention target is 12 months.';

--
-- Name: COLUMN query_log.retrieved_ids; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.query_log.retrieved_ids IS 'Map entity UUIDs only. Uploaded document passages are counted in n_doc_passages, not stored here.';

--
-- Name: migration_snapshot migration_snapshot_pkey; Type: CONSTRAINT; Schema: compass; Owner: -
--

ALTER TABLE ONLY compass.migration_snapshot
    ADD CONSTRAINT migration_snapshot_pkey PRIMARY KEY (migration_id, object_name);

--
-- Name: organization_ranking actor_ranking_actor_id_publisher_ranking_name_ranking_year__key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_ranking
    ADD CONSTRAINT actor_ranking_actor_id_publisher_ranking_name_ranking_year__key UNIQUE (organization_id, publisher, ranking_name, ranking_year, subject, position_text, source_id);

--
-- Name: canonical_write_audit canonical_write_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.canonical_write_audit
    ADD CONSTRAINT canonical_write_audit_pkey PRIMARY KEY (canonical_write_audit_id);

--
-- Name: contact_collection_authorization contact_collection_authorization_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contact_collection_authorization
    ADD CONSTRAINT contact_collection_authorization_pkey PRIMARY KEY (authorization_id);

--
-- Name: event_scoring event_scoring_event_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_scoring
    ADD CONSTRAINT event_scoring_event_id_key UNIQUE (event_id);

--
-- Name: event_scoring event_scoring_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_scoring
    ADD CONSTRAINT event_scoring_pkey PRIMARY KEY (event_scoring_id);

--
-- Name: fetched_document fetched_document_collection_run_id_canonical_url_content_ha_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetched_document
    ADD CONSTRAINT fetched_document_collection_run_id_canonical_url_content_ha_key UNIQUE (collection_run_id, canonical_url, content_hash);

--
-- Name: fetched_document fetched_document_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetched_document
    ADD CONSTRAINT fetched_document_pkey PRIMARY KEY (fetched_document_id);

--
-- Name: organization_evaluation organization_evaluation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_evaluation
    ADD CONSTRAINT organization_evaluation_pkey PRIMARY KEY (organization_evaluation_id);

--
-- Name: organization_ranking organization_ranking_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_ranking
    ADD CONSTRAINT organization_ranking_pkey PRIMARY KEY (organization_ranking_id);

--
-- Name: query_log query_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query_log
    ADD CONSTRAINT query_log_pkey PRIMARY KEY (query_id);

--
-- Name: organization_evaluation uq_organization_evaluation_context; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_evaluation
    ADD CONSTRAINT uq_organization_evaluation_context UNIQUE (organization_id, evaluation_context, context_entity_type, context_entity_id);

--
-- Name: ix_canonical_write_audit_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_canonical_write_audit_entity ON public.canonical_write_audit USING btree (entity_type, entity_id, created_at DESC);

--
-- Name: ix_organization_evaluation_context; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_organization_evaluation_context ON public.organization_evaluation USING btree (evaluation_context);

--
-- Name: ix_organization_evaluation_organization; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_organization_evaluation_organization ON public.organization_evaluation USING btree (organization_id);

--
-- Name: query_log_asked_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX query_log_asked_idx ON public.query_log USING btree (asked_at DESC);

--
-- Name: query_log_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX query_log_created_at_idx ON public.query_log USING btree (created_at DESC);

--
-- Name: query_log_feedback_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX query_log_feedback_idx ON public.query_log USING btree (feedback, created_at DESC);

--
-- Name: query_log_helpful_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX query_log_helpful_idx ON public.query_log USING btree (helpful) WHERE (helpful IS NOT NULL);

--
-- Name: canonical_write_audit canonical_write_audit_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER canonical_write_audit_append_only BEFORE DELETE OR UPDATE ON public.canonical_write_audit FOR EACH ROW EXECUTE FUNCTION public.ghus_reject_mutation();

--
-- Name: contact_collection_authorization contact_collection_authorization_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER contact_collection_authorization_append_only BEFORE DELETE OR UPDATE ON public.contact_collection_authorization FOR EACH ROW EXECUTE FUNCTION public.ghus_reject_mutation();

--
-- Name: organization_ranking organization_ranking_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER organization_ranking_append_only BEFORE DELETE OR UPDATE ON public.organization_ranking FOR EACH ROW EXECUTE FUNCTION public.ghus_reject_mutation();

--
-- Name: organization_ranking organization_ranking_university_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER organization_ranking_university_only BEFORE INSERT ON public.organization_ranking FOR EACH ROW EXECUTE FUNCTION public.ghus_guard_ranking_is_university();

--
-- Name: canonical_write_audit canonical_write_audit_actor_fact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.canonical_write_audit
    ADD CONSTRAINT canonical_write_audit_actor_fact_id_fkey FOREIGN KEY (actor_fact_id) REFERENCES public.organization_fact(organization_fact_id);

--
-- Name: canonical_write_audit canonical_write_audit_collection_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.canonical_write_audit
    ADD CONSTRAINT canonical_write_audit_collection_run_id_fkey FOREIGN KEY (collection_run_id) REFERENCES public.collection_run(collection_run_id);

--
-- Name: canonical_write_audit canonical_write_audit_entity_edge_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.canonical_write_audit
    ADD CONSTRAINT canonical_write_audit_entity_edge_id_fkey FOREIGN KEY (entity_edge_id) REFERENCES public.entity_edge(entity_edge_id);

--
-- Name: canonical_write_audit canonical_write_audit_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.canonical_write_audit
    ADD CONSTRAINT canonical_write_audit_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);

--
-- Name: contact_collection_authorization contact_collection_authorization_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contact_collection_authorization
    ADD CONSTRAINT contact_collection_authorization_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.person(person_id);

--
-- Name: event_scoring event_scoring_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_scoring
    ADD CONSTRAINT event_scoring_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.event(event_id);

--
-- Name: event_scoring event_scoring_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_scoring
    ADD CONSTRAINT event_scoring_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);

--
-- Name: fetched_document fetched_document_collection_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetched_document
    ADD CONSTRAINT fetched_document_collection_run_id_fkey FOREIGN KEY (collection_run_id) REFERENCES public.collection_run(collection_run_id);

--
-- Name: fetched_document fetched_document_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetched_document
    ADD CONSTRAINT fetched_document_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);

--
-- Name: organization_evaluation organization_evaluation_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_evaluation
    ADD CONSTRAINT organization_evaluation_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organization(organization_id);

--
-- Name: organization_evaluation organization_evaluation_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_evaluation
    ADD CONSTRAINT organization_evaluation_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);

--
-- Name: organization_ranking organization_ranking_context_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_ranking
    ADD CONSTRAINT organization_ranking_context_organization_id_fkey FOREIGN KEY (context_organization_id) REFERENCES public.organization(organization_id);

--
-- Name: organization_ranking organization_ranking_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_ranking
    ADD CONSTRAINT organization_ranking_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organization(organization_id);

--
-- Name: organization_ranking organization_ranking_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_ranking
    ADD CONSTRAINT organization_ranking_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);

--
-- Name: migration_snapshot; Type: ROW SECURITY; Schema: compass; Owner: -
--

ALTER TABLE compass.migration_snapshot ENABLE ROW LEVEL SECURITY;

--
-- Name: canonical_write_audit; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.canonical_write_audit ENABLE ROW LEVEL SECURITY;

--
-- Name: contact_collection_authorization; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.contact_collection_authorization ENABLE ROW LEVEL SECURITY;

--
-- Name: event_scoring; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.event_scoring ENABLE ROW LEVEL SECURITY;

--
-- Name: fetched_document; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.fetched_document ENABLE ROW LEVEL SECURITY;

--
-- Name: organization_evaluation; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.organization_evaluation ENABLE ROW LEVEL SECURITY;

--
-- Name: organization_ranking; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.organization_ranking ENABLE ROW LEVEL SECURITY;

--
-- Name: query_log; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.query_log ENABLE ROW LEVEL SECURITY;

--
-- Name: TABLE organization_evaluation; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.organization_evaluation TO anon;
GRANT ALL ON TABLE public.organization_evaluation TO authenticated;
GRANT ALL ON TABLE public.organization_evaluation TO service_role;

--
-- Name: TABLE actor_evaluation; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.actor_evaluation TO service_role;

--
-- Name: TABLE organization_ranking; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.organization_ranking TO anon;
GRANT ALL ON TABLE public.organization_ranking TO authenticated;
GRANT ALL ON TABLE public.organization_ranking TO service_role;

--
-- Name: TABLE actor_ranking; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.actor_ranking TO service_role;

--
-- Name: TABLE canonical_write_audit; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.canonical_write_audit TO anon;
GRANT ALL ON TABLE public.canonical_write_audit TO authenticated;
GRANT ALL ON TABLE public.canonical_write_audit TO service_role;

--
-- Name: TABLE contact_collection_authorization; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.contact_collection_authorization TO anon;
GRANT ALL ON TABLE public.contact_collection_authorization TO authenticated;
GRANT ALL ON TABLE public.contact_collection_authorization TO service_role;

--
-- Name: TABLE event_scoring; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.event_scoring TO anon;
GRANT ALL ON TABLE public.event_scoring TO authenticated;
GRANT ALL ON TABLE public.event_scoring TO service_role;

--
-- Name: TABLE fetched_document; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.fetched_document TO anon;
GRANT ALL ON TABLE public.fetched_document TO authenticated;
GRANT ALL ON TABLE public.fetched_document TO service_role;

--
-- Name: TABLE query_log; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.query_log TO service_role;

--
-- PostgreSQL database dump complete
--

COMMIT;
