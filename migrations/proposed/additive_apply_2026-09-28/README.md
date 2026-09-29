# Architecture V2 additive apply package

Prepared 2026-09-28. This package is for the schema owner/user to run; agents must not run it on shared Supabase.

## Scope

- Covers original logical migrations 001–016.
- Applies the safe additive portions of 001–012 and 014–016.
- Excludes 013/310 because production does not contain its `proposed_hub` prerequisite.
- Excludes Phase 3 migration 017/350 because the request was limited to the original 16.
- Preserves all existing columns and legacy read/write behavior.

## Deployment gate

This schema package is compatible with the legacy production application. Do **not** deploy the current Phase 3 backend against only this original-16 package: its unchanged test contract also requires Phase 3 migration 017/350 (`verify_actor` and three additional source-origin values) and assumes the completed V2 column cutover. Keep the existing application deployed until those later changes receive separate approval, or approve a separately tested additive 017/350 package and compatibility test profile. This package does not silently expand its approved scope.

Never merge `codex/architecture-v2` into `main` until the deferred/breaking migrations and their matching application code have been approved and deployed together. The repository's `architecture-v2-schema-gate` pull-request check deliberately fails while that gate is unmet; configure that check as required in `main` branch protection.

See `classification.md` for the per-migration decision and deferred phase order.

## Ordered apply

`manifest.json` is the executable order:

1. `190_v2_reference_data.sql`
2. `v2a01_actor_identity_additive.py`, then `200_v2_actor_location.sql`
3. `210_v2_topics.sql`
4. `v2a02_hubs_additive.py`, then `220_v2_hub_center_review.sql`
5. `230_v2_verification_history.sql`
6. `240_v2_fact_ledger.sql`
7. `250_v2_edges.sql`
8. `260_v2_collection_runs.sql`
9. `270_v2_rankings.sql`
10. `v2a03_people_additive.py`, then `280_v2_people_privacy.sql`
11. `v2a04_events_additive.py`, then `290_v2_event_evidence.sql`
12. `300_v2_strategic_connections.sql`
13. `320_v2_review_items.sql`
14. `330_v2_guards_and_audit_additive.sql`
15. `340_v2_compatibility_views_additive.sql`

Rollback uses the matching files in exact reverse order. It never restores the production dump.

## Schema-owner approval file

Create a plain-text approval file containing this exact marker:

`SCHEMA_OWNER_APPROVED_ADDITIVE_V2`

The shared-target runner refuses to operate without that file and a verified backup manifest.

## Apply after approval

Set only standard libpq environment variables. Put the password in a restricted `PGPASSFILE`; do not construct, pass, or print a connection URL:

```powershell
$env:PGHOST = 'approved-production-host'
$env:PGPORT = '5432'
$env:PGUSER = 'approved-schema-owner'
$env:PGDATABASE = 'postgres'
$env:PGSSLMODE = 'require'
$env:PGPASSFILE = 'C:\secure\ghus-production.pgpass'
Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
& .\scripts\apply_additive.ps1 `
  -SchemaOwnerApprovalFile C:\approved\architecture_v2_additive.txt
```

The wrapper performs, in order:

1. a fresh custom-format full `pg_dump` under `C:\Users\Ismail\GHUS-data\backups`, taken immediately before the apply;
2. SHA-256 and a backup manifest;
3. a read-only snapshot of every existing public-table row count and schema object;
4. the ordered additive apply;
5. a read-only row-count comparison and new-object inventory;
6. backend and frontend read-only smoke checks.

The wrapper stops on any failed step. A smoke success proves read compatibility only; application deployment remains subject to the deployment gate above.

The 2026-09-28 17:02Z dump is fallback evidence only. It does not satisfy the apply-day backup requirement and the wrapper does not accept it as a substitute for the fresh dump it creates.

## Existing-table compatibility behavior

The additive set adds no default to an existing table. It adds these existing-table functions/triggers:

- `actor`: `ghus_legacy_actor_category(text)`, `ghus_sync_actor_v2_compat()`, and trigger `actor_v2_compat_sync`.
- `person`: `ghus_sync_person_v2_compat()` and trigger `person_v2_compat_sync`.

Legacy columns win when a legacy and V2 value arrive together. The functions do not raise for a legacy insert/update. Known legacy actor types map through an explicit allowlist; an unmapped actor type leaves `actor_category` null. Run `scripts/prove_legacy_actor_writes.py` against `ghus_v2_test` to exercise inserts and updates for every currently stored actor type plus an unknown value; its transaction always rolls back.

## Rollback

Rollback is a schema operation, not a production restore. It requires the same approval file and verified backup manifest:

```powershell
& .\scripts\rollback_additive.ps1 `
  -SchemaOwnerApprovalFile C:\approved\architecture_v2_additive.txt `
  -BackupManifest C:\Users\Ismail\GHUS-data\backups\ghus_production_full_TIMESTAMP.dump.manifest.json
```

If new V2 tables have received data after deployment, export that data before rollback. Restoring a Supabase project is outside this package and remains prohibited.
