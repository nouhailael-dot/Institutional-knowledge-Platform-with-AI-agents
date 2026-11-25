# Migration 800: actor names back in the database

**Status: applied to production on 25 Nov 2026 (about 00:45 UTC).** Preflight passed
6/6 and verify 10/10, with 980 actors and 900 template rows; the ledger row carries
sha256 `829d46a5…`. The backup taken just before is
`supabase-before-800-20261124T234845Z-without-raw-document-rows.dump`.

**Decision (25 Nov 2026, Ismail; Nouhaila's database changes paused for it):** the
database uses the actor names again, as the platform's code always has. Migration 720
had renamed the actor tables to organization_* and left actor_* stand-in views; 800
removes the stand-ins and gives the real tables their actor names back.

Nothing built since 720 is undone. 730's template view stays and becomes `actor_template`.
740's event fields stay. The columns 750 and 770 removed stay removed. 790's single
organization table stays one table, now named `actor`. Only names change; no row is
written or moved.

People keep seeing "Organization" on the platform. The category label
"Company / Corporate Organization" and the column comments are unchanged.

## What it changes

- Drops the actor_* stand-in views. They are views only, so no data goes with them, and
  nothing else is built on them (`generate.py` refuses otherwise).
- Renames every relation named organization to actor, along with their columns named
  organization and the constraint, index, trigger and policy names on them.
- Rewrites the functions that 720 and 790 wrote with organization names, using the actor
  names. Functions with organization in their own name are dropped and created again
  under the actor name, and their triggers are re-created to point at them.
- Asks the API (PostgREST) to reload its schema.

## Files

| File | Purpose |
|---|---|
| `generate.py` | Builds everything below from a LOCAL copy of production (never Supabase) |
| `../deferred/800_actor_names.sql` | The migration (one transaction; refuses on any catalog difference) |
| `../deferred/rollback/800_actor_names.sql` | Puts back the organization names and the stand-ins exactly |
| `preflight.sql` | Read-only checks before applying |
| `verify.sql` | Read-only checks after applying |
| `ledger.sql` | The ledger row, with the migration's checksum |
| `catalog.json` | What it was generated from |

## Apply sequence (production)

1. Nouhaila's database changes are paused, and nothing has been applied since the
   latest ledger entry recorded in `catalog.json`.
2. Take a backup of production (`pg_dump`). Restore it locally, regenerate from that
   copy, and rehearse there: apply, verify, roll back, then confirm the schema comes
   back identical.
3. Run `preflight.sql`: every row must say ok = true.
4. Apply `800_actor_names.sql`, then `ledger.sql`.
5. Run `verify.sql`: every row must say ok = true.
6. Redeploy nothing. The platform's code already uses the actor names.
7. Nouhaila switches any of her own code or migrations from organization_* names to
   actor_* names before she resumes.

## Rollback

Run `../deferred/rollback/800_actor_names.sql`, then delete the 800 row from the
ledger. It needs the rows that 800 saved in `compass.migration_snapshot`, so that
table must not be dropped while 800 might still be rolled back.
