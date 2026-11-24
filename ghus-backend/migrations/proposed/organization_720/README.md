# Migration 720: "actor" becomes "organization" in the database (stage 1 of 2)

Status: **applied to Supabase on 24 Nov 2026** (platform owner's go-ahead, a quiet
window: no run in progress, no other session). GHUS decision of 24 Nov 2026: "actor"
becomes "Organization" everywhere, the database included.

Applied in order: backup `C:\Users\Ismail\GHUS-data\backups\supabase-before-720-20261124T144929Z-without-raw-document-rows.dump`
(every table's data except `raw_document`'s fetched pages, which 720 does not touch; a
full dump was cut off over the VPN on that table) → preflight (all true, after the fix
below) → 720 → ledger → verify (10 of 10 true). Afterwards the old and new names read
the same rows (980 organizations, 820 in the Directory view, 651 hub memberships,
13,086 facts) and the platform's Directory and record pages load.

The production preflight first refused: `ghus_guard_subscription_run_append_only` is
stored there with Windows line endings. The checks now read CRLF as LF (a real
difference still refuses); rehearsal rerun before applying.

| | File |
|---|---|
| Migration | `../deferred/720_organization_names.sql` (SHA-256 in `ledger.sql`) |
| Rollback | `../deferred/rollback/720_organization_names.sql` |
| Built by | `generate.py` from `catalog.json` (a local copy of production) |

`tests/db/test_organization_migration_package.py` fails if a file is edited by hand,
changes without its checksum, or loses a stand-in.

## What changes

- **27 relations renamed**: 21 tables and 6 views — `actor` → `organization`,
  `actor_fact` → `organization_fact`, `hub_actor` → `hub_organization`,
  `actor_read` → `organization_read`, `actor_update_subscription` →
  `organization_update_subscription` …
- **Their columns named actor** (`actor_id` → `organization_id`, `actor_category` →
  `organization_category`, `merged_into_actor_id` → `merged_into_organization_id` …),
  and the constraint, index, trigger and policy names on them.
- **Each old name stays as a stand-in view** with the old column names, so the platform
  and the agents keep working unchanged: reads, inserts (with `RETURNING` and
  `ON CONFLICT`), updates and deletes pass through to the renamed table, whose
  triggers and guards still run. The stand-ins use the caller's rights
  (`security_invoker`) and Supabase's public roles `anon` and `authenticated` have no
  access to them.
- **Nine functions** that name these relations are rewritten with the new names
  (five also renamed, e.g. `ghus_project_actor_verification_status` →
  `ghus_project_organization_verification_status`). The originals are saved in
  `compass.migration_snapshot`, with every rename made, for the rollback.
- **The category label** "Company / Corporate Actor" reads "Company / Corporate
  Organization".

No data changes apart from that label.

## Stage 2 (later, with the code)

The platform and the agents move to the new names, area by area; the columns named
actor in tables that keep their names (`event.host_actor_id`,
`collection_request.actor_id` …) are renamed in the same deploy as their code; the
internal type codes (`'actor'` in entity_type, `verify_actor`, `create_actor`) and the
session key `ghus.actor_is_human` change with the code that compares them; then the
stand-in views are dropped.

## Rehearsal (24 Nov 2026)

On `ghus_phase7_prodcopy_test` (the 5 Nov 2026 Supabase backup with 700 and 710
applied), in a throwaway copy:

- preflight: every row true; apply 720; ledger; verify: 10 of 10 true;
- through the old names: the same 978 organizations; an insert into `actor` lands in
  `organization`; setting "verified" directly is still refused by the guard; a
  verification event still projects the status; a delete is still refused;
  `actor_read` returns the same 819 rows as `organization_read`;
- rollback, then the whole `public` schema (`pg_dump --schema-only`) is identical to
  the original, function bodies included (0 lines differ); apply again: verify true;
- the backend suite on a copy with 720 applied: 1,193 passed, the same as on the
  copy without it; the platform's Directory (organizations, hubs, events, people, a
  record page) and Review's organization search return the same results.

Found by the rehearsal and fixed: `relkind` needs a cast to text in the checks.

## Apply sequence (Supabase SQL editor; one script per run; a quiet window)

1. No Discovery or Update run in progress; fresh backup with `pg_dump` to
   `C:\Users\Ismail\GHUS-data\backups`.
2. `preflight.sql` — every row `ok = true`. Stop otherwise (the migration would refuse
   anyway, changing nothing).
3. `../deferred/720_organization_names.sql` — one transaction.
4. `ledger.sql`.
5. `verify.sql` — every row `ok = true`.

No deploy is needed: the code keeps using the old names through the stand-ins.

## Rollback

`../deferred/rollback/720_organization_names.sql`, then
`DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '720';`.
If 750 (unused tables) is applied, roll it back first: 720's rollback renames
`organization_ranking`, which 750 removes.
