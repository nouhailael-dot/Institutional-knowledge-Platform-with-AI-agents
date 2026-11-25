-- Rollback of migration 810: recreates every table and function it removed, exactly as they
-- were on Supabase on 25 Nov 2026 after 800 (taken with pg_dump --schema-only from the live
-- database). The tables come back empty: their rows are in
-- GHUS-data/backups/archive-810-removed-tables-20261125.sql and in the backup taken before 810.
-- To put the rows back, run the archive's COPY sections for the tables you need.
-- Afterwards: DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '810';
-- Roll 810 back before rolling back 800.

BEGIN;

CREATE OR REPLACE FUNCTION public.ghus_guard_ranking_is_university()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE category text;
BEGIN
    SELECT a.actor_category INTO category FROM actor a
     WHERE a.actor_id = NEW.actor_id;
    IF category IS DISTINCT FROM 'university_academic' THEN
        RAISE EXCEPTION
            'rankings are recorded for university actors only; actor % is %',
            NEW.actor_id, COALESCE(category, 'unclassified');
    END IF;
    RETURN NEW;
END $function$;

CREATE OR REPLACE FUNCTION public.ghus_pre_cutover_data_loss_audit()
 RETURNS TABLE(check_name text, source_rows bigint, destination_rows bigint, passed boolean, detail jsonb)
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  field text;
  n_source bigint;
  n_dest bigint;
  dist_source jsonb;
  dist_dest jsonb;
  status_column text;
BEGIN
  -- 1. Category concept and raw evidence preserved in the migration audit.
  SELECT count(*) INTO n_source FROM actor;
  SELECT count(*) INTO n_dest FROM actor_category_migration_audit;
  check_name := 'actor category concept'; source_rows := n_source; destination_rows := n_dest;
  passed := n_source = n_dest; detail := '{}'; RETURN NEXT;

  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public'
             AND table_name='actor' AND column_name='actor_type_raw') THEN
    EXECUTE 'SELECT count(actor_type_raw) FROM actor' INTO n_source;
  ELSE n_source := NULL; END IF;
  SELECT count(legacy_category_raw) INTO n_dest FROM actor_category_migration_audit;
  check_name := 'actor.actor_type_raw'; source_rows := n_source; destination_rows := n_dest;
  passed := n_source IS NOT NULL AND n_source = n_dest; detail := '{}'; RETURN NEXT;

  -- 2. Legacy status distribution preserved exactly in prior_status, with an honest
  --    bootstrap event for every actor.
  SELECT CASE WHEN EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public'
              AND table_name='actor' AND column_name='verification_status')
         THEN 'verification_status' ELSE 'record_status' END INTO status_column;
  EXECUTE format('SELECT COALESCE(jsonb_object_agg(v,n),''{}'') FROM (SELECT COALESCE(%I,''<null>'') v,'
                 'count(*) n FROM actor GROUP BY 1) d', status_column) INTO dist_source;
  SELECT COALESCE(jsonb_object_agg(v,n),'{}') INTO dist_dest FROM (
    SELECT COALESCE(prior_status,'<null>') v, count(*) n FROM actor_category_migration_audit GROUP BY 1) d;
  SELECT count(*) INTO n_dest FROM actor_verification_event
   WHERE decision_origin='existing_canonical_migration' AND decision='verified'
     AND decided_by IS NULL AND decided_at IS NULL AND topic_id IS NULL;
  SELECT count(*) INTO n_source FROM actor;
  check_name := 'actor legacy status distribution'; source_rows := n_source;
  destination_rows := n_dest;
  passed := dist_source = dist_dest AND n_dest = n_source;
  detail := jsonb_build_object('legacy', dist_source, 'prior_status', dist_dest);
  RETURN NEXT;

  -- 3. Legacy state: normalized or listed for review, raw value kept.
  EXECUTE 'SELECT count(*) FROM actor WHERE NULLIF(btrim(state),'''') IS NOT NULL' INTO n_source;
  SELECT count(*) INTO n_dest FROM legacy_migration_record
   WHERE legacy_table='actor' AND legacy_field='state' AND disposition IN ('normalized','review');
  check_name := 'actor.state'; source_rows := n_source; destination_rows := n_dest;
  passed := n_source = n_dest; detail := '{}'; RETURN NEXT;

  -- 4. Narrative scalar fields: fact row that exists, or explicit audit record.
  FOREACH field IN ARRAY ARRAY['description','primary_technical_focus','technical_approach',
      'current_activities','technology_ip_notes','key_constraints','funding_summary',
      'estimated_trl','primary_lifecycle_role'] LOOP
    EXECUTE format('SELECT count(*) FROM actor WHERE NULLIF(btrim(%I::text),'''') IS NOT NULL', field)
      INTO n_source;
    SELECT count(*) INTO n_dest FROM legacy_migration_record r
     LEFT JOIN actor_fact f ON f.actor_fact_id=r.destination_id
     WHERE r.legacy_table='actor' AND r.legacy_field=field
       AND (r.disposition='audit_only' OR f.actor_fact_id IS NOT NULL);
    check_name := 'actor.' || field; source_rows := n_source; destination_rows := n_dest;
    passed := n_source = n_dest; detail := '{}'; RETURN NEXT;
  END LOOP;

  -- 5. Legacy tables 500 removes or narrows.
  SELECT count(*) INTO n_source FROM record_verification WHERE entity_type='actor';
  check_name := 'record_verification actor decisions'; source_rows := n_source;
  destination_rows := 0; passed := n_source = 0; detail := '{}'; RETURN NEXT;

  SELECT count(*) INTO n_source FROM organization_hierarchy;
  SELECT count(*) INTO n_dest FROM legacy_migration_record r
    JOIN review_item i ON i.review_item_id=r.destination_id
   WHERE r.legacy_table='organization_hierarchy';
  check_name := 'organization_hierarchy'; source_rows := n_source; destination_rows := n_dest;
  passed := n_source = n_dest; detail := '{}'; RETURN NEXT;

  SELECT count(*) FILTER (WHERE NULLIF(btrim(profile_summary),'') IS NOT NULL)
       + count(*) FILTER (WHERE NULLIF(btrim(identity_summary),'') IS NOT NULL)
       + count(*) FILTER (WHERE NULLIF(btrim(technical_summary),'') IS NOT NULL)
       + count(*) FILTER (WHERE NULLIF(btrim(lifecycle_summary),'') IS NOT NULL)
       + count(*) FILTER (WHERE NULLIF(btrim(funding_summary),'') IS NOT NULL)
    INTO n_source FROM actor_profile;
  SELECT count(*) INTO n_dest FROM legacy_migration_record r
     LEFT JOIN actor_fact f ON f.actor_fact_id=r.destination_id
   WHERE r.legacy_table='actor_profile' AND (r.disposition='audit_only' OR f.actor_fact_id IS NOT NULL);
  check_name := 'actor_profile values'; source_rows := n_source; destination_rows := n_dest;
  passed := n_source = n_dest; detail := '{}'; RETURN NEXT;

  SELECT count(*) INTO n_source FROM actor_capability_fact;
  SELECT count(*) INTO n_dest FROM legacy_migration_record r
     LEFT JOIN actor_fact f ON f.actor_fact_id=r.destination_id
   WHERE r.legacy_table='actor_capability_fact'
     AND (r.disposition='audit_only' OR f.actor_fact_id IS NOT NULL);
  check_name := 'actor_capability_fact'; source_rows := n_source; destination_rows := n_dest;
  passed := n_source = n_dest; detail := '{}'; RETURN NEXT;

  -- 6. Row counts unchanged since the cutover baseline, except rows archived by an
  --    explicit GHUS decision (which are counted as accounted for).
  FOR field, n_source IN SELECT table_name, row_count FROM architecture_v2_cutover_baseline LOOP
    EXECUTE format('SELECT count(*) FROM %I', field) INTO n_dest;
    IF field = 'hub' THEN n_dest := n_dest + (SELECT count(*) FROM hub_removed); END IF;
    IF field = 'hub_actor' THEN n_dest := n_dest + (SELECT count(*) FROM hub_actor_removed); END IF;
    check_name := 'row count ' || field; source_rows := n_source; destination_rows := n_dest;
    passed := n_source = n_dest; detail := '{}'; RETURN NEXT;
  END LOOP;
END;
$function$;

COMMENT ON FUNCTION public.ghus_pre_cutover_data_loss_audit() IS 'Architecture V2 pre-cutover data-loss audit; every row must pass before migration 500.';

--
-- PostgreSQL database dump
--

-- Dumped from database version 17.6
-- Dumped by pg_dump version 17.5

--
-- Name: actor_category_migration_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.actor_category_migration_audit (
    actor_id uuid NOT NULL,
    migration_batch_id text NOT NULL,
    legacy_category text,
    legacy_category_raw text,
    mapped_category text,
    mapping_status text NOT NULL,
    prior_status text,
    prior_source_origin text,
    prior_category_note text,
    prior_category_needs_review boolean,
    migrated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT actor_category_migration_audit_mapping_status_check CHECK ((mapping_status = ANY (ARRAY['mapped'::text, 'requires_review'::text])))
);

--
-- Name: actor_evaluation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.actor_evaluation (
    actor_evaluation_id uuid NOT NULL,
    actor_id uuid NOT NULL,
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
-- Name: actor_ranking; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.actor_ranking (
    actor_ranking_id uuid DEFAULT gen_random_uuid() NOT NULL,
    actor_id uuid NOT NULL,
    context_actor_id uuid,
    publisher text NOT NULL,
    ranking_name text NOT NULL,
    ranking_year integer NOT NULL,
    subject text,
    ranked_entity_name text NOT NULL,
    position_text text NOT NULL,
    source_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT actor_ranking_publisher_check CHECK ((publisher = ANY (ARRAY['QS'::text, 'THE'::text, 'U.S. News'::text, 'ARWU'::text]))),
    CONSTRAINT actor_ranking_ranking_year_check CHECK (((ranking_year >= 1900) AND (ranking_year <= 2200)))
);

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);

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
-- Name: hub_actor_removed; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hub_actor_removed (
    hub_id uuid NOT NULL,
    actor_id uuid NOT NULL,
    membership jsonb NOT NULL,
    reason text NOT NULL,
    decided_by text NOT NULL,
    removed_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: hub_center_review; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hub_center_review (
    hub_center_review_id uuid DEFAULT gen_random_uuid() NOT NULL,
    hub_id uuid NOT NULL,
    proposed_city text NOT NULL,
    proposed_state_code text,
    proposed_latitude numeric(9,6) NOT NULL,
    proposed_longitude numeric(9,6) NOT NULL,
    shift_miles numeric(8,2) NOT NULL,
    trigger_threshold_miles numeric(8,2) DEFAULT 25 NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT hub_center_review_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'approved'::text, 'rejected'::text])))
);

--
-- Name: hub_removed; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hub_removed (
    hub_id uuid NOT NULL,
    hub jsonb NOT NULL,
    reason text NOT NULL,
    decided_by text NOT NULL,
    removed_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: legacy_migration_record; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.legacy_migration_record (
    legacy_migration_record_id uuid DEFAULT gen_random_uuid() NOT NULL,
    migration_batch_id text NOT NULL,
    legacy_table text NOT NULL,
    legacy_key text NOT NULL,
    legacy_field text NOT NULL,
    actor_id uuid,
    disposition text NOT NULL,
    destination_table text,
    destination_id uuid,
    legacy_value text,
    legacy_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legacy_migration_record_check CHECK (((disposition = 'audit_only'::text) OR (destination_table IS NOT NULL))),
    CONSTRAINT legacy_migration_record_disposition_check CHECK ((disposition = ANY (ARRAY['fact'::text, 'duplicate_of_fact'::text, 'normalized'::text, 'review'::text, 'audit_only'::text])))
);

--
-- Name: person_topic; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.person_topic (
    person_id uuid NOT NULL,
    topic_id uuid NOT NULL,
    expertise_summary text NOT NULL,
    source_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: proposal; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.proposal (
    proposal_id uuid DEFAULT gen_random_uuid() NOT NULL,
    entity_id uuid,
    table_name text NOT NULL,
    field text,
    old_value text,
    new_value text,
    evidence_url text NOT NULL,
    evidence_snippet text NOT NULL,
    proposed_by text,
    status text DEFAULT 'pending'::text NOT NULL,
    reviewed_by text,
    reviewed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT proposal_status_valid CHECK ((status = ANY (ARRAY['pending'::text, 'approved'::text, 'rejected'::text])))
);

--
-- Name: TABLE proposal; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.proposal IS 'RAG-owned inbox for agent-proposed changes. Human approval is required before source data changes.';

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
-- Name: review_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.review_queue (
    review_id uuid NOT NULL,
    actor_id_a uuid NOT NULL,
    actor_id_b uuid NOT NULL,
    score numeric(4,3),
    model character varying(60),
    features json,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    decided_by character varying(120),
    decided_at timestamp without time zone,
    merge_id uuid,
    notes text,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);

--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    filename text NOT NULL,
    checksum text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: actor_category_migration_audit actor_category_migration_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_category_migration_audit
    ADD CONSTRAINT actor_category_migration_audit_pkey PRIMARY KEY (actor_id);

--
-- Name: actor_evaluation actor_evaluation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_evaluation
    ADD CONSTRAINT actor_evaluation_pkey PRIMARY KEY (actor_evaluation_id);

--
-- Name: actor_ranking actor_ranking_actor_id_publisher_ranking_name_ranking_year__key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_ranking
    ADD CONSTRAINT actor_ranking_actor_id_publisher_ranking_name_ranking_year__key UNIQUE (actor_id, publisher, ranking_name, ranking_year, subject, position_text, source_id);

--
-- Name: actor_ranking actor_ranking_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_ranking
    ADD CONSTRAINT actor_ranking_pkey PRIMARY KEY (actor_ranking_id);

--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);

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
-- Name: hub_actor_removed hub_actor_removed_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hub_actor_removed
    ADD CONSTRAINT hub_actor_removed_pkey PRIMARY KEY (hub_id, actor_id);

--
-- Name: hub_center_review hub_center_review_hub_id_proposed_latitude_proposed_longitu_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hub_center_review
    ADD CONSTRAINT hub_center_review_hub_id_proposed_latitude_proposed_longitu_key UNIQUE (hub_id, proposed_latitude, proposed_longitude, status);

--
-- Name: hub_center_review hub_center_review_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hub_center_review
    ADD CONSTRAINT hub_center_review_pkey PRIMARY KEY (hub_center_review_id);

--
-- Name: hub_removed hub_removed_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hub_removed
    ADD CONSTRAINT hub_removed_pkey PRIMARY KEY (hub_id);

--
-- Name: legacy_migration_record legacy_migration_record_legacy_table_legacy_key_legacy_fiel_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legacy_migration_record
    ADD CONSTRAINT legacy_migration_record_legacy_table_legacy_key_legacy_fiel_key UNIQUE (legacy_table, legacy_key, legacy_field);

--
-- Name: legacy_migration_record legacy_migration_record_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legacy_migration_record
    ADD CONSTRAINT legacy_migration_record_pkey PRIMARY KEY (legacy_migration_record_id);

--
-- Name: person_topic person_topic_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_topic
    ADD CONSTRAINT person_topic_pkey PRIMARY KEY (person_id, topic_id, source_id);

--
-- Name: proposal proposal_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposal
    ADD CONSTRAINT proposal_pkey PRIMARY KEY (proposal_id);

--
-- Name: query_log query_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.query_log
    ADD CONSTRAINT query_log_pkey PRIMARY KEY (query_id);

--
-- Name: review_queue review_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_queue
    ADD CONSTRAINT review_queue_pkey PRIMARY KEY (review_id);

--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (filename);

--
-- Name: actor_evaluation uq_actor_evaluation_context; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_evaluation
    ADD CONSTRAINT uq_actor_evaluation_context UNIQUE (actor_id, evaluation_context, context_entity_type, context_entity_id);

--
-- Name: review_queue uq_review_pair; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_queue
    ADD CONSTRAINT uq_review_pair UNIQUE (actor_id_a, actor_id_b);

--
-- Name: ix_actor_evaluation_actor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_actor_evaluation_actor ON public.actor_evaluation USING btree (actor_id);

--
-- Name: ix_actor_evaluation_context; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_actor_evaluation_context ON public.actor_evaluation USING btree (evaluation_context);

--
-- Name: ix_canonical_write_audit_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_canonical_write_audit_entity ON public.canonical_write_audit USING btree (entity_type, entity_id, created_at DESC);

--
-- Name: ix_review_queue_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_queue_score ON public.review_queue USING btree (score);

--
-- Name: ix_review_queue_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_review_queue_status ON public.review_queue USING btree (status);

--
-- Name: proposal_entity_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX proposal_entity_idx ON public.proposal USING btree (entity_id);

--
-- Name: proposal_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX proposal_status_idx ON public.proposal USING btree (status, created_at DESC);

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
-- Name: actor_category_migration_audit actor_category_migration_audit_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER actor_category_migration_audit_append_only BEFORE DELETE OR UPDATE ON public.actor_category_migration_audit FOR EACH ROW EXECUTE FUNCTION public.ghus_reject_mutation();

--
-- Name: actor_ranking actor_ranking_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER actor_ranking_append_only BEFORE DELETE OR UPDATE ON public.actor_ranking FOR EACH ROW EXECUTE FUNCTION public.ghus_reject_mutation();

--
-- Name: actor_ranking actor_ranking_university_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER actor_ranking_university_only BEFORE INSERT ON public.actor_ranking FOR EACH ROW EXECUTE FUNCTION public.ghus_guard_ranking_is_university();

--
-- Name: canonical_write_audit canonical_write_audit_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER canonical_write_audit_append_only BEFORE DELETE OR UPDATE ON public.canonical_write_audit FOR EACH ROW EXECUTE FUNCTION public.ghus_reject_mutation();

--
-- Name: contact_collection_authorization contact_collection_authorization_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER contact_collection_authorization_append_only BEFORE DELETE OR UPDATE ON public.contact_collection_authorization FOR EACH ROW EXECUTE FUNCTION public.ghus_reject_mutation();

--
-- Name: hub_actor_removed hub_actor_removed_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER hub_actor_removed_append_only BEFORE DELETE OR UPDATE ON public.hub_actor_removed FOR EACH ROW EXECUTE FUNCTION public.ghus_reject_mutation();

--
-- Name: hub_removed hub_removed_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER hub_removed_append_only BEFORE DELETE OR UPDATE ON public.hub_removed FOR EACH ROW EXECUTE FUNCTION public.ghus_reject_mutation();

--
-- Name: legacy_migration_record legacy_migration_record_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER legacy_migration_record_append_only BEFORE DELETE OR UPDATE ON public.legacy_migration_record FOR EACH ROW EXECUTE FUNCTION public.ghus_reject_mutation();

--
-- Name: actor_category_migration_audit actor_category_migration_audit_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_category_migration_audit
    ADD CONSTRAINT actor_category_migration_audit_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.actor(actor_id);

--
-- Name: actor_category_migration_audit actor_category_migration_audit_mapped_category_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_category_migration_audit
    ADD CONSTRAINT actor_category_migration_audit_mapped_category_fkey FOREIGN KEY (mapped_category) REFERENCES public.actor_category_definition(category_code);

--
-- Name: actor_evaluation actor_evaluation_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_evaluation
    ADD CONSTRAINT actor_evaluation_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.actor(actor_id);

--
-- Name: actor_evaluation actor_evaluation_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_evaluation
    ADD CONSTRAINT actor_evaluation_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);

--
-- Name: actor_ranking actor_ranking_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_ranking
    ADD CONSTRAINT actor_ranking_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.actor(actor_id);

--
-- Name: actor_ranking actor_ranking_context_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_ranking
    ADD CONSTRAINT actor_ranking_context_actor_id_fkey FOREIGN KEY (context_actor_id) REFERENCES public.actor(actor_id);

--
-- Name: actor_ranking actor_ranking_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.actor_ranking
    ADD CONSTRAINT actor_ranking_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);

--
-- Name: canonical_write_audit canonical_write_audit_actor_fact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.canonical_write_audit
    ADD CONSTRAINT canonical_write_audit_actor_fact_id_fkey FOREIGN KEY (actor_fact_id) REFERENCES public.actor_fact(actor_fact_id);

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
-- Name: hub_center_review hub_center_review_hub_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hub_center_review
    ADD CONSTRAINT hub_center_review_hub_id_fkey FOREIGN KEY (hub_id) REFERENCES public.hub(hub_id);

--
-- Name: hub_center_review hub_center_review_proposed_state_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hub_center_review
    ADD CONSTRAINT hub_center_review_proposed_state_code_fkey FOREIGN KEY (proposed_state_code) REFERENCES public.region_state(state_code);

--
-- Name: legacy_migration_record legacy_migration_record_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legacy_migration_record
    ADD CONSTRAINT legacy_migration_record_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.actor(actor_id);

--
-- Name: person_topic person_topic_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_topic
    ADD CONSTRAINT person_topic_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.person(person_id);

--
-- Name: person_topic person_topic_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_topic
    ADD CONSTRAINT person_topic_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source(source_id);

--
-- Name: person_topic person_topic_topic_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_topic
    ADD CONSTRAINT person_topic_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES public.topic(topic_id);

--
-- Name: review_queue review_queue_actor_id_a_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_queue
    ADD CONSTRAINT review_queue_actor_id_a_fkey FOREIGN KEY (actor_id_a) REFERENCES public.actor(actor_id);

--
-- Name: review_queue review_queue_actor_id_b_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_queue
    ADD CONSTRAINT review_queue_actor_id_b_fkey FOREIGN KEY (actor_id_b) REFERENCES public.actor(actor_id);

--
-- Name: review_queue review_queue_merge_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_queue
    ADD CONSTRAINT review_queue_merge_id_fkey FOREIGN KEY (merge_id) REFERENCES public.actor_merge_log(merge_id);

--
-- Name: actor_category_migration_audit; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.actor_category_migration_audit ENABLE ROW LEVEL SECURITY;

--
-- Name: actor_evaluation; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.actor_evaluation ENABLE ROW LEVEL SECURITY;

--
-- Name: actor_ranking; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.actor_ranking ENABLE ROW LEVEL SECURITY;

--
-- Name: alembic_version; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.alembic_version ENABLE ROW LEVEL SECURITY;

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
-- Name: hub_actor_removed; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.hub_actor_removed ENABLE ROW LEVEL SECURITY;

--
-- Name: hub_center_review; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.hub_center_review ENABLE ROW LEVEL SECURITY;

--
-- Name: hub_removed; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.hub_removed ENABLE ROW LEVEL SECURITY;

--
-- Name: legacy_migration_record; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.legacy_migration_record ENABLE ROW LEVEL SECURITY;

--
-- Name: person_topic; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.person_topic ENABLE ROW LEVEL SECURITY;

--
-- Name: proposal; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.proposal ENABLE ROW LEVEL SECURITY;

--
-- Name: query_log; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.query_log ENABLE ROW LEVEL SECURITY;

--
-- Name: review_queue; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.review_queue ENABLE ROW LEVEL SECURITY;

--
-- Name: schema_migrations; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.schema_migrations ENABLE ROW LEVEL SECURITY;

--
-- Name: TABLE actor_category_migration_audit; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.actor_category_migration_audit TO anon;
GRANT ALL ON TABLE public.actor_category_migration_audit TO authenticated;
GRANT ALL ON TABLE public.actor_category_migration_audit TO service_role;

--
-- Name: TABLE actor_evaluation; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.actor_evaluation TO anon;
GRANT ALL ON TABLE public.actor_evaluation TO authenticated;
GRANT ALL ON TABLE public.actor_evaluation TO service_role;

--
-- Name: TABLE actor_ranking; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.actor_ranking TO anon;
GRANT ALL ON TABLE public.actor_ranking TO authenticated;
GRANT ALL ON TABLE public.actor_ranking TO service_role;

--
-- Name: TABLE alembic_version; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.alembic_version TO anon;
GRANT ALL ON TABLE public.alembic_version TO authenticated;
GRANT ALL ON TABLE public.alembic_version TO service_role;

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
-- Name: TABLE hub_actor_removed; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.hub_actor_removed TO anon;
GRANT ALL ON TABLE public.hub_actor_removed TO authenticated;
GRANT ALL ON TABLE public.hub_actor_removed TO service_role;

--
-- Name: TABLE hub_center_review; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.hub_center_review TO anon;
GRANT ALL ON TABLE public.hub_center_review TO authenticated;
GRANT ALL ON TABLE public.hub_center_review TO service_role;

--
-- Name: TABLE hub_removed; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.hub_removed TO anon;
GRANT ALL ON TABLE public.hub_removed TO authenticated;
GRANT ALL ON TABLE public.hub_removed TO service_role;

--
-- Name: TABLE legacy_migration_record; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.legacy_migration_record TO anon;
GRANT ALL ON TABLE public.legacy_migration_record TO authenticated;
GRANT ALL ON TABLE public.legacy_migration_record TO service_role;

--
-- Name: TABLE person_topic; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.person_topic TO anon;
GRANT ALL ON TABLE public.person_topic TO authenticated;
GRANT ALL ON TABLE public.person_topic TO service_role;

--
-- Name: TABLE proposal; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.proposal TO service_role;

--
-- Name: TABLE query_log; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.query_log TO service_role;

--
-- Name: TABLE review_queue; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.review_queue TO anon;
GRANT ALL ON TABLE public.review_queue TO authenticated;
GRANT ALL ON TABLE public.review_queue TO service_role;

--
-- Name: TABLE schema_migrations; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.schema_migrations TO anon;
GRANT ALL ON TABLE public.schema_migrations TO authenticated;
GRANT ALL ON TABLE public.schema_migrations TO service_role;

--
-- PostgreSQL database dump complete
--

GRANT ALL ON FUNCTION public.ghus_guard_ranking_is_university() TO anon;
GRANT ALL ON FUNCTION public.ghus_guard_ranking_is_university() TO authenticated;
GRANT ALL ON FUNCTION public.ghus_guard_ranking_is_university() TO service_role;
GRANT ALL ON FUNCTION public.ghus_pre_cutover_data_loss_audit() TO anon;
GRANT ALL ON FUNCTION public.ghus_pre_cutover_data_loss_audit() TO authenticated;
GRANT ALL ON FUNCTION public.ghus_pre_cutover_data_loss_audit() TO service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;
