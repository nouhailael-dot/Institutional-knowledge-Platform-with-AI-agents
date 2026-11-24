# Migration 750: remove the tables Compass no longer uses

Numbered 750 because 730 (organization template) and 740 (event fields) were applied to
Supabase on 24 Nov 2026 by Nouhaila.

Status: **ready, not applied.** Platform owner's decision of 24 Nov 2026.

| Removed | Rows (24 Nov) | Why |
|---|---|---|
| `organization_ranking`, its stand-in view `actor_ranking` and its guard function | 0 | University rankings, planned in June, never filled. |
| `organization_evaluation` and its stand-in view `actor_evaluation` | 158 | Old Phase 1 evaluations; nothing reads them. |
| `event_scoring` | 87 | Old Phase 1 event scores; nothing reads them. |
| `fetched_document` | 0 | An earlier design for fetched pages; `raw_document` replaced it. |
| `canonical_write_audit` | 0 | A planned write log; nothing ever filled it. |
| `contact_collection_authorization` | 0 | Contact collection was never built. |
| `query_log` | 7 | Telemetry of the July Ask prototype; nothing writes to it. |
| `compass.migration_snapshot` | 256 | Definitions saved for rolling back 710 and 720. Its rows are kept in `restore_migration_snapshot.sql`, so those rollbacks stay possible. |

Kept on purpose: `challenge` (the NutriCrops challenge; `organization_relevance` points to
it), `strategic_document`, `strategic_entity` and `organization_strategic_connection_check`
(planned: personalization and the UM6P/OCP connection check).

The rows of `organization_evaluation`, `event_scoring` and `query_log` go with them; the
backup taken before applying keeps them. **No code change is needed**: every reader skips a
table that does not exist (the deletion clean-up's `PURGE_POLICY` included).

| | File |
|---|---|
| Migration | `../deferred/750_remove_unused_tables.sql` (SHA-256 in `ledger.sql`) |
| Rollback | `../deferred/rollback/750_remove_unused_tables.sql` (taken with `pg_dump --schema-only` from Supabase on 24 Nov) |
| Snapshot rows | `restore_migration_snapshot.sql` (the 256 rows, read from Supabase on 24 Nov) |

## Rehearsal (24 Nov 2026)

On a throwaway copy of `ghus_phase7_prodcopy_test` (the 5 Nov 2026 Supabase backup with
700 and 710) with 720 applied:

- preflight: every row true; apply 750; ledger; verify: 6 of 6 true; a second apply refuses;
- with 750 applied: the Directory loads (743 organizations, 48 hubs, 357 events, 7 people);
  deleting, checking the purge of and restoring an organization and an event work, and the
  deletion policy finds no uncovered link (in a transaction rolled back);
- rollback, then `restore_migration_snapshot.sql`: the schema is identical to before 750
  (0 structural lines differ; the rollback also restores Supabase's grants, which the local
  copy did not have), and 720's own rollback runs from the restored snapshot.

## Apply sequence (Supabase SQL editor; one script per run; a quiet window)

1. No Discovery or Update run in progress; fresh backup with `pg_dump` to
   `C:\Users\Ismail\GHUS-data\backups`.
2. `preflight.sql` — every row `ok = true`. Stop otherwise (the migration would refuse
   anyway, changing nothing).
3. `../deferred/750_remove_unused_tables.sql` — one transaction.
4. `ledger.sql`.
5. `verify.sql` — every row `ok = true`.

No deploy is needed.

## Rollback

1. `../deferred/rollback/750_remove_unused_tables.sql`
2. `restore_migration_snapshot.sql`
3. `DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '750';`

The three tables that had rows come back empty; their rows are in the backup. Roll 750 back
before rolling back 720 or 710.
