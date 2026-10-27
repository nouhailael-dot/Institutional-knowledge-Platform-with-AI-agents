# On-request Event and People Discovery (2026-10-23)

Scope: Event and People discovery gain an on-request mode on the Discovery page,
beside the automatic mode. Actor Discovery is unchanged. Nothing was committed,
pushed, merged or written to shared Supabase. Migration 580 was applied to the
local demo database (`ghus_v2_demo_test`) only.

## Decisions taken before implementing (conflicts with Architecture V2 Sept)

| Brief asked | Architecture says | Decision (GHUS, 2026-10-23) |
|---|---|---|
| Automatic People Discovery, if approved | 5.3: people are "not collected automatically"; only when GHUS asks | **On-request only.** No automatic People job. Supervisor approval is recorded; People runs are enabled through Discovery-page requests. |
| Event Light Pull with speakers, participating organizations, agenda | 5.4: themes are Deep Pull; speakers, organizations, agendas, sponsors are a Specific ask | **Always collect them**, each item checked on the page. |
| "Do not admit low-information events" | 5.4 lists "date unconfirmed" as a state | A date or place missing after the bounded follow-up excludes the event (reason kept). |

## 1. Automatic workflow status

| | Event | People |
|---|---|---|
| Automatic job | `.github/workflows/weekly-discovery.yml`, cron `0 6 * * 1` (Monday 06:00 UTC), unchanged | None, by decision |
| Entry point | `python -m agents.weekly_discovery` -> `agents.discovery.search.run --entity event` (+ climate_week, unga_programme, unga_guide) | - |
| Live or plan | Scheduled run is dry-run; live only by manual dispatch with `live` ticked (AGENTS rule 3) | - |
| Env / flags | `DATABASE_URL`, `ANTHROPIC_API_KEY`, `GHUS_AGENT_CONTACT_EMAIL` secrets; `open_web_discovery.fetch_enabled`, `max_usd_per_run` 5.00 | `open_web_discovery.people_enabled: true` |
| Database | the workflow's `DATABASE_URL` secret | - |
| Run logging | `scrape_run` (stats, cost, status), `raw_document`, `search_candidate`; reports/audit CSV uploaded as artifacts; `source-outcomes.md` | - |
| Review routing | every qualified event -> `event_review_queue` -> Review "Discovery Events" | - |
| Errors | a step at a cap is "attention", not failure; one page never stops a run; a failed run is recorded with its reason | - |

## 2. On-request workflows

Discovery -> New request now asks **Organizations / Actors, Events or People**.
Organizations shows the existing form exactly. Events and People show their own
forms and use the same request table (`actor_update_subscription`, plus
`discovery_entity` and `discovery_options` from migration 580), the same command
(`agents.collection.discovery_requests`), the same scheduler
(`agents.collection.subscription_runner`, `.github/workflows/discovery-requests.yml`,
daily plan, live on "Run now" or dispatch) and the same pipeline as the automatic
runs. There is no second scheduler.

- **Events form:** name, sector, topic and sub-topics, geographic scope, event date
  range, event types (up to 4), start, frequency and duration, Preview searches,
  Save request, Run now.
- **People form:** name, sector, topic or expertise, institution (optional),
  geographic scope, role or specialization (optional), start, frequency and
  duration, Preview searches, Save request, Run now.
- Queries come only from the request (`request_event_queries`,
  `request_person_queries`); no model is called to write them. Results outside the
  request (dates, area, institution) are excluded with the reason. At most the
  request's per-run number of new records is kept (default 10).
- Run types are recorded on every run: `stats.run_trigger` = `automatic` or
  `on_request`, with the request's title and scope.

## 3. Light Pull fields

**Events** (record + checked facts): name, website, type, start and end dates,
city/state/country or online format, organizer, description, sector and topic,
recurrence, upcoming / past / date unconfirmed, themes or agenda, registration
link and deadline, status, confirmed speakers, participating organizations,
UM6P/OCP involvement, publicly stated scale or standing claims, why it matched,
and evidence (quote, page, date read) for every fact.

**People** (five-field record + checked facts): name, title, organization, research
area, public profile; department, expertise, up to three named works, work
location (city/state as stated, never a home), other affiliations, UM6P/OCP
connection, LinkedIn (only when the official page links this person's own
profile; never fetched), why it matched, evidence for every fact. No contact
details, no biography text.

## 4. Gates and outcomes

Same gates in both modes (`agents/discovery/quality_gates.py`):

- **Qualified for Review** - events: official source, one named event, relevance,
  date, place or online format; people: name, identity source (official profile or
  matched LinkedIn), current affiliation on the page, relevance.
- **Needs More Research** - official and relevant but missing a date or place
  (event), or named and relevant but not yet identified or placed (person). One
  bounded follow-up reads an official page (`agents/discovery/search/followup.py`:
  the event's own site or its agenda/venue page; the person's official profile;
  never social or directory pages; at most 5 per run, 2 fetch attempts each). Still
  missing -> excluded, reason kept.
- **Excluded** - cancelled, news or listing page, not one event, irrelevant,
  outside the request, duplicate.

Every qualified event and person goes to the Review queues. Nothing is created on
the map until a person verifies it (previously a confident event was created as
Parked and never appeared in Review; a confident person was created directly).

## 5. Search and extraction

Deterministic queries from the request; URL dedupe; events already on the map or
already waiting in Review are skipped before fetching (overlapping runs cannot
stage the same record; live event and people runs also take an advisory lock);
readable page text instead of raw HTML; cached analyses reused; bounded official
follow-up; robots.txt respected by the existing fetcher. Cost recorded by stage:
search, triage, pages, ranking, follow-up, participants.

## 6. Review

Runs are listed under Discovery Events / Discovery People by name; both kinds of
record of one run (review-band candidates and queued staged records) share that
name, so a run is listed once. Selecting a record shows its "Collected
information": outcome, completeness, timing, why it matched, each check, and one
box per fact with quote, source and date read. Verify, Park and Reject and the
admission bridge are unchanged. (A run summary in boxes was tried and removed on
2026-10-24 at GHUS's request: the run's own report and the evaluation script keep
those figures.)

## 6a. United States only (2026-10-24)

Excluded results were mostly events abroad, found because the automatic run
searched for them ("World Food Forum Rome 2026", "Critical Minerals Summit
Bali", "Global Framework on Chemicals conference Geneva"). Now, before any
spend (`agents/discovery/search/us_scope.py`, events and people only):

- the model writing event searches is told United States (or online) only, and
  any search naming a foreign country, region or city is not run, whoever wrote it;
- the map's own event locations steer searches only when they are in the US;
  the fallback place is "United States" (was "global"), and the UM6P query asks
  for US events;
- a result on a foreign country domain, or whose title and snippet name a
  foreign place and no US place, is excluded before triage and reading, with
  that reason. A US place wins ("Africa Energy Forum, Houston, Texas"); online
  events are never dropped here.

Replayed on the recorded automatic run: 8 of 69 searches would not have run
(about $0.18), 83 of 358 results would have been excluded before triage, and no
record that reached Review would have been lost.

## 6c. People: targeted search, complete profiles only (2026-10-25)

The first live people runs found 39 results and no usable profile: news,
Wikipedia, conference speaker lists, LinkedIn pages. The People agent now goes
where a complete profile is (`agents/discovery/search/people_targets.py`):

- **Where it searches:** only the official sites of the institutions the map
  already holds in the requested state and topic (universities, research
  centres, national laboratories, government; universities and laboratories
  only when the role is academic), at most six sites per search, through the
  search tool's `allowed_domains`. A named institution: only its site. "Battery
  storage researchers in Texas, professor": 2 searches on tamu.edu, rice.edu,
  utexas.edu, uh.edu, bakerinstitute.org (was 6 open-web searches).
- **What it reads:** only a person's own profile page (/people/<name>,
  /faculty/<name>, /profiles/..., ~user). A people directory is opened without
  a model call and the profile links of the people whose listing mentions the
  topic are followed (at most 3 directories x 6 people). News, stories, events,
  documents and everything else are dropped before triage.
- **The rule:** a person reaches Review only with name, title, current
  organization stated on the official page, expertise, GHUS relevance and a
  professional bio copied from the page (kept only if its text is on the page;
  never family, age, home or contact) or a matched public LinkedIn URL.
  Otherwise: one more official-page read, then one LinkedIn-only search for the
  name and organization (the URL taken from the result title only when it
  carries the full name and the organization; LinkedIn never opened); still
  incomplete: excluded, with the reason.
- Review shows the bio and LinkedIn first in the person's boxes.

## 6b. Cost ceiling and caching (requested 2026-10-23)

- **Automatic event run ceiling: $5.00 -> $3.00** (`event_max_usd_per_run`).
  Every recorded live event run cost $0.13-$2.36 (mean $1.46, 16 runs), so no
  run would have been stopped; the new follow-up and participant reads add about
  $0.25 at most. A run that does reach the ceiling loses nothing: its unstaged
  pages are read again by the next run (from the analysis cache - no second
  model call). Actor and people runs keep $5.00; requests keep $1.00.
- **Search cache** (`agents/discovery/search/search_cache.py`): an identical event
  or people search within 72 hours is answered from disk. 146 of 505 event
  queries were exact repeats of an earlier run's. The weekly run is 7 days apart,
  so it always searches fresh: quality is unchanged; retries, re-runs and
  overlapping requests stop paying twice. Live: the third people run answered
  6 of 6 searches from the cache and cost $0.05 instead of ~$0.21.
- **Analysis cache keyed by readable text**: the page analysis is also stored
  under (address + readable text). 5 of 7 event pages re-read with changed HTML
  had identical text; the second event attempt paid $0.22 again for pages
  already analysed. Same address and text is the same model input, so the
  answer is reused unchanged.
- Not cached on purpose: triage (batched with sector and reference context that
  changes as the map grows - a cached decision could go stale) and the actor
  pipeline (unchanged by decision).

## 7. Robustness fixes found by the live test

- Participant extraction failing (a dropped API connection) no longer fails the
  run after every page was read and paid for.
- A page last read by a failed run, or by one stopped at its cost ceiling, is
  read again instead of being skipped as "unchanged" forever (events and people
  only).
- An unsure affiliation match (`route_person` via `route_actor`) routed a person
  to review with the ORGANIZATION's id as the matched person; the
  `person_review_queue` foreign key refused it and failed the run. The
  organization is now kept as `affiliation_candidate_actor_id`; the person goes
  to Review with no matched person. (Pre-existing; never reached before because
  People Discovery had not run live.)
- The demo database lacked migration 170 (`person_review_queue.affiliation_raw`,
  in the approved additive set of 2026-09-28); applied there only.

## LIVE_RESULTS

## Files changed

Backend: `agents/sql/580_v2_event_people_requests.sql` (+ rollback),
`agents/collection/{subscriptions,subscription_store,discovery_requests,subscription_runner}.py`,
`agents/discovery/search/{discovery_request,query_generation,run,phase2,followup,search_cache,event_scoring,person_scoring}.py`,
`agents/config/sources.yaml` (`event_max_usd_per_run`, `search_cache_ttl_hours`),
`agents/discovery/{quality_gates,page_facts,run}.py`, `scripts/evaluate_people_events.py`
(`--runs`), `evals/people_events_gold.jsonl`, tests
`tests/agent/test_event_people_requests.py` (new), `test_quality_gates.py`,
`test_actor_update_subscriptions.py`, `test_discovery_requests.py`,
`test_agents_open_web_phase2.py`.

Platform: `backend/app.py` (request model), `frontend/discovery.js` + `.css`
(selector, Events and People forms, request cards), `src/review/postgres_source.py`
(run summary), `frontend/review.js` + `.css` (run summary, outcome, new fact boxes),
tests `tests/test_review_discovery_runs.py` (new), `test_discovery_ui.mjs`,
`test_review_ui.mjs`.

## Approval and deployment still required

1. Migration 580 on shared Supabase (schema owner); 550 and 570 are prerequisites.
2. Deploy both repositories together (the platform sends `discovery_entity`).
3. The browser UI could not be checked visually in this environment (the in-app
   browser and headless Chrome both stall on page load here); check the Discovery
   forms and the Review run summary in a normal browser before release.
4. `TARGETING_POLICY.md` is still not in the repository.
5. Review with Nouhaila: the shared scorers, gates and the Review routing change.
