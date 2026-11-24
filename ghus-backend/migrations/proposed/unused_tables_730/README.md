# Migration 730: remove two unused tables

Status: **ready, not applied.** Platform owner's decision of 24 Nov 2026.

| Removed | Why it can go |
|---|---|
| `organization_ranking` (`actor_ranking` before 720), its stand-in view `actor_ranking` and its guard function `ghus_guard_ranking_is_university` | University rankings, planned in June and never filled (0 rows). Nothing points to it; no code writes to it. |
| `query_log` | Telemetry of the July Ask prototype; nothing writes to it any more (7 old rows in the 5 Nov backup; they go with it, the backup keeps them). |

Kept on purpose: `challenge` (holds the NutriCrops challenge; `organization_relevance`
points to it with 130 rows; the enrichment and Ask's database questions read it) and
`strategic_document` (for strategy documents attached for personalization).

**No code change is needed.** The deletion clean-up (`PURGE_POLICY`) still lists
`actor_ranking`: it skips a table that does not exist, and keeping the entry lets it
work unchanged on test databases that still have the table. The ORM models of the two
tables describe the older schemas and stay.

| | File |
|---|---|
| Migration | `../deferred/730_remove_unused_tables.sql` (SHA-256 in `ledger.sql`) |
| Rollback | `../deferred/rollback/730_remove_unused_tables.sql` |

## Rehearsal (24 Nov 2026)

On a throwaway copy of `ghus_phase7_prodcopy_test` (the 5 Nov 2026 Supabase backup with
700 and 710) with 720 applied:

- preflight: every row true; apply 730; ledger; verify: 7 of 7 true; a second apply
  refuses ("730 is already applied");
- rollback, then the whole `public` schema (`pg_dump --schema-only`) is identical to
  the copy before 730 (0 lines differ); apply again: the tables are gone;
- with 730 applied: the Directory loads (743 organizations, 48 hubs, 357 events,
  7 people); deleting an organization, the purge check and restoring it work, and the
  deletion policy finds no uncovered link (all in a transaction rolled back).

## Apply sequence (Supabase SQL editor; one script per run; a quiet window)

1. No Discovery or Update run in progress; fresh backup with `pg_dump` to
   `C:\Users\Ismail\GHUS-data\backups`.
2. `preflight.sql` — every row `ok = true`. Stop otherwise (the migration would refuse
   anyway, changing nothing).
3. `../deferred/730_remove_unused_tables.sql` — one transaction.
4. `ledger.sql`.
5. `verify.sql` — every row `ok = true`.

No deploy is needed.

## Rollback

`../deferred/rollback/730_remove_unused_tables.sql`, then
`DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '730';`.
`query_log` comes back empty (its rows are in the backup). Roll 730 back before 720.
