# Discovery redesign: request-driven actor discovery

Date: 2026-10-14. Scope: open-web **actor** discovery (backend `GHUS-Platform`)
and the new **Discovery** page (this platform). Nothing committed or pushed;
production Supabase untouched. All database work was on local isolated `*_test`
databases.

## What changed, in one paragraph

Actors are no longer discovered on a timer. A person asks on the **Discovery**
page — topic, sub-topics, area, start, duration, frequency, and a per-run ceiling
("for 3 months, every week, find Energy Transition organizations in the
Northeast focused on battery storage") — and the agent searches only for that,
only in that period, only that often. Every candidate is judged by a score
**and** hard gates: below 0.45 it is never picked; 0.85 and above with every gate
holding it is created (as **Parked**, never Verified); everything else goes to
Review. Events stay on their weekly schedule and gained a US-scope check. People
discovery stays disabled.

## Order of work

1. Quality gates and new thresholds
2. Request data model (migration 550)
3. Request-scoped search
4. Runner that executes only due requests
5. Schedule change (weekly actor sweep removed)
6. Discovery page
7. Events and people review
8. Tests on both repositories

## 1. Quality: three bands, decided by score and gates

Measured on 95 rubric-scored actor candidates (demo database): median 0.53, p75
0.72. The old 0.30 / 0.70 cut-offs auto-accepted 29%, including a page about
Texas Medical Center Innovation read from a third-party wiki (0.96) and UC Davis
read from someone else's site (0.84). The model marked "own organisational
page = true" for every one, so that item cannot be trusted alone.

| Band | Rule |
|---|---|
| **Reject** (never staged, never reviewed) | score < **0.45**, or any reject gate fails |
| **Review** (a person decides) | everything between |
| **Accept** (created as Parked + verify item) | score ≥ **0.85** and every accept gate holds |

Reject gates (fail → rejected whatever the score): no organisation name; page is
a directory / list / event / news / careers page; outside the requested sector;
outside the requested area.

Accept gates (fail → held for review): no official website stated; page is on a
different domain from the organisation's own site; fewer than 5 rubric criteria
evidenced; operating entity not established; no concrete programmes, research or
use cases; description missing, under 60 characters, more than 3 sentences or a
tagline; for requests with sub-topics, the page never mentions them.

Replay on the same 95 candidates: reject 9 → 26, review 58 → 64, accept 28 → 5.
The five still accepted: Urban Future Lab, BEAM Circular, Great Lakes WISE,
CalWEP, NYU Sustainability. Every decision stores its reasons, shown in Review.

## 2. Request data model — migration 550 (additive)

`agents/sql/550_v2_discovery_requests.sql` extends `actor_update_subscription`
(migration 540): `title`, `focus_terms` (≤ 8), `max_new_actors_per_run` (1–50,
default 10); `requested_via` gains `discovery_page`; cadence gains `biweekly`
(also on `collection_run`); a Discovery request must name a sector or topic. The
migration tests its own constraint before committing — which caught a real bug
on its first run (a NULL array passed the CHECK; fixed with `COALESCE`, as 540
does). Rollback refuses while any request depends on it. Applied, rolled back and
re-applied on `ghus_v2_demo_test`; applied on the new disposable
`ghus_v2_requests_test`. **Production needs schema-owner approval.**

## 3. Request-scoped search

A requested run replaces the hub grid entirely. Queries are sub-topic (or topic
name) × actor type × place, walked so every state is reached before any
combination repeats, plus use-case queries; 24 searches per run (`request_query_limit`).
Region → its states; state → that state; state + city → that city. Every
candidate is recorded against the requested topic, and "Why it matched" names
the request. A run stages at most the request's ceiling: accepted first, then
review, by score; the rest keep their evidence but are not queued, with the
reason recorded.

## 4. Runner

`python -m agents.collection.subscription_runner` — plan only by default (due
requests, skip reasons, exact queries; nothing searched, nothing written).
`--live` runs each due request, records a `collection_run` +
`actor_update_subscription_run` (append-only) linked to its search run, then sets
the next date or closes the request when its period ends. A failed request is
recorded, does not stop the others, and stays due. An advisory lock prevents two
runners at once. True spend is recorded even when the cost cap is overshot.

## 5. Schedule

- `agents/weekly_discovery.py`: the unconditional weekly actor sweep is
  **removed**. Events and the three event sources remain weekly, unchanged.
- New `.github/workflows/discovery-requests.yml`: daily 07:00 UTC. Scheduled
  runs are **plan only**; live needs a manual dispatch, or the repository
  variable `DISCOVERY_REQUESTS_SCHEDULED_LIVE=true`. That variable is unset and
  is the single switch that lets requests run on their own schedule — it needs
  supervisor sign-off (Architecture V2 rule 3).

## 6. Discovery page (this platform)

New sidebar item **Discovery** between Build the Map and Review. New request:
name, topic, sub-topics (chips, ≤ 8), area (region / state + optional city /
whole US), frequency (once, weekly, every two weeks, monthly, every three
months), start, duration (1 / 3 / 6 / 12 months or custom, max 365 days),
organizations per run. A sentence restates the request; **Preview searches**
shows the exact queries and first run date before saving. Requests list: status,
next run, runs, added to the map, sent to Review; pause / resume / cancel; per
request results (organizations found, with their band) and run history.

The page writes nothing itself: `/api/discovery/*` → `src/discovery/bridge.py` →
the backend command `agents.collection.discovery_requests`, the same pattern as
Review's admission bridge. Unconfigured, it says so and calls nothing.

Verified in the browser on the demo instance (port 8030): created "Energy
organizations in the Northeast" (3 months, weekly, battery storage + grid
modernization); preview showed 24 Northeast searches; pause and resume worked;
the runner's plan mode picked it up as due and wrote nothing.

## 7. Events and people

- **Events (still weekly):** new US-scope gate — an event whose own page names a
  country other than the US is rejected; a missing country is left unknown,
  never assumed. On demo data it changes exactly 2 of 25 events: Indonesia
  Critical Minerals Conference (was auto-accepted, 0.78) and AusIMM Critical
  Minerals 2026, Australia (was in review). Past events that are still accepted
  are the existing "minable" design (their named participants become actor
  leads) and were left as they are. Event thresholds unchanged: their scores are
  already sharply split (median 0.20) and the measured accepts were otherwise sound.
- **People:** unchanged and still disabled (feature flag, TARGETING_POLICY §6).

## Tests

| Repository | Result |
|---|---|
| Backend | 736 passed, 27 skipped, 3 failed — all 3 pre-existing, see below |
| Platform (pytest) | 281 passed, 1 skipped |
| Platform (node) | discovery 11/11, review 55/55, hub matching 6/6, map 9/9 (needs `--experimental-vm-modules`) |

New: `test_actor_quality_gates.py` (34), `test_discovery_requests.py` (28, incl.
the real pipeline run offline with a request), `test_discovery_request_runner.py`
(6, live against the disposable `ghus_v2_requests_test` only),
`test_actor_update_subscriptions.py` (+6), `test_discovery_bridge.py` (7),
`test_discovery_ui.mjs` (11).

Pre-existing failures, not caused by this work: `scripts/smoke_test_actor_merge.py`
(2 allowlist tests; from a 2026-10-13 session) and the installed `anthropic`
package being 0.116.0 while `requirements.txt` pins 1.0.0.

## Every modification

### Backend — `C:\Users\Ismail\Projects\GHUS-Platform`

New
- `agents/discovery/search/actor_quality.py` — bands, reject/accept gates, reasons, sub-topic check
- `agents/discovery/search/discovery_request.py` — request → scope, queries, per-run cap
- `agents/collection/subscription_store.py` — sole writer for requests and their run records
- `agents/collection/subscription_runner.py` — due-request runner (plan by default)
- `agents/collection/discovery_requests.py` — JSON command used by the Discovery page
- `agents/sql/550_v2_discovery_requests.sql`, `agents/sql/rollback/550_v2_discovery_requests.sql`
- `.github/workflows/discovery-requests.yml`
- `tests/agent/test_actor_quality_gates.py`, `tests/agent/test_discovery_requests.py`, `tests/db/test_discovery_request_runner.py`

Changed
- `agents/discovery/search/phase2.py` — gates wired in; request wording for "Why it matched"; per-run cap; event US-scope gate
- `agents/discovery/search/run.py` — accepts a request; request topic per candidate; refuses to scope events
- `agents/discovery/search/query_generation.py` — request queries replace the hub grid
- `agents/discovery/search/actor_scoring.py` — default thresholds 0.45 / 0.85
- `agents/collection/subscriptions.py` — biweekly; title, sub-topics, ceiling; `next_due`; validation mirrors 550
- `agents/weekly_discovery.py` — weekly actor sweep removed
- `agents/config/sources.yaml` — thresholds 0.45 / 0.85; `actor_quality`; `request_query_limit: 24`
- `config/architecture_v2.yaml` — biweekly; `discovery_page`; default ceiling 10
- Tests updated deliberately: `test_actor_update_subscriptions.py`, `test_agents_discovery_phase2.py` (weekly no longer sweeps actors), `test_agents_enrichment_phase4.py` (allowlist), `test_architecture_v2_schema.py` (550), `test_agents_open_web_discovery.py` and `test_agents_actor_rubric_pipeline.py` (new thresholds; fixtures made realistic)

### Platform — this worktree (`feature/review-redesign`)

New
- `frontend/discovery.js`, `frontend/discovery.css`
- `src/discovery/__init__.py`, `src/discovery/bridge.py`
- `tests/test_discovery_bridge.py`, `tests/test_discovery_ui.mjs`
- this report

Changed
- `backend/app.py` — `/api/discovery/status|options|requests|preview`, `/api/discovery/requests/{id}/{pause|resume|cancel}`
- `frontend/index.html` — Discovery nav item, breadcrumb, mount, stylesheet (Ask, Browse, Build the Map untouched)
- `scripts/run_demo_server.py` — configures Discovery against the same isolated `_test` database

### Databases (local only)
- `ghus_v2_demo_test`: 550 applied; one request created through the page. Test
  rows my first test run left there were removed (12 requests and their run
  records; the append-only trigger was bypassed for those rows only and re-enabled).
- `ghus_v2_requests_test`: new, from `ghus_v2_cutover_test` + 550, for the runner tests.

## Decisions needed

1. Approve migration 550 for production (schema owner).
2. Whether requests may run live on their schedule
   (`DISCOVERY_REQUESTS_SCHEDULED_LIVE`); until then scheduled runs only plan.
3. Thresholds 0.45 / 0.85 and the gate settings are configuration — confirm or adjust.
