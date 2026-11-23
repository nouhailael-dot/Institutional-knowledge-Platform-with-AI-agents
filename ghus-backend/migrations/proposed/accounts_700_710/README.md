# Migrations 700 and 710: schema-owner package

Status: **proposed, not applied to Supabase.** Needs the schema owner's approval
and the platform owner's authorization. Prepared 17–18 Nov 2026.

| | File | SHA-256 (LF bytes) |
|---|---|---|
| 700 Compass accounts | `../deferred/700_compass_accounts.sql` | `8197dc81cf70ea68f92e230558e491cd30f7c27b8d4fc2c06662d08f75cd578e` |
| 710 Record deletion, 30-day retention | `../deferred/710_record_deletion_retention.sql` | `d947eb4b498eb3a965355ba4da45c851f7cebaf15044f140a09f1d2b1a3fefa8` |
| Rollback 700 | `../deferred/rollback/700_compass_accounts.sql` | `f69f48749ef79fcdaa2869473ab0bc134225965694e54f96b095737c79911c79` |
| Rollback 710 | `../deferred/rollback/710_record_deletion_retention.sql` | `7f399f09520abd79e62817235c8967f103501313f0909fedb8b5f6dc5d73d024` |

`tests/db/test_accounts_migration_package.py` fails if a file changes without its checksum here.

## Dependencies

- Supabase Auth's `auth.users (id uuid)` — 700's profiles and invitations reference it.
- `gen_random_uuid()` (built in since PostgreSQL 13).
- 710 needs 700 and refuses to run (changing nothing) unless the four delete guards
  and `actor_read` are exactly as reviewed: `preflight.sql` checks the same values.
- Ledger after 621 (the latest on the 5 Nov 2026 backup). Neither migration depends on
  600–630 beyond what is on production; the purge policy also covers 630's tables if
  630 is applied later.

## What changes

- **700** — additive: a new schema `compass` (roles and permissions, profiles,
  invitations, audit, ownership, usage, notifications). Nothing in `public` changes.
  Row security on every table; `anon` and `authenticated` get no access to the schema,
  so the Supabase REST API exposes none of it. No user or role assignment is created.
- **710** — `compass.deleted_record` and `compass.migration_snapshot` (the exact
  definitions it replaces, for the rollback); in `public`, only the four delete
  guards (a DELETE passes for the approved cleanup of a deletion whose 30 days are
  over; everything else is still refused) and `actor_read` (also hides records
  pending deletion).

## Rehearsal on a production copy (done 18 Nov 2026)

The 5 Nov 2026 Supabase backup (`supabase-before-630-...-20261105-2022.dump`) restored
into a local `*_test` database, then:

```
python -m tests.db.rehearse_accounts_migrations --database ghus_phase7_prodcopy_test
```

28 of 28 checks passed: apply 700 → 710; 700 leaves `public` untouched; 710 changes
only the guards and `actor_read` there; row security and grants; guards still refuse;
the purge door opens only for a due deletion; `actor_read` hides a pending deletion;
one pending deletion per record; 30-day minimum; restore refused after the deadline;
the deletion history cannot be deleted or rewritten; every foreign key to a deletable
record is in the purge policy; ledger rows; rollback 710 refuses while a deletion
exists; rollback 710 then 700 restore the catalog exactly (guard bodies byte for byte);
re-applying gives the identical catalog. The backend deletion tests (11) also pass on
that copy.

Two problems were found and fixed by the rehearsal: 710 had been written against an
older schema (`actor_read` used `location_city`; production has `city`), and
production's guard bodies are stored with Windows line endings, so the rollback now
restores the definitions 710 saved instead of re-typed text.

## Apply sequence (Supabase SQL editor; one script per run)

1. Fresh backup: `pg_dump` to `C:\Users\Ismail\GHUS-data\backups` (Render Shell or a
   machine that reaches Supabase).
2. `preflight.sql` — every row `ok = true`. Stop otherwise.
3. `700_compass_accounts.sql`.
4. `710_record_deletion_retention.sql`.
5. `ledger.sql`.
6. `verify.sql` — every row `ok = true`.

Each migration is one transaction: a failure changes nothing.

## Rollback

Reverse order, one script per run: `rollback/710_...sql` (refuses once any record has
been deleted: a pending one would reappear, a purged one's history is kept), then
`rollback/700_...sql` (refuses once accounts or history exist). Then delete the two
ledger rows: `DELETE FROM architecture_v2_migration_ledger WHERE migration_id IN ('700','710');`.
After real use, rolling back is replaced by switching the features off
(`GHUS_AUTH_MODE` unset, `GHUS_PURGE_MODE=off`); the tables stay.
