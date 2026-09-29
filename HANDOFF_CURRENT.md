# UM6P Intelligence — Current Handoff

> **Latest consolidated handoff (21 September 2026):**
> [docs/CHAT_HANDOFF_2026-09-21.md](docs/CHAT_HANDOFF_2026-09-21.md).
> Read that file first. It reconciles the dated updates below, documents the
> latest people-search work and remaining tasks, and corrects stale statements
> about server reload, removed legacy modules, and repository-wide read-only behavior.

## Targeted people follow-up — 2026-09-18

People research now has two candidate-discovery queries followed by bounded
person-specific research. Queries adapt to university, government and company
roles. A deterministic relevance heuristic prioritizes profile, staff, project,
publication and grant pages for up to four page reads per query. Evidence is
deduplicated by URL and reuses per-task/parent caches; extraction sees at most
16 pages/excerpts at a time. Up to three candidates with at least one supported
criterion get up to two follow-ups for outstanding criteria. Stops occur on
no new evidence, no criterion improvement, sufficient assessed evidence or budget
exhaustion. Existing supported assessments survive merging. The $1 explicit
allowance remains unchanged; no live test was run, and improved quality/cost
is not yet measured. Affiliation validation remains conservative rather than
a full organization identity resolver. Backend restart required.


## People-search corrections — 2026-09-18

Extraction accepts bounded JSON-string/list wrappers using `entity_rows` without
paid parsing retries. Invalid/missing structured output raises ExtractionError;
people tasks preserve partial results and finish with error instead of done.
`people_queries` widens US .edu news subdomains to the university's .edu domain
and removes the exact quoted slash-combined name. General public suffixes are
not guessed. Explicit constituent-unit affiliation names are recognized, while
parent-only names, unrelated departments and guests remain excluded. Discovery
instructions now ask for separate units instead of combined actors. Supported
criteria need a quoted passage and supplied source URL; unsupported claims are
downgraded, including conference-only evidence for Africa project involvement.
These are conservative checks, not comprehensive fact verification.
Saved failed-run responses were parsed read-only without API calls. Historical
results/statuses were not rewritten. Restart the backend to load these fixes.


## University rankings — 2026-09-17

Map extraction now supports optional structured `rankings` for whole universities
only: QS World University Rankings and Times Higher Education World University
Rankings. Each entry carries position/band, edition year, overall/subject scope,
subject where relevant and a supplied source URL. `rankings.py` validates fields,
publisher and source membership, not claim truth. No extra ranking searches.
University cards show an expandable section, with "Not found in collected sources"
when absent. Labs/centers do not inherit parent university rankings. Exports format
available entries. No database schema change or retrospective paid backfill.
Restart the backend before new research uses these instructions.


## Funding summary refinement — 2026-09-17

Keep the existing `funding_summary` string. Extraction instructions now request
disclosed amounts/currencies and available funder, purpose and year from already
supplied sources. Preserve qualifiers and distinguish consortium totals from
the institution's share. No guessed amounts, currency conversion, new fields,
or extra funding searches. Existing saved results are not rewritten. The backend
needs a restart to use the updated extraction instructions.


## User-directed people discovery — 2026-09-16

Institutional maps no longer automatically search for missing people. People
already found in institution evidence remain. Each actor card now has a free-text
Find relevant people panel. Starting explicitly approves a separate $1 estimated
allowance, additional to the map budget; not a provider billing ceiling.
`people_research.py` performs two bounded queries using the organization, map
topic and criteria, with extraction and partial checkpoints. Cached parent pages
can be reused. Results stay in separate child tasks linked through SQLite
`people_tasks`, and reload under the organization panel. No main database writes
or export integration yet. Tasks have Stop and cost display but no automatic
retry/resume. Development tests use mocked model responses only. Backend restart
is required to load the new routes and workflow; the server was not restarted.


## Regional hub update — 2026-09-16

Build the Map cards now derive a regional ecosystem hub from the actor's US
state using National Geographic's five-region convention (Northeast, Southeast,
Midwest, Southwest, West). DC is Southeast by explicit application rule.
This replaces exact-city matching against the existing hub catalog. Country
must explicitly identify the US; unknown, multiple-state and territory locations
need review. Both `location_city` and `city` display correctly; city is optional.
This is frontend-only, works on saved maps, and costs no API credits. Database
hub records, Browse, saved payloads and exports remain unchanged. Regional
membership is not a topic-specific hotspot assessment.


## Cleanup update — 2026-09-15

The active entry point is now `build_map(description, plan=None, run=None)`.
Unused legacy workflows were removed: `build_map_legacy`, autonomous
`discover.py` and `enrich.py`, alternate planning entry points and unused
verification wrappers. Extraction schemas now live in `entity_schemas.py`,
and its lazy API client lives in `client.py`. `research.py` imports those modules
directly. Two legacy pipeline tests now cover the active controlled workflow.
The backend keeps legacy HTTP request fields for client compatibility, but no
longer forwards unused arguments into research. Earlier legacy-file descriptions
below and in historical documents refer to the pre-cleanup layout.


_Written 2026-09-13. Paste into a new chat to pick the project up cold._

> **This supersedes `HANDOFF.md`**, which is now materially wrong (it claims no
> persistence, no tests, placeholder colors, and describes a discovery pipeline
> that is no longer the active path). Keep it only as historical baseline.
>
> For the *narrative* of how the project got here — mentor feedback, decisions,
> what is a requirement vs a prototype vs done — read
> **`docs/PROJECT_CHANGE_HISTORY.md`**. It is the authoritative history and is
> carefully honest about what is and isn't finished. This file is the *current
> state* summary; it deliberately does not duplicate that narrative.

---

## 0. Read these, in this order

| File | What it gives you |
|---|---|
| **This file** | Where things stand right now, what's risky, what to do next |
| `docs/PROJECT_CHANGE_HISTORY.md` | Full narrative: decisions, mentor direction, limits per feature |
| `docs/MAP_COST_TRACKING.md` | Operational detail on budgets, recovery, cost semantics |
| `ARCHITECTURE_PROPOSAL.md` | Proposed data architecture (country → hub → actor → person). **A proposal — no migration has been applied.** |
| `HANDOFF.md` | Outdated. Historical only. |

---

## 1. What the platform is

An internal research platform for the **UM6P Global Hubs US team**. Local tool,
no authentication, runs on `localhost:8000`.

| Feature | Purpose | Costs money? |
|---|---|---|
| **Ask** | Question the existing database; SQL + semantic retrieval, cited answers | Yes (model calls, outside the map ledger) |
| **Browse** | Filter/inspect actors, hubs, events | No |
| **Build the Map** | Research organizations & people *beyond* current DB coverage | Yes — metered, budgeted |

**The database is READ-ONLY from this repo.** Schema and ETL are owned by a
colleague. The platform does **not** write map results into the main database.

---

## 2. Ground rules

- Working dir: `/Users/ghus/Desktop/um6p-rag`
- **Two Python environments exist.** The running server uses **`.venv`**
  (`.venv/bin/python`). A conda env at `~/.conda/envs/um6p` also exists. Use
  `.venv` to match the server.
- Run: `uvicorn backend.app:app --host 127.0.0.1 --port 8000`
- Open `http://localhost:8000/` — **never** open `frontend/index.html` via
  `file://`; the API routes require the server.
- Secrets in `.env` (git-ignored): `DATABASE_URL`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`.
- **Operate ONE API worker per SQLite store.** Avoid hot reload / restarts during
  paid work.
- Editing files restarts the dev server, which **interrupts an active map run**.
  Don't edit while a map is running.

---

## 3. Architecture as it is today

The active map path is **controlled research**, not the older autonomous loop.
`build_map` delegates to `build_controlled_map`. Legacy discovery code still
exists in the repo but is **not** the active workflow.

```
src/map_agent/
  research.py         ACTIVE controlled workflow — resumable, bounded, sequential
  search_backend.py   Claude search adapter; bounded page reads; evidence cache
  costs.py            THE paid-call gateway (estimates, reservation, settlement)
  run_store.py        Durable jobs/usage/checkpoints in SQLite; recovery
  relationships.py    People merging + multi-organization affiliations
  planner.py          Conversational planning; bounded task generation
  select.py           Request-based selection and ranking
  verify.py, judge.py Verification orchestration + model judgment
  export.py           Excel / PowerPoint output
  pipeline.py         Active entry point + retained legacy pipeline
  dedup.py, floor.py, urlcheck.py, discover.py, enrich.py   (supporting / legacy)
```

**How a map runs:** bounded plan → individual Claude web searches with
`max_uses: 1` → bounded evidence capture + limited direct page reads → structured
extraction (the extraction model **cannot browse**) → dedup + people linking →
request-based selection → progress and partial results saved as it goes.

Notable controls: citation filtering (model-returned URLs must belong to supplied
evidence), per-map caching of searches and page reads, worker-attempt tracking so
a stale worker can't spend against a newer attempt, and page-fetch restrictions
on address/port/redirect/content-type/size/duration.

---

## 4. Money — the part to understand before touching anything

This is the most carefully engineered area and the easiest to break.

- Every paid map call goes through **`costs.paid_message`**. Nothing else may pay.
- **New maps default to a $2 estimated budget**; an explicit recorded approval
  can raise the *same* map to **$3 total**. Approval does not itself start or
  resume work. Legacy saved budgets are left unchanged.
- Reservations are **integer micro-USD in SQLite transactions**, so pending calls
  count against the budget and concurrent work can't overspend.
- **Unknown charges retain their allowance and block further paid work.** A
  failure is never assumed to be free. This failure direction is deliberate.
- Unknown model pricing and unsupported tools are rejected **before** dispatch.
- SDK automatic retries are **disabled** in the paid path.
- Prices are a dated snapshot (`PRICING_DATE`, verified 2026-09-13).

**What it does NOT do:** it is *not* a provider billing ceiling. It is an estimate
from configured rates and reported usage. In-flight calls can still complete and
bill after Stop. Ask calls and a colleague's separate agent are outside this
ledger — a $2 map budget does not cap the shared API account.

**Known field issue:** Claude's `count_tokens` endpoint **rejects the server-side
web-search tool** (returns HTTP 400). The gateway falls back to a conservative
local UTF-8 size estimate plus headroom for those requests.

---

## 5. Persistence and recovery

- Jobs, messages, evidence, cost records and partial results live in
  **`.map_runs/runs.sqlite3`** (git-ignored). `MAP_RUN_DB` can point elsewhere.
- Saved maps are reopenable via a selector; the browser remembers the active map ID.
- **Startup recovery marks unfinished work interrupted and never auto-retries paid
  calls.** Continuation is an explicit action, never a side effect of reopening.
- Stop prevents *subsequent* paid calls; it cannot recall a dispatched request.
- Unresolved/unknown charges can block resume.

**Limits:** local to this machine. Not a cloud account, not a backup. Back up the
store if saved research must survive machine loss.

---

## 6. Testing

Offline suites now exist (the old handoff's "no tests" is obsolete).

| Suite | Covers |
|---|---|
| `tests/test_map_budget.py` | Billing math, reservations, races, cancellation, recovery |
| `tests/test_map_research.py` | Controlled research, evidence/search behavior |
| `tests/test_map_relationships.py` | People ↔ organization linking |
| `tests/test_map_ui.mjs` | Saved maps, stale responses, Stop, approval, continuation |
| `tests/test_hub_matching.mjs` | Location normalization, ambiguity, nonmutation |

Run Python tests (note: **unittest, not pytest**; pytest isn't installed):

```bash
.venv/bin/python -m unittest tests.test_map_budget tests.test_map_research tests.test_map_relationships
```

**Verified 2026-09-13: all 54 Python tests pass in ~0.5s, no network.**
JS suites were last recorded at 15 passing (9 map-state + 6 hub-matching).

---

## 7. UI state

Sidebar workspace layout: charcoal nav rail (Ask / Browse / Build the Map),
breadcrumb header, warm-gray workspace, white content panels. Brand orange
**`#D7410B`** (confirmed from the team's own workshop deck — the old `#ef7d1a`
was always a placeholder). All pages stay mounted when switching tabs, so a
running map is not interrupted by navigation.

**Uncommitted change made 2026-09-13 (CSS only, no behavior):** a motion layer was
appended to `frontend/index.html` just before the `prefers-reduced-motion` guard —
hover lifts, an orange rail that grows on the active nav item, prompt-card arrow
travel, button press feedback, a centre-out subnav underline, focus bloom on
inputs, staggered card entrance, and a sheen on the long-run progress panel.

> **Important detail if you touch entrance animations:** they animate
> **transform only, never opacity, with no fill-mode.** An earlier version faded
> content in and was caught leaving **11 elements stuck at `opacity: 0`** when the
> animation didn't start (hidden tab / throttled compositing) — i.e. a blank page.
> Worst case must be "no movement", never "no content".

**Known CSS debt:** there are **four stacked `:root` blocks** (~83 lines of
overrides on top of the original stylesheet) with three competing palettes.
`--serif` is aliased to `--sans`, so that token now lies. **Dark mode is dead** —
the override sets `color-scheme: light` and lands after the dark media query;
confirmed by forcing dark and getting an identical render. Consolidating into one
token set is unglamorous but would make future design work much safer.

---

## 8. Git state — read this before doing anything

Last commit: **`8228dbb`** (export feature). **A large amount of work is
uncommitted**, including the entire controlled-research architecture:

- **Modified:** `backend/app.py`, `frontend/index.html`, `.env.example`,
  `.gitignore`, and most of `src/map_agent/*.py`
- **Untracked:** `src/map_agent/{costs,run_store,search_backend,research,relationships}.py`,
  `tests/`, `docs/`, `ARCHITECTURE_PROPOSAL.md`, `HANDOFF.md`, `outputs/`, `.codex_tmp/`

A lost working directory loses the cost system, persistence, controlled research,
and all tests. **Committing this is the single highest-value next action.**
Verify push state with `git log origin/main..HEAD` — earlier commits may or may
not have been pushed.

---

## 9. Open issues, in the order I'd address them

1. **Commit the uncommitted work.** Everything else is at risk until this happens.
2. **Reconcile the cost ledger with provider billing.** One completed map showed
   ~$2 on the Claude platform while the local estimate was lower, and that gap is
   unexplained. *The entire budget system rests on estimates matching reality* —
   this deserves to be the top functional priority, above where the change-history
   doc lists it.
3. **Live acceptance test of Verify / Verify All.** Previously reported
   nonfunctional; handlers and wiring now exist, but there is explicitly **no
   claim of a live test**. "Implemented" is not "working".
4. **Measure wall-clock for a controlled map.** The old path ran 10 parallel
   workers and ~12 minutes was already the complaint; the new path is sequential
   but bounded. Nobody has a current number. Don't assume it improved.
5. **`actor.city` vs `location_city`.** The hub matcher reads `actor.city`; older
   mapping schemas use `location_city`. Records with only the latter are silently
   flagged incomplete.
6. **Database admission workflow.** Nothing writes to the main DB. Reviewer
   experience and admission criteria still need agreement with the DB owner.
7. Remaining meeting items: geography override, completion notifications, batch
   verification exclusions, criteria-based event discovery, the colleague's
   update-agent criteria.
8. Authentication / per-user history / shared deployment — separate, later phase.

---

## 10. Things that will bite you

- **Editing files restarts the server and interrupts a running map.** Don't edit
  mid-run.
- **One worker per SQLite store.** More than one will corrupt budget accounting.
- **Don't add a second paid-call path.** Everything must go through
  `costs.paid_message` or the ledger silently becomes wrong.
- **Don't treat a failed paid call as free.** The system deliberately blocks on
  unknown charges; "fixing" that by assuming $0 would reintroduce overspend.
- **The `$2` default vs real map cost** — historical maps were reported at ~$2–4
  and one test reached ~$7. If maps stop early, the budget is the likely cause,
  not a bug.
- **Existing-hub suggestions are frontend-only.** They are not stored, not
  exported, and a primary-city match does not prove ecosystem membership.
- The map's people model is **organization-first** — people are nested under
  actors, with a normalized top-level collection kept for API/export
  compatibility. Person identity uses normalized names and *can conflate people
  who share a name*.

---

## 11. Scope discipline that has served this project well

`docs/PROJECT_CHANGE_HISTORY.md` consistently separates **agreed requirement**,
**prototype**, and **completed database change**. Keep doing that. Several items
here look done but are explicitly not: hub integration (phase 1 suggestions only),
database writes (none), verification (implemented, unverified), architecture
(proposed, unmigrated).

Cost and latency figures in this project have a track record of being wrong when
estimated and right only when measured. Prefer `resp.usage` and a stopwatch over
reasoning about what something "should" cost.
