# Activating Compass individual accounts (runbook)

Not done yet. Every step needs explicit approval, in this order. Until step 7 the
hosted app keeps the shared login (`GHUS_ACCESS_USERS`) and nothing changes for
anyone. Permanent deletion stays off (`GHUS_PURGE_MODE=off`) until step 9 is
separately authorized.

| Step | What | Who | Reversible by |
|---|---|---|---|
| 0 | Approvals and prerequisites | platform owner, schema owner | — |
| 1 | Supabase Auth settings | platform owner (dashboard) | changing them back |
| 2 | Invitation email sender (SMTP) | platform owner (dashboard) | changing it back |
| 3 | Migrations 700 + 710 on Supabase | schema owner (SQL editor) | rollback scripts (until first use) |
| 4 | Render environment (mode still off) | platform owner (dashboard) | removing the keys |
| 5 | Deploy the merged code (mode still off) | platform owner (Manual Deploy) | redeploying the previous commit |
| 6 | First administrator | platform owner (Render Shell) | revoking the invitation |
| 7 | Switch to individual accounts | platform owner | removing `GHUS_AUTH_MODE` |
| 8 | Invite the team | the administrator (Users page) | deactivating accounts |
| 9 | Permanent-deletion cleanup: dry run, then live | platform owner, separately authorized | `GHUS_PURGE_MODE=off` |

## 0. Approvals and prerequisites

- The accounts branch merged into `main` (after review; it is synchronized with `main`
  as of `c12993a`, 18 Nov 2026).
- Real Supabase Auth validated on a separate test project:
  `python -m tests.supabase_auth_live_check` (see section 10). **Not done yet.**
- Schema-owner approval of migrations 700 and 710: package and evidence in
  `ghus-backend/migrations/proposed/accounts_700_710/README.md`.
- The name and email of the first administrator.

## 1. Supabase Auth settings (dashboard → Authentication)

| Setting | Value |
|---|---|
| Sign In / Providers → Email | Enabled. **Allow new users to sign up: OFF** (invitation-only) |
| Sign In / Providers → Email → Confirm email | On |
| URL Configuration → Site URL | `https://ghus-compass.onrender.com` (the Compass address) |
| URL Configuration → Redirect URLs | `https://ghus-compass.onrender.com/accept`, `https://ghus-compass.onrender.com/reset` only |
| Emails → Templates → Invite user | `docs/supabase-auth/invite.html` |
| Emails → Templates → Reset password | `docs/supabase-auth/recovery.html` |
| Security → Email OTP expiration | 86400 seconds (24 h) for the link; Compass's own invitation expiry (`GHUS_INVITATION_DAYS`, default 7) is checked separately |
| Rate limits | Keep the defaults; Compass adds its own limits |
| Password requirements | Minimum length 12 (Compass refuses shorter ones too) |
| JWT keys | Either works: with the legacy JWT secret set in `SUPABASE_JWT_SECRET` tokens are verified locally (HS256); a project on asymmetric signing keys leaves that variable empty and Compass asks Supabase Auth to confirm each token (cached 60 s) |

The templates contain no secrets. They link to Compass's `/accept` and `/reset`
pages with a single-use code that the server exchanges; never use
`{{ .ConfirmationURL }}`, which puts a session token in the address.

## 2. Invitation email sender (dashboard → Authentication → Emails → SMTP Settings)

Supabase's built-in sender is for testing only (a few emails per hour, to team
addresses). For the team, set **Custom SMTP**: host, port 587 (STARTTLS), user, the
sender `compass@<your domain>` and name "GHUS Compass". The SMTP password is entered
in the dashboard only, never in the repository or Render. Send one test invitation
to a team address before step 6.

## 3. Migrations 700 and 710 (Supabase SQL editor)

Follow `ghus-backend/migrations/proposed/accounts_700_710/README.md` exactly:
fresh `pg_dump` backup → `preflight.sql` (all ok) → `700_compass_accounts.sql` →
`710_record_deletion_retention.sql` → `ledger.sql` → `verify.sql` (all ok). Each is
one transaction; a failure changes nothing. With the mode still off the app does
not read these tables, so this step changes nothing for users either.

## 4. Render environment (Environment → Add, "Save only")

| Key | Value | Secret |
|---|---|---|
| `SUPABASE_URL` | `https://<project>.supabase.co` | no |
| `SUPABASE_ANON_KEY` | Project Settings → API → anon key | yes |
| `SUPABASE_SERVICE_ROLE_KEY` | service_role key (server only; never in the browser) | yes |
| `SUPABASE_JWT_SECRET` | Project Settings → API → JWT secret (legacy); empty on asymmetric keys | yes |
| `GHUS_SESSION_KEY` | 48+ random characters (`python -c "import secrets;print(secrets.token_urlsafe(48))"`); keep it stable — changing it signs everyone out | yes |
| `GHUS_PUBLIC_URL` | `https://ghus-compass.onrender.com` | no |
| `GHUS_PURGE_MODE` | `off` | no |
| `GHUS_INVITATION_DAYS` | `7` (optional) | no |
| `GHUS_SESSION_MAX_HOURS` | `12` (optional) | no |

The accounts tables are read through the existing `DATABASE_URL` (Session pooler);
no other database setting is needed. Do **not** set `GHUS_AUTH_MODE` yet. Check the
settings without printing them, in the service's Shell:
`python -m scripts.check_accounts_config`.

**Persistent storage:** accounts, roles, ownership, audit, usage, notifications and
deletions live in Supabase (schema `compass`); sessions live in the browser's HttpOnly
cookies. The existing disk (`/var/data`: Review store, Data Feed files, maps) is
unchanged; nothing new is stored on it.

## 5. Deploy the merged code with the mode still off

Manual Deploy of the approved `main` commit. With `GHUS_AUTH_MODE` unset the shared
login keeps working exactly as before, so nothing changes for testers. Check:
`GET /api/health` → `{"ok": true}`; sign in with the shared login; open Review and
the Directory.

## 6. The first administrator (service Shell)

```
python -m scripts.bootstrap_admin --email <admin email> --name "<Admin name>"
python -m scripts.bootstrap_admin --email <admin email> --name "<Admin name>" --live --confirm-email <admin email>
```

The first line is a dry run (it prints what it would do). The second sends the
invitation; it refuses if an administrator already exists, if a first invitation is
still open, or if the two email addresses differ. The invitation expires after 3
days. The person does not sign in yet: that needs step 7.

## 7. Switch to individual accounts

Set `GHUS_AUTH_MODE=supabase` and restart (Manual Deploy → "Restart service"). The
administrator opens the email, chooses a password at `/accept`, signs in, and checks:
Users page, Dashboard (with the Pending Deletion card), Audit History. The log line
`ACCOUNTS: no active administrator` disappears once they accept.

## 8. Invite the team

From **Users**: name, email, role (Admin, Editor/Reviewer, Viewer). Each person
chooses their own password from the email. Records, requests, maps and imports made
from now on carry their owner; decisions and changes are attributed to the signed-in
person.

## 9. Permanent-deletion cleanup (separately authorized)

Deleting and restoring work from step 7 on; nothing is removed permanently while
`GHUS_PURGE_MODE=off`.

1. **Dry run:** `GHUS_PURGE_MODE=dry-run`, restart. Each day (first run 10 minutes after
   start) the server runs the cleanup without changing anything and writes
   `cleanup.purge` to Audit History with what would be removed. By hand, in the Shell:
   `cd ghus-backend && python -m agents.review.purge` (dry by default).
2. **Live**, once the dry-run reports look right (no `blocked` or `error`):
   `GHUS_PURGE_MODE=live`, restart. Records whose 30 days are over are removed daily,
   one per transaction; a missed day is caught up on the next run; two servers never
   purge at once (database lock). If the service sleeps for long periods, a Render
   Cron Job can run `python -m agents.review.purge --live` daily instead (with
   `REVIEW_ADMISSION_WRITES_ENABLED=true`; then leave `GHUS_PURGE_MODE=off` on the web
   service).
3. **Stop at any time:** `GHUS_PURGE_MODE=off`. Deletions stay pending and restorable.

## 10. Real Supabase Auth validation (before step 0 is complete)

On a **separate** Supabase test project (never the production one), with synthetic
addresses only:

```
set GHUS_AUTH_TEST_URL=https://<test-project>.supabase.co
set GHUS_AUTH_TEST_ANON_KEY=...            (test project only)
set GHUS_AUTH_TEST_SERVICE_ROLE_KEY=...    (test project only)
set GHUS_AUTH_TEST_JWT_SECRET=...          (optional)
python -m tests.supabase_auth_live_check --database ghus_accounts_test --confirm-test-project <project-ref>
```

It refuses the production project and any non-local accounts database; it creates
synthetic users through the Admin API (no email is sent) and removes them at the end.
It checks invitation acceptance and password setup, sign-in, session renewal, sign-out,
password reset, role change and deactivation (also blocked in Supabase Auth), several
people at once, backend authorization, cookie flags (HttpOnly, Secure behind HTTPS,
SameSite=Lax) and recovery of a forgotten password.

## Health checks and monitoring

- Render health check: `GET /api/health` (public, no database call) — unchanged.
- Readiness after a deploy: `python -m scripts.check_accounts_config` (settings present,
  Supabase Auth reachable, compass schema present, an active administrator).
- Logs to watch (Render → Logs): `ACCOUNTS: no active administrator` (nobody can manage
  users), `AUDIT NOT WRITTEN` (an audit insert failed; the action itself happened),
  `Cleanup (...)` lines with `blocked` or `error` outcomes, `Could not read deleted ...`
  (hiding fell back to showing everything — investigate).
- Admin → Audit History: every change, every refusal (`access.denied`), every sign-in.
- Admin → Usage and Costs: per-person spend, exportable (CSV, Excel).

## Rollback plan

| Situation | Action | Effect |
|---|---|---|
| Sign-in problems after step 7 | Remove `GHUS_AUTH_MODE`, restart | Back to the shared login at once; accounts, ownership and history stay in Supabase for later |
| A bad deploy | Manual Deploy of the previous commit | As any release |
| Cleanup misbehaves | `GHUS_PURGE_MODE=off`, restart | Nothing more is purged; pending deletions stay restorable |
| Migrations before anyone used them | `rollback/710_...sql`, then `rollback/700_...sql`, delete the two ledger rows | Catalog exactly as before (rehearsed on a production copy) |
| Migrations after real use | Do not roll back (the rollbacks refuse); switch the features off instead | Data and history kept |
| A record deleted by mistake | Pending Deletion → Restore (within 30 days) | Back with status, owner, links and history |
