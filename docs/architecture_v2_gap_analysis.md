# Architecture V2 gap analysis and implementation plan

Audit date: 2026-09-24  
Backend repository: `C:\Users\Ismail\Projects\GHUS-Platform` on `codex/architecture-v2` (created from `392840a` current `main`)  
Frontend repository: `C:\Users\Ismail\Projects\Institutional-knowledge-Platform` on `codex/architecture-v2` (created from `8734605` current `main`)  
Source of truth: `docs/architecture_v2_sept.md` (SHA-256 matched the supplied `architecture_v2_sept.md`)

## Scope, assumptions, and limits

- Architecture/data phases 2-14 belong in the backend repository. UI, review/curation, browsing, Ask, retrieval/RAG, and source-label phases 15-16 belong in the frontend repository. The old draft at `C:\Users\Ismail\Documents\GHUS\GHUS-Platform-v2` is read-only reference material and must never be edited, committed, or used to run migrations.
- No shared-database write or DDL is permitted. At this re-baseline step, production had not yet been queried; the later Phase 2 proof step is authorized for read-only export and version/extension inspection only.
- The actor export has names and hub memberships but omits actor type, status, coordinates, and hierarchy. It can establish raw Phase 1 membership counts, but cannot establish the 10-independent-family/5-category/200-mile criterion.
- Status values observed in code are `phase_1`, `needs_review`, and `ai_inferred`; the live distinct-value set could not be verified without database access.
- “Missing” means no durable implementation was found. “Partial” means a nearby structure exists but cannot enforce the V2 rule. “Conflict” means current behavior contradicts V2.
- Phase 0 changes are limited to the source specification and this audit. No implementation code or DDL has been written.

## Executive result

Architecture V2 is a major versioned migration, not an incremental field addition. The current system has reusable foundations—staging, raw-document capture, source rows, dry-run defaults, agent-owned canonical writer boundaries, ER review queues, many-to-many hub membership, and a person feature gate—but lacks the V2 topic model, two-level actor taxonomy, deterministic geography, typed sourced edge graph, immutable topic-scoped fact ledger, verification history, hub geometry and proposal engine, UM6P/OCP checks, ranking attribution model, and most of the required Curate/RAG behavior.

The highest-risk current conflicts are:

1. Actor ER auto-absorbs model scores at or above `0.96`; V2 permits automatic reuse only for exact name/alternate-name/domain matches and forbids automatic merge for close matches.
2. `EntityResolver.refresh()` does not exclude `actor_type='aggregate'`, despite the repository invariant saying aggregate rows are excluded everywhere.
3. Actor absorption can reset an existing actor's `verification_status` to `needs_review`; the Streamlit admin app directly overwrites status without identity, reason, or history.
4. Agent enrichment has no Verified or actor+topic gate. The weekly job enriches up to 50 actors regardless of status.
5. Current facts are mutable actor columns or unique sidecar rows. They cannot represent V2 history, `not_found`, corroboration, conflict, pending update, topic, layer, or per-fact provenance.
6. Current actor discovery scores “practical GHUS engagement” and explicit use cases. V2 Job 1 must map honestly and must not guess how GHUS might use an actor.
7. The weekly event workflow performs a sector-wide sweep without a stated need/topic, contrary to V2.
8. The RAG index omits `actor_profile` and `actor_capability_fact`, has no edge graph or source-origin labels, and boosts results with `actor_relevance.max_relevance_score`. It does not check mapped data before any web-search path.

## Requirement inventory

The planned test names are acceptance targets, not tests that already exist.

| ID | Spec | Requirement | Current implementation and gap | Status | Target | Proof test |
|---|---|---|---|---|---|---|
| R001 | §1 | Job 1 maps and keeps current; it never guesses intended use. | Actor rubric scores eight GHUS use cases and reranks for “practical GHUS engagement” in `agents/discovery/search/actor_scoring.py`. | Conflict | P9/P16 | `test_mapping_has_no_use_case_fields_or_scores` |
| R002 | §1 | Job 2 reasons from a supplied spec and remains separate. | `actor_relevance`, `actor_evaluation`, and `partnership_profile.why_valuable_for_um6p` mix recommendation concepts into the map/RAG. | Conflict | P16 | `test_candidate_interface_requires_explicit_spec` |
| R003 | §1 | Check mapped data before every new search. | ER checks held actors during ingest, but Ask/Explore/search entry points have no universal database-first service. | Partial | P3/P16 | `test_every_request_checks_database_before_web` |
| R004 | §1 | Light pull runs for every discovered actor. | Discovery extracts a generic actor record; there is no V2 light-pull orchestrator or per-category schema. | Partial | P3/P9 | `test_new_actor_runs_light_pull_once` |
| R005 | §1/§4 | Deep pull runs only after GHUS verification. | `agents/enrichment/run.py` selects sparse actors without a verification filter. | Conflict | P10 | `test_deep_pull_refuses_non_verified_statuses` |
| R006 | §1 | Real parent if it exists; otherwise connect through sector, geography, hub. | `organization_hierarchy` exists, but discovery does not perform the ordered V2 parent decision and geography/topic connections are absent. | Partial | P3/P8 | `test_parent_case_order_and_standalone_complete` |
| R007 | §1 | Only GHUS verifies records and approves hubs. | Admin UI can set status directly; no identity/history. `proposed_hub` exists only as repository proposal SQL/model/code; it is absent from production and the fresh `ghus_v2_test` copy. | Conflict | P2/P6/P15 | `test_agent_cannot_verify_or_approve_hub` |
| R008 | §1 | New actor order is category → type → parent/connection → hub → light pull → Parked. | No single `map_new_actor`; promotion currently routes ER then writes generic fields/hubs. | Missing | P3 | `test_map_new_actor_exact_step_order` |
| R009 | §1 | Deep pull follows later, after verification. | Weekly enrichment is not event-driven from verification and is not topic-scoped. | Missing | P10 | `test_verification_enables_only_scoped_deep_pull` |
| R010 | §1 | Imported, Parked/Verified, and uploaded-document sources never mix. | `source` records exist, but actors/facts lack required origin enums and RAG source labels. | Partial | P2/P9/P16 | `test_source_origins_remain_distinct` |
| R011 | §1/§5.2 | Missing evidence is `not_found`, never a guess. | Prompts generally return `null`; durable `not_found` facts do not exist. | Partial | P9/P11 | `test_missing_evidence_writes_not_found_fact` |
| R012 | Prompt §0 | All tunables live in one config module. | Thresholds are spread across `sources.yaml`, `fields.yaml`, `config.py`, ER JSON, and Python constants such as `AI_CONFIDENCE=0.70`. | Conflict | P2 | `test_no_agent_magic_thresholds` |
| R013 | §2 | Exactly seven fixed U.S. regions exist. | Phase 4 has one exhaustive 51-jurisdiction partition in code and reference SQL. | Implemented | P4 | `test_region_partition_all_states_and_dc` |
| R014 | §2 | Northeast contains CT, ME, MA, NH, NY, RI, VT. | Deterministic `region_for_state` derives the specified membership. | Implemented | P4 | `test_fixed_region_memberships` |
| R015 | §2 | Mid-Atlantic contains DE, MD, NJ, PA, VA, WV, Washington DC. | Deterministic `region_for_state` derives the specified membership. | Implemented | P4 | `test_fixed_region_memberships` |
| R016 | §2 | Southeast contains AL, FL, GA, KY, MS, NC, SC, TN. | Deterministic `region_for_state` derives the specified membership. | Implemented | P4 | `test_fixed_region_memberships` |
| R017 | §2 | Midwest/Great Lakes contains IL, IN, IA, KS, MI, MN, MO, NE, ND, OH, SD, WI. | Deterministic `region_for_state` derives the specified membership. | Implemented | P4 | `test_fixed_region_memberships` |
| R018 | §2 | South Central/Texas Gulf contains AR, LA, OK, TX. | Deterministic `region_for_state` derives the specified membership. | Implemented | P4 | `test_fixed_region_memberships` |
| R019 | §2 | Mountain West/Rocky Mountain contains AZ, CO, ID, MT, NV, NM, UT, WY. | Deterministic `region_for_state` derives the specified membership. | Implemented | P4 | `test_fixed_region_memberships` |
| R020 | §2 | West Coast/Pacific contains AK, CA, HI, OR, WA. | Deterministic `region_for_state` derives the specified membership. | Implemented | P4 | `test_fixed_region_memberships` |
| R021 | §2 | Washington DC is Mid-Atlantic; Washington State is West Coast. | DC/D.C./District/Washington DC normalize to DC; Washington and Washington State normalize to WA. | Implemented | P4 | `test_dc_is_not_washington_state` |
| R022 | §2 | Region is derived from state and never entered manually. | Actor promotion discards candidate region/coordinates and derives them from state plus the Census gazetteer. The legacy mutable Hub.region UI remains P15. | Partial | P4/P15 | `test_region_and_coordinates_are_derived_never_candidate_inputs` |
| R023 | §2 | Every actor gets country/state/city/region/coordinates immediately. | Phase 4 derives these during the geocode step; missing/unknown places store null coordinates plus an immutable `not_found` fact and `geocode_failed` review. | Implemented | P3/P4 | `test_no_gazetteer_match_records_not_found_without_coordinates` |
| R024 | §2 | Actors are browsable region → state → city without a hub. | RAG Browse filters country/state and hub/type; no region/city hierarchy. | Missing | P15 | `test_explore_without_hub` |
| R025 | §2 | Hubs are a separate layer; an institution alone is not a hub. | Hub is first-class, but current imports include descriptive ecosystem rows and no V2 creation guard. | Partial | P6/P12 | `test_hub_requires_topic_center_radius_members` |
| R026 | §2.1 | Each hub has exactly one controlled topic. | Hub has narrative strengths and sector arrays, not a topic FK. | Missing | P2/P6 | `test_hub_requires_one_topic` |
| R027 | §2.1 | Each hub has a center coordinate and city. | Hub has nullable latitude/longitude/primary_city, with no method metadata. | Partial | P2/P6 | `test_hub_center_required_and_versioned` |
| R028 | §2.1 | Hub radius defaults to 200 miles; GHUS may choose smaller. | No radius field. | Missing | P2/P6 | `test_hub_radius_default_and_upper_rule` |
| R029 | §2.1 | Hub members are actor-hub rows. | `hub_actor` exists and is many-to-many. It lacks assignment state, decision source, evidence, and distance. | Partial | P2/P6 | `test_actor_hub_records_assignment_evidence` |
| R030 | §2.1 | Distances use deterministic city coordinates; no hand/LLM estimate. | Vendored checksummed Census Places data supplies coordinates; `distance_miles` is a pure miles-only haversine implementation. | Implemented | P4 | `test_haversine_known_city_distances_in_miles` |
| R031 | §2.1 | Phase 1 hub names and definitions are preserved exactly. | The current baseline contains 49 hub rows: the 48 historical Phase 1 names plus `Mining Hubs`, a `phase_1` row with no location or memberships. Apparent spreadsheet artifacts (`+A29`, `+A18`) are preserved pending GHUS review. Definitions are not in the export. | Partial | P12 | `test_phase1_hub_text_round_trip_exact` |
| R032 | §2.1 | Phase 1 center is computed from current members and default radius applied. | No center computation/radius. | Missing | P6/P12 | `test_phase1_center_computed_from_allowed_members` |
| R033 | §2.1 | A nonqualifying Phase 1 hub is retained and only reported. | No criterion/report. | Missing | P12 | `test_phase1_nonqualifying_hub_not_removed` |
| R034 | §2.1 | Approved hub center is frozen. | No `center_frozen`. | Missing | P2/P6 | `test_approved_center_cannot_move_automatically` |
| R035 | §2.1 | Center moves only on GHUS recalculation; drift is flagged. | No recalculation preview, drift threshold, or queue. | Missing | P6/P15 | `test_center_drift_creates_review_only` |
| R036 | §2.2 | Topic test runs before location; topic fail stops location check. | No topic-aware hub assignment. | Missing | P6 | `test_hub_assignment_topic_short_circuit` |
| R037 | §2.2 | Location test uses distance ≤ hub radius. | No automated assignment. | Missing | P6 | `test_hub_assignment_199_vs_201_miles` |
| R038 | §2.2 | Both tests pass → assigned. | Reviewer-selected hubs are inserted with `reviewed_assignment`; no rule decision/evidence. | Partial | P6 | `test_hub_both_pass_assigned` |
| R039 | §2.2 | Topic pass/location fail → unassigned needs review. | Missing assignment state/queue. | Missing | P6 | `test_hub_location_fail_review` |
| R040 | §2.2 | Topic fail → unassigned needs review without distance calculation. | Missing assignment state/low-priority queue. | Missing | P6 | `test_hub_topic_fail_low_priority_review` |
| R041 | §2.2 | Actor may belong to hubs on different topics. | `hub_actor` is many-to-many but hubs have no topics. | Partial | P6 | `test_different_topic_multi_hub_membership` |
| R042 | §2.2 | Same-topic overlap assigns nearest hub and flags overlap. | No topic/radius/distance logic. `hub_overlap` exists only as an ER helper and is excluded from the frozen model. | Missing | P6 | `test_same_topic_nearest_and_radius_overlap_item` |
| R043 | §2.3 | Candidate hub requires ≥10 Verified independent families. | No detector; current raw rows are not family-counted. | Missing | P7 | `test_hub_proposal_ten_families` |
| R044 | §2.3 | Candidate hub requires ≥5 categories, each family counting at most once. | No detector or bipartite matching. | Missing | P7 | `test_hub_category_matching_five` |
| R045 | §2.3 | All members are within 200 miles of center. | No actor coordinates/detector. | Missing | P7 | `test_hub_cluster_radius_200` |
| R046 | §2.3 | Pool is Verified, topic-matched, geocoded, and unassigned on that topic. | No topic, V2 status, coordinates, or detector. | Missing | P7 | `test_hub_pool_filters` |
| R047 | §2.3 | Candidate centers are actor cities; maximize families within 50-mile core. | No detector. | Missing | P7 | `test_center_maximizes_core_family_count` |
| R048 | §2.3 | Center tie uses mean 200-mile distance, then deterministic city ordering. | No detector. | Missing | P7 | `test_center_tie_breaks_deterministically` |
| R049 | §2.3 | Cluster includes all pool actors within 200 miles. | No detector. | Missing | P7 | `test_cluster_contains_all_in_radius` |
| R050 | §2.3 | Families share top-level `unit_of`/`operated_by`; other edges do not merge families. | Current hierarchy is untyped/free-text and has no recursive descendants view/source. | Partial | P7/P8 | `test_family_edges_only` |
| R051 | §2.3 | Same-topic existing hub covering center prevents proposal and runs assignment instead. | No detector. | Missing | P7 | `test_existing_same_topic_hub_suppresses_proposal` |
| R052 | §2.3 | Detector removes accepted candidate cluster and repeats. | No detector. | Missing | P7 | `test_two_separate_clusters_yield_two_proposals` |
| R053 | §2.3 | Proposal contains members, counts, distances, family/type, statement, and suggested name. | The repository-only 180 proposal defines a smaller `proposed_hub`; no deployed database currently has that root, and 310 cannot extend it until 180 is owner-approved and applied. | Missing | P2/P7 | `test_hub_proposal_payload_complete` |
| R054 | §2.3 | GHUS approves, renames, rejects, or sets smaller radius. | Review admission supports accept/reject only and cannot create a canonical hub by design. | Partial | P7/P15 | `test_hub_proposal_decision_actions` |
| R055 | §2.3 | Only GHUS creates the hub. | Review path avoids canonical hub creation, but no V2 approval service/RLS exists. | Partial | P7 | `test_only_ghus_role_creates_hub` |
| R056 | §2.3 | Parked/Imported do not trigger proposals but may join existing hubs. | No detector/status model. | Missing | P6/P7 | `test_parked_imported_assignment_not_trigger` |
| R057 | §2.3 | Rejected cluster is not reproposed unless membership changes. | No membership fingerprint. | Missing | P2/P7 | `test_rejected_fingerprint_suppression` |
| R058 | §3 | Classification is category first, then category type. | Phase 5 classifier enforces record-kind → category → hard rules → category-scoped type. | Implemented | P5 | `test_classifier_calls_category_before_type` |
| R059 | §3 | Exactly one category and one belonging type per actor. | New-write validation is complete; composite FK and completeness checks are proposed in deferred `380` pending P12/P16. | Partial | P2/P5/P12/P16 | `test_exactly_one_category_and_type` |
| R060 | §3 | Category is what the organization is, not sector/use. | Phase 5 prompt and schemas use only official self-description/main job and explicitly exclude sector, funder, fame, age, and GHUS use. | Implemented | P5 | `test_category_ignores_sector_funder_and_use` |
| R061 | §3 row 1 | University/Academic category and five listed types. | Reference data and medical-school hard rule are implemented for new records; existing rows await P12. | Partial | P2/P5/P12 | `test_university_type_seed_and_medical_school_rule` |
| R062 | §3 row 2 | Research Center/Institute/Lab category and three types; excludes national labs. | Reference data and designation guard are implemented for new records; existing rows await P12. | Partial | P2/P5/P12 | `test_research_center_type_seed` |
| R063 | §3 row 3 | National Laboratory category requires designation/FFRDC/federal national mission. | Phase 5 requires designation evidence, forces positive designation evidence into this category, and records classification evidence; existing rows await P12. | Partial | P5/P12 | `test_national_lab_requires_designation_fact` |
| R064 | §3 row 4 | Applied Research Facility/Testbed/Field Site and four types. | Controlled category/type reference data and new-write validation are implemented; existing rows await P12. | Partial | P2/P5/P12 | `test_applied_facility_type_seed` |
| R065 | §3 row 5 | Hospital/Clinical System/Medical Center and four types; medical school is category 1. | Controlled types and the medical-school exclusion are implemented for new records; existing rows await P12. | Partial | P2/P5/P12 | `test_hospital_types_and_medical_school_exclusion` |
| R066 | §3 row 6 | Company/Corporate Actor and four types. | Controlled types and new-write validation are implemented; legacy flat values await P12. | Partial | P2/P5/P12 | `test_company_type_seed` |
| R067 | §3 row 7 | Startup category uses development stage, with origin as one of three types. | Published development-stage evidence and origin deterministically govern new records; legacy rows and broader evidence collection await P9/P12. | Partial | P5/P9/P12 | `test_startup_origin_type_and_published_stage` |
| R068 | §3 row 8 | Innovation Platform/Incubator/Accelerator/Venture Studio and five types. | Controlled types and new-write validation are implemented; existing rows await P12. | Partial | P2/P5/P12 | `test_innovation_platform_type_seed` |
| R069 | §3 row 9 | Investor/VC/Funding Platform and six types. | Controlled types and new-write validation are implemented; existing rows await P12. | Partial | P2/P5/P12 | `test_investor_type_seed` |
| R070 | §3 row 10 | Government Agency/Public Authority and five types; public utility here. | Public utility → government and investor-owned utility → company hard rules are implemented; existing rows await P12. | Partial | P2/P5/P12 | `test_utility_ownership_category_rule` |
| R071 | §3 row 11 | Foundation/Nonprofit and five types. | Controlled types and new-write validation are implemented; existing rows await P12. | Partial | P2/P5/P12 | `test_nonprofit_type_seed` |
| R072 | §3 row 12 | Association/Consortium/Network and six types; network parent with location children. | Controlled types and aggregate exclusion are implemented; network/location conversion remains P8/P12. | Partial | P2/P5/P8/P12 | `test_network_parent_and_location_children` |
| R073 | §3 | People are separate records, never categories. | Phase 5 record-kind detection stops before actor classification and person discovery remains disabled; final DB constraint waits for P16. | Partial | P5/P14/P16 | `test_people_cannot_be_actor_category` |
| R074 | §3 | Events are separate records, never categories. | Phase 5 record-kind detection stops before actor classification and event participant stubs without evidence are reviewed rather than created; final DB constraint waits for P16. | Partial | P5/P14/P16 | `test_events_cannot_be_actor_category` |
| R075 | §3 | Main job is decided from self-description only, not funder, sector, fame. | Ordered Phase 5 classifier and schemas enforce this evidence boundary. | Implemented | P5 | `test_classifier_uses_self_description_only` |
| R076 | §3 | Multi-part organization becomes one record per part, linked to parent. | Extractor may return several actors, but no deterministic decomposition/typed sourced parent edge. | Partial | P3/P5/P8 | `test_multipart_org_creates_linked_records` |
| R077 | §3 | Type choices are restricted to the selected category. | Application validation and category-scoped schemas are implemented; deferred `380` adds the final composite FK after P12/P16. | Partial | P2/P5/P12/P16 | `test_cross_category_type_rejected` |
| R078 | §3 | Doubt uses closest value plus one-line note and GHUS review. | Implemented through the documented `classification`/`issue=category_doubt` bridge; deferred `370` converts it to canonical review kind `category_doubt`. | Partial | P2/P5/P16 | `test_category_doubt_note_and_queue` |
| R079 | §3 | No fitting type uses `other`, required note, and review. | Enforced for new writes and reference data; deferred `380` adds the final actor-table CHECK after P12/P16. | Partial | P2/P5/P12/P16 | `test_other_requires_note_and_review` |
| R080 | §4 | Layer 1 identifies, places, and explains match for every actor. | Generic discovery captures some fields; no placement derivation, topic reason, or fact layer. | Partial | P9 | `test_light_pull_required_fact_set` |
| R081 | §4 | Light completion sets status Parked until GHUS review. | New actors are `needs_review`, not V2 `parked`. | Conflict | P3/P9 | `test_light_pull_ends_parked` |
| R082 | §4 | Layer 2 is selected, topic-relevant, and non-exhaustive. | Enrichment is gap-based and generic, not category/topic/layer-scoped. | Missing | P10 | `test_deep_pull_selected_and_topic_scoped` |
| R083 | §4 | Layer 3 runs only on explicit GHUS request. | No specific-ask service/UI/audit. | Missing | P10/P15 | `test_specific_ask_requires_user_action` |
| R084 | §5.1 | Name plus official alternate/former names/abbreviations. | Actor has name only; no `alt_names`. | Missing | P2/P9 | `test_alt_names_are_normalized_and_searchable` |
| R085 | §5.1 | Category, type, and uncertainty note at Light. | Flat nullable `actor_type`; no type/note. | Conflict | P5/P9 | `test_light_classification_complete` |
| R086 | §5.1 | Parent or normal no-parent connections at Light. | `organization_hierarchy` exists but has no source and is not in mapping flow. | Partial | P8/P9 | `test_light_parent_or_complete_standalone` |
| R087 | §5.1 | Official website at Light. | Actor.website exists; current extraction may leave null. No normalized domain/index. | Partial | P2/P9 | `test_official_website_and_domain` |
| R088 | §5.1 | Description is 1–3 plain factual sentences. | Description exists; prompts say concise but code/schema do not enforce 1–3 sentences. | Partial | P9 | `test_description_sentence_limit` |
| R089 | §5.1 | Country/state/city, derived region/coordinates, multi-location flag. | Promotion derives scalar geography for a single location and writes separately geocoded `actor_location` rows with no parent coordinates for multi-location actors. | Implemented | P2/P4 | `test_multi_location_geocodes_rows_not_parent` |
| R090 | §5.1 | Hub set and distance to each center. | Membership exists; distance/evidence/state absent. | Partial | P6/P9 | `test_light_hub_distances` |
| R091 | §5.1 | Sector(s) and specific topic. | `actor_sector` exists; no `topic`/`actor_topic`. | Partial | P2/P9 | `test_actor_topic_and_sector_links` |
| R092 | §5.1 | Strong/moderate match plus 1–2 sentence reason. | Relevance/rubric is staged JSON, not durable per-topic canonical data. | Missing | P2/P9 | `test_match_strength_reason_constraints` |
| R093 | §5.1 | One dated recent activity if easy; otherwise defer. | `current_activities` is mutable actor text, not dated/topic/fact-layer scoped. | Conflict | P9/P11 | `test_easy_recent_activity_budget_state` |
| R094 | §5.1 | One documented topic funding signal if visible. | `funding_summary` is actor-level mutable text. | Conflict | P9/P11 | `test_light_funding_signal_fact` |
| R095 | §5.1 | Documented international/Africa/Morocco connection if visible. | Some partnership fields exist, but no topic/layer fact and no deterministic budget state. | Partial | P9/P11 | `test_light_international_connection_fact` |
| R096 | §5.1 | UM6P/OCP check runs at Light and Deep. | No entity list/check table or check function. | Missing | P13 | `test_um6p_check_both_layers` |
| R097 | §5.1 | Every fact stores source, origin, date read, confidence. | Source rows exist, but actor columns have one row-level `source_id`; absorption can create an unlinked source. | Conflict | P2/P9/P11 | `test_every_fact_has_complete_provenance` |
| R098 | §5.1 status | Imported means Phase 1 and never implicitly verified. | Current `phase_1`/other values are not the V2 enum; migration absent. | Conflict | P2/P12 | `test_imported_never_verified_by_migration` |
| R099 | §5.1 status | Parked is default for Claude-discovered actors. | Current default is `needs_review`. | Conflict | P3/P12 | `test_discovered_default_parked` |
| R100 | §5.1 status | Verified requires GHUS review. | Admin can set directly but no identity/event/RLS; agents can write `verification_status='needs_review'`/`ai_inferred`. | Partial | P2/P15 | `test_verified_requires_ghus_event` |
| R101 | §5.1 status | Rejected is retained with reason. | Admin sets `rejected` with no required reason/history. | Conflict | P2/P15 | `test_reject_requires_reason_and_retains_actor` |
| R102 | §5.1 | Verification is append-only history with by/date/notes. | No actor verification event. | Missing | P2/P15 | `test_verification_history_append_only` |
| R103 | §5.1 | GHUS notes are writable only by GHUS. | No actor `ghus_notes` or role guard. | Missing | P2/P15 | `test_ghus_notes_role_guard` |
| R104 | §5.2 | All category extraction is specific to the mapped topic. | Generic actor enrichment has no topic parameter. | Missing | P9/P10 | `test_all_category_facts_topic_scoped` |
| R105 | §5.2 | University light/deep/specific fields follow its table row. | No category-derived JSON schema; some generic/profile fields overlap. | Missing | P9/P10 | `test_university_layer_schemas` |
| R106 | §5.2 | Research Center light/deep/specific fields; no ranking at any layer. | No category schema or ranking guard. | Missing | P9/P10 | `test_research_center_schema_has_no_ranking` |
| R107 | §5.2 | National Lab light/deep/specific fields follow its row. | No category schema/designation fact. | Missing | P9/P10 | `test_national_lab_layer_schemas` |
| R108 | §5.2 | Applied Facility light/deep/specific fields follow its row. | No category schema. | Missing | P9/P10 | `test_applied_facility_layer_schemas` |
| R109 | §5.2 | Hospital light/deep/specific fields follow its row. | No category schema. | Missing | P9/P10 | `test_hospital_layer_schemas` |
| R110 | §5.2 | Company light/deep/specific fields follow its row. | No category schema. | Missing | P9/P10 | `test_company_layer_schemas` |
| R111 | §5.2 | Startup light/deep/specific fields; pilot evidence only if easy. | Generic TRL field exists and is enrichable; no published-evidence enforcement. | Conflict | P9/P10 | `test_startup_layer_schema_and_no_assumed_trl` |
| R112 | §5.2 | Innovation Platform light/deep/specific fields follow its row. | No category schema; supported startups are not guaranteed own records. | Missing | P9/P10 | `test_innovation_platform_layer_schemas` |
| R113 | §5.2 | Investor light/deep/specific fields follow its row. | No category schema; investments are not linked actor records. | Missing | P9/P10 | `test_investor_layer_schemas` |
| R114 | §5.2 | Government light/deep/specific fields follow its row. | No category schema. | Missing | P9/P10 | `test_government_layer_schemas` |
| R115 | §5.2 | Foundation/Nonprofit light/deep/specific fields follow its row. | No category schema. | Missing | P9/P10 | `test_nonprofit_layer_schemas` |
| R116 | §5.2 | Association/Network light/deep/specific fields; scope stays on parent. | No category schema/network-location transformation. | Missing | P8/P9/P10 | `test_network_scope_not_copied_to_locations` |
| R117 | §5.2 | Deep items outside starting list need material topic relevance and inclusion reason. | No fact `inclusion_reason` or topic-scoped cap. | Missing | P10 | `test_extra_deep_fact_requires_inclusion_reason` |
| R118 | §5.2 ranking | Rankings may be owned only by universities. | No ranking model/constraint. | Missing | P2/P9 | `test_only_university_owns_ranking` |
| R119 | §5.2 ranking | University-wide publishers are exactly QS, THE, U.S. News Best Colleges, ARWU. | No allowlist/model. | Missing | P9 | `test_university_ranking_publishers` |
| R120 | §5.2 ranking | Subject publishers are exactly QS Subject, THE Subject, U.S. News Graduate specialty. | No allowlist/model. | Missing | P9 | `test_subject_ranking_publishers` |
| R121 | §5.2 ranking | Publisher and year are required; position is exact as published. | No ranking model. | Missing | P2/P9 | `test_ranking_required_attribution` |
| R122 | §5.2 ranking | Department never inherits university overall rank. | No ranking model/guard. | Missing | P9/P16 | `test_department_never_inherits_overall_rank` |
| R123 | §5.2 ranking | University subject rank may display on department only as labeled university context. | No `displayed_as_context_on_actor_id`. | Missing | P2/P15 | `test_subject_rank_context_label` |
| R124 | §5.2 ranking | Link to unit only when verifiably the ranked program. | No evidence-aware attribution guard. | Missing | P9 | `test_program_rank_requires_verified_identity` |
| R125 | §5.3 | Person is its own record and links to organization. | `person` and `actor_person` exist. Current person promotion can create an actor affiliation stub. | Partial | P8/P14 | `test_person_links_to_known_org_or_review` |
| R126 | §5.3 | Mapping an organization never auto-collects people. | Event extraction may collect speakers only when feature enabled; actor extractor excludes people. No explicit org-mapping regression test. | Partial | P14 | `test_mapping_org_creates_zero_people` |
| R127 | §5.3 | Collect people only for experts request, people at Verified actor, or person-needed question. | Current open-web person discovery can run broadly in dry-run when enabled; request intent is not modeled. | Conflict | P14 | `test_person_discovery_allowed_triggers_only` |
| R128 | §5.3 | Person Light fields are name/title/org/expertise/profile/evidence/UM6P. | Current five fields omit evidence and UM6P check. | Partial | P13/P14 | `test_person_light_schema` |
| R129 | §5.3 | Person Deep fields run after separate verification and are topic-scoped/selected. | No person fact layer/deep pipeline. | Missing | P14 | `test_person_deep_requires_person_verification` |
| R130 | §5.3 | Only public professional information. | Prompts enforce this and Targeting Policy is stricter. | Present | P14 harden | `test_person_private_fields_rejected` |
| R131 | §5.3 | Contact only on explicit ask and only official public contact. | Canonical person has email/phone and weekly field set includes them; policy currently forbids them entirely. | Conflict | P10/P14 | `test_contact_requires_explicit_ask_and_official_source` |
| R132 | §5.3 | Person verification is separate from organization. | Person has mutable status but no verification history. | Partial | P2/P14 | `test_person_verification_independent` |
| R133 | §5.4 | Events are time-bound records, not actors. | Event is separate; temporal fields are incomplete. | Partial | P14 | `test_event_never_actor_category` |
| R134 | §5.4 | Event discovery only answers a specific need, never blanket sector sweep. | Weekly job always runs open-web event plus three event sources without a stated need. | Conflict | P14 | `test_event_run_requires_need_and_topic` |
| R135 | §5.4 | Event Light captures name/type/sector/topic/dates/location/organizer/site/recurrence/reason/temporal state/UM6P/description. | Current extraction has many fields but no canonical topic, organizer edge, reason, temporal state, claims structure, or UM6P state. | Partial | P2/P14 | `test_event_light_complete` |
| R136 | §5.4 | Public scale/reputation statements are claims with their source, not facts. | Current description/expected attendance/event scoring can flatten these into fields/scores. | Conflict | P2/P14 | `test_event_claims_are_sourced_claims` |
| R137 | §5.4 | Deep event pull after verification captures themes/sessions, existing actor links, later editions. | No gated event deep pipeline. | Missing | P14 | `test_event_deep_requires_verification` |
| R138 | §5.4 | Event specific ask covers speakers/orgs/agendas/sponsors. | No event specific-ask action/fact layer. | Missing | P10/P14/P15 | `test_event_specific_ask_types` |
| R139 | §5.4 | Past events remain with temporal state `past`. | Retrieval hides past events by default but canonical events are retained; no computed state. | Partial | P2/P14 | `test_past_event_retained_and_marked` |
| R140 | §5.4 | GHUS event notes area is optional and passively flagged empty. | No `event_ghus_notes`. | Missing | P2/P15 | `test_event_notes_empty_flag` |
| R141 | §5.4 | Claude never writes event GHUS notes and never prompts GHUS to fill them. | No notes area today; future role/write guard required. | Missing | P14/P15 | `test_agent_cannot_write_event_notes` |
| R142 | §5.5 | Controlled spreadsheet includes OCP Group/units, UM6P/units incl. UM6P US, INNOVX/funds/ventures/aliases. | No entity table/ingest; spreadsheet path not supplied. | Missing | P2/P12/P13 | `test_um6p_entity_alias_ingest` |
| R143 | §5.5 | “UM6” without P never matches. | No checker. | Missing | P13 | `test_um6_false_positive` |
| R144 | §5.5 | Check uses only documents already read and has no network client. | No checker. | Missing | P13 | `test_um6p_checker_has_no_network_dependency` |
| R145 | §5.5 | `found` stores entity, connection kind, and source. | No check state model. | Missing | P2/P13 | `test_um6p_found_state` |
| R146 | §5.5 | `not_found_in_read_sources` stores sources and is not a “no connection” claim. | No check state model/UI wording. | Missing | P2/P13/P15 | `test_um6p_not_found_wording_and_sources` |
| R147 | §5.5 | `not_yet_checked` is distinct. | No check state model. | Missing | P2/P13 | `test_um6p_not_yet_checked_state` |
| R148 | §5.5 | Connection never causes mapping or changes rank/priority/order. | No checker, but current RAG boosts `actor_relevance`; no invariant test for UM6P connection. | Missing | P13/P16 | `test_um6p_fact_does_not_change_ranking` |
| R149 | §5.5 | Dedicated UM6P/OCP search exists only as Layer 3 ask. | No specific ask. | Missing | P10/P13 | `test_um6p_search_specific_ask_only` |
| R150 | §6 | Relationships require real evidence; never invent a parent. | Hierarchy can be created by ETL without a source column; no map-time evidence guard. | Conflict | P8 | `test_parent_edge_requires_source` |
| R151 | §6 | Check Case 1 real parent, then Case 2 complete standalone. | No unified ordered relationship service. | Missing | P3/P8 | `test_parent_cases_in_order` |
| R152 | §6 | Check name, alternate names, and especially website domain before creating. | Frozen ER checks name/description/hubs; no alt names/domain field/index and not all request types use it. | Conflict | P2/P3 | `test_mapped_lookup_name_alt_domain` |
| R153 | §6 | Exact match appends facts/topic; no duplicate actor. | High model score, not exact keys, currently auto-absorbs mutable gaps. | Conflict | P3/P11 | `test_exact_domain_reuses_actor` |
| R154 | §6 | Close non-exact match is review-only; never auto-merge. | Score ≥0.96 auto-absorbs. Review score creates a second actor before review. | Conflict | P3 | `test_near_match_review_without_merge` |
| R155 | §6 | Parent view returns all descendants at any depth and updates live. | `organization_hierarchy` exists; no recursive view in tracked schema/UI. | Partial | P2/P8/P15 | `test_recursive_descendants_live` |
| R156 | §6 | Network is one parent; each physical location is its own child; scope stays parent-only. | Aggregate rows are excluded rather than transformed; no location model/migration. | Conflict | P8/P12 | `test_network_scope_parent_only` |
| R157 | §6 edge | `unit_of` is a sourced actor→actor edge. | Free-text hierarchy may represent it but no source/enum. | Partial | P2/P8 | `test_unit_of_edge_contract` |
| R158 | §6 edge | `operated_by` is a sourced actor→actor edge. | No controlled edge model/source. | Missing | P2/P8 | `test_operated_by_edge_contract` |
| R159 | §6 edge | `affiliated_with` links person→organization, at department when known. | `actor_person` exists without source; role is part of PK. | Partial | P2/P8 | `test_affiliation_department_and_source` |
| R160 | §6 edge | `member_of` is a sourced edge. | No general edge table. | Missing | P2/P8 | `test_member_of_edge_contract` |
| R161 | §6 edge | `portfolio_of` means accelerator participation, never ownership/parenthood. | No general edge type or descendants exclusion. | Missing | P2/P8 | `test_portfolio_not_parent` |
| R162 | §6 edge | `spinout_of` is a sourced edge. | No general edge table. | Missing | P2/P8 | `test_spinout_edge_contract` |
| R163 | §6 edge | `funded_by` is a sourced edge. | Funding is mostly summary text/source table for hubs. | Missing | P2/P8 | `test_funded_by_edge_contract` |
| R164 | §6 edge | `collaborates_with` is a sourced edge. | Collaboration is narrative text, not graph. | Missing | P2/P8 | `test_collaboration_edge_contract` |
| R165 | §6 edge | `organizes` links organization→event. | Event has one `host_actor_id`, not typed/source-backed/many-to-many. | Partial | P2/P8/P14 | `test_organizes_edge_contract` |
| R166 | §6 edge | `participates_in` links actor/person→event. | Participants can be staged, but no canonical typed sourced event edge. | Missing | P2/P8/P14 | `test_participates_in_edge_contract` |
| R167 | §6 edge | `connected_to_um6p_ocp` is a sourced edge/fact. | No entity/check/edge model. | Missing | P2/P8/P13 | `test_um6p_edge_contract` |
| R168 | §6 | Every edge has a type and source; reject otherwise. | Current hierarchy and actor_person have no source; types are not constrained. | Conflict | P2/P8 | `test_edge_source_and_type_constraints` |
| R169 | §6 | Never overwrite; add new facts alongside old. | Admin, ETL, maintenance, ER, enrichment, and merge paths update canonical rows in place. | Conflict | P11/P12 | `test_no_canonical_fact_overwrite_path` |
| R170 | §6 | Conflicting facts are flagged for GHUS. | Field proposals exist for enrichment, but no fact-version conflict state/queue. | Partial | P2/P11 | `test_agent_fact_conflict_queue` |
| R171 | §6 | Human facts are never auto-replaced; new version becomes pending update. | No fact creator class/history; actor row `source_id` can be overwritten by enrichment. | Conflict | P11 | `test_human_fact_pending_update` |
| R172 | §6 | Rejected records and reasons remain; no canonical delete. | Rejected actors remain today, but smoke scripts delete fixtures and merge code deletes/repoints relationship rows; no DB delete guard. | Partial | P2/P11 | `test_canonical_delete_revoked_and_rejected_retained` |
| R173 | Corrected scope §3a | Inventory and migrate every frontend `actor_type` runtime reference. | Runtime references exist in React, legacy Streamlit, Browse, assembly, router, enrichment, map export/discovery, and docs. | Conflict | P5/P15/P16 | `test_frontend_has_no_unaliased_actor_type_reference` |
| R174 | Corrected scope §3a | Inventory every frontend query and API route that touches actors, hubs, events, facts, review queues, or rankings. | Actor/hub/event/search queries exist; fact/ranking reads do not yet exist; review routes are only on the unmerged `review-workflow` branch. | Partial | P2/P15/P16 | `test_frontend_entity_query_contract_inventory_is_complete` |
| R175 | Corrected scope §3a | Identify and contract-test every V2-affected screen. | Ask, Browse Actors/Hubs/Events, Build the Map, and the pending Review screen all consume legacy shapes. | Conflict | P15/P16 | `test_every_v2_screen_uses_compat_contract` |
| R176 | Corrected scope §3a | Every backend migration documents frontend breakage and a compatibility alias or deploy order. | No cross-repository migration/deploy matrix existed. | Missing | P2/P5/P15/P16 | `test_each_backend_schema_change_has_frontend_compatibility_plan` |
| R177 | Corrected scope §3b | Canonical-table changes are owner-reviewed Alembic proposals, outside the live revision chain until approval. | The mistaken draft used raw SQL for all changes. | Conflict | P2 | `test_canonical_proposals_are_detached_alembic_revisions` |
| R178 | Corrected scope §3b | Platform-owned schema starts at `agents/sql/190` and never duplicates a canonical migration. | Existing platform SQL ends at 180; draft V2 tables were in one mixed directory. | Missing | P2 | `test_platform_v2_sql_starts_at_190_without_canonical_alters` |
| R179 | Corrected scope §3c | V2 extends existing hierarchy, merge log, fact/profile, review, admission, person-review, and hub-gap structures where semantics overlap. | The draft duplicated some adjacent concepts. | Conflict | P2 | `test_v2_schema_declares_extension_origin_for_every_table` |
| R180 | Corrected scope §3d | No canonical writer exists outside `promote.py` and `decisions.py`. | ER, admin, ETL, merge/review scripts, hierarchy scripts, and enrichment jobs write canonical rows directly. | Conflict | P3/P11/P12/P15 | `test_static_canonical_writer_allowlist` |
| R181 | Corrected scope §3e | The proposed `proposed_hub` workflow has an explicit, lossless deployment/cutover path into the V2 proposal model. | The root exists in repository proposal 180 and application/model code but has never been deployed to production; the draft also introduced parallel `v2_hub_proposal*` tables without cutover rules. | Conflict | P2/P7/P15 | `test_proposed_hub_cutover_preserves_references_and_history` |
| R182 | Corrected scope §3f | Defaults remain configurable and visibly pending GHUS confirmation. | Draft defaults exist, but need an explicit pending-decision register. | Partial | P2 | `test_pending_ghus_defaults_are_flagged_in_config` |
| R183 | Corrected scope §3f | Unrecoverable overwrite limits are stated and no historical value is invented. | Existing rows do not preserve all former actor/hub/event values. | Conflict | P2/P12 | `test_import_never_synthesizes_missing_history` |
| R184 | Corrected scope §5 | Constraints over populated canonical tables are `NOT VALID` until a successful backfill/validation step. | Draft constraints could reject existing production rows immediately. | Conflict | P2/P12 | `test_populated_table_constraints_are_backfill_safe` |

## Corrected frontend coverage baseline

### Framework, tests, and ownership

- The active platform is a FastAPI application (`backend/app.py`) serving a no-build React 19 + HTM browser UI from `frontend/index.html`. React, HTM, Marked, and DOMPurify are loaded through browser import maps; there is no npm manifest or bundler.
- The root `app.py` is a legacy Streamlit Ask/Browse implementation. Documentation still contains a `streamlit run app.py` command, but the current run instructions use `uvicorn backend.app:app`; V2 UI work must target FastAPI + React.
- Python tests use standard-library `unittest`. Browser logic has Node `.mjs` tests invoked with `node --test`. No frontend linter is configured. Phase 2 must add a smoke contract without introducing a package manager solely for testing.
- Pages/screens live in `frontend/index.html`; API routes live in `backend/app.py`; PostgreSQL access lives in `src/db.py`; relational assembly, embedding, and retrieval live in `src/assemble.py`, `src/embed.py`, `src/retrieve.py`, and `src/router.py`.
- `src/assemble.py` still exists. Retrieval is hybrid vector + PostgreSQL full-text search in `src/retrieve.py`, called by FastAPI Ask and the legacy Streamlit app.
- The frontend `review-workflow` branch (`dbe6097`) is two commits ahead of frontend `main` and adds the Review screen/routes. It is not silently folded into the V2 branch; its contracts are included below so Phase 15 does not erase that work.

### Complete `actor_type` impact inventory

| Surface | Runtime references and required compatibility |
|---|---|
| React UI | `frontend/index.html:668,707,721,798,875` filters/displays/exports `actor_type`; consume `actor_category` after Phase 5, with `actor_type` accepted only from the temporary compatibility response. |
| Legacy Streamlit | `app.py:195-196,257,368`; frozen legacy surface, covered by the compatibility alias until retirement. |
| Browse/data shaping | `src/browse.py:7,103,126,218,272-273`; query alias must be `actor_category AS actor_type` before coordinated cutover, then response key changes with the React deployment. |
| Search document assembly | `src/assemble.py:40,78`; use the same alias during the backend rename so index rebuilds do not fail. |
| SQL planner schema | `src/router.py:30`; deploy the compatibility schema prompt with the migration and remove the legacy name only after frontend cutover. |
| Frontend enrichment | `src/enrich/agent.py:96` and `src/enrich/gaps.py:32,37`; context/query alias only. This workflow remains proposal-only and must not become a canonical writer. |
| Build-the-Map pipeline | `src/map_agent/discover.py:65`, `enrich.py:30`, `select.py:101`, `export.py:36`; rename the transient payload field in one coordinated contract change and accept legacy imports during the transition. |
| Tracked documentation | `ARCHITECTURE_PROPOSAL.md:91`, `BUILD_THE_MAP_HANDOFF.txt:136`, `Database schema.md:25`, `CHAT_HANDOFF.md:181`, `HANDOFF.md:137`, `Tech_Summary.md:166`, and `AGENTS.md:33`; update when the runtime cutover lands. |

### Query, API, and screen coverage

| Surface | Tables/contracts touched | V2 breakage and prevention |
|---|---|---|
| Ask upload/stream: `POST /api/upload`, `GET /api/ask/stream` | `search_doc`; LLM-generated safe SELECT schema in `src/router.py` can query actor/hub/event relations. | Actor/status rename and fact/edge additions make the planner stale. Keep V1 compatibility views through Phase 16; deploy the V2 router schema only after those views and current-fact views exist. |
| Browse actors: `GET /api/browse/actors` | `actor`, `hub_actor`, `hub`, `partnership_profile`, `sector`. | Breaks on actor/status rename and later fact-ledger transition. Alias old columns in SQL/API until React changes; add region/category/type/status/origin fields additively. |
| Browse hubs: `GET /api/browse/hubs` | `hub`, `hub_actor`, `actor`, dynamic hub columns. | Hub V2 fields are additive, but renamed membership shape would break counts/detail. Preserve `hub_actor` compatibility view/API response through Phase 15. |
| Browse events: `GET /api/browse/events` | `event`. | Event status/date/topic migration changes the response. Maintain legacy date/status aliases until the Events screen changes. |
| Ask index build | `src/assemble.py` reads actor/profile/relevance/hub/event; `src/embed.py` upserts platform-owned `search_doc`; `src/retrieve.py` reads it. | Renames break assembly and stale documents hide V2 facts. Compatibility alias first, then rebuild index from current-fact/source/status views in Phase 16. |
| Build the Map routes | `/api/map/session`, `/api/maps`, `/api/map/upload`, `/api/map/chat`, `/api/map`, `/api/map/{id}`, stop/budget/resume, `/api/map/verify`, `/api/map/export`; local SQLite run store plus transient actor/hub/event payloads. | Payloads carry `actor_type`; use dual-read/one-write compatibility during Phase 5. These routes do not write canonical PostgreSQL. |
| Review routes on `review-workflow` | Candidate list/detail/edit/approve/reject/decision; reads `search_candidate`, `event_review_queue`, `person_review_queue`, `staged_record`, `scrape_run`, and `hub`. | Queue unification can strand candidates. Provide queue compatibility views/adapters before Phase 15 and preserve admission IDs/outcomes during hub-proposal cutover. |
| Direct utilities | `data_quality_scan.py` reads actor; `src/enrich/gaps.py` reads actor/hub; `src/db.py` owns normal/read-only connections. | Use compatibility views and require the isolated-test URL in smoke tests. |
| Facts and rankings | No current frontend query or route reads V2 facts or rankings. | Add only against `actor_fact_current` and contextual ranking views in Phases 15-16; absence today is a required-test gap, not evidence of compatibility. |

Affected screens are Ask, Browse/Actors, Actor detail, Browse/Hubs, Hub detail and membership, Browse/Events, Build the Map planning/results/verification/export, and the pending Review candidate list/detail/decision views. Backend schema changes must ship compatibility aliases before these screens deploy; destructive alias removal is last, after both repositories' contract tests pass.

## Migration ownership and extension matrix

Canonical proposals live in `migrations/proposed/versions/` as detached Alembic revisions with `down_revision = None` (or a documented placeholder), never imported by the live Alembic chain until the schema owner rebases/approves them. Platform-owned tables live under `agents/sql/`, beginning at 190. Every constraint on an already populated table is added `NOT VALID` and validated only after an idempotent backfill report succeeds.

| Planned change | Track | Existing structure extended, or reason it is new |
|---|---|---|
| Actor rename, category/type FK, status/origin, normalized domain, location columns | Alembic proposal A01 | Extends canonical `actor`; rename guarded by frontend/Agent 3 aliases. |
| Hub topic/center/radius/freeze fields and membership evidence/distance | Alembic proposal A02 | Extends canonical `hub`, `hub_actor`, and the hub gap fields from `a7c9d2e8f104`. |
| Person status/privacy projection columns | Alembic proposal A03 | Extends canonical `person`; person review queues remain platform-owned. |
| Event status/date/topic projection columns | Alembic proposal A04 | Extends canonical `event`; preserves host/event data while graph migration proceeds. |
| `actor_category_definition`, `actor_category_type_definition`, `region_definition`, `region_state`, `source_origin_definition` | `agents/sql/190_v2_reference_data.sql` | New controlled reference data because the legacy schema uses unconstrained strings. |
| `actor_location` | `agents/sql/200_v2_actor_location.sql` | New because one canonical actor row cannot represent multiple evidenced physical locations. |
| `topic`, `actor_topic`, `event_topic`, `person_topic` | `agents/sql/210_v2_topics.sql` | New controlled topic layer; extends current sectors without treating sector as topic. |
| `hub_center_review` | `agents/sql/220_v2_hub_center_review.sql` | New review history for approved/frozen hub-center drift without mutating historical decisions. |
| `record_verification` | `agents/sql/230_v2_verification_history.sql` | Extends stored verification columns and existing review queues with append-only identity/reason history. |
| `actor_fact`, `fact_resolution`, current-fact view | `agents/sql/240_v2_fact_ledger.sql` | Extends `actor_profile` and `actor_capability_fact` from `f6b9a8c7d2e1`; legacy tables become backfill/compatibility inputs, not parallel mutable truth. |
| `entity_edge`, recursive descendants view | `agents/sql/250_v2_edges.sql` | Extends `organization_hierarchy` from `18f57ec36d6e`, `event.host_actor_id`, and person affiliations into sourced typed edges. `actor_merge_log` from `F3a9c1b2d4e5` remains the merge audit. |
| `collection_request`, `collection_run`, `fetched_document` | `agents/sql/260_v2_collection_runs.sql` | Extends `scrape_run` and raw-document capture with explicit requester/layer/topic budgets. |
| `actor_ranking` | `agents/sql/270_v2_rankings.sql` | New because contextual rankings cannot be represented safely as actor ownership or a mutable profile field. |
| `contact_collection_authorization` | `agents/sql/280_v2_people_privacy.sql` | Extends person review queues with explicit Layer 3 authorization; disabled by default. |
| `event_claim` | `agents/sql/290_v2_event_evidence.sql` | New append-only event evidence because canonical event text cannot retain claim history. |
| `strategic_entity`, `actor_strategic_connection_check` | `agents/sql/300_v2_strategic_connections.sql` | New because UM6P/OCP checks require three-state, per-layer, sourced results independent of actor facts. |
| V2 hub proposal/member/decision data | `agents/sql/310_v2_hub_proposals.sql` | Repository proposal only. It depends on the undeployed `proposed_hub` and `review_admission_decision` roots in `agents/sql/180`; production and the fresh `ghus_v2_test` copy contain neither root. No parallel permanent proposal truth. |
| Unified `review_item` and decisions | `agents/sql/320_v2_review_items.sql` | Extends `review_queue` (`a7c2e91f4b03`), event/person queues, and review admission through compatibility views. |
| `canonical_write_audit` and permission guards | `agents/sql/330_v2_guards_and_audit.sql` | New audit/guard layer with RLS and explicit agent-role write/delete denials. |
| Compatibility/current views | `agents/sql/340_v2_compatibility_views.sql` | Views bridge existing consumers while each old queue/table is retired. |

The exact committed order is defined by `migrations/proposed/manifest.json`; every platform SQL file has a same-number rollback file under `agents/sql/rollback/`. No platform SQL file may alter a canonical table; no detached Alembic proposal may create an agent-owned table.

## Canonical writer audit and repair plan

| Writer | Finding | Required resolution |
|---|---|---|
| `agents/discovery/promote.py` | Allowed canonical creation/absorption writer. | Move to fact/edge ledger without adding DELETE; retain exact-match-only reuse and same-transaction provenance. |
| `agents/enrichment/decisions.py` | Allowed canonical decision writer. | Replace scalar metadata overwrite with immutable fact resolution and pending-human-update semantics. |
| `agents/review/admission.py` | Does not directly write actor/person/event/hub; it writes platform review/proposal tables and delegates promotion. | Keep as orchestrator; adapt it to the retired proposal/queue views without becoming a third writer. |
| `scripts/apply_review_decisions.py` | Conflict: calls merge logic and directly inserts `organization_hierarchy`. | Route decisions through `decisions.py`; graph changes become sourced ledger edges. Disable direct apply mode after cutover. |
| `src/ML/entity_resolution/resolve_or_create.py` and `scripts/run_er_sweep.py` | Conflict: directly inserts/updates actor using score-based absorption. | Make resolver advisory only; route exact create/reuse through `promote.py`, all non-exact cases to possible-duplicate review. |
| `src/admin/app.py:set_status` | Conflict: bulk updates status/updated_at directly. | Replace with verification decision service/history in Phase 15; shared role loses update privilege. |
| `scripts/actor_merge.py` | Conflict: deletes/repoints relationship rows and mutates merge state. | Preserve old merges for audit; replace future behavior with non-destructive edge/fact resolution through `decisions.py`. No new hard-delete path. |
| `scripts/create_hierarchy_edges.py` | Conflict: direct canonical hierarchy insert. | Convert to dry-run edge proposals and delegate accepted writes to `decisions.py`. |
| `scripts/run_actor_type_enrichement.py`, `src/enrichment/reclassify_others_actors.py` | Conflict: direct actor classification/status/source mutation. | Convert to staged category/type proposals/facts; accepted decisions flow through `decisions.py`. |
| `src/enrichment/actor_enrichment_candidates.py` and maintenance scripts under `scripts/actor_enrichment_maintenance/` | Conflict: direct actor/profile/capability mutation or backfill. | Freeze direct apply modes; ledger backfills are isolated migration tooling, and new decisions delegate to `decisions.py`. |
| `scripts/run_researcher_enrichement.py` | Conflict: directly creates people/affiliations. | Keep person discovery disabled; later stage person/edge proposals and delegate accepted canonical writes to `promote.py`/`decisions.py`. |
| ETL translators `ecosystem_mapping.py`, `ecosystem_events.py`, `hub_actor_extractor.py`, `nutricrops.py`, `un_mapping.py`, `um6p_un_events.py`, `UNGA_climate_week.py` | Conflict: insert/update actor, hub, event, memberships, profiles, and relevance directly. | Phase 12 converts imports to staged records plus approved writer calls; legacy apply modes are retired. |
| `scripts/smoke_test_actor_merge.py` | Conflict and safety risk: hard-deletes canonical fixtures. | Restrict to isolated test DB immediately; remove all DELETE-based cleanup when merge behavior moves to the ledger. |
| Frontend `src/embed.py` | Writes only platform-owned `search_doc`, not canonical entities. | Keep separate; add dry-run/parity and rebuild from V2 current views in Phase 16. |

Agent queue/provenance/run-store modules that write only `staged_record`, raw documents, run logs, review queues, or `index_dirty` are not canonical-writer conflicts. Static tests must maintain an explicit allowlist and fail on new actor/person/event/hub/membership/fact/edge mutations outside the two approved modules and isolated migration tooling.

### Phase 3 writer-audit closure (2026-09-28)

- `promote.py` now owns V2 actor creation, exact-match evidence append, topic/fact append, hub assignment, and review creation. It no longer uses similarity scores to absorb actors.
- `decisions.py` now appends actor enrichment values to `actor_fact` and exposes the canonical ORM/decision gateways used by legacy importers. Actor enrichment no longer updates actor scalar fields or actor-level provenance/status.
- `agents/review/admission.py` remains an orchestrator only and delegates canonical promotion.
- `apply_review_decisions.py`, `create_hierarchy_edges.py`, `actor_merge.py`, the destructive merge smoke script, legacy ER live writes, and legacy Streamlit status writes are retired. Their dry-run/report behavior remains where useful, but their former apply paths raise before any canonical write.
- Existing ETL and enrichment constructors now hand persistence to `decisions.py`; direct ORM `session.add` calls were removed from the audited files. Future Phase 12 work still converts their canonical-shaped inputs into staged V2 import records.
- Static tests scan `agents/`, `scripts/`, and `src/`: raw canonical SQL outside `promote.py`/`decisions.py`, canonical `DELETE`, or a newly introduced unallowlisted agent writer fails the suite.
- The obsolete `_promote_actor_legacy` / `_absorb_actor_fields` overwrite implementation was removed rather than merely left unreachable. Exact discovered-domain actor matches now retain the V2 exact-match append route; only non-exact similarity matches become `possible_duplicate` review items.

This closes the writer boundary but cannot reconstruct history already overwritten by earlier releases. Specifically unrecoverable from current rows alone are previous actor/hub/event narrative, category/type, location, `source_id`, status, confidence, and `updated_at` values. Old threshold absorptions remain report-only and are not automatically unmerged. Per the schema-owner hold, no backup/PITR action was taken.

Mapped-first coverage in Phase 3 applies to every backend path that can submit a newly discovered actor to canonical promotion, including event participants. Ask and Explore in the sibling platform are database-only today and do not trigger web discovery; the universal RAG/Build-the-Map database-first service remains explicitly tracked by R003 for Phase 16. Layer 3 specific asks do not exist yet and remain scheduled for Phase 10. This is a planned phase boundary, not permission for any current actor-creation path to bypass `map_new_actor`.

## Hub proposal overlap and retirement

Deployment correction (2026-09-29): the workflow exists in repository artifacts: `agents/sql/180_review_admission_workflow.sql`, `agents/review/admission.py`, `src/db/models_v2.py`, and their tests. It also existed temporarily in the Phase 2 incarnation of `ghus_v2_test` because that proof explicitly applied the complete proposed platform chain 010–180 before applying V2 proposals. That was test schema, not production deployment. Read-only production inspection found no `public.proposed_hub`; after `ghus_v2_test` was reset from a fresh production copy for the additive proof, it also returns null for `proposed_hub`, `proposed_hub_member`, and `proposed_hub_decision`. No verified database currently contains this workflow. Earlier wording that called it “existing” without qualification conflated the repository/temporary test schema with deployed production schema.

The proposed workflow is `agents/sql/180_review_admission_workflow.sql` -> `proposed_hub` -> `review_admission_decision.proposed_hub_id`, written by `agents/review/admission.py`. It captures a reviewer-suggested name/location/rationale tied to one reviewed candidate. The mistaken draft's `v2_hub_proposal`, member, and decision tables capture deterministic clusters, fingerprints, family/category counts, distances, rename/radius decisions, and final-hub linkage. They overlap in identity, status, reviewer decision, and source linkage but neither is a complete superset as written.

Retirement plan:

1. After schema-owner approval, deploy proposal 180 to create the root, then extend `proposed_hub` in place through platform SQL 310 with V2 nullable columns and child member/decision tables; do not create a second permanent proposal root.
2. Backfill a stable legacy fingerprint and origin kind for every existing row; preserve every `proposed_hub_id` referenced by review admission.
3. Point the detector and Review UI at the extended model; legacy candidate proposals remain distinguishable from deterministic cluster proposals.
4. Add compatibility views matching both the old admission shape and the temporary draft V2 shape.
5. After admission/UI/tests use the extended model, retire only the temporary `v2_hub_proposal*` names. Never delete or rewrite historical proposal/decision rows.

Proof: `test_proposed_hub_cutover_preserves_references_and_history` loads legacy 180 data, migrates forward, validates both views and idempotence, then exercises rollback without losing the export.

## Pending GHUS decisions and unrecoverable history

Every default below remains behind config and is **pending GHUS confirmation**: 50-mile hub core, 200-mile maximum/default radius, 10 independent families, 5 categories, 25-mile drift flag, Verified-only proposal trigger (with Verified+Imported comparison report), per actor+topic deep authorization, confidence rubric, three-page Light budget, category-specific Deep caps, low-priority topic-fail review, refresh cadence not scheduled, network-location classification, need/topic-gated event schedule, out-of-scope professional-services policy, and Job 2's `candidate_actors(spec)`-only interface. Person discovery and contact collection remain disabled.

Past overwritten values are not recoverable from the current database alone: prior actor-level `source_id`, verification status, confidence, `updated_at`, and canonical actor/hub/event narrative, classification, and location values changed by admin, ETL, maintenance, ER, merge, or enrichment paths. They may be reconstructed only from schema-owner backups/PITR, source spreadsheets, merge logs, or dated exports. Phase 12 must report possibilities and gaps; it must never invent history or automatically unmerge records absorbed by the old threshold logic.

### Phase 2 production baseline provenance

The read-only, repeatable-read production baseline dated 2026-09-24 is stored outside both repositories at `C:\Users\Ismail\GHUS-data\exports\architecture_v2_baseline_2026-09-24\manifest.json` (relocated manifest SHA-256 `61d1e834a8773b8db101c1e86bda091c617c1380f0cf28f3618c95cd027bbb31`). It contains the requested baseline scope: 965 actors, 49 hubs, 821 hub memberships, 356 events, 7,257 staged records, 280 actor review rows, 9 event review rows, and 0 person review rows. All Phase 12 records assigned `source_origin=Imported` must cite this dated manifest (plus the applicable CSV hash recorded inside it) as their import origin; the migration must not infer or manufacture missing history.

The current production baseline has the historical 48 Phase 1 hub names plus one additional row named `Mining Hubs`. This is informational only: all 49 current rows remain intact, no historical hub is demoted, and GHUS membership remains authoritative even when a later distance calculation exceeds 200 miles.

Production reported PostgreSQL 17.6 with `pg_stat_statements`, `pgcrypto`, `supabase_vault`, `uuid-ossp`, and `vector`; the isolated database uses PostgreSQL 17.5 with only `plpgsql`. All eight exported datasets were loaded into `ghus_v2_test`; a broader production dump was not taken because it would exceed the requested baseline export scope.

## Draft schema migration set

The table below is the original conceptual set and is superseded for file placement by the ownership matrix above. Canonical changes become detached Alembic proposals; platform-owned objects become `agents/sql/190+`. They are never applied to shared Supabase by automation. Each proposal must have an upgrade, validation queries, an explicit downgrade/rollback, populated-table-safe constraints, and owner-approval instructions.

| Order | Proposed file | Changes | Rollback approach |
|---|---|---|---|
| 001 | `001_v2_reference_taxonomy.sql` | Create `category_type`; seed all §3 types plus one `other` per category; create controlled status/origin/confidence/layer/state types or check constraints. | Drop seed rows/table/types after dependent objects are removed. |
| 002 | `002_v2_actor_identity_location.sql` | Rename `actor_type`→`actor_category`; add temporary compatibility view/alias; add `category_type`, `category_note`, `category_needs_review`, `alt_names`, normalized/indexed `website_domain`, V2 status/source origin/GHUS notes, derived region, coordinates, multi-location flag; add category/type composite FK and `other` note check. Add `actor_location` if multiple physical locations must coexist before network splitting. | Restore column name, remove constraints/indexes/new columns; retain a data export for reverse mapping. |
| 003 | `003_v2_verification_history.sql` | Create append-only actor/person/event verification event tables; triggers/projectors for current status; RLS/role grants denying agent decisions; require rejection reason. | Drop policies/triggers/tables and leave projected status values intact. |
| 004 | `004_v2_topics.sql` | Create `topic`, `topic_sector`, and `actor_topic` with strong/moderate check, reason, discovery run, and uniqueness/indexes. Seed 8 sectors + CROSS/DIASPORA mappings and existing hub themes after review. | Drop junctions/topics; sector table is untouched. |
| 005 | `005_v2_fact_ledger.sql` | Create/extend `actor_fact` and `person_fact` with topic/layer/value JSON/source origin/date/confidence/supersession/current/state/creator/inclusion reason/requester; allow explicit `not_found` and `not_yet_collected`; add immutable history and current uniqueness rules. Migrate `actor_capability_fact`/`actor_profile` through views or backfill, not destructive replacement. | Drop views/triggers/new tables only after exporting inserted facts; legacy sidecars remain. |
| 006 | `006_v2_rankings.sql` | Create `actor_ranking` with allowed publisher/family checks, university ownership enforcement, ranked entity link, contextual display link, exact position text, year/source/date. | Drop ranking policies/table. |
| 007 | `007_v2_edges.sql` | Create `actor_edge` (or generalized `entity_edge`) with the exact edge types, source/date/confidence/state; migrate hierarchy/host/affiliation links; create recursive `actor_descendants` restricted to parent edge types; no `parent_id`. | Restore compatibility views over legacy relations; drop recursive view/table after export. |
| 008 | `008_v2_city_gazetteer.sql` | Create `us_city_coord` and normalized unique/index keys; load vendored Census-derived places data with provenance/version; add region derivation function/check/generated field. | Drop function/table after clearing dependent constraints. |
| 009 | `009_v2_hubs.sql` | Extend/rebuild Hub with topic, center, radius, freeze/method/origin/audit fields; extend `actor_hub` with assignment/decider/evidence/distance; create drift/outside-radius semantics. | Restore legacy compatibility view; drop added constraints/columns only after export. |
| 010 | `010_v2_hub_proposals.sql` | Replace/extend `proposed_hub` with members JSON, family/category counts, fingerprint, V2 decisions/radius/final hub; retain review-admission source references. | Restore old view shape and drop V2-only fields/indexes. |
| 011 | `011_v2_people.sql` | Add person facts and independent verification integration; ensure public-professional fields and explicit-ask contact provenance; agent role restrictions. | Remove new sidecars/policies; retain legacy person rows. |
| 012 | `012_v2_events.sql` | Merge the already-requested event `verification_status`/`updated_at`/`confidence` change with V2 dates/topic/recurrence/temporal state/match reason/description/status; create sourced `event_claim`, `event_ghus_notes`, and verification integration. | Drop V2 sidecars/columns and restore legacy event compatibility view. |
| 013 | `013_v2_um6p_ocp.sql` | Create `um6p_ocp_entity`, aliases, and per-layer checks with three states and sources-read array; add constraints for found details. | Drop checks/entities after export. |
| 014 | `014_v2_review_items.sql` | Create unified `review_item` with exact kinds, priority, filters, audit/resolution; compatibility views for existing actor/event/person queues during migration. | Drop views/table after preserving legacy queues. |
| 015 | `015_v2_immutability_permissions.sql` | Revoke canonical DELETE from app/agent roles; append-only triggers on fact and verification history; role guards for GHUS notes/status/hub approval; edge/fact source constraints. | Restore prior grants and drop guards only with owner approval. |
| 016 | `016_v2_compatibility_views.sql` | Temporary Agent 3 `staged_record` compatibility alias `actor_type=actor_category`, legacy RAG views, and deprecation comments. | Drop only after teammate and RAG cutover confirmation. |

Schema design decisions to carry into implementation:

- `actor.status` is a cached/projected value derived from the latest verification event, not a second independent truth.
- A fact's `source_origin` vocabulary is separate from an actor's record origin; the names must not be collapsed.
- `actor_location` is preferable to repeated coordinates on a multi-location parent. Network physical sites still become their own actors as required by §6.
- The edge table should be generalized enough to represent person/event endpoints while exposing an actor-only recursive descendants view. If the schema owner prefers separate edge tables, their union must present one retrieval graph.
- `actor_capability_fact` cannot satisfy V2 as-is because its unique key overwrites the `(actor,fact_type,source_field)` slot and it lacks topic/layer/version/current/state/origin/date semantics. Preserve it as a compatibility view or migrate it idempotently into `actor_fact`.

## Claude and model prompt inventory

| Prompt site | Current purpose | V2 rules it must enforce/change |
|---|---|---|
| `agents/discovery/search/query_generation.py:QueryGenerator._llm_queries` | LLM search queries for events; actor/person queries are deterministic grids. | Database-first check; events require an explicit need/topic; CROSS/DIASPORA remain excluded only here; no use-case guessing. |
| `agents/discovery/search/providers.py:ClaudeWebSearchProvider.search` | Claude server-side web search execution. | Accept only approved query plan; cannot bypass mapped-first, specific-need, fetch, or cost gates. |
| `agents/discovery/search/triage.py:SearchTriageClient.triage` | Recall-oriented actor/event/person URL fetch gate. | Keep identity decisions out; enforce person/event trigger scope; do not score intended GHUS use; group/category pages remain rejected as actors. |
| `agents/discovery/search/actor_scoring.py:ActorRubricExtractor` | Extracts actor record plus engagement/use-case rubric. | Remove use-case/“practical engagement” components; classify category then type; self-description only; hard category rules; source-bound facts; no invented fields; topic match only. |
| `agents/discovery/search/actor_scoring.py:ActorListwiseReranker` | Orders candidates for “practical GHUS engagement.” | Replace objective with evidence quality/topic relevance or remove reranking; UM6P connection cannot influence order. |
| `agents/discovery/search/event_scoring.py:EventRubricExtractor` | Extracts event record and qualification rubric. | Require stated need/topic; capture reputation/scale only as sourced claims; temporal state; no automatic people; explicit `not_found`. |
| `agents/discovery/search/person_scoring.py:PersonRubricExtractor` | Five-field public professional extraction and relevance rubric. | Feature flag off; only three allowed triggers; add evidence and UM6P state; deep only after person verification; contacts only specific ask. |
| `agents/discovery/search/rubric_scoring.py:ListwiseReranker` | Shared listwise ordering. | Never use UM6P connection; mapping rank may use source/evidence/topic only, not hypothetical use. |
| `agents/discovery/extractors/actor.py:ActorExtractor` | Generic canonical-shaped actor extraction. | Replace flat `actor_type` with category-then-type schemas; `not_found`; description length; no region/coordinates as model input; produce staged evidence for `map_new_actor`. |
| `agents/discovery/extractors/event.py:EventExtractor` | Generic event extraction and optional participants. | Need/topic required; claims separated; participant people disabled by default; organizer/participant edges sourced; temporal state derived. |
| `agents/discovery/extractors/person.py:PersonExtractor` | Five permitted public professional fields. | Keep off by default; enforce trigger context; add layer/topic/evidence; no contact except explicit specific ask. |
| `src/enrichment/actor_enrichment_candidates.py:SYSTEM_PROMPT` | Validates candidate identity and fills five generic gaps. | Verified actor+topic gate before prompt; category-specific deep schema/caps; fact insert, never row overwrite; `not_found`; inclusion reason; fetched-doc list passed to UM6P checker. |
| `src/enrichment/extractors/actor_type.py:SYSTEM` | Flat actor type classifier. | Replace with category-first and restricted type-second structured calls; special rules and doubt note/review. |
| `src/enrichment/extractors/researchers.py:SYSTEM` | Extracts people from hub talent narratives. | Disable as automatic org mapping; allow only explicit people requests; public professional fields; separate verification. |
| Maintenance Claude prompts under `scripts/actor_enrichment_maintenance/*claude*.py` | One-off actor text cleanup/refinement. | Freeze or port to fact ledger; never rewrite canonical V2 facts; source/topic/layer required. |
| RAG `src/conversation.py:condense_question` | Condenses follow-up questions. | Preserve topic/status/source intent; never trigger web search before database lookup. |
| RAG `src/router.py:plan` | Claude SQL planner. | Update schema to actor_category/type/topics/facts/edges/status; SELECT current facts only; source/status labels; safe candidate interface for Job 2. |
| RAG `src/router.py:format_sql_answer` | Formats SQL results. | State record status/origin; label Parked as unreviewed; preserve not-found wording. |
| RAG `src/generate.py:SYSTEM_PROMPT` and citation repair | Generates cited answers from search docs. | Require source-origin and review-status disclosure; current facts only; no unsupported claims; “not found in what has been read” wording; distinguish university contextual ranking; never treat portfolio as ownership. |

## `actor_type` rename impact inventory

The database column is unconstrained `varchar(40)`, so the live vocabulary cannot be proven from migrations alone. The intended legacy list in `docs/architecture/entity-model.md` has 10 values, while mappings and production code reference many more, including `corporate_rd_lab`, `federal_agency`, `federal_research_system`, `national_research_center`, `industrial_partner`, `project_developer`, `un_programme`, `un_committee`, `un_secretariat`, `un_agency`, `multilateral_development_bank`, `intergovernmental_organization`, `research_organization`, `venture_capital`, `industry_association`, `health_system`, and `aggregate`. A live dry-run export is required before finalizing the mapping table.

Production references that must move to `actor_category` or a deliberate compatibility view:

| Area | Files / references |
|---|---|
| Canonical schema | `src/db/models.py:149-150`; `migrations/versions/890c436ee256_initial_v1_schema.py:57-58` |
| ER/promote | `src/ML/entity_resolution/resolve_or_create.py:58`; `agents/common/resolve_route.py:150`; `agents/discovery/promote.py` via `INHERITABLE_FIELDS`; `scripts/actor_merge.py:73`; `scripts/apply_review_decisions.py:42`; `scripts/backfill_confirmed_merges.py:215` |
| Discovery extraction/scoring | `agents/discovery/extractors/actor.py:75-119,162`; `agents/discovery/search/actor_scoring.py:229-486,652-661`; `agents/discovery/search/models.py:36,79,133`; `agents/discovery/search/phase2.py:418-522`; `agents/discovery/search/run.py:312-344,716-717` |
| Query/reference sets | `agents/discovery/search/query_generation.py:273-1032`; `agents/discovery/search/triage.py:387,567`; `agents/discovery/person_pages.py:35`; `agents/common/resolve_route.py:150` |
| Event participant output | `agents/discovery/event_qualification.py:16,186,206`; `agents/discovery/extractors/event.py:156-318`; `agents/discovery/extractors/unga_guide.py:180,232`; `agents/discovery/extractors/unga_programme.py:84` |
| Enrichment | `agents/enrichment/specs.py:37,116`; `src/enrichment/actor_enrichment_candidates.py:764-2408`; `src/enrichment/extractors/actor_type.py`; `src/enrichment/reclassify_others_actors.py` |
| ETL/import | `src/etl/translators/nutricrops.py`; `src/etl/translators/un_mapping.py`; `src/etl/translators/hub_actor_extractor.py`; `data/processed/actor_type_mapping.csv` |
| Maintenance/reporting | `scripts/run_actor_type_enrichement.py`; `scripts/tag_gold_entity_class.py`; `scripts/actor_enrichment_maintenance/actor_funding_summary_fill.py`, `actor_quality_claude_refine.py`, `actor_technical_claude_refine.py`, `actor_technical_fill.py`, `actor_technical_sonnet_refine.py`, `backfill_actor_profile_fact_evaluation.py`, `ghus_refresh_search_docs_from_actor.py`, `ghus_template_phrase_cleanup.py` |
| Docs/evals | `evals/run_eval.py`; `docs/data-dictionary.md`; `docs/architecture/entity-model.md`; `agents/README.md`; tests in `tests/agent/test_agents_actor_rubric_pipeline.py`, `test_agents_discovery_phase1.py`, `test_agents_event_rubric_pipeline.py`, `test_agents_open_web_discovery.py`, `test_agents_open_web_phase2.py` |
| RAG schema/index | sibling `src/assemble.py:52,119`; `src/browse.py:7,103,126,218,272-273`; `src/router.py:31`; `src/schema_check.py:16`; `app.py:532-533,594,705`; `Tech_Summary.md:166` |

Only the temporary Agent 3 compatibility alias may continue exposing the name `actor_type`; all application code and tests must otherwise stop reading it.

## Current hub audit (informational only)

The earlier 872-row Phase 0 export yields 48 distinct Phase 1 hub names. The 2026-09-24 production baseline adds `Mining Hubs`, a `phase_1` hub row with no location and no memberships, for 49 current rows. Raw membership is not the V2 independent-family count, does not exclude aggregates, has no category/type, and has no coordinates. Therefore the full V2 criterion remains **indeterminate**. Forty-seven hubs have at least 10 raw rows; `New York City AI Hub` has 9, and `Mining Hubs` has 0. Names are shown exactly as exported; all 49 remain informational and none is demoted.

| Hub | Raw linked actor rows | V2 criterion |
|---|---:|---|
| Arizona Mining & Mineral Resources Hub (Phoenix – Tucson – Southern Arizona) | 16 | Indeterminate |
| Arizona Water Innovation Hub (Phoenix- Tueson) | 14 | Indeterminate |
| Baltimore-Washington NIC Corridor (Baltimore – Bethesda – Washington D.C. – Rockville) | 20 | Indeterminate |
| Bay Area AI Hub (Stanford – UC Berkeley – Silicon Valley – San Francisco) | 21 | Indeterminate |
| Bay Area Chemistry & Materials Innovation Hub | 17 | Indeterminate |
| Boston- Cambridge Academic Medical Hub | 18 | Indeterminate |
| Boston–Cambridge AI Hub (MIT – Harvard – Greater Boston) | 20 | Indeterminate |
| Boston–Cambridge Chemistry & Chemical Biology Hub | 16 | Indeterminate |
| California Central Valley + Bay Area Industrial Green Chemistry Corridor (San Francisco Bay Area – Sacramento – Fresno Corridor) | 22 | Indeterminate |
| California Clean Energy Hub | 19 | Indeterminate |
| California Sustainability & Climate Systems Hub (Stanford – UC Berkeley – UCLA – LBNL – State of California) | 19 | Indeterminate |
| California Water Hub (UC Davis - Berkeley- Stanford) | 14 | Indeterminate |
| Colorado Energy & Climate Hub (Denver – Boulder – Golden – Front Range) | 15 | Indeterminate |
| Colorado Mining & Earth Systems Hub (Golden – Denver – Boulder)+A29 | 18 | Indeterminate |
| Colorado Sustainability & Earth Systems Hub (Boulder – Denver – Fort Collins) | 15 | Indeterminate |
| Colorado Water Hub (Boulder- Denver- Front Range)+A18 | 13 | Indeterminate |
| Cornell / Upstate New York – Agriculture & AgriTech Hub | 17 | Indeterminate |
| Delaware–Pennsylvania Catalysis & Reaction Engineering Hub | 18 | Indeterminate |
| Delaware–Philadelphia Chemistry Hub (Wilmington – Philadelphia – Newark) | 15 | Indeterminate |
| Great Lakes Water Hub | 14 | Indeterminate |
| Illinois Midwest Ag Corridor (Urbana-Champaign + Chicago) | 21 | Indeterminate |
| Massachusetts Energy Innovation Hub (Boston – Cambridge) | 14 | Indeterminate |
| Midwest Advanced Materials and Catalysis Hub (Illinois – Wisconsin – Minnesota Corridor) | 16 | Indeterminate |
| Midwest Chemistry & Advanced Materials Hub (Chicago – Urbana-Champaign – Ann Arbor – Madison) | 18 | Indeterminate |
| Midwest Clinical & Translational Health Hub (Great Lakes Medical Corridor) | 16 | Indeterminate |
| Midwest Energy & Industrial Transition Hub (Chicago – Detroit – Ohio – Indiana – Illinois) | 17 | Indeterminate |
| Midwest Sustainability & Industrial Transition Hub (Great Lakes Industrial Corridor) | 19 | Indeterminate |
| Mining Hubs | 0 | Fails raw 10-row floor and has no center/members; full criterion indeterminate |
| Missouri – St. Louis Plant Science & Ag-Biotech Hub | 14 | Indeterminate |
| Missouri Critical Minerals & Processing Hub (St. Louis – Rolla – Lead Belt) | 13 | Indeterminate |
| Nevada Mining & Critical Minerals Hub (Reno – Elko – Northern Nevada) | 16 | Indeterminate |
| New York City Academic Medicine Hub (Columbia – NYU – Mount Sinai – Cornell – Greater NYC) | 25 | Indeterminate |
| New York City AI Hub (Columbia - NYC - Cornell Tech) | 9 | Fails raw 10-row floor; full criterion indeterminate |
| New York City Sustainability & Urban Systems Hub (Columbia – NYU – Cornell Tech) | 15 | Indeterminate |
| Pacific Northwest Sustainability Hub (Seattle – Portland – Corvallis) | 17 | Indeterminate |
| Pennsylvania Mining & Energy Transition Hub (Pittsburgh – State College – Appalachian Basin) | 17 | Indeterminate |
| Pittsburgh AI & Robotics Hub (Carnegie Mellon Ecosystem) | 15 | Indeterminate |
| Research Triangle Chemistry Hub (Raleigh – Durham – Chapel Hill) | 20 | Indeterminate |
| San Francisco Bay Area Health & Biomedical Innovation Hub (UCSF – Stanford – Berkeley – Silicon Valley) | 17 | Indeterminate |
| Seattle AI Hub (University of Washington – Big Tech AI – Greater Seattle) | 13 | Indeterminate |
| Southern California (Los Angeles) AI Hub (USC – UCLA – Caltech – Greater LA) | 18 | Indeterminate |
| Texas A&M / College Station – Texas Ag Corridor | 21 | Indeterminate |
| Texas Energy Transition Hub | 20 | Indeterminate |
| Texas Gulf Coast Chemistry Hub (Houston – Baytown – Galveston – Beaumont) | 19 | Indeterminate |
| Texas Gulf Coast Specialty Chemicals Hub (Houston–Galveston–Baytown–Freeport corridor) | 20 | Indeterminate |
| Texas Medical Center Health Hub (Houston – Texas Medical Center Campus – Helix Park – TMC Innovation Factory) | 22 | Indeterminate |
| Texas Water Systems Hub | 14 | Indeterminate |
| UC Davis / Sacramento Valley Agriculture Ecosystem | 20 | Indeterminate |
| Utah Mining & Mettallurgy Hub | 14 | Indeterminate |

The Phase 12 dry run must recompute this table with: V2 category/type, top-level family, status, deterministic coordinates, center, 50/200-mile spread, and both Verified-only and Verified+Imported proposal counts.

Phase 6 implements only the reusable deterministic assignment and center-preview
machinery. It does not assign controlled topics, invent missing coordinates,
persist centers, or change any of the 821 authoritative memberships. The
baseline remains 49 hub rows but only 48 hubs with memberships: `Mining Hubs`
is the extra empty row. Real hub-topic mapping, status/geography eligibility,
center population, and membership migration remain P12.

## Current overwrite/delete audit

Current behavior is not V2-safe:

- `agents/discovery/promote.py:_absorb_actor_fields` fills gaps but also sets `verification_status='needs_review'`, which can downgrade a previously Verified record. Its inserted source may be disconnected when `actor.source_id` is already populated.
- `agents/enrichment/decisions.py:_update_canonical_gap` gap-guards the target field, but rewrites the actor-level `source_id`, verification status, confidence, and updated timestamp. That loses field-specific provenance and can overwrite human provenance metadata.
- `src/ML/entity_resolution/resolve_or_create.py` is a canonical writer outside the two allowed agent writer modules and implements threshold auto-absorb.
- `src/admin/app.py:set_status` directly overwrites verification status in bulk with no user identity, notes, rejection reason, event history, or writer delegation.
- ETL translators update existing canonical actors/hubs/events in place: `ecosystem_mapping.py`, `ecosystem_events.py`, `nutricrops.py`, `un_mapping.py`, `um6p_un_events.py`, `UNGA_climate_week.py`, and `hub_actor_extractor.py`.
- Maintenance and classification scripts update actor text/type in place, including `run_actor_type_enrichement.py`, `reclassify_others_actors.py`, `actor_quality_*`, `actor_technical_*`, and `ghus_template_phrase_cleanup.py`.
- `scripts/actor_merge.py` deletes/repoints junction rows and soft-merges actors. It is reversible through `actor_merge_log`, but it is not compatible with an immutable fact/edge ledger without migration.
- `scripts/smoke_test_actor_merge.py` uses hard DELETE for tagged test fixtures. It must remain test-only and use isolated test schema/transactions; it must never be available against production roles.
- `agents/index/refresh.py` deletes `index_dirty`, an agent-owned queue, not canonical facts; this is acceptable with existing non-empty/parity guards.

## Conflicts requiring explicit approval before Phase 2

1. **ER protected decision vs V2.** `AGENTS.md` says agents must use the frozen combiner and thresholds; V2 says only exact name/alt-name/domain reuses an actor and every close match is review-only. Proposed resolution: retain the frozen model only to rank possible-duplicate candidates, remove its authority to auto-absorb, and make exact keys the sole automatic reuse path.
2. **DDL location/ownership.** `AGENTS.md` says canonical DDL must be raised as a question and existing agent SQL lives under `agents/sql/`; the approved architecture workflow requires reviewable SQL under `migrations/proposed/`. Proposed resolution: approval of this Phase 0 plan explicitly authorizes writing—but never applying—the proposed canonical migrations under `migrations/proposed/`.
3. **Repository naming.** The implementation prompt calls the platform `um6p-rag`; local repository instructions define `um6p-rag` as a read-only consumer. Proposed resolution: canonical/agent work in `GHUS-Platform`; RAG/Streamlit work in the sibling consumer, coordinated by compatibility views.
4. **People contacts.** V2 permits official public contact information only on an explicit ask. Current `Targeting_Policy.md` §6 forbids email/phone and lacks supervisor sign-off. Proposed resolution: keep person discovery and contact collection off; implement the Layer 3 path behind separate disabled flags, and require an approved policy amendment before live use.
5. **Phase 1 hub text quality.** Exported names include likely spreadsheet artifacts and spelling variants (`+A29`, `+A18`, `Tueson`, `Mettallurgy`). V2 says preserve names exactly. Proposed resolution: import exactly, flag quality issues for GHUS, and never silently correct them.
6. **Status as derived vs stored.** The plan lists an actor `status` column and also says current status is derived from latest verification event. Proposed resolution: store a guarded projection/cache maintained by trigger/service; verification history is authoritative.
7. **Missing-state vocabulary.** V2 says absent evidence is `not_found`; the implementation plan adds `not_yet_collected` for fields outside the deterministic Light budget. Proposed resolution: `not_found` means searched/read and absent; `not_yet_collected` means deliberately not searched at that layer.

## Open decisions with defaults

| Decision | Default to implement | Audit note |
|---|---|---|
| Hub core, independence, overlap, drift | 50-mile core; family counts once; same-topic nearest-center assignment; 25-mile drift flag. | Put all in one V2 config module; pending GHUS confirmation. |
| Imported actors in new-hub trigger | Verified only. | Dry run also reports Verified+Imported comparison; pending GHUS confirmation. |
| Deep authorization | Per actor+topic. | Verification event must carry `topic_id`; pending GHUS confirmation. |
| Confidence rubric | High=official/government/allowed ranking; medium=reputable named third party; low=indirect/single secondary/aggregator. | Store confidence on every fact, not actor row. |
| Light fetch budget | 3 pages (homepage + up to two topic pages). | “Easy/visible” uses only these pages. |
| Deep caps | Category-specific configurable top-N. | No constant in prompts/agent code. |
| Topic-fail hub review | Low-priority, separately filterable. | Prevents burying actionable location reviews. |
| Refresh cadence | Propose monthly for stable identity facts and shorter configurable TTLs for event/date/funding/activity facts; do not schedule yet. | Requires GHUS approval. |
| Network location category/type | Classify each physical location by its own main job; if no listed type fits, `other`+note+review. | Never copy parent scope. |
| Weekly event schedule | Keep workflow shell, but every configured run must declare approved need/topic; otherwise skip loudly. | Current blanket sweep is incompatible. |
| Out-of-scope consulting/law/media | Skip unless a listed category genuinely fits by main job; otherwise closest category+doubt is not sufficient to force scope. | Needs GHUS policy decision. |
| Job 2 | Expose only `candidate_actors(spec)` interface. | No new fit/use fields until companion document arrives. |

## Ordered implementation plan after approval

1. **P2 — Proposed data model.** Add `migrations/proposed/README.md` and the ordered SQL set above; update ORM/compatibility models without applying DDL; add schema contract tests.
2. **P3 — Record creation orchestration.** Implement `map_new_actor(candidate, topic, run_ctx)` in the staged→promote boundary with database-first exact matching, possible-duplicate review, strict step trace, Parked end state, and dry/live candidate parity assertion.
3. **P4 — Geography (complete 2026-09-29).** Implemented all-state region derivation, vendored gazetteer loader/normalizer, coordinate derivation, geocode review, and miles-only haversine. See `docs/architecture_v2_phase4.md`.
4. **P5 — Category then type (complete 2026-10-01).** Seeded the 12-category/65-type source catalog, implemented ordered structured classification and deterministic hard rules, moved active discovery/promotion and Browse/RAG assembly to category-first dual-read compatibility, retired direct legacy classification writers, and retained the physical `actor_type`/Agent 3 bridge until P12/P16. See `docs/architecture_v2_phase5.md`.
5. **P6 — Existing hubs (complete 2026-10-01).** Implemented topic-first deterministic assignment, immutable distance evidence, nearest-center overlap routing, eligible-member density-center previews, frozen-center drift review, and read-only preservation assessment for all 821 Phase 1 memberships. Real topic/center/member backfill remains P12. See `docs/architecture_v2_phase6.md`.
6. **P7 — Hub proposals (complete 2026-10-01).** Implemented per-topic deterministic family clustering, fail-closed V2 family resolution, maximum bipartite category matching, family-set fingerprints, dry-run/on-demand execution, proposal-only live persistence, and the append-only GHUS decision service. The production-copy baseline cannot yield meaningful proposals yet because P8/P12 have not supplied controlled topics, authoritative structural edges, classification, coordinates, Verified statuses, or trusted hub topic/center/radius data. See `docs/architecture_v2_phase7.md`.
7. **P8 — Link graph.** Implement sourced typed edges, parent cases, recursive descendants, network/location treatment, and retrieval graph adapter.
8. **P9 — Light pull.** Generate schemas from category data, enforce three-fetch budget, write provenance facts including `not_found`/`not_yet_collected`, rankings, and Light UM6P check.
9. **P10 — Deep pull and specific asks.** Add verified actor+topic gate, category caps, linked sub-entity mapping through `map_new_actor`, explicit requester/audit, and no autonomous Layer 3 triggers.
10. **P11 — Immutable fact resolution.** Add corroboration, supersession, conflict, pending-human-update, current/history views, and remove mutable canonical fact writes.
11. **P12 — Existing-data migration.** Idempotent dry-run reports first: category/type mapping, aggregate/network CSV, geocode report, Phase 1 hub report, events, source origins/statuses, and UM6P spreadsheet ingest after its path is supplied.
12. **P13 — UM6P/OCP check.** Pure document-list function with three states and false-positive/ranking-invariance tests.
13. **P14 — People/events.** Keep people off, enforce triggers/privacy/separate verification, require event need/topic, retain past events/claims, and lock GHUS notes.
14. **P15 — Curate/Explore UI.** Replace direct status writes with services; add queues, history, actor/hub/duplicate/conflict screens, maps, source labels, and region browsing.
15. **P16 — RAG.** Join current fact views, source/status metadata, edge graph, mapped-first service, Parked wording, ranking attribution, and explicit Job 2 candidate interface; remove relevance boost/use-case leakage from Job 1 retrieval.
16. **P17 — Acceptance and migration verification.** Run all specified unit/integration/contract tests, idempotence test, dry/live parity, and static write-path audit. No production DB connection or migration execution.

## Phase 0 approval gate

No implementation should begin until GHUS approves this document, including the proposed resolutions for the ER and DDL conflicts. The Phase 12 UM6P/OCP ingest will additionally require the spreadsheet path. Live Phase 1 hub compliance remains unverified until an owner-provided database snapshot/export includes actor category/type, status, hierarchy, city/state, and hub definitions.
