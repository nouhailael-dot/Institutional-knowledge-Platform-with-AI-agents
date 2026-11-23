# For schema-owner review: migration 700 (Compass individual accounts)

**Request:** review and, when approved, apply to shared Supabase after a fresh
backup and with a ledger entry. Nothing has been applied there; it was applied
and rolled back only on a local `*_test` database.

| | |
|---|---|
| Migration | `ghus-backend/migrations/proposed/deferred/700_compass_accounts.sql` |
| Rollback | `ghus-backend/migrations/proposed/deferred/rollback/700_compass_accounts.sql` (refuses while accounts or history exist) |
| Kind | Additive: one new schema `compass`; no existing table, row, view or guard changes |
| Depends on | Supabase Auth's `auth.users` (present in every Supabase project) |

## What it adds

| Table | Purpose |
|---|---|
| `compass.permission`, `role`, `role_permission` | Configurable roles; seeded Admin (19 permissions), Editor / Reviewer (15), Viewer (5). No user is assigned. |
| `compass.user_profile` | Name, email, role, status, last sign-in, preferences (jsonb), `sessions_valid_after` (ends older sessions on password change or deactivation) |
| `compass.invitation` | Invitation-only sign-up: expiry, revocation, one open invitation per address, bootstrap flag for the first administrator |
| `compass.audit_event` | Permanent history of sensitive actions; append-only trigger |
| `compass.record_owner` | Original owner of a record, request, map or import, with `source_ref`; first write wins, a trigger refuses any change or delete |
| `compass.usage_event` | Who started each paid operation and how (manual, Run now, scheduled). Costs stay in their ledgers (`collection_run.spent_usd`, `scrape_run.cost_usd`, the map store's calls); a cost is kept here only for an operation with no ledger (an Ask answer priced from tokens, an unapplied check). Unique `(kind, reference)`; append-only |
| `compass.notification` | Per-user notices; unique `(user_id, dedupe_key)`; `email_requested` / `emailed_at` for a future approved sender |

## Security

- Row Level Security is enabled on every table, with no policies.
- `REVOKE ALL ON SCHEMA compass` from `PUBLIC`, `anon` and `authenticated`: the Supabase REST API exposes nothing.
- The platform backend (table owner) is the only client and enforces every permission.
- No ecosystem table is written; canonical writers and guards (including `ghus_guard_no_delete`) are untouched.

## How it was checked (local `ghus_accounts_test` only)

- Apply, rollback while empty, re-apply: all pass.
- Guards: audit and usage append-only; ownership unchangeable; rollback refuses with data; `anon` gets "permission denied for schema compass".
- Platform tests that apply it from scratch each run: `tests/test_accounts*.py` (Phases 1-5, 104 tests).

## Suggested apply steps (schema owner)

1. Fresh Supabase backup (Database → Backups).
2. Apply `700_compass_accounts.sql` in the SQL editor (one transaction).
3. Check: `SELECT count(*) FROM compass.role_permission;` returns 39; `SELECT count(*) FROM compass.user_profile;` returns 0.
4. Record it in the migration ledger.
5. Accounts stay off until `GHUS_AUTH_MODE=supabase` is set (see `docs/ACCOUNTS_ACTIVATION.md`).
