# Architecture V2 additive apply package: 180–350

Prepared 2026-09-29 for the schema owner/user to run. Agents must never run it on shared Supabase.

## Scope and order

The manifest applies the additive production-drift repair from 170, then every source file 180–350 in numerical order: 170 drift repair; 180 review admission; 190 reference data; 200 actor identity/location; 210–300 in source order; 310 hub proposals; 320–340 review/guards/compatibility; and the additive origin rows from 350.

Rollback uses the matching actions in exact reverse order. `deferred/` is separately inventoried and intentionally has no executable runner.

## Hard preconditions

Stop without touching the shared database unless all are true:

- the production password rotation is confirmed complete;
- only `PGPASSFILE` is used (`PGPASSWORD` removed; no credential-bearing URL);
- the schema owner has supplied an approval file containing `SCHEMA_OWNER_APPROVED_ADDITIVE_V2`;
- a fresh full custom-format `pg_dump` is taken immediately before apply and its SHA-256 manifest verifies;
- the status proof confirms legacy mapping never produces V2 `verified` or `rejected`.

The 2026-09-28 17:02Z dump is fallback evidence only and cannot satisfy apply-day backup.

## Shared apply after approval

Set standard libpq variables and a restricted `PGPASSFILE`, then run:

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

The wrapper creates and checksums the fresh backup, captures the pre-state, applies in order, automatically rolls back every successfully committed action if the first apply error occurs, checks all existing-table row counts, inventories new objects, and runs both read-only smokes. Errors are redacted and connection strings are never accepted or printed.

## Existing-table compatibility

No additive statement introduces a default or `NOT NULL` requirement on a table that existed in production. Existing-table write helpers are:

- `actor`: `ghus_legacy_actor_category(text)`, `ghus_legacy_record_status(text)`, `ghus_sync_actor_v2_compat()`, trigger `actor_v2_compat_sync`;
- `person`: `ghus_sync_person_v2_compat()`, trigger `person_v2_compat_sync`.

Unmapped actor types produce `actor_category=NULL` and never raise. Legacy status mapping is: `phase_1/imported → imported`, `ai_inferred/needs_review/parked → parked`, and every other value—including `verified`, `rejected`, and unknown values—maps to null. V2 `verified`/`rejected` decisions therefore come only from the verification ledger, never from legacy scalar status mapping.

File 180 adds nullable columns to existing queues; file 170 adds nullable columns plus an index. Neither adds an existing-table trigger or default.

## Deployment gate

The additive schema is read-compatible with the legacy application, but the complete Phase 3 new-actor runtime is not deployable against it: `verify_actor` remains excluded by the existing `review_item` CHECK because changing that CHECK is breaking. The repository schema gate must remain unmet. Never merge `codex/architecture-v2` into `main` until the deferred schema and matching code are approved and deployed together.
