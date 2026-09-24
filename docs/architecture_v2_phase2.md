# Architecture V2 Phase 2 report

Date: 2026-09-24  
Status: Phase 2 complete; stopped before Phase 3.

## 1. Repository verification

The two authoritative working directories were printed and confirmed before edits:

- Backend: `C:\Users\Ismail\Projects\GHUS-Platform`
- Frontend: `C:\Users\Ismail\Projects\Institutional-knowledge-Platform`

The outdated draft at `C:\Users\Ismail\Documents\GHUS\GHUS-Platform-v2` was read only. It was never edited and no migration was run from it.

### Backend

- Remote: `https://github.com/Ismailsabbar/GHUS_Platform.git`
- Starting branch/commit: `main` at `392840a`
- Current branch: `codex/architecture-v2`
- A local or remote `codex/architecture-v2` branch did not exist at verification time.
- Main log at verification:
  - `392840a Merge review admission workflow`
  - `b99ce2f Qualification-capped event bands, domain collapse, fetch backfill, affiliation normalisation`
  - `23a00a0 Reconcile latest original agent changes`
  - `d2cb6a7 Add transactional human review admission workflow`
  - `2c2ae7c Update config test for max_searches 52`
  - `d351091 Raise max_searches to 52 so use-case actor queries execute`
  - `caa58c0 Raise weekly job limit to 90 min; fail fast on open-web fetches`
  - `54fc2d3 Raise max_new_domains from 10 to 40`
- Legacy Streamlit remains at `src/admin/app.py`; it is an operations/admin surface, not the active end-user frontend.
- There is no backend `assemble.py`. Retrieval/RAG ownership is in the frontend repository.

### Frontend

- Remote: `https://github.com/nouhailael-dot/Institutional-knowledge-Platform-with-AI-agents`
- Starting branch/commit: `main` at `8734605`
- Current branch: `codex/architecture-v2`
- A local or remote `codex/architecture-v2` branch did not exist at verification time.
- Main log at verification:
  - `8734605 ActorsPeople Connection`
  - `8228dbb feat(map): export a map to branded .xlsx / .pptx`
  - `6833b3f feat(map): "Build the Map" — conversational web-scouting agent`
  - `9816f3d fix(ui): simplify Ask page welcome description`
  - `32e87af feat(app): add event type filter + suppress verbose search explanations`
  - `4be5adf docs: refresh CHAT_HANDOFF.md for the React app + chatbot + enrichment scaffolding`
  - `6150606 feat(app): chatbot-style multi-turn Ask + Hubs search + Events date filter`
  - `0d50c3d feat(app): React + FastAPI UI over the RAG engine (Ask, Browse, doc upload)`
- Active framework: FastAPI in `backend/app.py`, serving a no-build React 19 + HTM interface from `frontend/index.html`.
- Screens/pages are in the single React module in `frontend/index.html` (Ask, Browse, Build the Map and related panels).
- API routes are in `backend/app.py`: upload, Ask streaming, actor/hub/event browse, map lifecycle/export, health, and root.
- Retrieval/RAG remains in `src/assemble.py`, `src/retrieve.py`, `src/embed.py`, and `src/router.py`.
- Database access is in `src/db.py`.
- Tests are Python `unittest` plus Node `.mjs` tests. No frontend lint configuration or package manifest exists.
- Root `app.py` is a frozen Streamlit reference. Current run instructions use `uvicorn backend.app:app`; no V2 feature work was added to Streamlit.
- A separate `review-workflow` branch exists at `dbe6097`; its review UI was inventoried but not merged because Step 7 prohibited V2 feature work.

### Old draft

- Remote: `https://github.com/Ismailsabbar/GHUS_Platform.git`
- Branch: detached at `a553ce6`
- It shares the backend Git common directory (`C:/Users/Ismail/Projects/GHUS-Platform/.git`) and therefore the same history.
- Log:
  - `a553ce6 feat: add architecture v2 proposed data model`
  - `fc0f1d5 docs: approve architecture v2 phase 0`
  - `392840a Merge review admission workflow`
  - `b99ce2f Qualification-capped event bands, domain collapse, fetch backfill, affiliation normalisation`
  - `23a00a0 Reconcile latest original agent changes`
  - `d2cb6a7 Add transactional human review admission workflow`
  - `2c2ae7c Update config test for max_searches 52`
  - `d351091 Raise max_searches to 52 so use-case actor queries execute`
- It formerly held `codex/architecture-v2`; detaching it freed that branch name for the authoritative backend checkout without changing draft files.

### Specification gate

`docs/architecture_v2_sept.md` is the updated specification. It contains §2.1 center/200-mile hub semantics, the §2.3 threshold of at least 10 Verified actors from at least 5 categories within 200 miles, and §3 actor category/category type with a Category types column.

## 2. Changes and commits

### Backend commits

| Commit | Change |
|---|---|
| `94ce777` | Removed tracked pytest temp artifacts, ignored `.pytest-*`, and added repository/phase safety rules. |
| `7174f45` | Committed the corrected spec and extended the gap analysis across both repositories, both migration tracks, existing building blocks, writer conflicts, hub proposal retirement, pending decisions, and unrecoverable history. |
| `c5bd169` | Added the detached Phase 2 proposals, V2-only ORM metadata, safe migration runner, config defaults, rollbacks, and contract tests. |
| `6c6ccc8` | Proved permission denial and append-only enforcement as separate layers. |
| `8e11420` | Added the no-DELETE privilege matrix for every canonical table and Supabase-equivalent role. |
| `2a7240b` | Recorded preliminary baseline provenance and corrected proposal filenames in the gap analysis. |
| `d58799b` | Made every Phase 2 Python artifact pass the complete configured Ruff rules. |
| `bbfa900` | Recorded the completed eight-table production baseline, counts, and final manifest hash. |

The supplied duplicate `architecture_v2_sept.md` at repository root remains an unrelated untracked file; the committed authoritative copy is under `docs/`.

### Frontend commit

| Commit | Change |
|---|---|
| `b1a1c77` | Added `AGENTS.md` with authoritative paths, old-draft prohibition, database safety, dry-run/person-discovery rules, naming exclusions, and phase stop/report requirements. |

Pre-existing untracked frontend paths `.demo/`, `.review/`, and `exit` were preserved untouched.

## 3. Migration set and ownership tracks

The exact order is machine-readable in `migrations/proposed/manifest.json`. Canonical-table changes are detached Alembic proposals with `down_revision = None`; they are outside `migrations/versions/`, are not imported by `migrations/env.py`, and require schema-owner rebasing/approval. Platform-owned changes are numbered SQL files under `agents/sql/` with matching rollback files under `agents/sql/rollback/`.

| Logical migration | Alembic proposal track | Platform-owned `agents/sql` track |
|---|---|---|
| 001 reference data | — | `190_v2_reference_data.sql` |
| 002 actor identity/location | `v2a01_actor_identity.py` | `200_v2_actor_location.sql` |
| 003 topics | — | `210_v2_topics.sql` |
| 004 hubs | `v2a02_hubs.py` | `220_v2_hub_center_review.sql` |
| 005 verification history | — | `230_v2_verification_history.sql` |
| 006 fact ledger | — | `240_v2_fact_ledger.sql` |
| 007 sourced edges | — | `250_v2_edges.sql` |
| 008 collection runs | — | `260_v2_collection_runs.sql` |
| 009 rankings | — | `270_v2_rankings.sql` |
| 010 people/privacy | `v2a03_people.py` | `280_v2_people_privacy.sql` |
| 011 events | `v2a04_events.py` | `290_v2_event_evidence.sql` |
| 012 strategic checks | — | `300_v2_strategic_connections.sql` |
| 013 hub proposals | — | `310_v2_hub_proposals.sql` |
| 014 review items | — | `320_v2_review_items.sql` |
| 015 guards/write audit | — | `330_v2_guards_and_audit.sql` |
| 016 compatibility views | — | `340_v2_compatibility_views.sql` |

All canonical constraints over populated tables are `NOT VALID`. Platform SQL contains no canonical-table `ALTER`. `V2Base` is separate from the legacy `Base`, and a static contract test fails if application/autogeneration code imports `models_v2`.

`proposed_hub` is extended in place. `proposed_hub_member` and `proposed_hub_decision` are children; there is no parallel `v2_hub_proposal` root. Existing identifiers, `review_admission` references, decisions, and memberships are preserved. The forbidden name `hub_overlap` is absent; the review kind is `same_topic_overlap`.

Config defaults remain pending GHUS confirmation: dry-run on, person discovery/contact collection off, 10 actors, 5 categories, 200-mile radius, 50-mile core, and 25-mile drift flag. `aggregate` remains excluded, and `desc_both_present` was not reintroduced.

## 4. Isolated database proof

Chosen environment: local PostgreSQL at `127.0.0.1:55432`, database `ghus_v2_test`, data directory `C:\Users\Ismail\Documents\GHUS\.ghus-pg-v2` (outside both repositories).

Build sequence:

1. Dropped and recreated only `ghus_v2_test`.
2. Created local `anon` and `authenticated` roles with `NOBYPASSRLS`, and `service_role` with `BYPASSRLS`.
3. Applied the real Alembic chain through `f6b9a8c7d2e1`.
4. Applied the existing platform SQL chain `010` through `180`.
5. Loaded all eight authorized production baseline datasets.
6. Applied all 16 logical proposals up → down → up.
7. Ran the live ORM, seed, RLS, append-only, and role-permission tests.

Permission results:

- `authenticated` cannot insert verification events.
- `service_role` may insert verification events but cannot update/delete them.
- The owner-level append-only trigger independently rejects verification mutation.
- `anon`, `authenticated`, and `service_role` have no DELETE privilege on `actor`, `hub`, `event`, `person`, or `hub_actor`.
- Agent roles cannot write GHUS-only actor/event status/notes or hub approval/freeze fields.

Version/extension comparison:

| Environment | PostgreSQL | Extensions observed |
|---|---|---|
| Shared Supabase, read-only inspection | 17.6 | `pg_stat_statements`, `pgcrypto`, `plpgsql`, `supabase_vault`, `uuid-ossp`, `vector` 0.8.0 |
| Local isolated test database | 17.5 | `plpgsql` only |

No shared DDL or write was attempted. The production inspection explicitly verified `transaction_read_only=on` before export queries.

## 5. Real-data results and baseline export

Baseline directory (outside repositories):

`C:\Users\Ismail\Documents\GHUS\exports\architecture_v2_baseline_2026-09-24`

Manifest:

`C:\Users\Ismail\Documents\GHUS\exports\architecture_v2_baseline_2026-09-24\manifest.json`

Manifest SHA-256: `bd046babba1ed12047701cc553b535fe5714b2a3c81bf18892b7ea1c57bbbf76`.

The manifest records each CSV hash and is the documented origin for every later `source_origin=Imported` row.

| Table | Before proposals | After final up | Result |
|---|---:|---:|---|
| `actor` | 965 | 965 | preserved |
| `hub` | 49 | 49 | preserved |
| `hub_actor` | 821 | 821 | preserved |
| `event` | 356 | 356 | preserved |
| `staged_record` | 7,257 | 7,257 | preserved |
| `review_queue` | 280 | 280 | preserved |
| `event_review_queue` | 9 | 9 | preserved |
| `person_review_queue` | 0 | 0 | preserved |

All 16 migrations completed up → down → up on these rows. The first local load exposed one genuine schema difference: local `event_review_queue` has a `notes` column absent from production. The failed isolated load was discarded by restarting from a truncate, then the export columns were mapped explicitly; the complete rerun passed.

Constraint/backfill findings:

- `ck_actor_record_status`: 965 violations, intentionally tolerated by `NOT VALID` pending Phase 12 backfill.
  - `ai_inferred`: 834
  - `needs_review`: 27
  - `phase_1`: 97
  - null: 7
- Actor coordinates: 0 violations.
- Hub radius and center coordinates: 0 violations.
- Hub membership assignment outcome: 0 violations.
- Event status, date status, and date ordering: 0 violations.
- Person rows were not part of the requested baseline export and the exported person review queue was empty; production person-constraint validation remains a schema-owner/full-copy check.

The current production snapshot has the historical 48 Phase 1 hub names plus `Mining Hubs`, for 49 rows. All remain as-is. No hub was demoted, membership was not changed, and future outside-200-mile flags are informational only.

Past actor/hub/event overwrites remain unrecoverable from current rows alone: overwritten `source_id`, status, confidence, `updated_at`, narrative, classification, and location values cannot be reconstructed reliably. Old threshold absorptions are report-only and must not be automatically unmerged.

## 6. Tests and lint

### Backend

- Static proposal contracts without a database: 8 passed, 4 skipped (live-only checks).
- Final live V2 schema/ORM/RLS/permission suite: 12 passed.
- Full suite: 290 passed, 2 failed, 2 warnings.
- The two failures are unchanged inherited discovery-routing tests:
  - `test_dry_run_discovery_routes_against_real_candidates`: expected `absorb`, received `create`.
  - `test_out_of_sector_record_is_staged_and_never_promoted`: expected one promotion, received zero.
- On the exact parent of draft commit `a553ce6`, commit `fc0f1d5`, the same two tests failed with the same assertions (2 failed). They were not skipped or xfailed and remain scheduled for V2 rule rewrites in Phase 3.
- All Phase 2 Python files pass complete `ruff check` and `ruff format --check`.
- Repository-wide Ruff remains pre-existing debt: 721 findings; format check reports 136 files would be reformatted. No broad mechanical rewrite was made in this phase.

### Frontend

- Python `unittest`: 54 passed.
- Node tests with the repository-documented `--experimental-vm-modules` flag: 15 passed.
- There is no configured frontend linter.
- Because a real test suite exists, the conditional Step 7 smoke-test addition was not triggered.

## 7. Canonical writer audit

Direct or indirect canonical writes outside the approved `promote.py` / `decisions.py` boundary were found in `scripts/apply_review_decisions.py`, `src/ML/entity_resolution/resolve_or_create.py`, `scripts/run_er_sweep.py`, admin status code, actor merge/hierarchy scripts, actor enrichment and maintenance scripts, researcher enrichment, ETL translators, and a merge smoke script. `agents/review/admission.py` delegates canonical writes to `promote.py` and only writes proposal/review tables.

The repair plan is recorded in `docs/architecture_v2_gap_analysis.md`: Phase 3/11/12/15 must route canonical creation and fact decisions through the two allowed modules and the immutable ledger, remove production DELETE paths, retain queue cleanup only for non-canonical queues, and preserve audit/history.

## 8. Deviations and reasons

1. A full public-schema production dump was not taken. It would exceed the requested export scope and include additional sensitive tables. The eight explicitly requested datasets were exported and loaded; therefore person and other dependency-table production rows were not tested locally.
2. The first attempt to stream the large staged-record CSV in one statement was terminated by the production connection. It did not update the manifest. The successful export used bounded 100-row COPY statements in one read-only repeatable-read snapshot and required an exact 7,257-row match before writing the manifest.
3. The first eight-table local import stopped on the production/local `event_review_queue.notes` difference. The isolated data was truncated, explicit exported-column mapping was added, and the full import plus up → down → up was restarted successfully.
4. The two discovery-routing tests remain red by instruction; their identical parent-commit failures are proven above. They were not weakened.
5. Repository-wide Ruff remains red because fixing hundreds of unrelated files would violate phase scope. Every Phase 2 Python file is fully clean.
6. No frontend smoke suite was added because the frontend already has Python and Node suites.
7. Production currently has 49 hub rows rather than the historical 48. The extra `Mining Hubs` row is reported only; no hub or membership was changed.

## 9. Open questions

1. Does the schema owner have Supabase backups or point-in-time recovery that could restore any overwritten actor, hub, or event history? No recovery will be attempted by agents.
2. Should `Mining Hubs` be formally classified as the post-Phase-1 49th hub, or handled under another owner-defined category? It remains untouched either way.
3. Please confirm or revise the config-backed defaults still marked pending GHUS confirmation in the gap analysis.

Phase 3 has not started.
