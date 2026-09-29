# UM6P Intelligence — Development changes and current status

## Subsequent cleanup — 15 September 2026

Removed the unused legacy pipeline, autonomous discovery/enrichment modules,
alternate planning functions and uncalled verification wrappers. Shared entity
schemas moved to `src/map_agent/entity_schemas.py`, and the extraction client's
factory moved to `src/map_agent/client.py`. The active entry point now accepts
only description, plan and tracked run. Backend worker calls were updated,
while legacy HTTP input fields remain compatible. Tests that previously called
the old pipeline now check the equivalent active workflow behavior. The detailed
history below describes the earlier layout where those legacy files still existed.


Prepared: 13 September 2026 (America/New_York).

## 1. Purpose and scope

This document explains the project evolution discussed with Nouhaila: the original platform, mentor feedback, subsequent development, cost-control work, interface redesign, and the first ecosystem-hub integration.

It combines the conversation history with inspection of the current code. It is a narrative development record, not a commit-by-commit audit: the working tree contains uncommitted changes, and not every historical step has a separately recorded date. Historical spending figures below are user-reported observations, not independently reconciled invoices.

**Important distinction:** an agreed requirement, a prototype, and a completed database change are not the same thing. Each section distinguishes these. Nothing in this documentation task changes the application or starts a paid research test.

## 2. The starting platform

The active application uses FastAPI (`backend/app.py`) and a single-file React interface (`frontend/index.html`). The older Streamlit interface is a reference implementation, not the target of the recent UI changes.

The three main features already existed:

| Feature | Purpose | Cost distinction |
|---|---|---|
| Ask | Answer questions using the existing database, with SQL and semantic retrieval | Uses model calls; not included in the Build the Map ledger |
| Browse | Filter and inspect existing actors, hubs, and events | No research-model calls |
| Build the Map | Research organizations, people, and events beyond existing database coverage | Uses paid model/search calls |

Excel and PowerPoint exports were also present. The starting research process used more autonomous discovery and optional per-entity enrichment. Results originally depended on in-memory job storage, so restarts could lose work.

The original `HANDOFF.md` is useful historical context, but its statements about lack of persistence, lack of tests, the discovery implementation, and placeholder web colors no longer describe the current application.

## 3. Mentor feedback and direction agreed

The meeting established the following direction:

- Settle database architecture before expanding features dependent on that schema.
- Keep general research guidance instead of a narrowly customized central policy layer; prepare a prompting guide for the team.
- Keep US-first behavior, with an explicit geography override requested for future implementation.
- Add ecosystem-hub mapping alongside actor mapping.
- Connect people to their organizations, including multiple affiliations.
- Improve verification controls and decide how much information reviewers need before accepting results.
- Revisit hub-level information, including rankings and descriptions, from the original mapping materials.
- Add completion notifications; consider accounts and personal history in a later phase.
- Develop a proposal for criteria-based event discovery rather than relying on three historical websites.

These were requirements and decisions, not all completed features. The meeting feedback's original verification description was explicitly challenged by Nouhaila and should not be repeated as a validated four-layer guarantee.

Nouhaila also corrected the initial general cost description to approximately **$2–4 per map**. Later individual tests exceeded that range; it is not a guaranteed price.

## 4. Responsibility split

Nouhaila's work focuses on the platform and Build the Map experience. Ismail's separate agent is intended to keep the database current by looking for actors and people within topics already covered by the database.

The central open question for that update agent is the admission criteria: what makes a newly discovered actor worth adding? Updating existing people when their jobs or affiliations change is another requested responsibility.

This document does not claim that Ismail's agent has been implemented, tested, or changed in this repository. Its implementation and database-write process must be confirmed with him.

## 5. Keeping maps available while navigating

### Original problem

Switching to another platform page made a running map appear to stop. Later, persistence across server restarts also became a major concern.

### Changes

- Ask, Browse, and Build the Map remain mounted when switching navigation tabs.
- Map polling and local result state are preserved instead of being destroyed on a tab switch.
- The browser remembers the active map ID in local storage.
- Saved map records can be reopened through a saved-map selector.
- Map jobs, messages, evidence, cost records, and partial results are now stored in a local SQLite store.
- Default storage is `.map_runs/runs.sqlite3`, excluded from Git. `MAP_RUN_DB` can point to an isolated store.
- Interrupted work is recognized on startup rather than automatically resubmitted.

### Limits

Persistence is local to this computer/store. It is not a cloud account or a backup. A server restart interrupts an active worker; retaining its data does not mean the worker continues running. Eligible unfinished work requires explicit continuation. Unknown charges can block continuation.

## 6. Connecting people to organizations

### Original problem

People and organizations appeared as separate lists, making their relationships difficult to understand. Name-based deduplication could discard useful information.

### Changes

- Research is organization-first.
- People supported by organization evidence are attached to the relevant organization.
- Organization result cards have expandable people sections.
- A normalized top-level people collection remains for API/export compatibility.
- People can have more than one organization affiliation in the map result structure.
- Merging combines sources and fills or enriches person fields rather than simply dropping subsequent records.
- Exports were adjusted to carry organization–person relationship information.
- In controlled research, selected organizations missing people can receive targeted official-domain searches; existing evidence is reused where possible.

### Limits

These are map-result relationships, not a completed migration of the main database. The relationship normalizer still uses normalized names to identify people, which can conflate different people with the same name. A legacy standalone-person matching path uses heuristic organization matching. These mechanisms are not a complete identity-resolution system.

Main implementation: `src/map_agent/relationships.py`, `dedup.py`, `research.py`, `export.py`, and organization cards in the frontend.

## 7. Why research became expensive

Nouhaila reported tests costing around $7 and taking more than 20 minutes, and a test consuming around $2 despite an earlier $1 target. She also observed an approximately $10 account-balance reduction; attribution was unresolved because the account might also have been used by her colleague.

The original architecture allowed repeated search/tool turns and large evidence contexts. Adding people research expanded work further. Per-entity enrichment multiplied calls, and repeatedly sending accumulated material increased input-token consumption.

A model output-token limit alone does not cap a map's total bill. Planning, search tools, input tokens, extraction, selection, and verification can all contribute. Account-wide balance changes also cannot automatically be attributed to one map.

## 8. Durable cost tracking and budget controls

### Implemented changes

- A map session is created before planning so planning and later stages share one ledger.
- Map model calls go through `costs.paid_message`.
- Calls record returned usage, configured price snapshots, estimated cost, duration, stage, and operation identity.
- New maps default to a **$2 estimated total budget**.
- An eligible map can receive explicit approval for an additional $1, raising the same budget to **$3 total**.
- Approval does not itself start or resume research.
- Legacy saved budgets are not silently changed.
- Before dispatch, the system reserves an allowance against available budget.
- Reservations use integer micro-dollars and SQLite transactions to account for pending work.
- Unknown charges retain their allowance and block further paid work instead of being treated as free failures.
- Automatic SDK retries are disabled in the paid gateway.
- Unsupported tools and unknown model pricing fail before dispatch.
- The UI displays estimated spending, total budget, reserved/unknown usage, and stage breakdowns.

### What this does not guarantee

The local budget is **not a hard provider billing ceiling**. It depends on configured rates, estimates before dispatch, and provider-reported usage. In-flight calls can still finish and be charged after Stop.

Nouhaila reported one completed map as approximately $2 on the Claude platform while the local estimate was lower. That discrepancy remains unreconciled. Neither the local ledger nor the account dashboard alone establishes the exact attribution without matching provider records.

Ask calls and a colleague's separate agent are outside this map ledger. A configured $2 budget does not cap the shared API account's total spending.

## 9. Controlled research replaces autonomous loops

The active `build_map` entry point delegates to `build_controlled_map`. Legacy discovery code remains in the repository but is not the active workflow.

The controlled path:

1. Produces a bounded plan.
2. Dispatches individual Claude web-search requests with `max_uses: 1`.
3. Captures bounded evidence and performs limited direct page reads.
4. Extracts structured organizations and people from supplied evidence without allowing the extraction model to browse.
5. Deduplicates and links people to organizations.
6. Applies request-based selection and reports coverage gaps.
7. Saves workflow progress and visible results as work proceeds.

Additional controls include:

- Up to four distinct topic queries in the controlled discovery stage; this is not a claim that all stages together use only four paid calls.
- Bounded captured results, page reads, extracted text, and model output.
- Per-map caching of search results and successful/failed page reads.
- Reuse of saved operation responses during safe continuation.
- Worker-attempt tracking to prevent stale workers overwriting or spending against a newer attempt.
- Citation filtering: model-returned source URLs must belong to supplied evidence.
- Page-fetch restrictions on destination addresses, ports, redirects, content types, size, and duration.
- Explicit focused-coverage messaging rather than presenting a limited map as exhaustive.
- Map document uploads extract text without the Ask upload embedding path.

Claude remains the selected search provider. No separate search API subscription was adopted for this implementation.

### Token-count endpoint error

A real test returned HTTP 400 because Claude's token-count endpoint rejected the server-side web-search tool. The cost gateway now uses a conservative local UTF-8-size estimate and result headroom for those requests. Other eligible requests still use the token-count endpoint. This avoids that incompatible request shape; it does not turn estimates into billing guarantees.

## 10. Stop, recovery, and saved work

- Stop prevents subsequent paid calls; it cannot undo a dispatched provider request.
- Late usage and evidence from dispatched work are still recorded.
- Saved results can be read without rerunning research.
- Startup recovery marks unfinished work interrupted and unresolved pending charges unknown.
- Eligible continuation reuses the original plan, budget, and cached work.
- Continuation is an explicit action, not a side effect of reopening a page.
- Manual stops, unresolved charges, and other unsafe states can prevent resume.
- Stale browser responses are guarded so switching maps does not let an older response replace the selected map.

Operate one API worker per SQLite store. Avoid hot reload or server restarts during paid work. Back up the store if saved research must survive computer loss.

## 11. Verification: actual behavior and unfinished scope

Nouhaila originally reported Verify and Verify All as nonfunctional. The current repository contains working request handlers and frontend wiring for individual and batch verification, with session-budget accounting and error handling. This is an implementation statement, not a claim of a recent comprehensive live acceptance test.

The verification path includes URL checks, a separate model judge, and relevance-floor annotations. Request-based selection is also part of the mapping workflow. A relevance judgment is not equivalent to independently proving every factual claim against an organization's website.

Human approval and insertion into the main database are **not completed by these buttons**. The platform does not currently write map actors, people, or hub links into that database. The requested batch review experience with individual exclusions should receive a separate acceptance check before being described as fully delivered.

## 12. Database architecture discussions — proposals, not migrations

The two original spreadsheets had different information structures. The actor-table email asked managers which additional source fields should be retained and whether important actor information was missing.

Additional fields discussed included project/challenge relevance; separate Discovery, Validation, Scale-Up, and Deployment flags; collaboration orientation; relevance score; maturity risk; why an actor is valuable; and analyst notes.

The manager proposed:

- Universal fields for every actor.
- Conditional fields by category, rather than forcing TRL, IP, and technical approach on every organization.
- Explicit links to sector/topic, ecosystem hub, and GHUS engagement mode.
- Hub assignment or a review flag for every actor.
- University-specific information such as departments, reputation/ranking signals, mobility potential, executive education, existing links, and entry points.
- Different category-specific information for startups, government agencies, investors, and other types.

The manager also proposed treating individual experts as an actor category. This was a proposal, not an implemented replacement of the separate people relationship model.

Hub rankings were clarified as hub-level information in the earlier source discussion; the manager's later university reputation/ranking proposal is a separate category-specific concept.

**No main-database schema migration is established by the recent work documented here.** The finalized columns, relationships, and admission criteria still require coordination with the database owner.

## 13. Program-management deliverables

A Gantt-style development plan was prepared to communicate phases, ownership between Nouhaila and Ismail, status, and completion deadlines. The UI/UX design phase was included without expanding it into a long task list.

The plan used UM6P orange, matching the workshop presentation. A concise accompanying email explained that dates and phases might evolve with future feedback and requirements. Generated artifacts are under `outputs/program_management_20260909/`.

This documentation does not reinterpret relative dates such as “this Friday” as current deadlines. The original tracker should be consulted and updated with the owners.

## 14. Platform UI/UX redesign

### Requested direction

Redesign the whole platform to feel more professional, interactive, and dynamic while retaining UM6P orange. After the initial pass, Nouhaila requested stronger contrast because it looked “white on white.”

### Implemented changes

- Persistent navigation sidebar for Ask, Browse, and Build the Map.
- Workspace breadcrumb and platform identity.
- UM6P orange `#D7410B` for key actions and active navigation.
- A charcoal sidebar, warmer gray workspace, and distinct white content panels after the contrast feedback.
- More consistent typography, spacing, borders, controls, tables, result cards, and expandable sections.
- Ask starter-question cards; selecting one fills the input instead of immediately sending a paid query.
- Browse page heading and clearer category navigation.
- Responsive layouts for smaller screens.
- Keyboard focus styling and reduced-motion support.
- A mobile composer adjustment so the Ask button remains usable and the composer does not cover content.

The changes are in the existing React frontend, not a replacement framework. Core navigation still keeps all pages mounted. The branding is rendered with text/CSS, not a newly supplied official logo asset.

Browser screenshots were inspected for the initial desktop/mobile redesign. Later contrast and hub changes have automated checks but should still receive user visual acceptance. A passing state-transition test does not prove visual quality.

## 15. Ecosystem hub definition and integration

### Agreed concept

An ecosystem hub is a geography with critical mass across strategic dimensions, not simply an organization or any arbitrary city. The six dimensions currently retained are:

1. Academic excellence.
2. Applied research.
3. Industry presence.
4. Expert talent.
5. Innovation platforms.
6. Global engagement.

Africa-focused partnership potential, the seventh dimension on the slide, was set aside for now.

For a nationwide map, candidate regional ecosystems must be assessed separately. One assessment of the entire US would not establish the regional hubs within it.

### First phase implemented: existing-hub suggestions

- Organization cards load the existing hub directory from `GET /api/browse/hubs`.
- A shared frontend promise reuses the directory request across cards.
- Matching is deterministic and does not call an LLM or search the web.
- It compares actor city/country and state with a hub's recorded primary city/country/state.
- US country aliases and state names/abbreviations are normalized.
- One match is shown as an existing-hub suggestion.
- Multiple matches remain ambiguous and require review.
- Missing location or no exact match produces a review explanation.
- Match details show the hub location and available topic information.
- Directory-load failures show an unavailable state and Retry control.
- Saved maps can display these suggestions without rerunning research.

### Important limitations

- This is a **frontend suggestion**, not a stored relationship. It is not currently included as a persisted hub assignment or exported hub link.
- A primary-city match does not prove ecosystem membership or relevance across the six dimensions.
- Broad regional boundaries, aliases, nearby cities, and branch campuses are not resolved.
- US matches require city, country, and state. For non-US records, missing state information can still allow a city/country match; conflicting provided states are rejected.
- The matcher currently reads `actor.city`. Older mapping schemas mention `location_city`; records using only that field will be flagged incomplete until compatibility handling is added.
- No exact match does not mean a new hub should be created.
- The hub catalog is reused for the current page session; refreshing the page reloads it.

### Not implemented yet

New-hub discovery, six-dimension evidence assessments, regional grouping, approval of proposed hubs, and database insertion/linking. These require the next implementation phase and an agreed cost allocation.

## 16. Testing and validation record

Offline tests now exist where the original handoff reported none:

| Test file | Main coverage |
|---|---|
| `tests/test_map_budget.py` | Cost accounting, reservations, job and budget behavior |
| `tests/test_map_research.py` | Controlled research and evidence/search behavior |
| `tests/test_map_relationships.py` | People/organization linking and related behavior |
| `tests/test_map_ui.mjs` | Saved maps, stale responses, Stop, budget approval, and explicit continuation |
| `tests/test_hub_matching.mjs` | Location normalization, missing/conflicting geography, ambiguity, and nonmutation |

The latest hub implementation run passed **15 JavaScript tests**: nine map-state tests and six hub-matching tests. Earlier development recorded 54 passing Python tests; they were not rerun for this documentation task. The automated suites use fake responses/local stores rather than paid research.

No paid research queries were run during the UI redesign, existing-hub suggestion implementation, or preparation of this document. Earlier live map tests did incur costs; this statement does not apply retrospectively to all project development.

## 17. Current gaps and next steps

1. Confirm the main actor/hub schema and who owns each field and approval decision.
2. Validate existing-hub suggestions against real records, including `city` versus `location_city`, regional hubs, and international locations.
3. Define explicit hub boundaries and membership rules before broadening automatic suggestions.
4. Add regional grouping and evidence-backed proposed hubs using the six agreed dimensions, with a separate bounded research allowance.
5. Decide what reviewers see before approval and finish the database-add workflow.
6. Reconcile local cost estimates with provider billing and shared-account usage.
7. Perform a controlled quality evaluation of source accuracy, coverage, and people affiliations before raising research limits.
8. Complete or acceptance-test remaining meeting items: geography override, completion notifications, batch verification exclusions, event sourcing, and the colleague's update-agent criteria.
9. Plan authentication, per-user history, and shared deployment separately from the local saved-map feature.

## 18. Operating the platform

Open **http://127.0.0.1:8000/** or **http://localhost:8000/**. Do not open `frontend/index.html` through a `file://` URL: API routes require the server.

The most recent server check returned HTTP 200 and the platform HTML from `127.0.0.1:8000`. This was a check at that moment, not a guarantee that the process will remain running indefinitely.

The application remains a local tool without per-user authentication. Keep it bound to localhost. Do not publish its paid endpoints without access controls. API keys belong in ignored environment configuration and are intentionally not reproduced here.

## 19. File guide

| Location | Responsibility |
|---|---|
| `frontend/index.html` | Navigation, UI design, maps, cost display, people cards, existing-hub suggestions |
| `backend/app.py` | API endpoints, background work, saved records, stop/resume and verification |
| `src/map_agent/research.py` | Active controlled research workflow |
| `src/map_agent/search_backend.py` | Claude search adapter, bounded page reads, evidence cache |
| `src/map_agent/costs.py` | Paid-call gateway, estimates, reservation and settlement |
| `src/map_agent/run_store.py` | Durable jobs, usage, workflow checkpoints and recovery |
| `src/map_agent/relationships.py` | People merging and organization affiliations |
| `src/map_agent/planner.py` | Conversational planning and bounded task generation |
| `src/map_agent/pipeline.py` | Active entry point and retained legacy pipeline |
| `src/map_agent/select.py` | Request-based selection and ranking |
| `src/map_agent/verify.py`, `judge.py` | Verification orchestration and model judgment |
| `src/map_agent/export.py` | Excel/PowerPoint formatting and relationship export changes |
| `docs/MAP_COST_TRACKING.md` | Detailed operational cost/recovery notes; some historical test-status wording is older |
| `ARCHITECTURE_PROPOSAL.md` | Architecture proposal; not proof of an applied migration |
| `HANDOFF.md` | Earlier project baseline, with now-outdated implementation details |

**Summary:** the major completed evolution is from a more autonomous, fragile map run to a saved, resumable, budget-aware workflow with organization-linked people, a redesigned interface, and conservative existing-hub suggestions. Full hub mapping and database admission remain separate unfinished work.
