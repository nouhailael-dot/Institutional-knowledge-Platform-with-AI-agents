# Architecture V2 additive apply preparation report

**Date:** 2026-09-28

**Scope:** original logical migrations 001–016 only

**Shared database action:** none; production access was read-only except for `pg_dump`

## Outcome

The original 16 migrations were classified and every mixed migration was split. The executable manifest contains only additive operations. It preserves all legacy columns and existing application contracts, including `actor.actor_type` and `actor.verification_status`, and excludes all deferred breaking operations.

The package was proved on the isolated local PostgreSQL database `ghus_v2_test` in the required order: fresh production-data copy, first apply, unchanged tests and read-only smokes, exact rollback, and second apply. Schema apply/rollback behavior and row preservation passed. The unchanged frontend suites passed. Four unchanged Phase 3 backend tests failed because they intentionally assert schema elements outside this original-16 additive scope; this is a deployment gate described below.

## Classification

| Logical migration | Result | Package decision |
|---|---|---|
| 001 / 190 reference data | ADDITIVE | Included. |
| 002 / v2a01 + 200 actor identity/location | MIXED, SPLIT | Nullable compatibility columns, synchronization trigger, indexes, and new location table included. Renames, drops, requiredness, and legacy-table constraints deferred. |
| 003 / 210 topics | ADDITIVE | Included. |
| 004 / v2a02 + 220 hubs | MIXED, SPLIT | Nullable columns, indexes, and new center-review table included. Requiredness and legacy-table constraints deferred. |
| 005 / 230 verification history | ADDITIVE | Included. |
| 006 / 240 fact ledger | ADDITIVE | Included. |
| 007 / 250 sourced edges | ADDITIVE | Included. |
| 008 / 260 collection runs | ADDITIVE | Included. |
| 009 / 270 rankings | ADDITIVE | Included. |
| 010 / v2a03 + 280 people | MIXED, SPLIT | Nullable compatibility columns, synchronization trigger, and new privacy/topic tables included. Rename, requiredness, and legacy-table constraints deferred. |
| 011 / v2a04 + 290 events | MIXED, SPLIT | Nullable columns and new evidence/topic tables included. Requiredness and legacy-table constraints deferred. |
| 012 / 300 strategic connections | ADDITIVE | Included. |
| 013 / 310 hub proposals | MIXED, DEFERRED ENTIRELY | Not executable because production lacks the required `proposed_hub` root introduced by migration 180. |
| 014 / 320 review items | ADDITIVE | Included. |
| 015 / 330 guards/audit | MIXED, SPLIT | New audit objects and new-table-only RLS included. All permission changes on legacy tables deferred. |
| 016 / 340 compatibility views | MIXED, REWRITTEN | Legacy-safe views included. Final renamed-column definitions deferred. |

The complete rationale and later breaking order are in `classification.md`. Migration 017/350 is Phase 3 work and is outside the requested original 16.

## Prepared apply and rollback package

`manifest.json` is the single ordered source for 15 executable logical migrations: 001–012 and 014–016. It combines four additive Alembic revisions with SQL files numbered 190–340. The runner applies each transactionally and rolls back through matching down actions in exact reverse order.

Shared-target safeguards require both:

1. a schema-owner approval file containing `SCHEMA_OWNER_APPROVED_ADDITIVE_V2`; and
2. a verified full-backup manifest whose SHA-256 matches the dump.

The PowerShell apply wrapper performs the backup, before snapshot, ordered apply, row-count comparison, new-object inventory, and both read-only smoke checks. The rollback wrapper performs schema rollback only. It never restores the Supabase project.

## Production backup prepared read-only

- Full custom-format dump: `C:\Users\Ismail\GHUS-data\backups\ghus_production_full_20260928T170256Z.dump`
- Manifest: `C:\Users\Ismail\GHUS-data\backups\ghus_production_full_20260928T170256Z.dump.manifest.json`
- Size: 42,063,995 bytes
- SHA-256: `08d9ce68efae470f553cb4d8b0324c0c570f7037450d8af38b5a43da07bf424b`
- `pg_dump` client: PostgreSQL 17.5
- Supabase production server: PostgreSQL 17.6

This is evidence and a load source only. The apply wrapper deliberately takes another dated full dump immediately before a future approved shared apply so the safety copy cannot be stale.

## Isolated proof on `ghus_v2_test`

### Fresh production-data copy

The local test database was reset and loaded from the dated full production dump. The local server is PostgreSQL 17.5. Supabase-only extension ownership was not reproduced locally. The only public application object excluded was `public.search_doc` and its dependants because the local server does not have the `vector` extension; the source dump itself remains complete.

Key baseline row counts were:

| Table | Before | After second apply |
|---|---:|---:|
| actor | 965 | 965 |
| hub | 49 | 49 |
| hub_actor | 821 | 821 |
| event | 356 | 356 |
| person | 0 | 0 |
| staged_record | 7,286 | 7,286 |
| review_queue | 280 | 280 |
| event_review_queue | 9 | 9 |
| person_review_queue | 0 | 0 |

The automated comparison covered every pre-existing public base table, not only the key rows above. Result: no changed existing-table row counts after either apply.

### Apply → test → rollback → apply

1. **First apply:** all 15 manifest entries succeeded.
2. **Legacy-write compatibility probe:** writing legacy `actor_type` and `verification_status` populated the corresponding V2 compatibility columns; the probe transaction was rolled back.
3. **Read-only smokes:** backend passed (`actors=965`); frontend passed (`actors=965`).
4. **Frontend Python:** 54 passed, 1 warning.
5. **Frontend Node:** 15 passed.
6. **Backend:** 298 passed, 4 failed, 2 warnings. No test was skipped, xfailed, or rewritten.
7. **Rollback:** all 15 manifest entries succeeded in reverse order. Exact snapshot comparison reported `row_counts_equal=true`, `objects_equal=true`, and no expected-only or actual-only objects.
8. **Second apply:** all 15 manifest entries succeeded.
9. **Second post-check:** all pre-existing row counts unchanged; both read-only smokes passed again.

### Unchanged backend failures and deployment gate

The four failures are scope/contract mismatches, not apply or rollback failures:

1. `test_isolated_database_contains_v2_schema` expects the migration-310 proposal tables, but 310 cannot run without the absent production `proposed_hub` prerequisite.
2. `test_orm_columns_match_isolated_v2_database` expects the completed V2 cutover to have removed legacy `actor_type` and `verification_status`; this package is required to preserve them.
3. `test_reference_seed_counts` expects seven source origins; the original 16 define four, while the other three are in excluded Phase 3 migration 017/350.
4. `test_phase3_record_creation_dry_run_executes_then_rolls_back` requires the `verify_actor` review kind from excluded migration 017/350.

Therefore the additive schema package is compatible with the legacy production application, but the current Phase 3 backend must **not** be deployed with only this package. Keep the existing application deployed, or separately approve and prove an additive 017/350 package plus a compatibility contract before deploying Phase 3 code. The tests were left unchanged as requested.

## New objects after the second apply

- 26 tables: `actor_category_definition`, `actor_category_type_definition`, `actor_fact`, `actor_location`, `actor_ranking`, `actor_strategic_connection_check`, `actor_topic`, `canonical_write_audit`, `collection_request`, `collection_run`, `contact_collection_authorization`, `entity_edge`, `event_claim`, `event_topic`, `fact_resolution`, `fetched_document`, `hub_center_review`, `person_topic`, `record_verification`, `region_definition`, `region_state`, `review_item`, `review_item_decision`, `source_origin_definition`, `strategic_entity`, `topic`.
- 5 views: `actor_descendant_edge`, `actor_fact_current`, `actor_profile_current`, `actor_v1_compat`, `staged_record_agent3_compat`.
- 3 functions, 59 indexes (including implicit constraint indexes on new tables), 2 policies on the new `record_verification` table, and 12 triggers.
- 315 new inventory entries under columns, including columns belonging to new tables/views and nullable additions to existing tables.

The machine-readable before, after, and rollback comparisons are retained in `evidence/`.

## Deferred breaking order

1. P5 classifier deployment and P12 backfill/validation: actor category/type and status constraints.
2. P6 hub deployment and P12 backfill/validation: hub/member constraints and requiredness.
3. P7 detector plus P15 review workflow: create/migrate the proposal root before migration 310 constraints and indexes.
4. P11 immutable resolution and P12 backfills: validate actor/status/source constraints.
5. P14 people/events deployment and P12 validation: person/event constraints and requiredness.
6. P15 caller cutover and role audit: RLS/grant/revoke changes on legacy tables.
7. P16 reader cutover: final compatibility views, then legacy-column rename/drop only after compatibility telemetry is clean.

## Validation of the package itself

- Python package scripts and additive Alembic files: `py_compile` passed.
- Ruff E9/F/I checks: passed.
- PowerShell parser validation: passed.
- Generated `__pycache__` directories: removed.
- Shared production DDL/writes: none.

## Security note

During preparation, a failed read-only helper exposed the configured production database credential in local tool output. No database operation occurred in that failed attempt, and the credential is not stored in this package. Treat it as compromised and rotate it before running any approved apply.
