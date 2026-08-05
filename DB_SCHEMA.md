# UM6P Intelligence — Database Schema

_Read-only survey of the live Supabase (Postgres + pgvector) database. Generated 2026-08-05 against `public`. Row counts are live at that date. This supersedes the schema notes in the stale `HANDOFF.md`._

> **Provenance model.** This is no longer a simple read-model — it is a **provenance-aware knowledge base**. Almost every content table carries `source_id` (→ `source`), `evidence_url`, `verification_status`, `confidence`, and `generated_by`, so each fact can be traced to a citation and to whatever produced it (a deterministic backfill or a named model). The schema is **migration-managed by Alembic** (`alembic_version = f6b9a8c7d2e1`).

> **Liveness rule.** `actor` rows are live only where `merged_into_actor_id IS NULL`. ALWAYS apply that filter when counting or listing actors — the rest are merged duplicates (see `actor_merge_log`).

---

## At a glance

- **29 base tables** in `public`.
- **952 actors** (872 live + 80 merged) · **49 hubs** · **231 events** · **1,448 sources**.
- An **AI enrichment layer has already run**: 5,712 cited capability facts and 952 per-actor profiles (520 written by `claude-haiku-4-5`).
- A **dedup pipeline is in active use**: 80 merges done, 277 pairs queued.
- The **propose→approve→apply loop is scaffolded but unused**: `proposal` exists (RLS on) with 0 rows.

---

## Core entities

### `actor` — 952 rows (24 cols)
The central table: organizations, labs, companies, funders, universities.
`actor_id` (uuid PK), `name`, `slug`, `actor_type`, `actor_type_raw`, `description`, `website`, `location_city`, `state`, `country`, `primary_technical_focus`, `technical_approach`, `current_activities`, `technology_ip_notes`, `key_constraints`, `estimated_trl` (1–9 or null), `primary_lifecycle_role`, `source_id`, `verification_status`, `confidence`, `created_at`, `updated_at`, `merged_into_actor_id`, `funding_summary`.
- `verification_status` ∈ `phase_1` (96, hand-curated, richest), `ai_inferred` (755, extracted), `needs_review` (14), null (7). Live totals.
- `country` is free text and inconsistent (`USA` 625 vs `United States` 178) — normalize on read.

### `hub` — 49 rows (32 cols)
Innovation ecosystems, very rich. Identity + `primary_city`/`state`/`country`/`region`, `latitude`/`longitude`, `primary_sectors`/`secondary_sectors`, `official_websites`, `strategic_value_summary`, `core_topic_strengths`, plus six long narratives (`composition_`, `programs_and_labs_`, `talent_`, `research_infrastructure_`, `industry_integration_`, `international_engagement_narrative`) and flow write-ups (`upstream_inputs`, `downstream_outputs`, `integrated_flow_description`).

### `event` — 231 rows (15 cols)
Conferences and programs. `name`, `event_type`, `location`, `website`, `recurring_pattern`, `next_date`, `sponsoring_orgs`, `host_actor_id`, `description`, `thematic_focus`, `expected_attendance`, `access_type`. Only a minority carry a real `next_date`.

### `challenge` — 1 row (9 cols)
The UM6P challenge/theme that actors are scored against (`actor_relevance`). `name`, `sponsoring_org`, `target_sectors`, `target_technologies`, `source_document_id`.

### `sector` — 10 rows (6 cols)
Sector taxonomy. `sector_id`, `code`, `name`, `description`, `parent_sector_id`. Note: actor↔sector links are **empty** (see `actor_sector`).

### `source` — 1,448 rows (7 cols)
The **citation backbone** every evidence field points at. `source_id`, `source_type`, `url`, `retrieved_at`, `description`, `trust_tier`, `created_at`.

### `person` — 0 rows (14 cols) · empty scaffolding
People: `full_name`, `title`, `email`, `orcid`, `bio`, `linkedin_url`, `tel_num`, `country_code`, + provenance cols.

### `funding_source` — 0 rows (4 cols) · empty scaffolding
`funding_source_id`, `name`, `category`, `description`.

### `strategic_document` — 0 rows (10 cols) · empty scaffolding
Uploaded strategy docs: `title`, `source_organization`, `document_type`, `full_text`, `extracted_themes`, `storage_uri`.

---

## AI-generated content & evidence about actors

### `actor_capability_fact` — 5,712 rows (12 cols)
Structured, citable facts per actor: **6 fact types × 952 actors** (`constraint`, `current_activity`, `funding`, `technical_approach`, `technical_focus`, `technology_ip`). `fact_type`, `source_field`, `fact_value`, `source_id`, `evidence_url`, `verification_status`, `confidence`, `generated_by`. 4,818 rows carry an `evidence_url`; all currently `generated_by = deterministic_actor_column_backfill` (a normalization of existing `actor` columns into facts, not fresh web extraction).

### `actor_profile` — 952 rows (13 cols)
One narrative profile per actor: `profile_summary`, `identity_summary`, `technical_summary`, `funding_summary`, `lifecycle_summary`. `generated_by`: **520 `claude-haiku-4-5`**, 432 deterministic backfill.

### `actor_evaluation` — 158 rows (14 cols)
Scored evaluations of an actor within a context. `evaluation_context`, `context_entity_type`, `context_entity_id`, `score`, `evaluation_summary`, `evidence_summary`, + provenance.

### `actor_relevance` — 130 rows (13 cols)
Actor↔challenge relevance. `challenge_id`, `relevance_score`, `maturity_risk`, `collaboration_orientation`, `why_relevant`, `current_evidence`, `additional_validation_needed`, `challenge_relevance_narrative`, `source_links`.

### `partnership_profile` — 28 rows (20 cols)
Deep, human-grade partnership dossiers for a curated few actors: `thematic_focus`, `strategic_plan`, `africa_specific_mandate`, `why_valuable_for_um6p`, `budget_overview`, `university_partnership_examples`, `key_entry_points`, `funding_delivery_mechanisms`, `key_constraints`.

---

## Relationships (join tables)

| Table | Rows | Links | Key columns |
|---|---|---|---|
| `hub_actor` | 821 | actor ↔ hub | `hub_id`, `actor_id`, `relationship_type`, `is_primary` |
| `event_sector` | 87 | event ↔ sector | `event_id`, `sector_id` |
| `organization_hierarchy` | 42 | actor ↔ actor (parent/child) | `parent_actor_id`, `child_actor_id`, `relationship_type` |
| `actor_sector` | **0** | actor ↔ sector — **empty** | `actor_id`, `sector_id`, `confidence`, `source_id` |
| `hub_sector_strength` | **0** | hub ↔ sector strength — **empty** | `hub_id`, `sector_id`, `strength_score`, `actor_count`, `top_actor_ids` |
| `hub_funding` | **0** | hub ↔ funder — **empty** | `hub_id`, `funding_source_id`, `narrative` |
| `actor_person` | **0** | actor ↔ person — **empty** | `actor_id`, `person_id`, `role`, `is_current` |

> Sector-by-actor browsing remains impossible: `actor_sector` and `hub_sector_strength` are empty even though `sector` (10) and `event_sector` (87) are populated.

---

## Event scoring

### `event_scoring` — 87 rows (22 cols)
Six scored dimensions → an overall tier: `longevity_`, `recognition_`, `scale_`, `audience_profile_`, `organizer_profile_`, `geographic_reach_score` (each with a matching `_description`), `total_score`, `tier`, `tier_raw`, `scoring_methodology_version`, `scored_at`.

---

## Dedup / curation workflow

### `review_queue` — 277 rows (12 cols)
Candidate duplicate actor pairs awaiting a decision. `actor_id_a`, `actor_id_b`, `score`, `model`, `features`, `status`, `decided_by`, `decided_at`, `merge_id`, `notes`.

### `actor_merge_log` — 80 rows (11 cols)
Completed merges (audit + revertible). `winner_actor_id`, `loser_actor_id`, `score`, `method`, `decided_by`, `decided_at`, `pre_merge_state`, `status`, `reverted_at`.

### `proposal` — 0 rows (13 cols) · **scaffolded, unused, RLS enabled**
The propose→approve→apply table for agent-suggested edits. `proposal_id`, `entity_id` (nullable → null when proposing a **new** entity), `table_name` (NOT NULL), `field`, `old_value`, `new_value`, `evidence_url` (**NOT NULL**), `evidence_snippet` (**NOT NULL**), `proposed_by`, `status` (NOT NULL), `reviewed_by`, `reviewed_at`, `created_at`.

---

## Search / RAG index

### `search_doc` — 1,010 rows (6 cols)
The live retrieval index. `entity_id`, `entity_type`, `name`, `doc_text`, `embedding` (pgvector), `doc_tsv` (tsvector).

### `search_doc_2` — 1,010 rows (11 cols)
Enriched index variant adding `website`, `updated_at`, `verification_status`, `confidence`, `indexed_at`. (An unexplained second copy — reconcile with `search_doc` before relying on it.)

---

## Ops

- **`query_log`** — 7 rows (10 cols): usage/feedback. `question`, `route`, `retrieved_ids`, `found_by`, `top_distance`, `latency_ms`, `answer`, `helpful`.
- **`alembic_version`** — 1 row: current migration head `f6b9a8c7d2e1`.

---

## Notable gaps & data-quality flags

- **`actor_sector` is empty** → sector-based browsing of actors is not possible.
- **Website / country coverage of live actors** is now high: website 627/755 `ai_inferred` (+94/96 `phase_1`); country missing on only ~16 `ai_inferred`. The messy `USA` (625) vs `United States` (178) split persists.
- **Empty scaffolding** ready for future work: `person`, `actor_person`, `strategic_document`, `funding_source`, `hub_funding`.
- **Two search-doc copies** (`search_doc`, `search_doc_2`) — provenance of the second is unexplained.
- The rich provenance layer (`actor_capability_fact`, `actor_profile`, dedup tables, Alembic) indicates a more complete pipeline has been applied to this shared DB than the RAG/application repo itself contains — coordinate before duplicating it.
