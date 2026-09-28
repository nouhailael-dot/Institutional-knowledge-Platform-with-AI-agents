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

Load the production URL from the approved secret manager without printing it, then run:

```powershell
& .\scripts\apply_additive.ps1 `
  -DatabaseUrl $productionDatabaseUrl `
  -SchemaOwnerApprovalFile C:\approved\architecture_v2_additive.txt
```

The wrapper performs, in order:

1. a custom-format full `pg_dump` under `C:\Users\Ismail\GHUS-data\backups`;
2. SHA-256 and a backup manifest;
3. a read-only snapshot of every existing public-table row count and schema object;
4. the ordered additive apply;
5. a read-only row-count comparison and new-object inventory;
6. backend and frontend read-only smoke checks.

The wrapper stops on any failed step. A smoke success proves read compatibility only; application deployment remains subject to the deployment gate above.

## Rollback

Rollback is a schema operation, not a production restore. It requires the same approval file and verified backup manifest:

```powershell
& .\scripts\rollback_additive.ps1 `
  -DatabaseUrl $productionDatabaseUrl `
  -SchemaOwnerApprovalFile C:\approved\architecture_v2_additive.txt `
  -BackupManifest C:\Users\Ismail\GHUS-data\backups\ghus_production_full_TIMESTAMP.dump.manifest.json
```

If new V2 tables have received data after deployment, export that data before rollback. Restoring a Supabase project is outside this package and remains prohibited.
