# Graph Report - Institutional-knowledge-Platform  (2026-10-06)

## Corpus Check
- 110 files · ~168,163 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 97 file(s) not represented in the graph (top: .csv 54, .log 35, (none) 3)

## Summary
- 1174 nodes · 2621 edges · 62 communities (49 shown, 13 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 136 edges (avg confidence: 0.87)
- Token cost: 402,383 input · 0 output

## Community Hubs (Navigation)
- Review Store Core
- Map Rankings Export
- Project Handoff Docs
- Postgres Review Source
- People Research
- Review UI Frontend
- Paid Call Cost Gateway
- Controlled Map Research
- Review Store Tests
- Search Backend Fetching
- Enrichment Gap Agent
- RAG Embedding Retrieval
- Map Run Store
- Backend API Browse/Ask
- Budget Tests
- Map API Endpoints
- Verify Chain
- Read-only DB Browse
- ER Diagram Tables (data copy)
- ER Diagram Tables (docs copy)
- Streamlit Browse App
- People-Actor Relationships
- Controlled Run Tests
- Architecture V2 Rules
- Ask SQL Router
- Document Upload Extraction
- People Evidence Validation
- API Request Models
- Review Decision Endpoints
- Sept 29 Handoff Decisions
- Answer Generation
- Tech Summary Features
- Data Architecture Proposal
- Review Admission Bridge
- Sept 21 Handoff UI
- Dev Plan (preview)
- People Query Planning
- Database Schema Survey
- Map Cost Tracking Docs
- Document Chunk Store
- Dev Plan (orange preview)
- Map API Tests
- Agent Standing Rules
- Build Map Entrypoint
- Data Quality Report
- Project Change History
- Python Dependencies
- Retrieval Evals
- Actor Category Filters
- Frontend App Pages
- Human Review Workflow
- HTML Page Parser
- DB Connection Tests
- Review Demo Safety
- Organization Hierarchy
- Claude Client
- V2 Review Integration Test
- Model Dump Stub
- Graphify Rules

## God Nodes (most connected - your core abstractions)
1. `RunStore` - 51 edges
2. `ReviewStore` - 34 edges
3. `RunContext` - 33 edges
4. `MapStopped` - 30 edges
5. `paid_message()` - 29 edges
6. `BudgetTests` - 29 edges
7. `extract()` - 25 edges
8. `PostgresReviewSource` - 25 edges
9. `Build the Map Detailed Handoff` - 23 edges
10. `research_people()` - 21 edges

## Surprising Connections (you probably didn't know these)
- `Review (createReviewPage)` --implements--> `Human Review Workflow`  [INFERRED]
  frontend/index.html → docs/REVIEW_WORKFLOW.md
- `map_store()` --uses--> `RunStore`  [INFERRED]
  backend/app.py → src/map_agent/run_store.py
- `start_people_search()` --uses--> `MapStopped`  [INFERRED]
  backend/app.py → src/map_agent/run_store.py
- `map_chat_turn()` --uses--> `MapStopped`  [INFERRED]
  backend/app.py → src/map_agent/run_store.py
- `map_chat_turn()` --uses--> `RunContext`  [INFERRED]
  backend/app.py → src/map_agent/run_store.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Build the Map on-demand verification chain** — build_the_map_handoff_verify_orchestrator, build_the_map_handoff_url_liveness_check, build_the_map_handoff_independent_judge, build_the_map_handoff_relevance_floor [EXTRACTED 1.00]
- **Build the Map discovery pipeline stages** — build_the_map_handoff_build_map_pipeline, build_the_map_handoff_planner_stage, build_the_map_handoff_discover_stage, build_the_map_handoff_enrich_stage, build_the_map_handoff_dedup_stage, handoff_select_stage [EXTRACTED 1.00]
- **Human-approval governance principles** — tech_summary_agent_proposes_human_approves, architecture_v2_sept_claude_proposes_ghus_decides, agents_canonical_writers, architecture_proposal_propose_for_database_action, database_schema_proposal_table [INFERRED 0.85]
- **Build the Map cost-control mechanism** — docs_map_cost_tracking_paid_message_gateway, docs_map_cost_tracking_budget_reservations, docs_map_cost_tracking_session_budget, docs_map_cost_tracking_bounded_search, docs_map_cost_tracking_resumable_checkpoints [EXTRACTED 1.00]
- **Human-in-the-loop admission governance** — docs_chat_handoff_2026_09_29_claude_proposes_ghus_decides, docs_chat_handoff_2026_09_29_status_lifecycle, docs_chat_handoff_2026_09_29_verify_as_save_action, docs_review_workflow_review_decisions, docs_review_workflow_admission_adapter [INFERRED 0.85]
- **Actor Profile V2 contract** — docs_actor_profile_v2_twelve_actor_categories, docs_actor_profile_v2_seven_ghus_regions, docs_actor_profile_v2_organization_relationships, docs_actor_profile_v2_multi_location_flag, docs_chat_handoff_2026_09_29_normalize_actor_profile [EXTRACTED 1.00]
- **Entities carrying source_id + verification_status + confidence (reviewable records)** — docs_architecture_entity_model_hub, docs_architecture_entity_model_actor, docs_architecture_entity_model_person, docs_architecture_entity_model_partnership_profile, docs_architecture_entity_model_verification_provenance_pattern [INFERRED 0.85]
- **Strategic document -> challenge -> actor relevance matching** — docs_architecture_entity_model_strategic_document, docs_architecture_entity_model_challenge, docs_architecture_entity_model_actor_relevance, docs_architecture_entity_model_actor [INFERRED 0.85]
- **Sector tagging join tables** — docs_architecture_entity_model_sector, docs_architecture_entity_model_actor_sector, docs_architecture_entity_model_event_sector, docs_architecture_entity_model_hub_sector_strength [INFERRED 0.85]
- **Tables carrying source_id provenance** — data_processed_architecture_entity_model_source, data_processed_architecture_entity_model_hub, data_processed_architecture_entity_model_actor, data_processed_architecture_entity_model_person, data_processed_architecture_entity_model_strategic_document, data_processed_architecture_entity_model_actor_relevance, data_processed_architecture_entity_model_event, data_processed_architecture_entity_model_event_scoring, data_processed_architecture_entity_model_partnership_profile, data_processed_architecture_entity_model_hub_funding [EXTRACTED 1.00]
- **Actor-centric junction tables** — data_processed_architecture_entity_model_actor, data_processed_architecture_entity_model_hub_actor, data_processed_architecture_entity_model_actor_sector, data_processed_architecture_entity_model_actor_person, data_processed_architecture_entity_model_organization_hierarchy [EXTRACTED 1.00]
- **Strategic document to challenge to actor relevance flow** — data_processed_architecture_entity_model_strategic_document, data_processed_architecture_entity_model_challenge, data_processed_architecture_entity_model_actor_relevance, data_processed_architecture_entity_model_actor [INFERRED 0.85]
- **Phases jointly owned by Nouhaila and Ismail** — outputs_program_management_20260909_preview_nouhaila, outputs_program_management_20260909_preview_ismail, outputs_program_management_20260909_preview_database_architecture, outputs_program_management_20260909_preview_testing_and_management_review, outputs_program_management_20260909_preview_presentation_and_rehearsal [EXTRACTED 1.00]
- **In-progress phases due Sep 11-16 2026** — outputs_program_management_20260909_preview_database_architecture, outputs_program_management_20260909_preview_build_the_map_development, outputs_program_management_20260909_preview_verification_workflow, outputs_program_management_20260909_preview_data_maintenance_agent, outputs_program_management_20260909_preview_data_quality, outputs_program_management_20260909_preview_exports [EXTRACTED 1.00]
- **Phases jointly owned by Nouhaila & Ismail** — outputs_program_management_20260909_preview_orange_nouhaila, outputs_program_management_20260909_preview_orange_ismail, outputs_program_management_20260909_preview_orange_database_architecture, outputs_program_management_20260909_preview_orange_testing_and_management_review, outputs_program_management_20260909_preview_orange_presentation_and_rehearsal [EXTRACTED 1.00]
- **In-progress phases due weeks of Sep 7 / Sep 14** — outputs_program_management_20260909_preview_orange_database_architecture, outputs_program_management_20260909_preview_orange_build_the_map_development, outputs_program_management_20260909_preview_orange_verification_workflow, outputs_program_management_20260909_preview_orange_data_maintenance_agent, outputs_program_management_20260909_preview_orange_data_quality, outputs_program_management_20260909_preview_orange_exports [EXTRACTED 1.00]

## Communities (62 total, 13 thin omitted)

### Community 0 - "Review Store Core"
Cohesion: 0.09
Nodes (19): ReadOnlyRunStore, _candidate_id(), _candidate_name(), _clean_text(), _duplicate_state(), DuplicateRisk, _editable_payload(), _evidence() (+11 more)

### Community 1 - "Map Rankings Export"
Cohesion: 0.05
Nodes (18): _box(), _field_value(), _kicker_and_title(), _name(), _selected(), _sources_text(), _tb(), _text() (+10 more)

### Community 2 - "Project Handoff Docs"
Cohesion: 0.08
Nodes (48): build_map pipeline orchestrator (pipeline.py), Build the Map feature (Task 2), Dedup stage (dedup.py, rapidfuzz), Discovery stage (discover.py, Sonnet web_search/web_fetch), Build the Map Detailed Handoff, Enrich detail pass (enrich.py), Evidence capture (sources per entity), Input-cost problem (29:1 ratio, max_content_tokens lever) (+40 more)

### Community 3 - "Postgres Review Source"
Cohesion: 0.10
Nodes (13): _database_url_from_environment(), _event_name(), _extend_with_powershell_dns(), _json_list(), _json_object(), PostgresReviewSource, PostgresReviewSourceError, _public_ipv4_addresses() (+5 more)

### Community 4 - "People Research"
Cohesion: 0.08
Nodes (11): _collect(), followup_query(), merge_people(), research_people(), collect_and_extract(), ExtractionError, RunContext, FollowupTests (+3 more)

### Community 5 - "Review UI Frontend"
Cohesion: 0.09
Nodes (33): actorReviewSummary(), canSubmitReview(), createReviewPage(), decide(), load(), save(), decisionKey(), decisionOptions() (+25 more)

### Community 6 - "Paid Call Cost Gateway"
Cohesion: 0.09
Nodes (11): paid_message(), usage_cost(), _get_client(), judge_entities(), judge_entity(), _render_entity(), _get_client(), apply_request() (+3 more)

### Community 7 - "Controlled Map Research"
Cohesion: 0.09
Nodes (18): normalize_actor_profile(), region_for(), deduplicate(), _is_duplicate(), _merge_pair(), _name_key(), _website_key(), submit_entities_tool() (+10 more)

### Community 8 - "Review Store Tests"
Cohesion: 0.09
Nodes (5): AdmissionBridgeError, discovery_candidate(), result_bundle(), ReviewApiTests, ReviewStoreTests

### Community 9 - "Search Backend Fetching"
Cohesion: 0.09
Nodes (9): ClaudeSearch, add(), fetch_page(), _field(), operation_key(), plain_text(), ResearchSources, Block (+1 more)

### Community 10 - "Enrichment Gap Agent"
Cohesion: 0.08
Nodes (14): build_report(), fetch_live_actors(), find_near_duplicate_names(), main(), md_table(), scan_country(), _context_block(), enrich() (+6 more)

### Community 11 - "RAG Embedding Retrieval"
Cohesion: 0.12
Nodes (12): assemble_actors(), assemble_all(), assemble_events(), assemble_hubs(), _section(), get_connection(), build_index(), embed_texts() (+4 more)

### Community 13 - "Backend API Browse/Ask"
Cohesion: 0.11
Nodes (15): _actors(), ask_stream(), browse_actors(), browse_events(), browse_hubs(), _events(), health(), _hubs() (+7 more)

### Community 14 - "Budget Tests"
Cohesion: 0.09
Nodes (3): BudgetTests, complete(), response()

### Community 15 - "Map API Endpoints"
Cohesion: 0.18
Nodes (18): BudgetExtensionRequest, map_budget_extension(), map_chat_turn(), map_record(), map_resume(), map_session(), map_start(), map_stop() (+10 more)

### Community 16 - "Verify Chain"
Cohesion: 0.11
Nodes (8): apply_relevance_floor(), partition(), _check_one(), check_urls(), _entity_urls(), verify_links(), summarize(), verify()

### Community 17 - "Read-only DB Browse"
Cohesion: 0.11
Nodes (10): event_date_bounds(), filter_events(), load_actors(), load_events(), load_hubs(), normalize_country(), verification_label(), _connect() (+2 more)

### Community 18 - "ER Diagram Tables (data copy)"
Cohesion: 0.17
Nodes (20): Entity Model ER Diagram (dbdiagram.io), actor table (organization: actor_type, TRL, lifecycle role, verification), actor_person join table (role, is_current, dates), actor_relevance table (relevance_score, maturity_risk, why_relevant), actor_sector join table (confidence), challenge table (target_sectors, target_technologies), event table (host_actor_id, recurring_pattern), event_scoring table (longevity/recognition/scale/audience scores, tier, methodology version) (+12 more)

### Community 19 - "ER Diagram Tables (docs copy)"
Cohesion: 0.26
Nodes (20): Entity Model ER Diagram (dbdiagram.io), Actor table (organizations, actor_type, TRL, lifecycle role), Actor-Person junction table (role, is_current), Actor Relevance table (actor-to-challenge relevance score), Actor-Sector junction table, Challenge table, Event table, Event Scoring table (longevity/recognition/scale/audience scores, tier) (+12 more)

### Community 20 - "Streamlit Browse App"
Cohesion: 0.19
Nodes (10): _actors(), _browse_actors(), _browse_events(), _browse_hubs(), _events(), _hubs(), ordered_hub_cols(), _render_actor_detail() (+2 more)

### Community 21 - "People-Actor Relationships"
Cohesion: 0.17
Nodes (8): _bounded_tasks(), _key(), link_people_to_actors(), register(), _matching_actor(), _merge_person(), _sources(), MapRelationshipTests

### Community 22 - "Controlled Run Tests"
Cohesion: 0.19
Nodes (4): ControlledTests, response(), response(), response()

### Community 23 - "Architecture V2 Rules"
Cohesion: 0.16
Nodes (14): Source/Evidence/Verification/Candidate/Proposal/Review model, 12 actor categories and category types, Actor status (Imported, Parked, Verified, Rejected), Ecosystem Hub Intelligence Platform Architecture V2, Event records and GHUS event notes, Hub = topic + center + radius (200mi) + members, People collected only on request, Ranking attribution rule (+6 more)

### Community 24 - "Ask SQL Router"
Cohesion: 0.17
Nodes (9): gen(), _sources(), _sse(), _extract_sql(), format_sql_answer(), is_safe_select(), plan(), run_sql() (+1 more)

### Community 25 - "Document Upload Extraction"
Cohesion: 0.20
Nodes (7): _evict_docs(), map_upload(), upload(), _clean(), _extract_pdf(), extract_text(), ExtractionError

### Community 26 - "People Evidence Validation"
Cohesion: 0.19
Nodes (5): affiliation_matches(), check_people_evidence(), entity_rows(), normalized(), ParsingTests

### Community 27 - "API Request Models"
Cohesion: 0.13
Nodes (8): ask_map_prompt(), ChatRequest, ExportRequest, map_export(), MapPromptRequest, MapRequest, PeopleRequest, VerifyRequest

### Community 28 - "Review Decision Endpoints"
Cohesion: 0.19
Nodes (12): _local_review_demo_enabled(), _raise_review_error(), review_candidate(), review_candidate_approve(), review_candidate_decision(), review_candidate_reject(), review_candidate_update(), review_store() (+4 more)

### Community 29 - "Sept 29 Handoff Decisions"
Cohesion: 0.18
Nodes (11): Actor Profile V2 (retained changes), Multi-location Flag, Source-linked Organization Relationships, Twelve Canonical Actor Categories, Chat Handoff 29 Sept 2026, Architecture V2 Sept (spec of record), normalize_actor_profile() enforcement, Imported/Parked/Verified/Rejected Status Lifecycle (+3 more)

### Community 30 - "Answer Generation"
Cohesion: 0.21
Nodes (7): answer_question(), _build_messages(), condense_question(), _format_context(), _get_client(), map_prompt_from_conversation(), stream_answer()

### Community 31 - "Tech Summary Features"
Cohesion: 0.16
Nodes (10): Task 1A enrichment agent (paused), proposal table (scaffolded, unused, RLS), Criteria layer (policy, categories, structure, format), Tech Summary (UM6P Intelligence Platform), Four user features (Ask, Browse, Radar, Inbox), Inbox (proposal review), last_verified 90-day staleness rule, Radar (event/funder alerts) (+2 more)

### Community 32 - "Data Architecture Proposal"
Cohesion: 0.15
Nodes (10): Architecture Proposal (Data Architecture & Map Design), hub_actor many-to-many relationship, person_actor_role (dated roles), Propose for database final action, Controlled topic table + actor_topic/hub_topic junctions, Never overwrite, never delete, actor_relevance, actor_sector (empty) (+2 more)

### Community 33 - "Review Admission Bridge"
Cohesion: 0.17
Nodes (6): review_admission_bridge(), review_candidates(), review_postgres_source(), review_source_store(), _sync_review_candidates(), AdmissionBridge

### Community 34 - "Sept 21 Handoff UI"
Cohesion: 0.18
Nodes (13): Seven GHUS Regions, Chat Handoff 21 Sept 2026, Build the Map Controlled Workflow, Funding Summary Rules, People Query Planning Call, Organization-specific People Search, QS/THE Ranking Lookups, Existing-hub Suggestions (frontend matcher) (+5 more)

### Community 35 - "Dev Plan (preview)"
Cohesion: 0.26
Nodes (13): Platform Development Plan (orange Gantt preview), Build the Map Development phase (due Sep 15), Data Maintenance Agent phase (due Sep 15), Data Quality phase (dedup, merging, re-verification; due Sep 16), Database Architecture phase (Hub, Actor, Person tables; due Sep 11), Exports phase (Excel/PowerPoint; due Sep 11), Ismail, Nouhaila (+5 more)

### Community 36 - "People Query Planning"
Cohesion: 0.35
Nodes (4): people_queries(), plan_people_queries(), BudgetStopped, QueryPlanningTests

### Community 37 - "Database Schema Survey"
Cohesion: 0.21
Nodes (10): actor_capability_fact, actor_profile, Alembic migration management, Database Schema Survey, event table, partnership_profile, search_doc retrieval index, search_doc_2 enriched index variant (+2 more)

### Community 38 - "Map Cost Tracking Docs"
Cohesion: 0.21
Nodes (11): Build the Map: Saved Jobs and Cost Tracking, POST /api/map/{id}/budget-extension, Micro-dollar Budget Reservations, costs.paid_message Paid Gateway, Resumable Checkpoints and Explicit Continue, POST /api/map/{id}/resume, Map RunStore (.map_runs/runs.sqlite3), Map Session Budget ($2 default, $3 extension) (+3 more)

### Community 39 - "Document Chunk Store"
Cohesion: 0.24
Nodes (4): chunk_text(), _split_units(), build_store(), search_chunks()

### Community 40 - "Dev Plan (orange preview)"
Cohesion: 0.30
Nodes (12): Platform Development Plan (Sep 9 2026 preview), Build the Map Development, Data Maintenance Agent, Data Quality (dedup, merging, re-verification, multi-org affiliations), Database Architecture (Hub/Actor/Person tables), Exports (Excel and PowerPoint), Ismail, Nouhaila (+4 more)

### Community 42 - "Agent Standing Rules"
Cohesion: 0.31
Nodes (5): AGENTS.md - GHUS Platform Agent Rules, Isolated test DB ghus_v2_test, Codex Execution and Git Safety, hub_overlap / aggregate exclusion from ER model, Repository Boundaries (frontend vs GHUS-Platform backend)

### Community 44 - "Data Quality Report"
Cohesion: 0.32
Nodes (8): Country field hygiene (USA vs United States), data_quality_scan (read-only scan), Data Quality Report, Near-duplicate actor names (rapidfuzz >=88), actor_merge_log, actor table, Actor liveness rule (merged_into_actor_id IS NULL), review_queue (duplicate pairs)

### Community 45 - "Project Change History"
Cohesion: 0.25
Nodes (7): Bounded Claude Web Search (max_uses 1), Project Change History, Ecosystem Hub Six Dimensions, Ismail's Database Update Agent, People-to-Organization Linking, Platform UI/UX Redesign (UM6P orange), frontend/index.html (single-file React/HTM UI)

### Community 46 - "Python Dependencies"
Cohesion: 0.25
Nodes (7): Read-only PostgreSQL Review Source, fastapi, groq (free-tier LLM for v0.1 answers), openpyxl (Excel export), psycopg (Postgres v3), python-pptx (PowerPoint export), voyageai (embeddings)

### Community 47 - "Retrieval Evals"
Cohesion: 0.32
Nodes (4): load_questions(), main(), retrieve(), _rrf_merge()

### Community 48 - "Actor Category Filters"
Cohesion: 0.32
Nodes (3): actor_filter_options(), filter_actors(), ActorCategoryCompatibilityTests

### Community 49 - "Frontend App Pages"
Cohesion: 0.33
Nodes (6): Ask -> Build a Map Bridge, answerLooksThin, App, Ask, Browse, Review (createReviewPage)

### Community 50 - "Human Review Workflow"
Cohesion: 0.40
Nodes (6): Unresolved Hub/Rejection Contradictions (minutes vs V2), Human Review Workflow, agents.review.admission Adapter, rejected_by_reviewer State / review_rejection Table, Review Demo Launcher (run_review_demo.ps1), sql/review_workflow.sql Migration

### Community 54 - "Organization Hierarchy"
Cohesion: 0.50
Nodes (4): organization_hierarchy (parent/child actors), Connecting records: real parent or sector/geography/hub, Typed, sourced link types (unit of, portfolio of, ...), organization_hierarchy join table

## Knowledge Gaps
- **59 isolated node(s):** `REVIEW_STATUS_LABELS`, `DUPLICATE_LABELS`, `REJECTION_REASONS`, `REVIEW_FIELD_LABELS`, `page` (+54 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 347 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `RunStore` connect `Map Run Store` to `Review Store Core`, `People Research`, `Paid Call Cost Gateway`, `Review Store Tests`, `Map API Tests`, `Search Backend Fetching`, `Backend API Browse/Ask`, `Budget Tests`, `Map API Endpoints`, `Controlled Run Tests`, `V2 Review Integration Test`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Are the 9 inferred relationships involving `RunStore` (e.g. with `map_store()` and `ApiTests`) actually correct?**
  _`RunStore` has 9 INFERRED edges - model-reasoned connections that need verification._
- **What connects `REVIEW_STATUS_LABELS`, `DUPLICATE_LABELS`, `REJECTION_REASONS` to the rest of the system?**
  _59 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Review Store Core` be split into smaller, more focused modules?**
  _Cohesion score 0.09226594301221167 - nodes in this community are weakly interconnected._
- **Why does `RunContext` connect `People Research` to `Paid Call Cost Gateway`, `Search Backend Fetching`, `Backend API Browse/Ask`, `Budget Tests`, `Map API Endpoints`, `Controlled Run Tests`?**
  _High betweenness centrality (0.025) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `RunContext` (e.g. with `map_chat_turn()` and `map_verify()`) actually correct?**
  _`RunContext` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Should `Map Rankings Export` be split into smaller, more focused modules?**
  _Cohesion score 0.05499735589635114 - nodes in this community are weakly interconnected._