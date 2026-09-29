# UM6P Intelligence Platform — Detailed Chat Handoff

Prepared for Nouhaila on **21 September 2026**. Project: `/Users/ghus/Desktop/um6p-rag`.

## 1. Instructions for the receiving chat

### Subsequent update: official ranking lookups

The user authorized dedicated QS/THE lookups. New maps now look up selected whole universities after selection: one search per publisher on topuniversities.com and timeshighereducation.com, up to three official-domain pages each, within the existing parent map allowance. Only matching university names and explicitly evidenced overall rankings/years are merged. Progress is checkpointed per lookup. Completed saved maps are not automatically rerun. Offline Python suite: 87 passing tests; live lookup quality untested. This supersedes the earlier instruction against additional ranking searches.

### Subsequent update: people allowance

The user subsequently approved a $3 estimated allowance per new people search, replacing $1. Backend creation and UI approval now use $3. Existing saved task budgets remain unchanged.

### Subsequent update: people query planning

People discovery now uses one tracked Claude call (`People query planning`) to prepare two initial queries from the full people request, parent map topic and organization identity. It shares the existing $1 child allowance. Invalid structured output falls back to the existing templates without a planning retry; API failures and budget stops propagate. Domain restrictions are checked against the supplied source-supported website. Missing websites permit organization-name searches. Follow-up query generation is unchanged. The Python offline suite now passes 85 tests; live quality for this planning change has not been tested. Saved earlier runs are unchanged. Page certificate failures remain unresolved.

Read this document before making changes. It combines the user's decisions, the implementation state, known limitations and the next work. Treat current source code as authoritative for implementation details. Older handoff documents contain superseded descriptions.

- Collaborate with Nouhaila; explain changes in clear language and work one issue at a time.
- Preserve the existing uncommitted changes. Do not reset the repository or restore deleted legacy modules.
- **Do not run paid API tests, embeddings, research, Ask queries or database migrations without explicit authorization.** Offline mocked tests are safe.
- Do not infer permission to increase budgets from the user's preference for better quality.
- Do not expose `.env`, API keys, connection strings or private research records.
- Do not restart a server during active research without checking and coordinating first.
- Distinguish research results, evidence-supported criteria, independent verification, human approval and admission to the production database. They are different stages.
- The immediate next step is to test the latest people-search improvements with the user, not to start another broad redesign.

## 2. Executive summary and current checkpoint

This is an internal research platform for **UM6P Global Hubs US**. Nouhaila owns the platform work in this repository. Her colleague **Ismail** works on database/schema matters and a separate agent that continuously finds and updates actors and people within topics already represented in the database.

The platform offers:

- **Ask:** answers questions using existing database information, with SQL and semantic retrieval.
- **Browse:** filters and displays database actors, hubs and events.
- **Build the Map:** researches information outside existing database coverage; presents organizations and associated people; provides verification and Excel/PowerPoint exports.

The recent focus has been **Build the Map cost control and people-search quality**. Automatic deeper searches for people were replaced with an explicit, organization-specific search box. The user describes the people they want, approves a separate allowance, and sees people attached to that organization.

The latest implementation adds targeted follow-up research for promising people whose requested criteria are only partially supported. It has passed offline tests, but **its real-world improvement in quality, completeness, cost and time is not yet measured**.

### Checked during preparation of this handoff

- No process was listening on TCP port **8000** when checked on 21 September 2026. The backend was not started during handoff preparation.
- Python suite: **78 tests passed**.
- JavaScript suite: **15 tests passed**.
- These were offline tests; no live Claude research was initiated.
- Production database schema/content was not freshly audited for this handoff.
- Latest visible Git commit: `8734605 ActorsPeople Connection`. Many newer changes are **uncommitted**, including new source modules and tests.

## 3. How to run and test safely

Work from the project directory and use its `.venv`, not an unrelated Conda environment.

```sh
cd /Users/ghus/Desktop/um6p-rag
env MAP_RESEARCH_ENABLED=1 MAP_SEARCH_PROVIDER=claude .venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/**. Do not open `frontend/index.html` via `file://`: API calls need the backend. Starting the server alone does not start paid research.

Useful read-only checks:

```sh
lsof -nP -iTCP:8000 -sTCP:LISTEN
curl http://127.0.0.1:8000/api/health
git status --short
```

Offline regression commands:

```sh
.venv/bin/python -m unittest discover -s tests -q
/Users/ghus/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --experimental-vm-modules --test tests/test_map_ui.mjs tests/test_hub_matching.mjs
```

Use **one API worker per local run store**. The command above has no hot reload: Python changes require a restart; frontend changes require a browser refresh. Older notes saying every edit automatically restarts the server do not apply to this command.

Before restarting a running server, inspect local runs for `planning`, `running` or `verifying` work. Use a read-only SQLite connection for diagnostics. Stopping/restarting cannot undo charges for an already submitted request. Startup recovery marks unfinished work interrupted; it does not automatically retry paid work.

## 4. Important user and manager decisions

### Product and workflow

- Keep UM6P orange branding, with a professional, interactive UI. The user disliked a white-on-white design.
- US-first research is the default. Explicit geography override was requested, but should not be claimed fully implemented without end-to-end validation.
- No narrow central policy defining which institutions are universally “best.” Broad guidance and a team prompting guide were preferred. Later requests for GHUS relevance/engagement fields need alignment with this decision, not an invented automatic exclusion policy.
- Organization discovery should precede optional deeper people research. Keep people already found in organization evidence.
- People search uses a **free-text box**, not a fixed set of criteria fields.
- A person may be affiliated with multiple organizations. Persistent production-database support still needs coordination with schema ownership.
- User asked about hiding criteria-assessment text, then chose to test first. The warnings remain; do not treat their removal as completed.

### Funding

- Keep the existing `funding_summary` field.
- Include disclosed amounts/currency and available funder, purpose and year from collected evidence.
- Preserve qualifications such as “up to”; distinguish consortium totals from an organization's own allocation.
- Do not guess missing amounts or infer awards from opportunities.
- No additional funding-specific search, new funding table or manual funding button was requested in this implementation.

### University rankings

- Only **QS World University Rankings** and **Times Higher Education World University Rankings**.
- Whole universities only; do not give a lab or center its parent university's ranking.
- Keep rank/band, edition year, overall versus subject scope, subject if applicable, and source.
- No additional ranking searches; use collected evidence.
- Field/source validation does not independently prove the ranking claim or its currentness.

### Hubs and regions

- An ecosystem hub was initially defined as a geographic concentration with academic excellence, applied research, industry, expert talent, innovation platforms and global engagement.
- A seventh dimension, Africa-focused partnership potential, was explicitly set aside for now.
- The latest practical decision is to assign actors to **five US regions**; this is not the same as proving a topic-specific hotspot.
- No numerical ecosystem score was agreed. The user specifically corrected an earlier suggestion that managers had requested one.

### Cost

- User has experienced unexpected spending, including a reported $7/20+ minute run and account balance movements that could include a colleague's activity.
- They prioritize search quality now, but still need explicit spending controls.
- Current defaults: **$2 estimated map allowance**, explicit extension to **$3 total**, and **$1 separate allowance per deeper people search**.
- These are local estimated allowances, not guaranteed provider billing caps.
- Do not reuse early quoted demo costs as measured current performance.

## 5. Architecture and where files fit

```text
Browser: frontend/index.html
  ├─ Ask / Browse → backend/app.py → database retrieval modules
  └─ Build the Map → backend/app.py
       ├─ planner.py → pipeline.py → research.py
       │                              ├─ search_backend.py
       │                              ├─ entity_schemas.py / client.py
       │                              ├─ dedup.py / relationships.py
       │                              └─ rankings.py / people_validation.py
       ├─ actor-specific people task → people_research.py
       ├─ verification → verify.py → urlcheck.py / judge.py / floor.py
       └─ exports → export.py

Tracked model calls → costs.py → run_store.py → .map_runs/runs.sqlite3
Production actor/hub/person database is separate from this local run store.
```

### App and database modules

- `backend/app.py`: FastAPI routes, background jobs, local run lifecycle, people tasks, verification, exports, and serving the frontend.
- `frontend/index.html`: active single-file React/HTM UI; no separate frontend build. Includes map planning/results, cost/status controls, organization cards, people panel, regional hub display and ranking display.
- `app.py`: older Streamlit application; not the active web frontend.
- `src/db.py`: Postgres connection helpers, including read-only connections.
- `src/router.py`: Ask routing, SQL planning/safety checks and SQL answer generation.
- `src/retrieve.py`: vector and keyword retrieval with result merging.
- `src/generate.py`: conversational question condensation and answer generation/streaming.
- `src/assemble.py`: assembles database entities into searchable content.
- `src/browse.py`: loads and normalizes actors/hubs/events and supports filtering.
- `src/embed.py`: embedding/index-building utility; **can write the search index and incur API costs**. Do not describe the entire repository as read-only.
- `src/documents/`: document extraction, chunking and document context storage.
- `src/enrich/`: separate older enrichment code. Do not assume it is Ismail's current agent or active Build the Map research without checking its caller.

### Map modules

- `pipeline.py`: small active entry point, `build_map(description, plan=None, run=None)`, delegating to `build_controlled_map`.
- `planner.py`: conversational map planning (`map_chat`) and bounded research tasks.
- `research.py`: controlled institution research, evidence extraction, checkpoints and result finalization.
- `search_backend.py`: Claude web-search adapter, bounded page reads, evidence handling and caching.
- `entity_schemas.py`: structured extraction tool schemas.
- `client.py`: lazy extraction API client.
- `costs.py`: tracked paid-call gateway, reservations, usage settlement and cached responses.
- `run_store.py`: SQLite jobs, call ledger, budget approvals, work cache, child people tasks, recovery and cancellation.
- `people_research.py`: explicit organization-specific discovery and candidate follow-up research.
- `people_validation.py`: extraction parsing, conservative affiliation matching and criterion evidence checks.
- `relationships.py`: people merging and organization affiliation relationships in map results.
- `dedup.py`: entity deduplication/merging.
- `rankings.py`: university ranking field/source validation and formatting support.
- `select.py`: request-based entity selection/ranking; not an agreed ecosystem-hub scoring methodology.
- `verify.py`: orchestrates link checks, model judgment and relevance-floor annotations.
- `urlcheck.py`, `judge.py`, `floor.py`: those individual verification components.
- `export.py`: branded XLSX/PPTX generation from map results.

### Removed legacy code

The unused autonomous `discover.py`, `enrich.py` within `src/map_agent/`, `build_map_legacy`, alternative planner entry points and unused verification wrappers were removed. Shared schema/client logic was moved into the modules above. Do not restore these merely because historical docs mention them. Legacy HTTP request fields remain for compatibility; that does not mean the old workflow is active.

## 6. Current Build the Map workflow

1. Create a tracked session and clarify the request through the map planner.
2. Produce a bounded research plan, up to four topic queries.
3. Execute controlled Claude web-search requests, each allowing one server-side search use.
4. Read a bounded number of pages and extract structured entities from supplied evidence.
5. Validate source membership, deduplicate and checkpoint partial results.
6. Finalize organizations and any people already present in the collected institution evidence.
7. User optionally requests deeper people discovery from an individual organization card.
8. User can run existing verification and export map results.

The institution path uses up to ten search hits and normally up to three full-page reads per query, with bounded source excerpts. **A search hit is a page/result, not a distinct researcher.** Seven hits may yield one usable person after extraction, deduplication, affiliation and evidence checks.

Automatic deeper people research is no longer run for every organization. This was an important cost/workflow change.

### Persistence and navigation

- Runs, partial results, calls and checkpoints persist in `.map_runs/runs.sqlite3`.
- Work executes on the backend, so changing app tabs does not cancel it.
- Saved maps can be reopened and polled without automatically buying more research.
- Recovery after a stopped backend is not the same as keeping an in-flight request alive.
- Stop prevents further work where possible; an already submitted provider request may complete and be charged.
- Production database admission is not implemented by saving a map locally.

## 7. Organization-specific people search — latest work

### User experience

- Expand **Find relevant people** on an organization card.
- Describe the desired people in free text.
- Explicitly approve the **$1 allowance and search**.
- See progress, estimated spend, stop control, resulting people, evidence/criteria annotations and sources.
- Opening the panel/history itself does not make a paid request.
- Existing institution-discovered people remain; the new search is a separate child task.

### Backend/API

- `GET /api/map/{job_id}/people`: retrieve child task history for an actor.
- `POST /api/map/{job_id}/people`: explicitly start a child task with actor name, website, criteria, request key and approval.
- Actor is resolved against the saved parent map rather than accepting an arbitrary actor payload.
- Atomic task creation and request keys reduce duplicate requests; an active task for the same parent actor is rejected.
- Child status/stop use normal map status and stop routes.
- Child tasks have their own cost allowance; it is **additional to**, not included in, the parent map's displayed budget.
- SQLite `people_tasks` links child run IDs to parent/actor/request identity.
- No automatic child retry/resume flow or child-specific budget-extension UI.
- Deeper people results are not yet integrated into parent exports or production database insertion.

### Latest search-quality improvements

- Start with two discovery queries, adapting vocabulary for universities, government agencies and companies.
- Widen US `.edu` news subdomains to the university domain; do not guess arbitrary public suffixes.
- Avoid searching a slash-combined organization name as one exact quoted phrase.
- Reuse cached parent pages and per-task evidence where available.
- Prioritize likely profile, staff, team, faculty, publication, project and grant pages with a deterministic relevance heuristic.
- Read up to four full pages per people query; fall back to search excerpts when necessary and disclose this.
- Deduplicate evidence by URL; extraction receives at most sixteen pages/excerpts at a time.
- Consider up to three candidates with at least one supported criterion and at least one outstanding criterion.
- Give each up to two bounded, person-specific follow-up queries directed at missing criteria.
- Stop when no new evidence appears, no criterion improves, assessed criteria are supported, or the budget stops further work.
- Preserve previously supported assessments when merging follow-up results.

These are upper bounds, not promises that the $1 allowance can fund every follow-up. Candidate ordering is a heuristic, not a proven optimal ranking. Candidates with no supported criteria currently do not receive targeted follow-up; that can miss worthwhile people.

### Evidence and affiliation checks

- Structured extraction accepts supported JSON string/list wrappers without buying an extra parsing retry.
- Malformed/missing structured output raises `ExtractionError`; partial results are retained and the task finishes with an error rather than falsely appearing successful.
- Affiliations must explicitly match the actor or recognized constituent units of a combined actor. Parent-only or unrelated affiliations and guest/speaker associations can be rejected.
- A supported criterion needs a supplied source URL and a sufficiently long quote appearing in the available evidence excerpt.
- Conference participation alone is not accepted as proof of participation in an Africa-based project.
- These checks are conservative heuristics, **not comprehensive independent factual verification**.
- “Not established” means the collected evidence did not establish the criterion, not that the person definitely fails it.
- “Not independently verified” means the separate verification stage has not established that person's record; it is not itself a claim that the record is false.

### Known limitations to evaluate next

- Full organization identity resolution is not implemented; government/parent/unit naming variants remain difficult.
- Page access can fail and search excerpts may be insufficient.
- The model's selected criterion labels do not guarantee exhaustive coverage of every user requirement.
- Quote presence does not prove a quote logically supports the whole claim.
- The internal `research_status` field is not currently displayed in the people UI.
- People panel browser/hook coverage is less complete than map navigation tests.
- Cached extraction operation keys were not comprehensively versioned for every prompt change; resumed old runs may reuse earlier responses. Prefer a clearly identified fresh test when evaluating changed prompts.

## 8. Failure history that motivated the fixes

The user tested:

> Find researchers working on water treatment who have published since 2023 and led or participated in projects in Africa.

An organization was represented as “University of Florida Water Institute / Center for African Studies,” using a news subdomain. The search was too narrowly aimed at that combined name/domain. Two extraction responses were rejected because their entity lists were encoded as JSON strings rather than the expected list shape. The old UI then showed no supported people and a successful-looking completion.

- Relevant historical child run: `53a1e08d290044469cbfb4ba301aba37`.
- Recorded local estimate: `$0.196624` (approximately `$0.197` in the UI), not an independently reconciled provider invoice.
- Saved responses were examined and parsed offline. Historical run statuses/results were **not rewritten**.
- Parser, query generation, affiliation and evidence handling were corrected; extraction errors now surface properly.
- The later targeted follow-up improvements still need a live evaluation.

A separate Bureau of Reclamation test showed seven page hits but only one researcher, with two records excluded for missing source/affiliation support. Page counts must not be presented as expected people counts; the exact exclusions should be investigated using saved evidence before loosening safeguards.

## 9. Cost tracking: what exists and what it does not guarantee

`costs.py` requires a tracked run before a paid map call. It reserves allowance before the request, then settles using reported usage. Calls and pending/unknown amounts are persisted. Cached operations can be reused without another model call.

- Money is tracked in integer micro-USD.
- SDK automatic retries are disabled; requests have a timeout.
- Missing/ambiguous usage is not assumed to be free.
- Claude server-side search is restricted to the supported one-search configuration.
- The token-count endpoint rejects server tools. The bounded search path therefore uses a conservative local request estimate plus search-result headroom, instead of sending that tool to `count_tokens`.
- Other supported calls use token counting before reservation.
- Current code pricing snapshot is dated `2026-09-13`: `claude-sonnet-5` input/output 2/10 USD per million tokens, Haiku 1/5, search $0.01/request. **These are the code's configured assumptions, not pricing freshly verified for this handoff.** Check provider documentation/account billing before asserting exact costs or changing models.
- Local estimates previously differed from Claude dashboard spend. Reconciliation is still pending; shared account usage may be a factor but must not be assumed to explain every discrepancy.
- Ask and separate embedding workflows are not covered by the map ledger.
- Reservation checks limit subsequent work; a single call may exceed an estimate. Therefore an allowance is not a hard provider-side billing ceiling.

## 10. Hub implementation and remaining integration

Current regional assignment is deterministic **frontend-only**. It uses explicit US country plus a recognized state; city is optional. Unknown, non-US, multiple-state and territory cases are left for review rather than guessed.

Five-region mapping currently used:

- Northeast: CT, ME, MA, NH, NJ, NY, PA, RI, VT.
- Southeast: AL, AR, DE, FL, GA, KY, LA, MD, MS, NC, SC, TN, VA, WV; DC is included by an explicit application rule.
- Midwest: IL, IN, IA, KS, MI, MN, MO, NE, ND, OH, SD, WI.
- Southwest: AZ, NM, OK, TX.
- West: AK, CA, CO, HI, ID, MT, NV, OR, UT, WA, WY.

It follows the selected National Geographic-style convention, not a claim that there is one universal US five-region standard. It requires no extra model calls and works on saved maps.

**Not done:** database hub migration/relationships, Browse alignment, storing regional assignment in results, export inclusion, or topic-specific hotspot assessment. Do not claim every actor has already been linked to a production hub record.

## 11. Verification, approval and exports

Unlike the earliest meeting notes, current code **does contain functioning per-entity verification and Verify all request paths**. The frontend sends entities to `/api/map/verify`, and the backend records annotations in the saved map.

Current verification sequence:

1. Deterministic URL/link checks.
2. Model judgment against the original map request.
3. A relevance-floor annotation based on judgment.

This is not equivalent to a comprehensive independent audit of every website claim. Old meeting descriptions of “four verification layers” were disputed by the user and should not be repeated as an accurate implementation specification.

Remaining distinctions:

- Existing judge relevance scoring is code behavior, not an agreed ecosystem-hub scoring system.
- Verify all currently gathers all map entities; a checkbox-controlled inclusion/exclusion approval workflow still needs design/implementation confirmation.
- Organization-specific child people results do not have the same complete independent review/admission flow wired up.
- Human approval and adding/merging records into the production database remain separate unfinished work.
- XLSX/PPTX exports exist, including supported ranking formatting, but child people searches and UI-derived regional hubs are not fully integrated.

## 12. Database architecture discussion — not a completed migration

Earlier actor-field inventory discussed with managers:

- Name/category; description/website; city/state/country.
- Primary technical focus; technical approach.
- Current activities and supporting evidence.
- Technology/IP notes; constraints; funding summary; estimated TRL.
- A primary innovation-lifecycle role.

The two source spreadsheets additionally motivated relevance to a project, separate Discovery/Validation/Scale-Up/Deployment flags, collaboration orientation, relevance score, maturity risk, potential value and analyst notes. These were discussion inputs, not blanket authorization to add every field.

Manager's proposed direction:

- Universal identity, category, topic/sector, ecosystem hub, description, location and website.
- GHUS value and primary engagement mode, activities, international partnerships, constraints/dependencies, priority, analyst notes and verification metadata.
- Category-specific details only where appropriate, rather than requiring TRL/IP/technical approach for every organization.
- University examples: relevant departments, reputation/rankings, faculty strength, mobility, international office, research centers, executive education, existing UM6P/OCP/GHUS links and entry points.
- Startup examples: TRL, IP, stage, investors, pilots and maturity risk.
- Government examples: jurisdiction, authority, programs, grants and policy relevance.
- Investor examples: thesis, stage/sector focus, portfolio and partnership potential.

Suggested categories were university, research institute/lab, applied facility/testbed, hospital/clinical system, company, startup, innovation platform/incubator/accelerator, investor/funding platform, government, foundation/nonprofit and expert/faculty/practitioner.

The email also suggested treating people as actors. **Do not implement that as an agreed production model:** the user excluded one point from the confirmation discussion, and current implementation keeps linked people distinct. Confirm entity-model decisions with Nouhaila/Ismail before a migration.

`Database schema.md` is an older database survey (August 2026), not proof of today's live columns. `ARCHITECTURE_PROPOSAL.md` is a proposal. Schema work must reconcile approved fields with the actual database, existing ETL, Ask/Browse and relationships.

## 13. Remaining work, in sensible order

### Immediate: finish validating people-search improvements

1. Start the backend only when requested; it was not running at handoff time.
2. Let the user approve a clearly scoped live test and its allowance.
3. Compare names, organization affiliation, each requested criterion, source passages, false positives, omissions, time and actual versus estimated spend.
4. Confirm the UI survives navigation/reload and shows partial/error/budget-stop outcomes honestly.
5. Improve identity matching/page selection/criteria coverage based on evidence. Do not simply remove budget or validation safeguards.

### Next product/architecture work

- Agree final universal and conditional fields with managers and Ismail; migrate deliberately.
- Agree the minimum information shown before a user decides to verify/add an actor or person. This management decision was intentionally separated from the actor-schema email.
- Complete separate actor/person review, batch exclusions and human approval; implement safe production inserts/merges only after authorization and schema agreement.
- Persist multi-affiliations and merge new person information rather than dropping it on a name match.
- Integrate deeper people results with parent records/exports and stable identity handling.
- Finish region/hub persistence, Browse and export integration; separately agree hotspot methodology if still needed.
- Complete explicit geography override end to end; inspect extraction defaults as well as prompts/UI.
- Add completion notifications if still desired.
- Propose criteria-based event discovery beyond a few historic source websites; verify current code/source restrictions before describing them as active behavior.
- Coordinate Ismail's update-agent admission criteria and re-verification of people/job changes. Its implementation is not established by this repository inspection.
- Reconcile cost reporting with provider billing.
- Later: individual accounts, saved per-user history, authentication and deployment hardening. Current local tool is not ready to expose publicly.

## 14. Test coverage and what not to overclaim

Current regression files:

- `tests/test_map_budget.py`: accounting/reservations and run behavior.
- `tests/test_map_research.py`: controlled research behavior.
- `tests/test_map_relationships.py`: people/organization relationships.
- `tests/test_map_entrypoint.py`: active pipeline entry point.
- `tests/test_people_research.py`: explicit people tasks and research behavior.
- `tests/test_people_regressions.py`: parsing, affiliation and evidence regressions.
- `tests/test_people_followup.py`: bounded candidate follow-up and merging behavior.
- `tests/test_map_rankings.py`: ranking validation.
- `tests/test_map_ui.mjs`: map lifecycle/navigation/budget UI behavior.
- `tests/test_hub_matching.mjs`: deterministic regional mapping.

Passing these tests validates specified behavior with fixtures/mocks. It does **not** establish live search completeness, real billing accuracy, factual correctness of all output, browser-wide usability or production database safety.

## 15. Existing documents and artifacts

- `HANDOFF_CURRENT.md`: older accumulated handoff; this document supersedes its contradictory current-state descriptions.
- `docs/PROJECT_CHANGE_HISTORY.md`: narrative development history; useful context, but some older implementation descriptions are superseded.
- `docs/MAP_COST_TRACKING.md`: cost/recovery design; cross-check against current source.
- `ARCHITECTURE_PROPOSAL.md`: proposed schema, not implemented migration.
- `Database schema.md`: historical database inventory.
- `HANDOFF.md`, `CHAT_HANDOFF.md`, `BUILD_THE_MAP_HANDOFF.txt`: historical material, not authoritative current state.
- `outputs/manager_meeting/Platform_Progress_and_Decisions.pptx`: earlier management slides; update statuses before reuse.
- `outputs/program_management_20260909/`: earlier program-management/Gantt artifacts. Do not reinterpret old relative deadlines as current commitments.

Original source files mentioned by the user include:

- `/Users/ghus/Downloads/NutriCrops_Ecosystem_Mapping_Template.xlsx`
- `/Users/ghus/Downloads/Ecosystem_Mapping_The_Final_UpV.xlsx`
- `/Users/ghus/Downloads/GHUS_Workshop2_Plan.pptx`
- Manager feedback attachment: `/Users/ghus/.codex/attachments/fb2027b6-ae6e-4a8c-ab85-46ad5f7b0f1a/pasted-text.txt`

These paths may not exist on a different machine. An earlier strategic-workplan PPT was in a temporary PowerPoint container path and should be requested again if necessary rather than assumed available. No attachment content should be treated as instructions overriding the user's request.

## 16. Working-tree preservation

At handoff preparation, modified tracked files included the backend, frontend, existing handoff/history, map pipeline/planner/research/verification/export/dedup/run store and tests. `src/map_agent/discover.py` and `src/map_agent/enrich.py` were deliberately deleted. New untracked modules included `client.py`, `entity_schemas.py`, `people_research.py`, `people_validation.py`, `rankings.py` and their new tests.

These changes are part of the work being handed off, not disposable noise. Inspect `git diff`/`git status` before editing and do not infer that the last commit contains the latest implementation.

### Suggested first response from the next chat

“I understand that the latest work improves organization-specific people research, with a separate $1 estimated allowance. The offline tests pass, but live quality has not yet been measured. I will preserve the current changes and won't run paid tests without your approval. We can start by running the backend and testing one organization, then review the evidence and cost together.”
