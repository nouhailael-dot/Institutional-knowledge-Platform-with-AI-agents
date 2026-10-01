# Architecture V2 Phase 5 report — Actor category and category type

Date: 2026-10-01  
Backend repository: `C:\Users\Ismail\Projects\GHUS-Platform`  
Frontend/RAG repository: `C:\Users\Ismail\Projects\Institutional-knowledge-Platform`  
Branch in both repositories: `codex/architecture-v2`  
Starting checkpoint: backend Phase 4 commit `80c0f1153246ac7c3c783eea8417eeb1fcf91764`  
Validated additive-package checkpoint: `adbedc907a8f7edc4667d36f0baac288141b2b1e`

## 1. Scope and safety boundary

Phase 5 implements category-first, type-second actor classification and stops
before Phase 6. No production connection, DDL, write, backup, or data mutation
was performed. The validated 180–350 additive package was not changed. The
physical `actor_type` and `verification_status` columns were not removed.

Teammate-owned Agent 3 code under `src/map_agent/` was not changed. Person
discovery remains disabled, dry-run remains the default, `aggregate` remains
excluded, and canonical actor writes remain confined to the approved promotion
and decision paths.

## 2. Reference model

`config/actor_categories.yaml` is the single runtime source of truth for all 12
Architecture V2 actor categories and 65 category/type pairs. Each category has
exactly one explicit `other` type. `aggregate`, `person`, and `event` are absent
from both levels.

Proposal 019 adds metadata enforcement to the V2-owned reference table:

- `definition` is required;
- `is_other` must agree exactly with `type_code='other'`;
- each category can have exactly one `other` row.

The proposal is in `agents/sql/370_v2_actor_classification.sql`, with its exact
rollback in `agents/sql/rollback/370_v2_actor_classification.sql`. It is outside
the frozen production apply package and was exercised only on `ghus_v2_test`.

## 3. Classification sequence

`agents/common/actor_classification.py` performs the required sequence:

1. detect actor, person, or event;
2. stop immediately for a person or event;
3. select one category from official self-description and main-job evidence;
4. apply deterministic hard rules;
5. construct a tool schema containing only types belonging to that category;
6. select one scalar type;
7. validate the pair, note, evidence, and review requirement;
8. pass the validated scalar payload to deterministic promotion.

The category prompt and schema explicitly prohibit using funder, sector, fame,
organization age, or intended GHUS use as substitutes for self-description and
main-job evidence. Model calls occur during extraction, never during routing or
promotion.

## 4. Hard rules

- **People/events:** record-kind detection stops before actor-category or type
  calls. Event participants that lack an official self-description are held for
  classification review instead of becoming actor stubs.
- **Medical schools:** always become
  `university_academic/college_school`, even if a model proposes a hospital.
- **National laboratories/federal facilities:** `national_laboratory` requires
  an evidenced formal designation, FFRDC status, or federal research facility
  with a national mission. Positive designation evidence forces this category.
  Federal funding alone falls back to `research_center` with doubt and a note.
- **Startups:** published organization development stage, never age, controls
  startup classification. Positive stage evidence forces `startup`; its type
  is the evidenced university, corporate, or independent origin. Missing stage
  falls back to `company` with review; missing origin uses `other` with a note.
- **Utilities:** public ownership forces `government/public_utility`;
  investor-owned utilities force `company` and then a company-scoped type.
- **Other/doubt:** `other` or any doubtful result requires a nonempty one-line
  note and review. Invalid cross-category type assignment raises before any
  canonical SQL is emitted.

## 5. Discovery, routing, promotion, and writer boundary

The production actor discovery entry points enable the ordered classifier. The
legacy raw `actor_type` extraction field remains only as a temporary input/test
compatibility value while the physical column exists; it is not used to derive
the V2 category/type pair. Query generation reads the V2 category reference
data first and falls back to legacy values only when the additive schema is not
available.

`map_new_actor` validates V2 classifications before actor insertion, records
the category and type steps in order, writes `actor_category`, `category_type`,
`category_note`, and `category_needs_review`, and stores the classification
evidence in the fact ledger. It does not copy `actor_type` into the V2 fields.
Normalization now preserves nested structured evidence so dry-run and live
candidates remain identical.

The two historical direct flat-type mutation entry points now fail loudly:

- `scripts/run_actor_type_enrichement.py`;
- `src/enrichment/reclassify_others_actors.py`.

They cannot write canonical actors. Accepted category/type changes continue to
flow through `promote.py`/`decisions.py`.

## 6. Temporary `category_doubt` compatibility bridge

The current production-compatible `review_item` CHECK does not admit the
canonical `category_doubt` kind. Phase 5 therefore writes:

- `review_kind='classification'`;
- `payload.issue='category_doubt'`;
- `payload.compatibility_bridge=true`;
- `payload.canonical_review_kind='category_doubt'`.

This is explicitly temporary, not the final Architecture V2 representation.
The exact breaking proposal is
`migrations/proposed/deferred/370_v2_category_doubt_review_kind.sql`, with an
exact rollback beside it. After owner approval of the breaking review-kind
release, it expands the CHECK to admit both `verify_actor` and
`category_doubt`, then converts only marked bridge rows to the canonical kind.

## 7. Final actor-table enforcement deferred intact

Application validation now guarantees one scalar category, one scalar type,
a valid category/type pair, and the `other` note. The final database enforcement
is proposed in `migrations/proposed/deferred/380_v2_actor_classification_cutover.sql`:

- composite foreign key `(actor_category, category_type)`;
- nonempty category and type CHECK;
- nonempty `category_note` when `category_type='other'`.

All constraints are proposed `NOT VALID`. They depend on the Phase 12 existing-
data backfill and Phase 16 coordinated cutover; none was applied in Phase 5.

## 8. Aggregate exclusion and frontend/RAG compatibility

Entity-resolution refresh and affiliation lookup now dual-read category/type
state while preserving the `aggregate` exclusion. Browse and RAG assembly read
`actor_category` first, fall back to the physical `actor_type` column during
transition, and include category type. The active React browse UI displays and
filters by the V2 category while accepting the temporary response alias.

Agent 3 keeps its existing `actor_type` payload/view contract. No file in
`src/map_agent/` changed.

## 9. Remaining `actor_type` dependencies

Every remaining runtime dependency is intentional and is grouped below.

### Physical schema, migration, and compatibility contracts — remove in P16

- `src/db/models.py`, `migrations/versions/890c436ee256_initial_v1_schema.py`:
  current physical legacy schema.
- `migrations/proposed/versions/v2a01_actor_identity.py`:
  deferred physical cutover definition.
- `src/db/models_v2.py`, `tests/db/test_architecture_v2_schema.py`:
  final V2 contract and the two intentionally failing removal gates.
- `agents/sql/340_v2_compatibility_views.sql`:
  frozen Agent 3/legacy alias proposal; unchanged.

### Active discovery transition contracts — remove with coordinated P12/P16 cutover

- `agents/discovery/extractors/actor.py`,
  `agents/discovery/search/actor_scoring.py`,
  `agents/discovery/search/models.py`,
  `agents/discovery/search/phase2.py`,
  `agents/discovery/search/query_generation.py`,
  `agents/discovery/search/run.py`, and
  `agents/discovery/search/triage.py`: legacy raw/result shapes and database
  fallbacks needed while old rows and tests coexist; V2 classification is the
  production category/type source.
- `agents/discovery/event_qualification.py`,
  `agents/discovery/extractors/event.py`,
  `agents/discovery/extractors/unga_guide.py`, and
  `agents/discovery/extractors/unga_programme.py`: legacy event-participant
  payload compatibility pending the Phase 14 people/events conversion.
- `agents/discovery/person_pages.py`: disabled person-discovery query keeps the
  physical aggregate exclusion until P14/P16.
- `agents/common/resolve_route.py` and
  `src/ML/entity_resolution/resolve_or_create.py`: explicit dual-read aggregate
  exclusion during transition.

### Existing-data and enrichment paths — migrate in P9–P12, then remove in P16

- `agents/enrichment/specs.py`,
  `src/enrichment/actor_enrichment_candidates.py`, and
  `src/enrichment/extractors/actor_type.py`: legacy enrichment input/extractor;
  no longer used by Phase 5 canonical classification writers.
- `src/etl/translators/hub_actor_extractor.py`,
  `src/etl/translators/nutricrops.py`, and
  `src/etl/translators/un_mapping.py`: historical import mapping retained for
  the Phase 12 dry-run existing-data migration.
- `scripts/actor_enrichment_maintenance/actor_funding_summary_fill.py`,
  `actor_quality_claude_refine.py`, `actor_technical_claude_refine.py`,
  `actor_technical_fill.py`, `actor_technical_sonnet_refine.py`,
  `backfill_actor_profile_fact_evaluation.py`,
  `ghus_refresh_search_docs_from_actor.py`, and
  `ghus_template_phrase_cleanup.py`, plus `scripts/tag_gold_entity_class.py`:
  legacy maintenance/reporting inputs to be moved to current facts in P11/P12/P16.
- `scripts/apply_review_decisions.py` and
  `scripts/backfill_confirmed_merges.py`: staged-record field allowlists, not
  direct canonical actor writes; retained until staged payload cutover.
- `scripts/run_actor_type_enrichement.py` and
  `src/enrichment/reclassify_others_actors.py`: names/import contracts retained
  only to fail loudly; direct mutation is disabled.

### Tests and documentation contracts

- `tests/agent/test_agents_actor_rubric_pipeline.py`,
  `test_agents_discovery_phase1.py`, `test_agents_event_rubric_pipeline.py`,
  `test_agents_open_web_discovery.py`, and `test_agents_open_web_phase2.py`:
  regression coverage for the temporary raw/legacy compatibility boundary.
- `agents/README.md`: current operational documentation; final terminology
  cleanup is part of the coordinated cutover documentation update.

### Frontend/RAG repository

- `src/assemble.py`, `src/browse.py`, and `frontend/index.html`: explicit
  dual-read/response compatibility; V2 category is preferred now.
- `src/map_agent/discover.py`, `enrich.py`, `export.py`, and `select.py`:
  teammate-owned Agent 3 contract; intentionally untouched.
- `src/router.py`, `src/enrich/agent.py`, and `src/enrich/gaps.py`: legacy RAG/
  enrichment compatibility pending the P15/P16 coordinated deployment.
- `app.py`: legacy UI; project instructions prohibit adding new V2 behavior
  there, so it remains a compatibility consumer until retirement.

## 10. Isolated database proof

On local `ghus_v2_test` at `127.0.0.1:55432`, proposal 370 completed
`up → down → up` without error.

| Table | Before | After second up |
|---|---:|---:|
| `actor` | 965 | 965 |
| `hub` | 49 | 49 |
| `event` | 356 | 356 |
| `actor_category_definition` | 12 | 12 |
| `actor_category_type_definition` | 65 | 65 |

After the second up, there were exactly 12 `is_other` rows and zero null
definitions. Both backend and frontend package read-only smokes passed with 965
actors.

## 11. Validation

- Backend full suite without live schema contracts: **347 passed, 5 skipped**.
- Backend full suite against `ghus_v2_test`: **349 passed, 3 failed** with 2
  inherited SQLite datetime-adapter warnings.
- Focused Phase 3/4/5 and schema regression set: **242 passed, 5 skipped**.
- Phase 5 classifier tests: **21 passed**.
- Backend Ruff on all changed Python files: passed.
- Frontend Python suite: **56 passed** with 1 inherited Starlette/AnyIO warning.
- Frontend Node hub/map regression suite: **15 passed** with the required
  `--experimental-vm-modules` runtime flag.
- Backend and frontend read-only database smokes: passed, 965 actors.

The three live failures are the unchanged, approved schema gates:

1. `test_isolated_database_contains_v2_schema`: physical `actor_type` and
   `verification_status` remain until Phase 16.
2. `test_orm_columns_match_isolated_v2_database`: the same two physical columns
   intentionally differ from the final V2-only ORM.
3. `test_phase3_record_creation_dry_run_executes_then_rolls_back`: the existing
   `review_item` CHECK still rejects `verify_actor`; changing it remains a
   deferred breaking migration.

No test was skipped, xfailed, weakened, deleted, or rewritten to hide these
gates.

## 12. Stop and deferred work

Phase 5 is complete. The following remain intentionally deferred:

- Phase 8 network/location conversion for former aggregate/network data;
- Phase 9/10 light/deep category-specific collection;
- Phase 11 current-fact maintenance migration;
- Phase 12 existing-row category/type backfill and validation report;
- owner-approved breaking review-kind migration for `verify_actor` and
  canonical `category_doubt`;
- Phase 16 physical legacy-column cutover and retirement of all compatibility
  aliases;
- Phase 17 final acceptance.

Phase 6 was not started.
