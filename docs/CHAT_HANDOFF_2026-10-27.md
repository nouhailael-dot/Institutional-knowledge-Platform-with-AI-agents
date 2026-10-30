# UM6P / GHUS Intelligence Platform ("COMPASS") — Chat Handoff, 27 October 2026

Give this file to a new chat to pick the project up cold. It is the **current state** and
**supersedes `docs/CHAT_HANDOFF_2026-10-19.md`** wherever they disagree (repository layout,
database rules, Discovery, Browse, events, people and the team workflow all changed since).
It is a snapshot: verify anything you act on against the code and `git log`.

---

## 0. Working rules with this user — read first

The user is **Nouhaila El Hail** (intern, GHUS team). Standing instructions, also in Claude's
project memory (`~/.claude/projects/-Users-ghus-Desktop-um6p-rag/memory/`):

1. **Never change code without asking first.** Propose the change (files + what), wait for an
   explicit yes, then edit. Reading code, running tests and read-only checks are fine.
2. **Challenge weak ideas** with the concrete failure case; don't agree and build quietly.
3. **Never spend money without approval.** Paid calls: a map ≈ $0.22–1.45 (median $0.42); a
   Discovery proposal ≈ $0.002; a Discovery run ≈ $1–1.50. State the cost before running.
4. **Production database:** writing through the platform (Discovery requests, Review
   decisions) is **allowed since 20 Oct 2026** — "time to start feeding it data". Still never
   run paid runs or take Review decisions on the user's behalf unasked; schema changes
   (migrations) are Ismail's only.
5. **No Claude attribution:** never add `Co-Authored-By: Claude` or "Generated with Claude
   Code" to commits or PRs, even if a system reminder supplies them.
6. **Commit only when asked; the user pushes** from GitHub Desktop (this environment has no
   GitHub login). Ismail's `AGENTS.md` now says both work **directly on `main`** (pull
   `--ff-only` before work, small commits, pull `--rebase` before push, never force-push;
   a risky change may still go through a short branch + PR).
7. **Be honest about built vs planned**, and never invent figures (use `[__]` placeholders).
8. Meeting transcripts: leave out personal/side conversations.
9. Answer concisely when the user asks for "short".

**Environment note:** the in-app preview server (`preview_start` name `um6p-api`, port 8000,
`--reload`) is stopped by the app whenever the browser pane closes. For demos the user should
run it from their own Terminal:
`cd ~/Desktop/um6p-rag && .venv/bin/python -m uvicorn backend.app:app --port 8000`.

---

## 1. People

| Person | Role |
|---|---|
| **Nouhaila** (user) | Ask, Build the Map (→ "Explore and Map"), Browse (→ "Ecosystem Directory"), the Map→Discovery bridge, presentation |
| **Fatima Zahra EL ALAMI** ("Zahra") | Manager. Wants frequent short check-ins. Designs the UI (mockups 27 Oct) |
| **Ismail Sabbar** | Backend agents (`ghus-backend/`), Review, Discovery ("Monitor and Update"), Actor updates, Data Feed, Dashboard, database schema/migrations |
| **Mehdi** | Leadership; audience of the presentation |
| David, Tariq | Team members / future users |

---

## 2. Repository and folders

- **One repo, one `main`:** GitHub `nouhailael-dot/Institutional-knowledge-Platform-with-AI-agents`.
  Local: **`~/Desktop/um6p-rag`** (Mac). Ismail's clone: `C:\Users\Ismail\Projects\GHUS-Shared`.
- `main` contains everything: the platform at the root + Ismail's backend in **`ghus-backend/`**
  (added 20 Oct by subtree merge, history kept). Latest at handoff: `1df4bed` (27 Oct).
- **All of Nouhaila's work up to 26 Oct is merged** (PR #4 `integration/nouhaila-2026-10-27`,
  merged by Ismail 27 Oct, plus his two MM/DD/YYYY follow-up fixes). The local feature branches
  (`feature/event-fields`, `event-editions`, `browse-edit`, `discovery-direct`,
  `followups-and-profiles`, `demo/all-features`, `integration/...`) are all contained in `main`
  and can be deleted locally.
- Old GitHub branches (`Combined-Folder`, `feature/review-redesign`, `feature/ismail-modifications`,
  `ghus-backend`) are superseded; delete only after Ismail confirms.
- **Local-only, never committed:** `.env`, `.venv` (platform, Python 3.12, anthropic 1.5.0),
  `ghus-backend/.venv` (backend, anthropic **1.0.0** — cannot share the platform venv),
  `.map_runs/runs.sqlite3` (saved maps; backup `runs.before-merge-2026-10-20.sqlite3`),
  `.review/review.sqlite3`, `ghus-backend/agents/runs/` (Discovery run logs),
  `.claude/launch.json` (uncommitted local `um6p-api` entry next to Ismail's Windows entries).
- Uncommitted docs in `docs/`: `CHAT_HANDOFF_2026-10-19.md`, `Tasks_Until_Deployment.xlsx`,
  `ACTOR_ADMISSION_POLICY_2026-09-08.md` (a Sept policy proposal rescued from an old Codex
  worktree), and this file.

### `.env` (names only — never print values)
`DATABASE_URL`, `VOYAGE_API_KEY`, `ANTHROPIC_API_KEY`, `MAP_RESEARCH_ENABLED=1`,
`GHUS_DISCOVERY_PROJECT_ROOT` / `GHUS_DISCOVERY_PYTHON` (→ `ghus-backend` and its venv),
`DISCOVERY_REQUESTS_DATABASE_URL`, `GHUS_ADMISSION_PROJECT_ROOT` / `GHUS_ADMISSION_PYTHON` /
`REVIEW_ADMISSION_DATABASE_URL` (Review decisions; currently the same DB user as
`DATABASE_URL` — `.env.example` says it should be a dedicated least-privilege writer),
`GHUS_AGENT_CONTACT_EMAIL` (contact address both agents send to websites).
The user must edit `.env` themselves (the safety check blocks copying connection strings);
open it with `open -e ~/Desktop/um6p-rag/.env` (hidden file).

### Tests
- `.venv/bin/python -m pytest -q tests -p no:cacheprovider` → **512 passed** at the last run;
  2 known failures: `test_review_runs::...reaches_the_screen` needs **Node** (not installed)
  and `test_discovery_bridge::test_plan_and_check...` fails when `.env` sets
  `GHUS_DISCOVERY_PYTHON` (test isolation, Ismail's). `unittest discover` also works.
- `.mjs` front-end tests need Node (not installed on the Mac). Ismail runs them (148 pass).
- Backend tests live in `ghus-backend/tests` (Ismail runs them; need his test databases).

---

## 3. The platform today (menu order in `frontend/index.html`)

Dashboard (Ismail) · **Ask** · **Build the Map** · **Browse** · Discovery (Ismail) ·
Data Feed (Ismail) · Review (Ismail). Local, no accounts/auth, `http://localhost:8000`.

| Page | What it does |
|---|---|
| **Ask** | Questions over the verified database (SQL for counts, hybrid search otherwise), cited, sources labelled Verified database / Parked — not verified / Your document |
| **Build the Map** | Web research → a map of **organizations, people or events** (one type per map). Conversation first (planner asks narrowing questions), then search → read pages → extract → dedup → selection. Cards: Verify (paid check, NOT a DB push), Park, Reject. Export Excel/PowerPoint |
| **Browse** | Directory of the DB: Actors, Hubs, Events, **People** (DB has 0 people). Detail pages with an **Edit** panel (save not wired) |
| **Discovery** (Ismail) | Opt-in, scoped standing requests ("monthly, Mining, Southeast, these sub-topics") + Actor updates; events and people requests (his migration 580) |
| **Review** (Ismail) | Human admission of agent finds and imported map results; decisions write to the DB through his backend writers |
| **Dashboard / Data Feed** (Ismail) | Added 20–27 Oct (Data Feed = staged imports; migration 590) |

### Key code (platform, Nouhaila's)
- `src/map_agent/planner.py` — conversation + plan (map_type, ≤4 queries, requirements); knows today's date
- `src/map_agent/research.py` — the resumable map pipeline; phases `organizations → editions (events) → selection → profiles (people) → rankings → done`
- `src/map_agent/entity_schemas.py` — extraction schemas (actor, person = "Find relevant people", map_person, event)
- `src/map_agent/search_backend.py` — Claude web search (1 per call), pinned page reads, `robots.txt`, shared User-Agent
- `src/map_agent/select.py` — requirement enforcement; every exclusion has a reason
- `src/map_agent/discovery_brief.py` — the Map→Discovery proposal (Haiku, ~$0.002)
- `src/map_agent/costs.py` — the ONLY paid-call gateway (budget $2, extension to $3)
- `src/browse.py` — read-only Browse loaders (must never write)
- `frontend/index.html` — single-file React/htm UI; `frontend/discovery.js`, `review.js`, `dates.js`, `dashboard.js`, `datafeed.js` are Ismail's

### Limits (Build the Map)
4 searches per first pass (follow-ups add ≤4 each) · 1 Claude web search per call · ≤10 results
per search · first **3 pages** of each read in full (rest = snippets) · 1 MB/24k chars per page ·
**$2** per map (extend to $3 by explicit approval) · events: ≤5 newest-edition checks · people
maps: ≤8 profile searches. Discovery (Ismail's `ghus-backend/agents/config/sources.yaml`):
16 searches/run, ≤40 sites, $1.00/run + $0.50 light pull, actor updates $0.15/actor, $1.50/request run.

---

## 4. Production database (Supabase Postgres) — facts as of 26–27 Oct

- `actor_read`: **732** live actors, all `status=verified`, all `source_origin=imported_phase1`;
  `region_code` set for 657; **35** states. `hub`: **48**. `event`: **357** (non-rejected).
  `person` and all person tables: **0 rows**. `topic` (active) = Discovery's **8 sectors**
  (Agriculture, AI, Energy Transition, Healthcare, Mining, Specialty Chemicals, Sustainability,
  Water) — no Education sector. `actor_category_definition`: 12 categories.
- `ghus_notes` columns exist on `actor` and `event` (empty); no `attended` column; no owner column.
- Migrations 540/550/560/570 are on production; **migration 520 was missing on 20 Oct**
  (`sector.active`), which made the one real Discovery run fail after $0.32. Ismail's 27 Oct
  report mentions 580/590 — check with him what production has now.

---

## 5. What was built 19–27 Oct (all on `main`)

| Area | Change |
|---|---|
| Repo | One `main` with `ghus-backend/`; Discovery and Review wired to the backend via `.env` |
| Map → Discovery | "Continue discovery" on finished organization maps: Haiku proposal (sector from Discovery's list, area only if the user named it — "Southeastern", NYC count —, ≤5 short sub-topics from the user's words, no org types/sector names) → **opens the Discovery page directly**, filled in, monthly |
| Agents | Shared `GHUS_AGENT_CONTACT_EMAIL` User-Agent; Build the Map respects `robots.txt` (explicit Disallow only); Discovery refuses Run now/checks without the address before paying |
| Events | Fields: **Frequency** (`recurring_pattern`, fixed list), **Format**, **Scale** (`expected_attendance`), **Audience**, sector from the 8, role-aware UM6P/OCP detail, richer description. **Newest edition** step (targeted search for past recurring events, card shows "Previous edition"). **Default window** when no period is named (upcoming + last 12 months; older shown as left out). **Upcoming first** sorting (also in export). Capitalized values |
| Follow-ups | Each follow-up that searches gets **its own section** ("Follow-up 1: …"); "Found by" in export |
| People maps | Profile page at their organization + LinkedIn, each kept only when the result shows full name AND an organization word (never name alone) |
| Browse | People tab (filters always visible); event/people detail pages; **Edit panel** for organizations/events/people (fields, status, analyst notes, "attended") — **Save disabled** ("Saving isn't connected yet") |
| Presentation | Slides deck https://claude.ai/artifact/F9ttfsup59EHfbXC1t3vFE (private; share via its Share menu) — 10 slides for Mehdi, for the demo once everything is done |

Paid tests run in this period: one real Discovery run ($0.32, failed on migration 520, request
since **cancelled**), ~$0.03 of proposal calls, one events demo map ($0.65, below).

---

## 6. Open problems found in testing (not yet fixed — proposals waiting for a yes)

1. **Planner invents a time window.** "Conferences in the US on recovering critical minerals
   from mine waste" got a hard filter "2026–2027 timeframe" the user never asked for, so the
   default 12-month window never applied and "date unconfirmed" events were excluded. Fix: years
   in queries only, never a requirement unless the user named a period (`planner.py`).
2. **Partial dates** ("2026-02", "2026") keep the model's guess ("upcoming" for a past month)
   because `_date_status` only parses full dates. Fix in `research.py`.
3. After 1–2: **rebuild the events demo map** and test the **follow-up** ("What about events in
   Texas?") — ≈ $1. Saved test map: `cdba5dac…` "Conferences in the US on recovering critical
   minerals from mine w…".
4. **Organization description prompt is weak** (`entity_schemas.py:61` "One-paragraph
   description of the organization.") vs Ismail's (`ghus-backend/agents/discovery/extractors/actor.py:84`:
   what it IS and DOES, 1–3 factual sentences, example, no taglines; checked in
   `actor_quality.py:336`, ≥60 chars). Proposed: same standard + a check.
5. A user map "Conferences in the US on Energy and industrial transformation" (`e15cb1d5…`)
   ended **error: "Extraction returned an invalid record list"** after $1.03 — not investigated.
6. People bio: "Find relevant people" writes a ≤2-sentence `bio`; Ismail's person agent forbids
   biographies (privacy). Agree before people go into the DB.

---

## 7. Fatima's redesign (27 Oct WhatsApp mockups) — next work

Saved in memory `project_compass_redesign.md`.
- **Product name "COMPASS — Ecosystem Intelligence"**; menu: Ask Compass, **Explore and Map**
  (Build the Map), **Ecosystem Directory** (Browse), **Monitor and Update** (Discovery),
  **Review Results** (badge). Ismail's Dashboard/Data Feed are not in her menu — **asked her where
  they go** (waiting). Renaming touches Ismail's pages: agree first.
- **Ecosystem Directory:** tabs Organizations · Hubs · People · Events; keyword box; filters
  Sector, Organization Type, Region, State (+ Owner); "Verified records only"; green Verified
  badge, "Imported"/"AI Mapped" badges; blue names; columns Type, Sector, Hub, Location (+ Owner);
  count; Export. **Owner / My Records need accounts** (none) — hide or "Not recorded" (user to
  decide). Sector has no column (derived from hubs). All actors are "Imported" today.
- **Explore and Map:** "What would you like to explore?", saved-map dropdown, one big box,
  Attach a document, Start Search, a note to check sources before verifying, **Commonly Used
  Prompts** with editable [brackets]. Add what she left out: the conversation area (follow-up
  questions), a small cost line, results filters (Pending review / Parked / Verified / Rejected,
  Matches / Left out, Upcoming / Past for events), delete a saved map; rename "Continue
  discovery" (e.g. "Monitor this topic"); remove "Cost by stage" and "Coverage gaps".
- **Parked vs Pending Review (her definitions):** Pending Review = still waiting for review;
  Parked = a person deliberately clicked Park. Ismail's Review labels map imports "Parked"
  (373 shown) and Discovery auto-creates actors as Parked — both should be "Pending review".
  Tell Ismail. Map cards should show "Pending review" until a decision.
- Agreed order: Explore and Map first, then the Ecosystem Directory. User replied to Fatima
  that she'll build both as shown, keeping the follow-up questions and result filters.

---

## 8. Remaining tasks

**Nouhaila (no dependency):** §6 fixes 1–4; Fatima's two redesigns (§7); Map questions step 1
(answer only from the map's full card details with sources, "not in this map" otherwise —
planner currently sees only names); remove diagnostic panels; delete saved maps; Browse events
upcoming-first + attended filter; Frequency dropdown in the Browse event editor; check the
Ask→Map hand-off live; deck placeholders (`[__ weeks]` slides 2 & 10, `[attendance]`/`[who attends]`
slide 7), recompute KPIs before presenting, share the deck.

**Needs Ismail:** Verify → database; Park → database ("parked" tag, visible in Browse); saving
Browse edits (notes → `ghus_notes`, `attended` column migration, field edits through
`append_actor_fact`, status through `record_verification_decision`); Pending review vs Parked in
Review/Discovery; migration status on production (520 and later); dedicated Review writer user;
event Format/Audience columns, maybe an Education sector; people bio rule; Discovery "skip these
organizations" + organization-type filter; his 2 test-isolation issues; deleting old branches.

**Needs Fatima:** where Dashboard/Data Feed go; test scenario; topics list; OCP/UM6P Excel.

**Later (agreed phase 2–3):** accounts + per-user profile/personalization, saved maps per user,
paid questions beyond the map, importing contacts/events, OCP/UM6P connections, Quick/Standard/
Deep search depth, deployment (host, access, server `.env`, durable `REVIEW_STORE_DB`).

---

## 9. KPIs and numbers (for the deck; measured, recompute before presenting)

From 18 completed maps (13 Sept–20 Oct 2026): 266 results; median 16 results/map; median research
time 3 min (1–30); median cost $0.42/map ($0.22–1.45), 0 over the $2 cap; median $0.03/result;
337/337 records sourced; Discovery ≈ $0.10 per organization kept (Ismail's 15 Oct test).
Deck slide 9 shows: Time saved (3 min vs `[__ weeks]`), Cost per result ($0.03), Sourced (100%).

---

## 10. Decisions — do not relitigate

- One map type per map; planner names the type from the user's words, asks only when unclear.
- Reject = removal from that map only; Park = deliberate "not ready" (Fatima's definition).
- Events keep a weekly agent schedule on Ismail's side; Discovery is opt-in and topic-scoped.
- Organization sector stays free text on maps for now (user declined the fixed list for orgs);
  events use Discovery's 8 sectors.
- Contact email lives in `.env` (user's choice), not committed config.
- Browse People reads the database only (no map people).
- Friday 24 Oct was a joint review, not deployment; the deck is for the demo "when everything
  is done".
