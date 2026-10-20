# Architecture V2 additive 180–350 proof report

Date: 2026-09-29 UTC

Backend repo: `C:\Users\Ismail\Projects\GHUS-Platform`, branch `codex/architecture-v2`

Frontend repo: `C:\Users\Ismail\Projects\Institutional-knowledge-Platform`, branch `codex/architecture-v2`

## Outcome

The additive package now covers every `agents/sql` file 180–350, plus the only additive production drift found in 010–170. It passed fresh local restore → apply → both read-only smokes and both repositories' suites → exact rollback → reapply. No shared database DDL or write occurred.

The package is **not authorized for production yet**. Password rotation and schema-owner approval have not been confirmed in this task. The shared preflight must stop until both are confirmed and an immediate fresh dump verifies.

## Production drift and file 180 prerequisites

The local test database was recreated from the most recent verified production dump, `ghus_production_full_20260928T170256Z.dump` (SHA-256 `08d9ce68efae470f553cb4d8b0324c0c570f7037450d8af38b5a43da07bf424b`). `search_doc` was omitted because local PostgreSQL lacks the production vector extension; it is unrelated to migrations 170–350.

All file-180 dependencies exist in production: `search_candidate`, `event_review_queue`, and `person_review_queue`, including the columns used by 180. Objects from 010–160 and their expected indexes are present. File 170 differs:

- missing `person_discovery_profile.affiliation_raw`;
- missing `person_discovery_profile.needs_actor_enrichment`;
- missing `person_review_queue.affiliation_raw`;
- consequently missing `ix_person_discovery_profile_actor_enrichment`.

The executable repair adds the three columns as nullable plus the index. The original `DEFAULT false NOT NULL` is held in `deferred/170_person_affiliation_resolution_breaking.sql`.

## Apply contents and deferred contents

The ordered executable manifest is 170, 180, 190, 200, 210, 220, 230, 240, 250, 260, 270, 280, 290, 300, 310, 320, 330, 340, 350. Files 180, 200, 220, 280, 290, 310, 330, 340, and 350 are split. Full per-file classification and phase dependencies are in `classification.md`; concrete held statements/inventory are in `deferred/`.

Notable decisions:

- 180 creates `proposed_hub` and `review_admission_decision`, but adds only nullable columns to legacy queues. Existing queue CHECK replacements and review-status requiredness are deferred.
- 310 adds nullable root columns and the new member/decision tables. Root default/requiredness/FKs/CHECKs are deferred.
- 350 adds the three source-origin rows. Its existing `review_item` CHECK replacement is deferred because the request classifies a new constraint on an existing table as breaking.
- 340 remains a legacy-safe compatibility view set. `actor_type` and `verification_status` are not renamed or dropped.

## Real-data proof

Database identity: `ghus_v2_test` at `127.0.0.1:55432`, PostgreSQL 17, local role `ghus_test`. Credentials were supplied through `PGPASSFILE`; no credential-bearing URL was printed or accepted by package helpers.

Existing-table row counts were unchanged after both applies. Representative production-copy counts:

| Table | Before | After first apply | After reapply |
|---|---:|---:|---:|
| actor | 965 | 965 | 965 |
| hub | 49 | 49 | 49 |
| hub_actor | 821 | 821 | 821 |
| event | 356 | 356 | 356 |
| person | 0 | 0 | 0 |
| staged_record | 7,286 | 7,286 | 7,286 |
| review_queue | 280 | 280 | 280 |
| event_review_queue | 9 | 9 | 9 |
| person_review_queue | 0 | 0 | 0 |

The machine-readable post-check compares every pre-existing public table, not only this representative list, and reports `existing_table_row_counts_unchanged=true`. No new constraint was applied to a production-existing table, so there were no existing-row constraint violations. New-table constraints accepted the package and seed data with zero errors.

The apply created 30 tables, including `proposed_hub`, `proposed_hub_member`, `proposed_hub_decision`, `review_admission_decision`, and the V2 ledger/review/reference tables. The complete new-object inventory is in `evidence/extended_after_second_apply.json`.

Rollback ran all 19 logical steps in exact reverse order. `evidence/extended_rollback_comparison.json` reports `row_counts_equal=true` and `objects_equal=true`. Reapply then completed all 19 steps and both read-only smokes passed again.

## Legacy-write and status proof

The proof used the same legacy actor INSERT/UPDATE column shape for all 30 stored `actor_type` values (including null) plus one unknown value: 31 inserts and 31 updates in a transaction, zero errors, then rollback. Unmapped actor types remained `actor_category=NULL`; actor count stayed 965.

The status probe covered every production value (`NULL`, `ai_inferred`, `needs_review`, `phase_1`) plus `verified`, `rejected`, and an unknown value. Mapping results were restricted to `imported`, `parked`, or null; `verified_or_rejected_mapping_count=0`.

## Tests

- Backend full suite against the final repository package: **303 passed, 3 failed, 2 warnings**.
- Frontend Python: **54 passed, 15 subtests passed, 1 warning**.
- Frontend Node: **15 passed** (6 hub matching + 9 map UI).
- Backend and frontend package read-only smokes: **passed** after first apply and reapply.
- Exact rollback comparison: **passed**.

The first backend invocation used the repository interpreter with a `psycopg` URL although that environment contains `psycopg2`; its five live tests failed during driver setup. It was rerun with the installed `psycopg2` dialect, password-free URL, and `PGPASSFILE`; after the final package-safety tests were added, the authoritative result was 303/3. The map UI Node harness likewise required its documented `--experimental-vm-modules` flag; with that flag all tests passed. These were test-launch corrections, not product failures.

## The four schema-gate tests

Of the four previously failing schema-gate tests, one now passes and three fail:

1. `test_isolated_database_contains_v2_schema` — still fails because the test demands that `actor_type` be absent; the additive contract requires it to remain.
2. `test_orm_columns_match_isolated_v2_database` — still fails because `V2Base` models the final schema without `actor_type`/`verification_status`, while this package intentionally retains both.
3. `test_reference_seed_counts` — now passes; file 350's three additive origins bring the count to seven.
4. `test_phase3_record_creation_dry_run_executes_then_rolls_back` — still fails at the final `verify_actor` insert because the existing `review_item_review_kind_check` excludes that kind. Replacing it is deferred breaking work from 350.

The two inherited V2 routing tests continue to pass without skip/xfail: `test_dry_run_checks_mapped_records_before_discovery_and_exact_event_absorbs` and `test_out_of_sector_record_is_staged_and_never_promoted`.

## Phase 3 runtime compatibility and schema gate

Mapped-first resolution, exact website/name/alternate-name append, rejected-sighting preservation, close-match `possible_duplicate`, classification, geocoding, parent/connection, hub fit, light pull, and creation of a Parked actor all execute in unit tests with legacy `actor_type` present. Exact-match and possible-duplicate paths do not require the deferred 350 change.

The complete new-actor transaction cannot commit: its required final `verify_actor` review item is rejected by the unchanged existing CHECK. The dry-run reaches that statement and then rolls back. Therefore the Phase 3 runtime is **not deployable** against the additive-only schema, and the schema gate was not relaxed or marked met. The exact unblock is to deploy deferred 350 and Phase 3 code together after approval; the P16 legacy-column tests remain gated on final cutover.

## Production preconditions

| Precondition | Result |
|---|---|
| Password rotation confirmed complete | **UNMET / not confirmed** |
| PGPASSFILE-only helpers; redacted errors | **MET** |
| Status mapping never yields `verified`/`rejected` | **MET**, dynamically proved |
| Schema-owner approval received | **UNMET / not confirmed** |
| Fresh apply-day dump and checksum | **PENDING**, wrapper-enforced |

Because two hard preconditions are unmet, no production backup/apply/post-check was started. Once the user confirms rotation and schema-owner approval, the authorized sequence remains: notify colleague → fresh verified dump → ordered apply with automatic rollback on first error → post-checks → stop and report; the user sends the change note.
