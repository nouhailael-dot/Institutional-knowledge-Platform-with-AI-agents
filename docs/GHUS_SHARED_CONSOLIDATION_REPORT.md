# GHUS-Shared consolidation — 27 October 2026

Branch `integration/ghus-shared-2026-10-27`, based on `origin/main` `12fc6b2`
(still the latest `main` at the end of the work). Committed locally only:
nothing was pushed, no Pull Request was opened or merged, no migration was
applied anywhere shared, and no production data was read or written.

## 1. What `main` already had

| Source | State in `main` |
| --- | --- |
| `feature/review-redesign` up to `ed41cc6` (Review, Discovery, actor updates of 19 Oct) | Included (merges `dc3b42d`, `5558721`) |
| Backend `ghus-backend` branch up to `62e4008` (19 Oct) | Included as `ghus-backend/` (merge `d58c9d9`) |
| Nouhaila's work: Build the Map hand-off to Discovery, People in Browse, one contact identity, robots.txt | Included |
| `codex/architecture-v2`, backend `main`, `codex/review-admission`, the July clone's `main` | Included |

## 2. What this branch adds

| Commit | Content |
| --- | --- |
| `ef772c3` | `integration/ghus-complete` (GHUS-Complete-Integration, 21-22 Oct): Phase 12 Review workflows (bulk category confirmation, location and legacy-relationship decisions, keep-both locations, rejected actors hidden from Browse/Ask), and the 22 Oct backend reconciliation. |
| `bfbb211` | `ghus-backend/` brought up to the latest backend (GHUS-Platform `9640da0`, `e2f67fc` and the uncommitted work of 27 Oct): events and people on request (migration 580), discovery quality gates, page facts, people targets, US scope, search cache, follow-up searches, Data Feed staging and imported-as-Verified (migration 590), the Deep Pull reader behind the actor/topic gate, Light Pull for kept organisations, live run progress and spend, and the 540-580 ledger reconciliation package. |
| `6174acd` + `a21bbef` | Platform work of 20-27 Oct: Data Feed, Dashboard, events and people requests, Any sector, five event types, Frequency, Running / Scheduled / Period over, Run again, Show Results, Light Refresh with Deep Pull on request for verified actors, Run Deep Pull in Review, MM/DD/YYYY dates. |
| `abc15ab` | GHUS-Shared as the single repository (AGENTS.md, launch configuration) and the Browse connection fix below. |

### How conflicts were resolved

- Backend: three-way merged against the exact sources the 22 Oct reconciliation
  copied (`GHUS-Complete-Integration/.demo/backend-reconciliation-source`). With
  that base there were no conflicts: its adaptations and the later changes touch
  different lines.
- Platform, 11 files: both sides kept. Nouhaila's menu order and Build the Map
  hand-off; the Phase 12 forms inside the redesigned Review workspace; the
  redesigned Actor updates panel (it already carries the integration's sources,
  access attempts and one-time history) plus the integration's unreadable-site
  error; V2 status first in Browse plus `source_origin`.

### Fixes made while testing

- `ghus-backend/.gitattributes`: release-manifest migration modules pinned to LF.
  The manifest hashes them byte for byte, so every Windows clone failed the
  release test.
- Review no longer fails as a whole on a database without migration 550's
  request title or without the collection ledger.
- Browse names sectors through its own connection. It used `DATABASE_URL`, so
  the isolated demo read sector names from the shared database named in `.env`,
  and an instance without `.env` could not open Browse.
- The demo launcher, the Data Feed end-to-end test and 13 maintenance scripts
  under `ghus-backend/scripts/actor_enrichment_maintenance` found the backend at
  `C:\Users\Ismail\Projects\GHUS-Platform`; they now use this repository (three
  scripts also lacked a `Path` import).
- Plan wording discloses the fallback web search for Light and Deep updates.
- Two dated tests (a fixed "today" that had passed; a render test that followed
  an old `useState` order) corrected.

## 3. Left out on purpose (preserved, not lost)

| Item | Why |
| --- | --- |
| `alembic.ini`, a whitespace-only migration, a comment-only change to frozen ER code | Machine-specific or no behaviour change |
| `scripts/smoke_test_actor_merge.py` | Writes outside the approved writers; fails two guard tests |
| Historical ADR/plan drafts, interim data CSV, demo seeding, local agent configuration, `graphify-out/` | Not functionality |
| PR #1 `feature/ismail-modifications` (8 Oct) and `integration/background-work` (2 Oct) | Old layout (backend at the repository root) and committed virtual environments; superseded by `ghus-backend/` |
| `integration/architecture-v2-functional`, `review-workflow` | Already in `main` in later form |
| July clone's uncommitted Ask-index edits | Superseded by main's guarded pruning; Ask belongs to its owner |

Every uncommitted change was preserved before any work, without touching the
working trees, on `backup/wip-2026-10-27-*` branches: `-backend` in
GHUS-Platform; `-frosty-gates`, `-phase12-worktree` and
`-platform-main-checkout` in Institutional-knowledge-Platform; `-july-clone` in
Institutional-knowledge-Platform-with-AI-agents.

## 4. Tests

| Suite | Result |
| --- | --- |
| Backend, offline (`ghus-backend`, `tests`) | 1007 passed, 76 skipped, 0 failed |
| Backend, isolated PostgreSQL (`tests/integration`, `tests/db`) | 79 passed, 11 skipped, 2 failed (below) |
| Platform, offline (`tests`) | 490 passed, 11 skipped, 0 failed |
| Platform, isolated PostgreSQL | 494 passed, 7 failed (below) |
| Frontend (`tests/*.mjs`) | 148 passed, 0 failed |
| In-process API smoke from GHUS-Shared (every page asset and API, a free plan through the in-repo backend) | All passed |

The remaining database failures need matching fixture databases and fail the
same way without this branch:
- 2 backend schema tests expect the pre-cutover column set (same result in the
  old GHUS-Platform folder).
- 6 platform cutover smoke tests expect frozen snapshot counts and an
  `actor_read` view; 1 Review API test expects a fixture actor the backend test
  leaves rejected. All 7 fail identically on `integration/ghus-complete`.

## 5. Pending

- Review and merge this branch into `main` (Pull Request), then sync GHUS-Shared.
- Close PR #1 (`feature/ismail-modifications`) as superseded.
- Migration 590 and the 540-580 ledger reconciliation: proposed only, awaiting
  the schema owner; nothing applied to Supabase.
- People admission through Data Feed is still held by the frozen resolver's
  review band (affiliation); decide with Nouhaila.
- `GHUS-Shared/.venv` is a local link to the existing platform environment. A
  fresh environment for both requirement sets needs one decision: the backend
  pins `anthropic==1.0.0`, the platform needs `>=1.5`.
- Fixture databases for the 9 database tests above.
