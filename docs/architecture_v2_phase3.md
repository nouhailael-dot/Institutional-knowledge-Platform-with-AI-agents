# Architecture V2 Phase 3 report

Date: 2026-09-28  
Phase: record creation pipeline (implementation prompt §3)  
Status: complete; stopped before Phase 4

## 1. Repositories and commits

- Backend: `C:\Users\Ismail\Projects\GHUS-Platform`, branch `codex/architecture-v2`.
  - Implementation commit: `030d630` (`feat: implement architecture v2 record creation`).
  - The documentation commit containing this report is listed in the final handoff.
- Frontend: `C:\Users\Ismail\Projects\Institutional-knowledge-Platform`, branch `codex/architecture-v2`, unchanged at `b1a1c77`.
  - No frontend code changed in Phase 3. The approved ownership plan assigns canonical/data phases 2–14 to the backend and UI/RAG integration to phases 15–16. The current Ask and Explore routes read the database and do not trigger web discovery; the universal Build-the-Map/RAG mapped-first service remains R003/P16. Layer 3 specific asks do not yet exist and remain P10.
  - Pre-existing untracked `.demo/`, `.review/`, and `exit` were preserved untouched.

## 2. Phase 2 carryovers closed

### 2.1 Hub count: 48 versus 49

The difference is one production row:

- name: `Mining Hubs`
- hub ID: `663e5dcd-7c09-435e-bc04-a1d30326c217`
- status: `phase_1`
- location: none
- memberships: 0

The earlier Phase 0 export contained the 48 historical names; the 2026-09-24 baseline contains those 48 plus `Mining Hubs`. The gap analysis and its Phase 1 hub table now cover all 49 exactly as exported. All 49 remain informational, none was demoted, and GHUS memberships remain authoritative even when a later distance calculation is over 200 miles.

### 2.2 Real-data migration evidence

The requested evidence is in `docs/architecture_v2_phase2.md`, §5, lines 162–204. It records the production-copy before/after counts and violations:

| Dataset | Before | After final up |
|---|---:|---:|
| actor | 965 | 965 |
| hub | 49 | 49 |
| hub_actor | 821 | 821 |
| event | 356 | 356 |
| staged_record | 7,257 | 7,257 |
| review_queue | 280 | 280 |
| event_review_queue | 9 | 9 |
| person_review_queue | 0 | 0 |

All 16 Phase 2 proposals completed up → down → up on the production copy. The populated-row findings were: 965 intentionally tolerated `ck_actor_record_status` violations (`ai_inferred` 834, `needs_review` 27, `phase_1` 97, null 7); actor-coordinate, hub-radius/center, hub-membership, and event status/date violations were all 0. The constraint remains `NOT VALID` pending the Phase 12 backfill.

Phase 3 proposal 017 (`350_v2_record_creation.sql`) was then exercised up → down → up on the same isolated database. The first attempt exposed a seed display-name collision (`Uploaded document`); the proposal was corrected to `GHUS uploaded document` and the complete cycle passed. Final proof: 3 new source-origin codes, the `verify_actor` review-kind constraint present and not validated, 965 actors preserved, and no test review rows left behind.

### 2.3 Baseline and isolated database relocation

- Baseline: `C:\Users\Ismail\GHUS-data\exports\architecture_v2_baseline_2026-09-24`
- Manifest: `C:\Users\Ismail\GHUS-data\exports\architecture_v2_baseline_2026-09-24\manifest.json`
- Isolated PostgreSQL data directory: `C:\Users\Ismail\GHUS-data\postgres\ghus-pg-v2`
- Manifest SHA-256: `61d1e834a8773b8db101c1e86bda091c617c1380f0cf28f3618c95cd027bbb31`

All eight CSV hashes in the manifest were rechecked after relocation and matched. The obsolete export and database paths under `C:\Users\Ismail\Documents\GHUS` do not exist. The manifest names this dated, read-only, repeatable-read snapshot as the origin for later `Imported` records.

### 2.4 Safety-blocked staging directories and git index

The external staging/test directories retained outside git are:

- `C:\Users\Ismail\Documents\GHUS\phase2-redo`
- `C:\Users\Ismail\Documents\GHUS\.pytest-tmp`

`git ls-files` returns no entries for `.pytest-phase2-final/**` or `.pytest-phase2-venv/**` on `codex/architecture-v2`. Local pytest scratch directories are not tracked.

### 2.5 Canonical-writer audit

- `agents/discovery/promote.py` is the actor creation/append boundary. The old mutable actor absorb helper was removed. Exact matches append a sighting fact/topic; they never rewrite actor scalars or status.
- `agents/enrichment/decisions.py` is the decision/compatibility boundary. Actor enrichment appends `actor_fact`; verification decisions append `record_verification`.
- `agents/review/admission.py` remains orchestration-only for canonical entities and delegates promotion.
- `scripts/apply_review_decisions.py` retains report/dry-run behavior, but its apply path now raises before a canonical write.
- `scripts/create_hierarchy_edges.py`, `scripts/actor_merge.py`, and the destructive merge smoke script have their former apply/delete paths retired.
- Legacy ER live create/absorb and legacy Streamlit status writes raise and direct callers to the approved writer services.
- Audited ETL/enrichment jobs no longer call `session.add` directly; they enter through `decisions.py`. Their conversion to staged V2 imports remains Phase 12.
- Static tests fail on canonical SQL outside `promote.py`/`decisions.py` and on canonical application `DELETE` statements.

Unrecoverable from current rows alone are prior actor/hub/event narrative, category/type, location, `source_id`, status, confidence, and `updated_at` values overwritten by earlier releases. Old threshold absorptions are report-only; nothing was automatically unmerged.

### 2.6 Recovery hold

No backup, PITR, recovery, or restore action was taken. If the schema owner later supplies a downloaded backup, the only permitted action remains loading it into a separate local comparison database—never restoring the Supabase project.

## 3. Record creation pipeline

`map_new_actor(staged, route, session, live)` now owns the staged-record → promote boundary. Its enforced trace is:

1. `mapped_first`
2. `category`
3. `category_type`
4. `geocode`
5. `parent_connection`
6. `hub_fit`
7. `light_pull`
8. `parked`
9. `verify_actor`

Phase 3 supplies the orchestration and persistence boundary; the category classifier, deterministic gazetteer, link graph, hub algorithms, and bounded Light collector are implemented in their prescribed later phases. The pipeline accepts their staged results in the required order and rejects an out-of-order transition.

Routing behavior:

- A unique exact normalized website-domain match reuses the actor.
- A unique exact normalized name or alternate-name match reuses the actor.
- Exact reuse appends an immutable discovery-sighting fact and topic link; no new actor is created.
- An exact Rejected match stays Rejected and receives the sighting.
- Multiple exact candidates or any non-exact similarity match create a `possible_duplicate` review item only. Even a model score above the former absorb threshold cannot merge.
- Exact actors found through a newly discovered event domain still append; the former discovered-domain override was removed. Non-exact discovered-domain matches remain review-only.
- A genuinely new actor is created with `record_status=parked`, `source_origin=claude_discovered`, Light facts/topic/hub assignments, and a `verify_actor` review item.

Dry-run remains the default. It executes the same SQL path inside a transaction and rolls back; live execution still requires explicit dispatch. Person discovery remains disabled.

## 4. Migration proposal 017

Added, but never applied to shared Supabase:

- `agents/sql/350_v2_record_creation.sql`
- `agents/sql/rollback/350_v2_record_creation.sql`
- logical ID `017` in `migrations/proposed/manifest.json`

It adds the three required actor source origins (`imported_phase1`, `claude_discovered`, `ghus_uploaded_doc`) and extends the review-kind constraint with `verify_actor`. The populated-table check is `NOT VALID`. The rollback refuses to discard live `verify_actor` history.

## 5. Tests and verification

### Backend

- Full suite against local `ghus_v2_test` at `127.0.0.1:55432`: **302 passed**, 2 SQLite datetime-adapter deprecation warnings.
- The two inherited routing tests were rewritten to V2 behavior; neither is skipped or xfailed.
- New regression coverage includes exact domain/name/alternate-name reuse, Rejected sightings, non-exact high-score review, discovered-domain exact reuse, strict pipeline order, real PostgreSQL dry-run rollback, writer allowlist, and no canonical application DELETE.
- Targeted Ruff (`E9,F,I`) over every Phase 3 Python file: passed.
- Repository-wide Ruff: 684 findings, all pre-existing/general debt; the exact parent commit had 721. No unrelated mass rewrite was performed.
- `git diff --check`: passed.

The backend environment declares `psycopg2`, while the live SQLAlchemy tests use the `psycopg` dialect. The successful run used the backend virtual environment with the sibling environment's already-installed `psycopg` package appended to `sys.path`; no package was installed and neither environment was modified.

### Frontend

- Python suite in the frontend `.venv`: **54 passed**, 1 Starlette/AnyIO deprecation warning.
- Node suite with the repository-documented experimental VM-modules flag: **15 passed**.
- No frontend linter is configured.

## 6. Deviations and pending work

1. The universal frontend RAG/Build-the-Map mapped-first service is not implemented in this backend-owned phase. It remains the documented R003/P16 integration. Current Ask and Explore are database-only; Layer 3 specific asks remain P10. No current backend actor-creation path is exempt from mapped-first routing.
2. Phase 3 orchestrates the strict later-phase steps but does not implement Phase 4 geography, Phase 5 classification, Phase 6 hub assignment logic, Phase 8 link inference, or Phase 9 Light collection ahead of order.
3. Legacy importers now cross the approved `decisions.py` gateway, but conversion of their canonical-shaped records into staged V2 import records is intentionally deferred to Phase 12.
4. Full-repository Ruff remains red from inherited debt; every Phase 3 Python file is clean under the selected error/import rules.
5. No shared-database write, DDL, backup, PITR, restore, unmerge, hub demotion, or membership change occurred.

## 7. Stop gate

Phase 3 is complete. Phase 4 has not started and requires GHUS approval.
