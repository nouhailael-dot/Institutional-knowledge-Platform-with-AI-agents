-- Rollback of migration 820: brings back topic and the nine other tables exactly as they were
-- on Supabase on 27 Nov 2026 (pg_dump --schema-only of the live database, grants included), the
-- eight topic rows, the sectors' own ids, every link to topic, and Nouhaila's template view
-- with its Topic column. The other tables come back empty: their rows are in
-- GHUS-data/backups/archive-820-removed-tables-20261127.sql (run its COPY sections; topic is
-- already filled here, so skip its section). A research area or profile page written on
-- person after 820 is dropped with the two columns. Afterwards:
-- DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '820';
-- Deploy the code from before 820 again, too.

BEGIN;

DROP VIEW public.actor_template;

--
-- PostgreSQL database dump
--

-- Dumped from database version 17.6
-- Dumped by pg_dump version 17.5

--
-- Name: actor_location; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.actor_location (
    actor_location_id uuid DEFAULT gen_random_uuid() NOT NULL,
    actor_id uuid NOT NULL,
    location_name text,
    country text NOT NULL,
    state_code text,
    city text NOT NULL,
    region_code text,
    latitude numeric(9,6),
    longitude numeric(9,6),
    is_primary boolean DEFAULT false NOT NULL,
    source_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT actor_location_check CHECK (((latitude IS NULL) = (longitude IS NULL)))
);

--
-- Name: actor_relevance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.actor_relevance (
    actor_relevance_id uuid NOT NULL,
    actor_id uuid NOT NULL,
    challenge_id uuid NOT NULL,
    relevance_score numeric(3,2),
    maturity_risk character varying(40),
    collaboration_orientation character varying(60),
    why_relevant text,
    current_evidence text,
    additional_validation_needed text,
    source_id uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    challenge_relevance_narrative text,
    source_links text
);

--
-- Name: actor_topic; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.actor_topic (
    actor_id uuid NOT NULL,
    topic_id uuid NOT NULL,
    match_strength text NOT NULL,
    match_reason text NOT NULL,
    source_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT actor_topic_match_reason_check CHECK (((char_length(match_reason) >= 1) AND (char_length(match_reason) <= 1000))),
    CONSTRAINT actor_topic_match_strength_check CHECK ((match_strength = ANY (ARRAY['strong'::text, 'moderate'::text])))
);

--
-- Name: topic; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.topic (
    topic_id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: architecture_v2_cutover_attestation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.architecture_v2_cutover_attestation (
    audit_name text NOT NULL,
    artifact_sha256 text NOT NULL,
    passed boolean NOT NULL,
    approved_by text NOT NULL,
    approved_at timestamp with time zone NOT NULL,
    details jsonb DEFAULT '{}'::jsonb NOT NULL
);

--
-- Name: architecture_v2_cutover_baseline; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.architecture_v2_cutover_baseline (
    table_name text NOT NULL,
    row_count bigint NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: challenge; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.challenge (
    challenge_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    sponsoring_org character varying(120),
    description text,
    target_sectors character varying(20)[],
    target_technologies character varying(200)[],
    source_document_id uuid,
    created_date date,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);

--
-- Name: event_claim; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event_claim (
    event_claim_id uuid DEFAULT gen_random_uuid() NOT NULL,
    event_id uuid NOT NULL,
    claim_text text NOT NULL,
    source_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: event_topic; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event_topic (
    event_id uuid NOT NULL,
    topic_id uuid NOT NULL,
    why_matched text NOT NULL,
    source_id uuid NOT NULL,
    collection_request_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: person_discovery_profile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.person_discovery_profile (
    person_discovery_profile_id uuid NOT NULL,
    person_id uuid NOT NULL,
    actor_id uuid NOT NULL,
    role character varying(120) NOT NULL,
    research_area text,
    public_profile_url text,
    source_id uuid NOT NULL,
    source_url text NOT NULL,
    fetched_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    affiliation_raw text,
    needs_actor_enrichment boolean DEFAULT false NOT NULL
);

--
-- Name: actor_location actor_location_actor_id_country_state_code_city_location_na_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_location
    ADD CONSTRAINT actor_location_actor_id_country_state_code_city_location_na_key UNIQUE (actor_id, country, state_code, city, location_name);

--
-- Name: actor_location actor_location_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_location
    ADD CONSTRAINT actor_location_pkey PRIMARY KEY (actor_location_id);

--
-- Name: actor_relevance actor_relevance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_relevance
    ADD CONSTRAINT actor_relevance_pkey PRIMARY KEY (actor_relevance_id);

--
-- Name: actor_topic actor_topic_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_topic
    ADD CONSTRAINT actor_topic_pkey PRIMARY KEY (actor_id, topic_id, source_id);

--
-- Name: architecture_v2_cutover_attestation architecture_v2_cutover_attestation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.architecture_v2_cutover_attestation
    ADD CONSTRAINT architecture_v2_cutover_attestation_pkey PRIMARY KEY (audit_name);

--
-- Name: architecture_v2_cutover_baseline architecture_v2_cutover_baseline_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.architecture_v2_cutover_baseline
    ADD CONSTRAINT architecture_v2_cutover_baseline_pkey PRIMARY KEY (table_name);

--
-- Name: challenge challenge_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.challenge
    ADD CONSTRAINT challenge_name_key UNIQUE (name);

--
-- Name: challenge challenge_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.challenge
    ADD CONSTRAINT challenge_pkey PRIMARY KEY (challenge_id);

--
-- Name: event_claim event_claim_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_claim
    ADD CONSTRAINT event_claim_pkey PRIMARY KEY (event_claim_id);

--
-- Name: event_topic event_topic_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_topic
    ADD CONSTRAINT event_topic_pkey PRIMARY KEY (event_id, topic_id, source_id);

--
-- Name: person_discovery_profile person_discovery_profile_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_discovery_profile
    ADD CONSTRAINT person_discovery_profile_pkey PRIMARY KEY (person_discovery_profile_id);

--
-- Name: topic topic_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic
    ADD CONSTRAINT topic_code_key UNIQUE (code);

--
-- Name: topic topic_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic
    ADD CONSTRAINT topic_name_key UNIQUE (name);

--
-- Name: topic topic_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.topic
    ADD CONSTRAINT topic_pkey PRIMARY KEY (topic_id);

--
-- Name: actor_relevance uq_actor_challenge; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_relevance
    ADD CONSTRAINT uq_actor_challenge UNIQUE (actor_id, challenge_id);

--
-- Name: ix_actor_topic_topic; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_actor_topic_topic ON public.actor_topic USING btree (topic_id, actor_id);

--
-- Name: ix_person_discovery_profile_actor_enrichment; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_person_discovery_profile_actor_enrichment ON public.person_discovery_profile USING btree (actor_id, created_at) WHERE (needs_actor_enrichment IS TRUE);

--
-- Name: ix_person_discovery_profile_reverify; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_person_discovery_profile_reverify ON public.person_discovery_profile USING btree (person_id, fetched_at DESC) WHERE (public_profile_url IS NOT NULL);

--
-- Name: uq_actor_one_primary_location; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_actor_one_primary_location ON public.actor_location USING btree (actor_id) WHERE is_primary;

--
-- Name: uq_person_discovery_profile_source; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_person_discovery_profile_source ON public.person_discovery_profile USING btree (person_id, actor_id, role, source_id);

--
-- Name: actor_location actor_location_no_delete; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER actor_location_no_delete BEFORE DELETE ON public.actor_location FOR EACH ROW EXECUTE FUNCTION public.ghus_guard_no_delete();

--
-- Name: actor_topic actor_topic_no_delete; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER actor_topic_no_delete BEFORE DELETE ON public.actor_topic FOR EACH ROW EXECUTE FUNCTION public.ghus_guard_no_delete();

--
-- Name: event_claim event_claim_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER event_claim_append_only BEFORE DELETE OR UPDATE ON public.event_claim FOR EACH ROW EXECUTE FUNCTION public.ghus_reject_mutation();

--
-- Name: actor_location actor_location_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_location
    ADD CONSTRAINT actor_location_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.actor(actor_id);

--
-- Name: actor_location actor_location_region_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_location
    ADD CONSTRAINT actor_location_region_code_fkey FOREIGN KEY (region_code) REFERENCES public.region_definition(region_code);

--
-- Name: actor_location actor_location_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_location
    ADD CONSTRAINT actor_location_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);

--
-- Name: actor_location actor_location_state_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_location
    ADD CONSTRAINT actor_location_state_code_fkey FOREIGN KEY (state_code) REFERENCES public.region_state(state_code);

--
-- Name: actor_relevance actor_relevance_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_relevance
    ADD CONSTRAINT actor_relevance_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.actor(actor_id);

--
-- Name: actor_relevance actor_relevance_challenge_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_relevance
    ADD CONSTRAINT actor_relevance_challenge_id_fkey FOREIGN KEY (challenge_id) REFERENCES public.challenge(challenge_id);

--
-- Name: actor_relevance actor_relevance_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_relevance
    ADD CONSTRAINT actor_relevance_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);

--
-- Name: actor_topic actor_topic_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_topic
    ADD CONSTRAINT actor_topic_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.actor(actor_id);

--
-- Name: actor_topic actor_topic_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_topic
    ADD CONSTRAINT actor_topic_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);

--
-- Name: actor_topic actor_topic_topic_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_topic
    ADD CONSTRAINT actor_topic_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.topic(topic_id);

--
-- Name: challenge challenge_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.challenge
    ADD CONSTRAINT challenge_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.strategic_document(document_id);

--
-- Name: event_claim event_claim_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_claim
    ADD CONSTRAINT event_claim_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.event(event_id);

--
-- Name: event_claim event_claim_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_claim
    ADD CONSTRAINT event_claim_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);

--
-- Name: event_topic event_topic_collection_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_topic
    ADD CONSTRAINT event_topic_collection_request_id_fkey FOREIGN KEY (collection_request_id) REFERENCES public.collection_request(collection_request_id);

--
-- Name: event_topic event_topic_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_topic
    ADD CONSTRAINT event_topic_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.event(event_id);

--
-- Name: event_topic event_topic_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_topic
    ADD CONSTRAINT event_topic_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);

--
-- Name: event_topic event_topic_topic_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_topic
    ADD CONSTRAINT event_topic_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.topic(topic_id);

--
-- Name: person_discovery_profile person_discovery_profile_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_discovery_profile
    ADD CONSTRAINT person_discovery_profile_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.actor(actor_id);

--
-- Name: person_discovery_profile person_discovery_profile_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_discovery_profile
    ADD CONSTRAINT person_discovery_profile_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.person(person_id);

--
-- Name: person_discovery_profile person_discovery_profile_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_discovery_profile
    ADD CONSTRAINT person_discovery_profile_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);

--
-- Name: actor_location; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.actor_location ENABLE ROW LEVEL SECURITY;

--
-- Name: actor_relevance; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.actor_relevance ENABLE ROW LEVEL SECURITY;

--
-- Name: actor_topic; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.actor_topic ENABLE ROW LEVEL SECURITY;

--
-- Name: architecture_v2_cutover_attestation; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.architecture_v2_cutover_attestation ENABLE ROW LEVEL SECURITY;

--
-- Name: architecture_v2_cutover_baseline; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.architecture_v2_cutover_baseline ENABLE ROW LEVEL SECURITY;

--
-- Name: challenge; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.challenge ENABLE ROW LEVEL SECURITY;

--
-- Name: event_claim; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.event_claim ENABLE ROW LEVEL SECURITY;

--
-- Name: event_topic; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.event_topic ENABLE ROW LEVEL SECURITY;

--
-- Name: person_discovery_profile; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.person_discovery_profile ENABLE ROW LEVEL SECURITY;

--
-- Name: topic; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.topic ENABLE ROW LEVEL SECURITY;

--
-- Name: TABLE actor_location; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.actor_location TO anon;
GRANT ALL ON TABLE public.actor_location TO authenticated;
GRANT ALL ON TABLE public.actor_location TO service_role;

--
-- Name: TABLE actor_relevance; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.actor_relevance TO anon;
GRANT ALL ON TABLE public.actor_relevance TO authenticated;
GRANT ALL ON TABLE public.actor_relevance TO service_role;

--
-- Name: TABLE actor_topic; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.actor_topic TO anon;
GRANT ALL ON TABLE public.actor_topic TO authenticated;
GRANT ALL ON TABLE public.actor_topic TO service_role;

--
-- Name: TABLE topic; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.topic TO anon;
GRANT ALL ON TABLE public.topic TO authenticated;
GRANT ALL ON TABLE public.topic TO service_role;

--
-- Name: TABLE architecture_v2_cutover_attestation; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.architecture_v2_cutover_attestation TO anon;
GRANT ALL ON TABLE public.architecture_v2_cutover_attestation TO authenticated;
GRANT ALL ON TABLE public.architecture_v2_cutover_attestation TO service_role;

--
-- Name: TABLE architecture_v2_cutover_baseline; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.architecture_v2_cutover_baseline TO anon;
GRANT ALL ON TABLE public.architecture_v2_cutover_baseline TO authenticated;
GRANT ALL ON TABLE public.architecture_v2_cutover_baseline TO service_role;

--
-- Name: TABLE challenge; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.challenge TO anon;
GRANT ALL ON TABLE public.challenge TO authenticated;
GRANT ALL ON TABLE public.challenge TO service_role;

--
-- Name: TABLE event_claim; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.event_claim TO anon;
GRANT ALL ON TABLE public.event_claim TO authenticated;
GRANT ALL ON TABLE public.event_claim TO service_role;

--
-- Name: TABLE event_topic; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.event_topic TO anon;
GRANT ALL ON TABLE public.event_topic TO authenticated;
GRANT ALL ON TABLE public.event_topic TO service_role;

--
-- Name: TABLE person_discovery_profile; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.person_discovery_profile TO anon;
GRANT ALL ON TABLE public.person_discovery_profile TO authenticated;
GRANT ALL ON TABLE public.person_discovery_profile TO service_role;

--
-- PostgreSQL database dump complete
--

INSERT INTO public.topic (topic_id, code, name, description, active, created_at) VALUES
    ('73a59102-c273-412e-8551-f05b2e91c5d6'::uuid, 'AGRI', 'Agriculture', NULL, true, '2026-10-06 23:37:37.49624+00'),
    ('53b09a74-b200-4fb3-93c7-609271e37c8d'::uuid, 'AI', 'Artificial Intelligence', NULL, true, '2026-10-06 23:37:37.49624+00'),
    ('a455be87-fd19-415a-9366-ad218785111b'::uuid, 'CHEM', 'Specialty Chemicals', NULL, true, '2026-10-06 23:37:37.49624+00'),
    ('0a30d7b5-7b4c-458d-a7d4-b9f6ca57c97d'::uuid, 'ENERGY', 'Energy Transition', NULL, true, '2026-10-06 23:37:37.49624+00'),
    ('2526b704-0419-498d-a586-f4ec9747e206'::uuid, 'HEALTH', 'Healthcare', NULL, true, '2026-10-06 23:37:37.49624+00'),
    ('dda23062-eaec-4533-8885-fd24c02e1b69'::uuid, 'MINING', 'Mining', NULL, true, '2026-10-06 23:37:37.49624+00'),
    ('e9799151-ff40-4723-be3a-39c731118136'::uuid, 'SUSTAIN', 'Sustainability', NULL, true, '2026-10-06 23:37:37.49624+00'),
    ('63471230-55f6-4c65-820f-d6d9d90abd2c'::uuid, 'WATER', 'Water', NULL, true, '2026-10-06 23:37:37.49624+00');

-- The sectors take back their own ids; their links follow; topic_id points to topic again.
ALTER TABLE public.actor_fact DROP CONSTRAINT actor_fact_topic_id_fkey;
ALTER TABLE public.actor_fact_current_pointer DROP CONSTRAINT actor_fact_current_pointer_topic_id_fkey;
ALTER TABLE public.actor_strategic_connection_check DROP CONSTRAINT actor_strategic_connection_check_topic_id_fkey;
ALTER TABLE public.actor_verification_event DROP CONSTRAINT actor_verification_event_topic_id_fkey;
ALTER TABLE public.collection_request DROP CONSTRAINT collection_request_topic_id_fkey;
ALTER TABLE public.entity_edge DROP CONSTRAINT entity_edge_topic_id_fkey;
ALTER TABLE public.hub_assignment_evidence DROP CONSTRAINT hub_assignment_evidence_topic_id_fkey;
ALTER TABLE public.proposed_hub DROP CONSTRAINT fk_proposed_hub_topic;
ALTER TABLE public.record_verification DROP CONSTRAINT record_verification_topic_id_fkey;
ALTER TABLE public.review_item DROP CONSTRAINT review_item_topic_id_fkey;
ALTER TABLE public.hub DROP CONSTRAINT hub_topic_id_fkey;
ALTER TABLE public.actor_sector DROP CONSTRAINT actor_sector_sector_id_fkey;
ALTER TABLE public.event_sector DROP CONSTRAINT event_sector_sector_id_fkey;
ALTER TABLE public.hub_sector DROP CONSTRAINT hub_sector_sector_id_fkey;
ALTER TABLE public.sector DROP CONSTRAINT sector_parent_sector_id_fkey;
CREATE TEMP TABLE sector_id_back (new_id uuid, old_id uuid) ON COMMIT DROP;
INSERT INTO sector_id_back VALUES
    ('73a59102-c273-412e-8551-f05b2e91c5d6'::uuid, '7ba672dd-6fa0-40eb-baae-6344f28e2a2d'::uuid),  -- AGRI
    ('53b09a74-b200-4fb3-93c7-609271e37c8d'::uuid, '73766b89-526d-4098-b908-46700bb018d1'::uuid),  -- AI
    ('a455be87-fd19-415a-9366-ad218785111b'::uuid, '5d49458c-776a-4088-85b6-3f76868ff5f5'::uuid),  -- CHEM
    ('0a30d7b5-7b4c-458d-a7d4-b9f6ca57c97d'::uuid, '296652b9-af87-4182-ade4-fc0d0ba3d4f7'::uuid),  -- ENERGY
    ('2526b704-0419-498d-a586-f4ec9747e206'::uuid, 'e948059b-c920-404a-acfb-39cd4056161c'::uuid),  -- HEALTH
    ('dda23062-eaec-4533-8885-fd24c02e1b69'::uuid, '0bcd841c-d320-4f5a-b32a-3946711069f8'::uuid),  -- MINING
    ('e9799151-ff40-4723-be3a-39c731118136'::uuid, '51cc4552-8217-4d28-bdcb-310d26dad8e2'::uuid),  -- SUSTAIN
    ('63471230-55f6-4c65-820f-d6d9d90abd2c'::uuid, '501ce607-0bc6-4335-8f54-a62a025360ed'::uuid);  -- WATER
UPDATE public.sector s SET sector_id = b.old_id FROM sector_id_back b WHERE s.sector_id = b.new_id;
UPDATE public.sector s SET parent_sector_id = b.old_id FROM sector_id_back b WHERE s.parent_sector_id = b.new_id;
ALTER TABLE public.actor_sector DISABLE TRIGGER actor_sector_append_only;
UPDATE public.actor_sector x SET sector_id = b.old_id FROM sector_id_back b WHERE x.sector_id = b.new_id;
ALTER TABLE public.actor_sector ENABLE TRIGGER actor_sector_append_only;
UPDATE public.event_sector x SET sector_id = b.old_id FROM sector_id_back b WHERE x.sector_id = b.new_id;
UPDATE public.hub_sector x SET sector_id = b.old_id FROM sector_id_back b WHERE x.sector_id = b.new_id;
ALTER TABLE public.actor_sector ADD CONSTRAINT actor_sector_sector_id_fkey FOREIGN KEY (sector_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.event_sector ADD CONSTRAINT event_sector_sector_id_fkey FOREIGN KEY (sector_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.hub_sector ADD CONSTRAINT hub_sector_sector_id_fkey FOREIGN KEY (sector_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.sector ADD CONSTRAINT sector_parent_sector_id_fkey FOREIGN KEY (parent_sector_id) REFERENCES public.sector(sector_id);
ALTER TABLE public.actor_fact ADD CONSTRAINT actor_fact_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.topic(topic_id);
ALTER TABLE public.actor_fact_current_pointer ADD CONSTRAINT actor_fact_current_pointer_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.topic(topic_id);
ALTER TABLE public.actor_strategic_connection_check ADD CONSTRAINT actor_strategic_connection_check_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.topic(topic_id);
ALTER TABLE public.actor_verification_event ADD CONSTRAINT actor_verification_event_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.topic(topic_id);
ALTER TABLE public.collection_request ADD CONSTRAINT collection_request_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.topic(topic_id);
ALTER TABLE public.entity_edge ADD CONSTRAINT entity_edge_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.topic(topic_id);
ALTER TABLE public.hub_assignment_evidence ADD CONSTRAINT hub_assignment_evidence_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.topic(topic_id);
ALTER TABLE public.proposed_hub ADD CONSTRAINT fk_proposed_hub_topic FOREIGN KEY (topic_id) REFERENCES public.topic(topic_id) NOT VALID;
ALTER TABLE public.record_verification ADD CONSTRAINT record_verification_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.topic(topic_id);
ALTER TABLE public.review_item ADD CONSTRAINT review_item_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.topic(topic_id);
COMMENT ON COLUMN public.actor_fact.topic_id IS NULL;
COMMENT ON COLUMN public.hub.topic_id IS NULL;
COMMENT ON COLUMN public.collection_request.topic_id IS NULL;

ALTER TABLE public.person DROP COLUMN research_area, DROP COLUMN public_profile_url;

CREATE VIEW public.actor_template WITH (security_invoker = true) AS
SELECT o.actor_id,
    o.name,
    array_to_string(o.alt_names, '; '::text) AS alternate_names,
    o.website,
    cat.display_name AS actor_category,
    COALESCE(ctype.display_name, o.category_type) AS category_type,
    o.category_note,
    o.description,
    sec.primary_sector,
    top.topic,
    sec.additional_sectors,
    o.city,
    o.state_code,
    reg.display_name AS region,
    o.country,
    par.parent_name,
    par.parent_relationship,
    src.url AS source_url,
    o.recent_activity,
    NULL::text AS recent_activity_date,
    o.funding_signal,
    o.international_connection,
    o.primary_technical_focus,
    o.technical_approach,
    o.current_activities,
    o.funding_summary,
    o.ghus_notes,
    o.um6p_ocp_connection,
    o.topic_unit_and_work,
    o.institution_control,
    o.land_grant_designation,
    o.relevant_centers_programs,
    o.parent_and_center_type,
    o.topic_research_focus,
    o.active_recent_projects,
    o.main_funders,
    o.sponsoring_agency,
    o.formal_national_designation,
    o.topic_program_area,
    o.facility_type_operator,
    o.testing_demonstration_scope,
    o.current_project,
    o.clinical_research_focus,
    o.parent_academic_link,
    o.hospital_type_scale,
    o.current_initiative,
    o.ownership_and_size,
    o.topic_business_segment_product,
    o.mapped_geography_operations,
    NULL::text AS development_stage,
    o.technology_and_problem,
    o.founding_year_location,
    o.funding_stage,
    o.pilot_customer_evidence,
    o.platform_type_operator,
    o.sector_focus,
    o.platform_offerings,
    o.scale_indicator,
    o.investor_type_headquarters,
    o.sector_stage_focus,
    o.geographic_focus,
    o.published_fund_size,
    o.topic_investment_thesis,
    o.jurisdiction_parent_agency,
    o.topic_mandate_program,
    o.visible_funding_programs,
    o.mission_sector_focus,
    o.relevant_program,
    o.programs_grant_themes,
    o.association_type,
    o.sector_geographic_scope,
    o.member_types,
    o.current_initiative_working_group,
    o.linked_members,
    o.network_scope_locations,
    o.status
   FROM actor o
     LEFT JOIN actor_category_definition cat ON cat.category_code = o.actor_category
     LEFT JOIN actor_category_type_definition ctype ON ctype.category_code = o.actor_category AND ctype.type_code = o.category_type
     LEFT JOIN region_definition reg ON reg.region_code = o.region_code
     LEFT JOIN source src ON src.source_id = o.source_id
     LEFT JOIN LATERAL ( SELECT max(s.name::text) FILTER (WHERE os.is_primary) AS primary_sector,
            string_agg(s.name::text, '; '::text ORDER BY (s.name::text)) FILTER (WHERE NOT os.is_primary OR os.is_primary IS NULL) AS additional_sectors
           FROM actor_sector os
             JOIN sector s ON s.sector_id = os.sector_id
          WHERE os.actor_id = o.actor_id) sec ON true
     LEFT JOIN LATERAL ( SELECT string_agg(t.name, '; '::text ORDER BY t.name) AS topic
           FROM actor_topic ot
             JOIN topic t ON t.topic_id = ot.topic_id
          WHERE ot.actor_id = o.actor_id) top ON true
     LEFT JOIN LATERAL ( SELECT p.name AS parent_name,
            replace(e.relationship_type, '_'::text, ' '::text) AS parent_relationship
           FROM entity_edge e
             JOIN actor p ON p.actor_id = e.object_id
          WHERE e.subject_id = o.actor_id AND (e.subject_type = ANY (ARRAY['actor'::text, 'organization'::text])) AND (e.object_type = ANY (ARRAY['actor'::text, 'organization'::text])) AND (e.relationship_type = ANY (ARRAY['unit_of'::text, 'operated_by'::text]))
          ORDER BY e.created_at DESC
         LIMIT 1) par ON true
  WHERE o.merged_into_actor_id IS NULL;
COMMENT ON VIEW public.actor_template IS 'Organizations template (2026-11-12.1) as a view: one row per organization, template column order. Migration 730.';
COMMENT ON COLUMN public.actor_template.name IS 'Official name';
COMMENT ON COLUMN public.actor_template.alternate_names IS 'Other names';
COMMENT ON COLUMN public.actor_template.website IS 'Website';
COMMENT ON COLUMN public.actor_template.actor_category IS 'Organization Category';
COMMENT ON COLUMN public.actor_template.category_type IS 'Category Type';
COMMENT ON COLUMN public.actor_template.category_note IS 'Category note';
COMMENT ON COLUMN public.actor_template.description IS 'Description';
COMMENT ON COLUMN public.actor_template.primary_sector IS 'Sector';
COMMENT ON COLUMN public.actor_template.topic IS 'Topic';
COMMENT ON COLUMN public.actor_template.additional_sectors IS 'Additional sectors';
COMMENT ON COLUMN public.actor_template.city IS 'City';
COMMENT ON COLUMN public.actor_template.state_code IS 'State';
COMMENT ON COLUMN public.actor_template.region IS 'Region';
COMMENT ON COLUMN public.actor_template.country IS 'Country';
COMMENT ON COLUMN public.actor_template.parent_name IS 'Parent organization';
COMMENT ON COLUMN public.actor_template.parent_relationship IS 'Relationship to parent';
COMMENT ON COLUMN public.actor_template.source_url IS 'Source URL';
COMMENT ON COLUMN public.actor_template.recent_activity_date IS 'Recent activity date (no column of its own: empty)';
COMMENT ON COLUMN public.actor_template.ghus_notes IS 'GHUS Notes';
COMMENT ON COLUMN public.actor_template.um6p_ocp_connection IS 'UM6P/OCP connection';
COMMENT ON COLUMN public.actor_template.development_stage IS 'Startup: development stage (no column of its own: empty)';

NOTIFY pgrst, 'reload schema';

COMMIT;
