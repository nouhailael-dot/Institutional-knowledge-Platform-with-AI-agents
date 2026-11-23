# Compass multi-user accounts: architecture and phase plan

Built on branch `feature/multi-user-accounts` (local workspace
`C:\Users\Ismail\Projects\GHUS-Shared-accounts`). The deployed app on Render,
`main`, the local 8030 server and shared Supabase are untouched: nothing is
pushed, and every database change is a proposal applied only to a local
`*_test` database.

## Architecture

- **Identities: Supabase Auth.** Compass never stores passwords. Sign-in,
  refresh, sign-out, invitations and password resets are Supabase Auth's,
  called from the server only. The browser holds the session in three
  HttpOnly, SameSite=Lax cookies (Secure over HTTPS) and never sees an API key
  or a token.
- **The backend is the gatekeeper.** Every route has a permission in
  `src/accounts/permissions.py`; a route with no policy is refused for
  everyone, and a test fails when a route is added without one. Hiding a
  button is never the protection.
- **Roles are data.** `compass.role_permission` decides; changing a role's
  permissions is a database change, not a code change.
- **Who acted comes only from the verified session** (`src/identity.py`), never
  from a request field. The 20 places that already record "who" pick up the
  real name with no further change.
- **New tables live in their own schema, `compass`** (migration 700). No
  ecosystem table is duplicated or altered. Row Level Security is on for
  every table, and the browser roles have no grant on the schema, so the
  Supabase REST API exposes none of it.
- **Mode switch.** `GHUS_AUTH_MODE=supabase` turns accounts on. Without it the
  shared login (`backend/access.py`) works exactly as today.

## Phases

| Phase | Content | Status |
|---|---|---|
| 1. Foundation | Migration 700 (profiles, roles, invitations, audit, ownership, usage, notifications) with rollback; permission catalogue and route policy; Supabase Auth client and token checks; sign-in, sign-out, session renewal, maximum session age, immediate sign-out; deactivation; sign-in rate limit; cross-site protection; sign-in page; who is signed in and Sign out in the sidebar | **Done, tested** |
| 2. Account management | Invitations (expiry, revoke, resend, no duplicates), accept and set password, password reset, profile and password change, Users page (invite, role, deactivate, activate), first-administrator command, email templates, configuration check, activation runbook | **Done, tested** |
| 3. Ownership and audit | Owner of records, requests, maps and imports; review decisions, edits and notes linked to the user id; audit entries for every sensitive action; My Records / All Records; My Review History | |
| 4. Personal experience | My Dashboard (activity, requests, maps, imports, pending work, notifications); preferences (saved filters, sectors, dashboard, notifications); pages and buttons shown by permission | |
| 5. Usage and costs | Per-user usage from the recorded costs (map runs, discovery runs, Ask tokens); personal view; admin dashboard with monthly comparison and export | |
| 6. Permanent deletion | Proposal for the schema owner: `docs/proposals/PERMANENT_DELETION.md` (guard unchanged) | Awaiting schema-owner review |
| 7. Activation | Test against a real Supabase Auth server (Docker), the activation runbook, then your first admin and the team's accounts | |

## Decisions needed

1. **Permanent deletion vs. the Architecture V2 rule.** The organisation,
   person, event and hub tables have a database guard that refuses every
   delete: "is never deleted: reject the record and keep it, with its reason".
   Permanent deletion therefore needs a schema-owner-approved change to that
   guard: deletion only through the approved writer, after dependency checks,
   leaving an audit tombstone. Until then, Delete stays the reversible removal
   it is today.
2. **Supabase Auth settings** (from the Supabase dashboard, when activating):
   project URL, anon key, service role key (server only), JWT secret; invite
   and reset email templates; the site URL and redirect URLs; SMTP for
   invitation emails (Supabase's built-in sender is rate-limited).
3. **First administrator.** Who, before activation. The system never runs
   without one.

## Phase 1 test results

- `tests/test_accounts.py`: 41 passed (roles match the migration, every route
  has a policy, forged or expired tokens refused, each role gets exactly its
  permissions, no role / invited / deactivated cannot sign in, deactivation
  ends access at once, wrong passwords limited, token renewal, revoked
  sessions, maximum session age, forged session start, cross-site changes
  refused, impersonation through the request refused, two users at once).
- Whole platform suite in this workspace: 697 passed (656 existing + 41 new).
- Migration 700 on a local test database: apply, rollback, re-apply; audit
  append-only; ownership unchangeable; rollback refuses with data; browser
  role denied.
- Browser: sign-in page, wrong password message, sign in, sidebar name and
  role, HttpOnly cookies invisible to scripts, Sign out, phone layout, viewer
  refused an edit.

## Phase 2 test results

- `tests/test_accounts_phase2.py`: 17 passed (invite and accept; duplicates and invalid input refused
  before any email; expired invitation refused, then resent and accepted; revoked invitation refused
  and no password set; no orphan identity when recording fails; only user managers reach
  administration; nobody grants a role above their own; role change applies at once; Compass always
  keeps an active administrator; deactivation cuts access, blocks sign-in and recovery, and can be
  undone; password reset is single-use and ends other sessions; recovery never reveals whether an
  account exists and is limited; other sites refused; own name and password; first-administrator
  bootstrap; keys never in a repr; configuration check).
- Phase 1 tests: 41 passed. Whole platform suite in the workspace: 714 passed.
- Browser (synthetic users): admin invites from Users, the invitation link opens /accept and is
  removed from the address bar, mismatched passwords refused, account created and signed in as
  Editor (no Users menu), My profile, admin deactivates with confirmation and the person's
  sign-in is refused.

## Phase 3: ownership, activity and Review attribution (done, 11 Nov 2026)

- Original owner (compass.record_owner, first claim wins, database refuses changes): maps (empty
  session, first chat, research start), Monitor and Update requests, Data Feed imports and map
  saves (only records they created; a match to an existing record keeps its owner), records
  verified as new in Review (the importer when they came from an import, otherwise the verifier).
  Records from before accounts: no owner, shown "Not recorded"; nothing is assigned afterwards.
- One audit entry per successful change (route, record, what the route noted: decision, record
  created, fields changed) and per refusal (access.denied, access.cross_site); account routes
  write their own. Failed actions are not recorded as done. Append-only in the database.
- Who acted comes from the session only; names or ids in a request body or header are ignored.
- Directory lists carry each record's owner; My Records works. My work page: My Records, My
  Requests, My Maps, My Imports, My Review History. GET /api/admin/audit for audit.view_all.
- Canonical writers, immutable facts and Review's own log are unchanged (Review still records the
  reviewer's name); the person's account id is linked in compass.audit_event and record_owner.
- Migration 700 change in this phase: record_owner.source_ref (immutable provenance).
- Tests: tests/test_accounts_phase3.py 15 passed; all accounts phases 73; platform suite 729.

## Phase 4: dashboard, notifications, preferences, role-aware pages (done, 12 Nov 2026)

- Personal Dashboard (welcome, notifications, running and recent runs, recent activity, My Records,
  Requests, Maps, Imports, Review History, preferred sectors), sections by role and preference.
- Notifications from existing data (own runs, maps, imports, schedules; others' decisions and edits
  on one's work); one per event and person; read/unread kept; bell in the header; email prepared,
  delivery refused until an approved sender.
- Preferences per person: sectors, saved Directory filters, default My/All view, Dashboard sections,
  notification kinds and email; validated on the server; never change shared data.
- Role-aware menu and pages (pages mount only when allowed); actions a role cannot use hidden
  (data-needs); the server still refuses them.
- Late import records get the importer as owner; record page shows owner, verifier, last editor.
- Bug found in the browser and fixed: Dashboard link buttons split across templates (htm), page
  failed to draw; regression test added.
- Tests: tests/test_accounts_phase4.py 19 passed; accounts phases 92; platform suite 748.
- Schema-owner packages: docs/schema-review/01_MIGRATION_700_ACCOUNTS.md and 02_PERMANENT_DELETION.md.

## Phase 5: usage, AI costs and reporting (done, 17 Nov 2026)

- Costs read from the existing ledgers, never copied: collection_run (Discovery, Organization
  Updates, organization checks and Deep Pull), scrape_run (Data Feed AI completion), the map store's
  calls (maps, people searches), Ask token usage (no ledger; priced with the maps' price table when
  the model has a price, otherwise tokens kept and cost unknown), unapplied checks (cost the check
  reported; replaced by the ledger run once applied).
- Attribution: Run now presser; scheduled runs to the request owner with trigger "scheduled"; check
  runner; completion starter or import owner; map owner; people-search starter; asker. No person
  recorded: "Not recorded", never inferred.
- Labels: final, in progress, partial run, estimate (calls still running), recorded by the check,
  priced from tokens, unknown.
- My usage (usage.view_own) and Usage and Costs (usage.view_all): filters by person, months,
  feature, Not recorded; by person and month; by feature; counts; reconciliation (difference 0
  per ledger); CSV and Excel exports.
- Bugs found and fixed: Ask usage object not priced (every answer would have been "unknown");
  month filter accepted 2026-13.
- Tests: tests/test_accounts_phase5.py 12 passed; accounts phases 104; platform suite 760.

## Phase 6: record deletion, 30-day retention and recovery (built 17 Nov 2026, not activated)

Policy (GHUS, 17 Nov 2026): Delete hides a record at once; it waits 30 days under Pending
Deletion, restorable by Admins and Editors/Reviewers; then the scheduled cleanup removes it
permanently. Adjusted 18 Nov 2026: Pending Deletion is kept entirely separate from Review
Results' Rejected — a compact Dashboard card (count, three nearest deadlines, View all) and a
dedicated Pending Deletion page (name, type, deleted by, date, reason, days left, Restore).

- Migration 710 + rollback (schema review: `docs/schema-review/02_PERMANENT_DELETION.md`):
  `compass.deleted_record` (tombstone, deadline, restore, purge, minimal kept audit), a
  DELETE-only "purge door" in the four Architecture V2 guards, `actor_read` hides pending
  deletions.
- Backend writer (`agents/enrichment/decisions.py`): `delete_record`, `restore_record`,
  `purge_record` with an explicit per-table policy; unknown links block the purge. Admission
  kinds `delete_record` / `restore_record`; matching a candidate to a deleted record is refused
  (no recreation); actor updates skip deleted organizations. Cleanup job
  `python -m agents.review.purge [--live]` (dry by default, one transaction per deletion,
  advisory lock, idempotent).
- Platform: `POST /api/browse/{kind}/{id}/delete` (confirmation, optional reason, the signed-in
  account), `GET /api/review/deleted`, `POST /api/review/deleted/{id}/restore`; deleted records
  hidden from Directory lists, profiles, Ask sources and dashboard counts; owner notified; every
  step audited (person names kept out of the permanent audit). In-app daily cleanup
  (`backend/purge_scheduler.py`, `GHUS_PURGE_MODE` off | dry-run | live, default off), audited
  as `cleanup.purge`.
- UI: Directory Delete for all four record types (with accounts; organizations-only removal
  stays for the shared login); Pending Deletion card on the Dashboard and its own page, both
  only for Admins and Editors/Reviewers (`records.delete_permanent`, also on the list API).
- Tests: backend 10, platform 14, JS 5 (plus updated earlier tests).
- Activation: `docs/ACCOUNTS_ACTIVATION.md` section 8.

## Phase 7: integration and deployment readiness (18 Nov 2026, not activated)

- **Synchronized with `main` (`c12993a`, 31 new commits).** Four files conflicted and were
  resolved by hand: `src/identity.py` (main's shared-login `acting_as(name)`/`done` kept as
  is; the accounts context manager is now `signed_in_as(account)`; an account takes
  precedence over the shared-login name), `backend/app.py` (Run now keeps main's per-person
  queue and records who pressed it), `frontend/index.html` (main's script versions and
  "opens on the Dashboard", plus the accounts block), `frontend/datafeed.js` (main's).
  Three routes added on main were given policies: `GET /api/me` (signed in),
  `POST /api/map/{job_id}/settle-charges` (`maps.create`),
  `POST /api/datafeed/imports/{run_id}/withdraw` (`datafeed.import`).
- **Bug found by integration:** main's `plain_reasons` middleware rebuilt every `/api/`
  JSON response from a dict of headers, keeping one `Set-Cookie`; with accounts on nobody
  could stay signed in (the shared login uses no cookies, so it never showed). Fixed to
  keep every header; regression test `tests/test_app_headers.py`.
- **Pending Deletion kept apart from Review's Rejected** (adjustment of 18 Nov): Dashboard
  card and its own page; the list API now needs `records.delete_permanent`.
- **Migrations 700 + 710:** rehearsed on a restore of the 5 Nov 2026 Supabase backup —
  28/28 checks (`ghus-backend/tests/db/rehearse_accounts_migrations.py`). Two problems found
  and fixed: 710's `actor_read` was written against an older schema (`location_city`), and
  production's guard bodies have Windows line endings (the rollback now restores the
  definitions 710 saves). 710 now refuses to run on any drift. The purge policy gained
  `actor_details`, `person_fact`, `event_fact` (production) and `event_details`,
  `person_details` (630). Package: `ghus-backend/migrations/proposed/accounts_700_710/`.
- **Real Supabase Auth (19 Nov):** `tests/supabase_auth_live_check.py` against a separate
  Supabase test project: 25/25 (invitations, password setup, single-use links, sign-in,
  renewal, sign-out, reset, role change, deactivation blocked in Supabase, several users at
  once, authorization, cookie flags). It found two problems, fixed with tests
  (`tests/test_accounts_tokens.py`): newer projects sign tokens with asymmetric keys even
  when a legacy secret exists, and Compass refused them (every session after sign-in, and
  a 500 on renewal); a copied REST address (`/rest/v1/`) broke the project URL.
- **Integration:** `tests/accounts_integration_check.py` runs the real app in accounts
  mode with the real backend writers on a migrated production copy.
- Runbook: `docs/ACCOUNTS_ACTIVATION.md` (rewritten: order, Render, migrations, bootstrap,
  monitoring, rollback).

## Personal pages (GHUS decision, 23 Nov 2026)

- Everything is personal apart from the Ecosystem Directory. Each person sees only their own
  maps (and Ask's parked organizations from them), Monitor and Update requests (their scheduled
  runs included), one-off organization updates, Data Feed imports and map saves, Review Results
  (items from their own requests, imports and checks) and Pending Deletion (their own deletions).
- Admins' own pages are personal too; everyone's work is seen on Users, Usage and Costs and Audit
  History only. `GET /api/dashboard/spending` (everyone's spending) now needs usage.view_all.
- Made before accounts (no recorded owner): shared with everyone, marked "Shared · from before
  accounts". Nothing is reassigned or guessed.
- The Directory stays shared and shows an Owner column on every tab.
- One check in the sign-in middleware (`src/accounts/personal.py`): a route naming someone else's
  map, request, import, Review item, deletion or check answers 404 "Not found."; owners that cannot
  be read answer 503 rather than showing everyone's items. Lists filter the same way.
- Tests: tests/test_personal_pages.py; phase 5 and 6 tests updated (Run now and restore on someone
  else's request or deletion are now refused).
