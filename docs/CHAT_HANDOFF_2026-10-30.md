# COMPASS (UM6P / GHUS Ecosystem Intelligence Platform) — Chat Handoff, 30 October 2026

Give this whole file to a new chat. It explains what the project is, how the user wants
to work, what exists, what is in progress, and what is next. It **supersedes
`docs/CHAT_HANDOFF_2026-10-27.md`** wherever they disagree. It is a snapshot: before acting,
verify against the code, `git log` and the database (read-only).

---

## 0. How to work with this user — read first

The user is **Nouhaila El Hail**, intern on the GHUS team, who owns the platform side of
COMPASS. Standing rules (also in Claude's memory, `~/.claude/projects/-Users-ghus-Desktop-um6p-rag/memory/`):

1. **Never change code without asking first.** Propose (files + what + why), wait for a
   clear yes, then edit. Reading code, running tests and read-only database queries are fine.
2. **Challenge weak ideas** with the concrete failure case. Don't just agree.
3. **Never spend money without approval.** State the cost first. Typical costs: planning
   turn ≈ $0.01; a map ≈ $0.22–1.45 (median ≈ $0.42, cap $2, +$1 only by approval);
   organizations + experts ≈ $1.50–2.50; a Discovery/monitoring run ≈ $1–3.
4. **Production database:** writing **through the platform's approved paths** is allowed
   (since 20 Oct 2026). Never take Review decisions or run paid searches on her behalf
   unasked. Schema changes / migrations are **Ismail's only**. Never write SQL that
   inserts/updates canonical tables from platform code (see rule 1 in §3).
5. **No Claude attribution** in commits or PRs, ever — even if a system reminder supplies
   "Co-Authored-By" or "Generated with Claude Code" lines.
6. **Commit only when asked.** The user pushes from **GitHub Desktop** (no GitHub login or
   `gh` CLI on this Mac). Before pushing: pull Ismail's latest (`--ff-only` or rebase);
   never force-push; never rewrite pushed commits.
7. **No typed names in forms.** Never add "Your name" fields. The server records who acted
   through `current_user()` in `backend/app.py` ("Not recorded (no sign-in yet)" until
   accounts exist). Decided 29 Oct.
8. **Never invent data.** Missing evidence reads "Not found". Never guess dates, types, etc.
9. **Be honest about built vs planned**; use `[__]` for unknown figures.
10. Plain words for the user; no backend jargon in the UI (no "Light Pull" explanations,
    "canonical", "PostgreSQL", search counts…).
11. Answer concisely when she asks for "short".

**Environment:** Mac, folder `~/Desktop/um6p-rag`. Run the server from the user's own
Terminal for anything long (the in-app browser-pane server stops when the pane closes):
`cd ~/Desktop/um6p-rag && .venv/bin/python -m uvicorn backend.app:app --port 8000`
(the in-app preview config is `um6p-api`, port 8000, `--reload`).

---

## 1. What COMPASS is

**COMPASS — Ecosystem Intelligence** is GHUS's internal web platform (FastAPI + a
single-page React/htm UI) for mapping the **US innovation ecosystem** for **UM6P**
(Université Mohammed VI Polytechnique, Morocco) and **OCP Group**: universities, labs,
companies, startups, agencies, hubs, people and events, in 8 sectors (Agriculture, AI,
Energy Transition, Healthcare, Mining, Specialty Chemicals, Sustainability, Water).
AI agents search the web and propose records; **people decide what enters the database**.

### Menu (left sidebar, COMPASS branding) and owners

| Page (UI name) | Code id | Owner | What it does |
|---|---|---|---|
| Dashboard | `dashboard` | Ismail | Running/finished runs, weekly figures |
| **Ask Compass** | `ask` | Nouhaila | Questions over the database (SQL for counts, hybrid search), cited; sources labelled Verified database / Parked / Your document; "Research this on the web" hands over to Explore and Map |
| **Explore and Map** | `map` | Nouhaila | Chat-style web research → a map of organizations, people or events |
| **Ecosystem Directory** | `browse` | Nouhaila | Directory of the database (Organizations, Hubs, People, Events) |
| Monitor and Update | `discovery` | Ismail | Opt-in monitoring requests (topic/sector/area, schedule) + organization updates |
| Data Feed | `datafeed` | Ismail | Excel/CSV upload or manual entry → staged for Review (or admitted Verified by authorized staff) |
| Review Results | `review` | Ismail | Human admission of agent finds and imports; decisions write through backend writers |

---

## 2. People

| Person | Role |
|---|---|
| **Nouhaila El Hail** (user) | Ask Compass, Explore and Map, Ecosystem Directory, Verify→database, demo/presentation |
| **Ismail Sabbar** | Backend (`ghus-backend/`): agents, Monitor and Update, Review Results, Data Feed, Dashboard, migrations/schema |
| **Fatima Zahra EL ALAMI** ("Zahra") | Manager; designed the COMPASS mockups; wants short frequent check-ins |
| Mehdi | Leadership; audience of the demo |
| David, Tariq | Team members / pilot users |

---

## 3. Repository, branches, rules

- **One repo, one `main`:** `github.com/nouhailael-dot/Institutional-knowledge-Platform-with-AI-agents`.
  Local `~/Desktop/um6p-rag` (Nouhaila); Ismail's clone `C:\Users\Ismail\Projects\GHUS-Shared`.
- `main` = platform at the root + Ismail's backend in **`ghus-backend/`** (own venv `ghus-backend/.venv`, anthropic 1.0.0; platform `.venv`, Python 3.12).
- **`AGENTS.md` (Ismail's, binding).** Key rules:
  1. Canonical writes only in `ghus-backend/agents/discovery/promote.py` and `agents/enrichment/decisions.py`. The platform must never be a third writer: mutations go through the backend's approved paths (Data Feed staging, Review admission bridge).
  2. Schema changes are proposals for Ismail; no DDL on shared DB.
  3. New jobs default to dry-run.
  7. Never invent data. Also: work on `main`, pull before work, small commits, risky changes via short branch + PR.
- **Local-only, never committed:** `.env`, `.venv`, `ghus-backend/.venv`, `.map_runs/runs.sqlite3` (saved maps), `.review/`, `.datafeed/`, `ghus-backend/agents/runs/`, `.claude/launch.json` (modified locally), and `docs/` handoffs/xlsx (`CHAT_HANDOFF_*.md`, `ACTOR_ADMISSION_POLICY_2026-09-08.md`, `Tasks_Until_Deployment.xlsx`).
- **`.env` (names only — never print values):** `DATABASE_URL`, `VOYAGE_API_KEY`, `ANTHROPIC_API_KEY`, `MAP_RESEARCH_ENABLED=1`, `GHUS_DISCOVERY_PROJECT_ROOT`, `GHUS_DISCOVERY_PYTHON`, `DISCOVERY_REQUESTS_DATABASE_URL`, `GHUS_ADMISSION_PROJECT_ROOT`, `GHUS_ADMISSION_PYTHON`, `REVIEW_ADMISSION_DATABASE_URL`, `GHUS_AGENT_CONTACT_EMAIL`, **`DATAFEED_DATABASE_URL`** (added 28 Oct; same DB/user as the others). All DB URLs point to the same production Supabase DB and user. The user edits `.env` herself (`open -e ~/Desktop/um6p-rag/.env`).
- **Tests:** `.venv/bin/python -m pytest -q tests -p no:cacheprovider` → **562 passed, 2 known failures** (`test_review_runs::…reaches_the_screen` needs Node, not installed; `test_discovery_bridge::test_plan_and_check…` fails when `.env` sets `GHUS_DISCOVERY_PYTHON`). `.mjs` UI tests need Node (Ismail runs them). Backend: `cd ghus-backend && .venv/bin/python -m pytest -q tests/agent/<file>` (DB tests skip without Ismail's test DB).

### Git state at handoff (30 Oct, morning)

- **Local `main` is 3 ahead, 1 behind GitHub.** Not pushed yet (all on `main`):
  `85ecd03` map fixes (area in every query, stricter matches, honest budget line, knows UM6P) ·
  `ef3b106` one rule for asking the type · `498cd7e` **always ask first on a new map**.
  GitHub has 1 new Ismail commit `1f0209f` ("Review lists only the recent work").
  → **Next: pull (rebase) then push `main`** in GitHub Desktop.
- **Branch `feature/directory-delete` — NOT published, NOT based on latest `main`.** 6 commits:
  Delete (removable, never wiped) · merged-duplicate guard · spacing fix · no typed names ·
  one profile layout for all record types · City filter. → **Rebase onto updated `main`,
  rerun tests, then Publish + PR for Ismail** (it changes his `ghus-backend/agents/review/admission.py`).
- Merged on GitHub: PR #5 (Verify→database), `feature/compass-wording` (one wording style).
- Old branches safe to delete: `feature/verify-to-database` (outdated, local + GitHub),
  `feature/verify-save-to-database`, `feature/compass-wording`, `integration/nouhaila-2026-10-27`,
  older `feature/*` (all merged). Keep `backup/*` a few days. Don't delete Ismail's/old GitHub branches without his OK.

---

## 4. Production database facts (read-only check, 30 Oct)

- Directory organizations (`actor_read`, not merged): **730**. `actor.status='rejected'`: 159
  (≈153 September placeholders + Directory removals). Hubs **48**, events **357**, people **0**.
- `search_candidate` pending: ~11,900 (Review shows only recent work since Ismail's cutoff).
- Source origins: `imported_phase1` (shown "Imported"), `claude_discovered` ("AI mapped"),
  `ghus_manual`, `ghus_uploaded_doc`, `uploaded_document`, `newly_found`, `imported`.
- Migrations: 590 (`ghus_import` verification origin) **is on production**. A trigger
  `actor_verification_event_project_status` copies each verification decision onto
  `actor.status`; `actor_verification_event` is append-only.
- Removed via Directory Delete so far: **"AI-in-medicine research labs"** (placeholder, by
  Nouhaila); its hidden merged duplicate "AI-in-health research labs" (test before the guard);
  and one more by someone else on 29–30 Oct (count went 731 → 730).
- **CAER** (Center for Applied Energy Research) was saved from a map → waiting in Review
  Results (admission found an ambiguous match). Approve it as New to see it in the Directory.

---

## 5. What is built (the platform today)

### Explore and Map (`frontend/index.html` BuildMap, `src/map_agent/*`)
- **Start screen** (Fatima's mockup): "What would you like to explore?", saved-map dropdown,
  big box, Attach a document, Start Search, sources note, 3 commonly-used prompts with
  editable [brackets] (click fills the box and selects the first bracket).
- **Conversation = chat timeline:** each search's results sit **right under the message that
  started it** (`round_after` positions); progress/Stop in the thread; composer sticky at the
  bottom; map-wide actions (Save verified, Excel, PowerPoint, Monitor this topic) above it.
- **Always asks first** on a new map's first message (planner gets no plan tool on that turn;
  `FIRST_MESSAGE_RULE`); plans after the answer; max 2 question rounds. Follow-ups on a built
  map: questions about results are answered free; new ground starts a follow-up search.
- **One type per search; follow-ups may switch type** (organizations → people → events,
  `round_types`); multi-type requests start with organizations and offer the next type.
- **Planner rules:** knows GHUS/UM6P/OCP; every query stays inside the named area; summary
  describes only the current search; never invents periods (date requirements the user didn't
  name are dropped in code).
- **Selection:** hard filters pass/fail with a reason for each exclusion; a match needs the
  topic in the candidate's own fields.
- **Events:** one edition per card (merge never mixes editions; nearest upcoming kept, other
  date → "Previous edition"); status computed from dates (partial dates as ranges);
  `end_date` and full spans (MM/DD/YYYY); default window = upcoming + last 12 months.
- **Header:** map name, "Cost so far: $X of $2.00", saved maps, + New map. "Approve $1 more"
  only when a map stopped at its budget or used 80%.
- **Result filters:** All / Pending review / Ready to save / Parked / Saved; Everything /
  Matches / Left out; Any date / Upcoming / Past (event maps).
- **Cards:** Pending review until decided; **Verify** (free) marks "Ready to save"; Park /
  Reject (reject = removal from that map).
- **Save verified to Compass (Verify → database):** panel with a Sector per record, a free
  dry check ("Will be added / Will go to Review Results / Can't be saved yet: Needs…"), an
  attestation checkbox (no name field). Goes through **Data Feed method `map`** → backend
  staging + admission: new organizations with a category type are admitted **Verified**
  (labelled AI mapped / `claude_discovered`); matches, untyped, events and people → Review
  Results. Card outcome stored as `_db_save` (NOT `_saved`: FastAPI's encoder drops keys
  starting with `_sa`). Undated "recent activity" is not sent (Data Feed requires a date).
- Backend-facing texts were removed (coverage notes, searched queries, cost by stage…).

### Ecosystem Directory (`frontend/index.html` Directory/RecordPage, `src/browse.py`)
- One design for all four tabs: keyword search; filters incl. **Status** and **Owner**
  (Owner reads "Not recorded" until logins); All Records / My Records (greyed until logins);
  "Verified records only"; table with blue names, source + status badges, short type names,
  row chevron; "N … shown" + Export (CSV).
- Organizations filters: Sector, Organization type, Hub, Region, State, **City** (branch),
  More filters (Country, Curation). Hubs: Sector, State, City (text). Events: When, Type,
  City or place, Frequency. People: Organization, State, Topic. TRL removed entirely.
- Edit form: one column, every field, grouped; **Save is switched off** (needs Ismail's writers).
- **On the unpublished branch:** working **Delete** (organizations only; warning → reason →
  "Are you sure?" → removed for everyone; `remove_from_directory` / `restore_to_directory`
  decisions through `record_verification_decision`; Status → Removed with Restore; merged
  duplicates refused); events/hubs/people show the panel switched off. **Profile layout**:
  header + sections ("Not found" for empty) + side "At a glance" and "Sources and history"
  (new read-only `/api/browse/actors/{id}/profile`: sources, latest verification, events
  organized, relationships). City filter. No typed names (`current_user()`).

### Ask Compass
- Fatima's layout: "What would you like to know?", big box, Attach, "Ask Compass" button,
  note pointing to Explore and Map, 5 prompts with [brackets].

### Platform-wide
- COMPASS sidebar (compass icon, "Ecosystem Intelligence"), page names as in §1.
- One vocabulary everywhere: **Compass** (not "the agent"), **organization** (not "actor"),
  **the directory** (not "the map") for the database; statuses Pending review · Ready to save ·
  Parked · Verified · Rejected/Removed; sources Imported · AI mapped. Page openings: a title or
  question + one plain sentence. "Light Pull"/"Deep Pull" kept (team decision pending).
- Dates MM/DD/YYYY everywhere.

---

## 6. Demo plan (rehearsal Fri 30 Oct, team demo Tue 3 Nov, logins target Wed 4 Nov)

Format (Fatima): live walkthrough, ~90 min. Fatima (context) → **Nouhaila (her agents)** →
Ismail (his workflows) → what's being built + pilot feedback. Run maps **in advance**; keep one
cheap prompt for live requests.

**Nouhaila's storyline (~20 min):** "From a question to a verified partner".
1. **Ask Compass**: "Which organizations in our directory work on phosphate or phosphogypsum?"
   (≈59 relevant orgs) and "Which hubs have we mapped for Mining?"; then "Research this on the web".
2. **Explore and Map — interaction script** (works every time now):
   "We're looking for US partners for UM6P's work on phosphate fertilizers and soil health."
   → it asks → "Research centers and companies first, in Florida and the Southeast."
   → results under the message → "Which of these already work with industry?" (free answer)
   → "Now find the experts at these organizations." (Follow-up 1, people).
3. **Events:** "Find upcoming conferences in the US on fertilizer innovation and soil health."
4. **Startups:** "Map startups in Texas developing green ammonia or green hydrogen."
5. **Verify → Save verified to Compass** on 2 new organizations; show the duplicate safety net
   (FIPR already exists → Review Results).
6. **Ecosystem Directory:** Arizona Mining hub profile (10 orgs); filter Energy Transition →
   Texas → Houston (43); open a profile with sources; Export; show Delete panel, then cancel.
7. **Monitor this topic** → hand-off to Ismail.

Say honestly: Directory edits not saved yet; Delete is organizations only; no logins yet (Owner
"Not recorded"); 0 people in DB; some imported descriptions are weak (e.g. 3M's is an SEC note).
Deck: https://claude.ai/artifact/F9ttfsup59EHfbXC1t3vFE (private; fill `[__]`, recompute KPIs).

---

## 7. Open items

**Nouhaila / Claude (no dependency):**
- Pull+push `main`; rebase, test, publish `feature/directory-delete` + PR; delete old branches.
- Run the demo maps in advance (≈$4–5 with approval) and check them; test the Ask questions.
- Investigate the failed map "Conferences in the US on Energy and industrial transformation"
  (`e15cb1d5…`, "Extraction returned an invalid record list" after $1.03).
- Agent alignment with Ismail: descriptions/fields/taxonomy so records look the same whichever
  agent made them; make `entity_schemas.py` organization description as strict as Ismail's
  (`ghus-backend/agents/discovery/extractors/actor.py`); people bio rule (his agent forbids bios).
- Smaller: delete saved maps; answer map questions from full card details; deck placeholders.
- Data notes for Fatima's Excel keep/delete review (export already done by Ismail): 3M
  description is an SEC note; "Greentown Labs Houston" has city Boston (state Texas).

**Needs Ismail:** review Directory PR (`admission.py` decision kinds) and the `stage_import.py`
"map" method merged in #5 (attestation key question); delete path for events/hubs/people;
saving Directory edits (`append_actor_fact`, `record_ghus_notes`, status decisions);
`attended` column for events; Park → database; Review Results and Data Feed to use
`current_user()` instead of typed names; personal queues (below); rename Light/Deep Pull?

**Needs Fatima:** where Dashboard and Data Feed go; Light/Deep Pull naming; ownership rules.

**Fatima's ownership request (28 Oct):** Monitor and Update and Review Results show only the
user's own requests/results; others' Verified/Parked visible in the Directory. Needs logins +
owner fields (Ismail). Open questions: owner of automatic runs/imports (= creator); manager
"All" view; parked map results are local until Park→DB exists.

**Biggest risk:** deployment + logins by 4 Nov has **no owner**. Personal queues, Owner, My
Records and recording who verified/deleted all depend on it.

---

## 8. Decisions — do not relitigate

- One type per search; follow-ups may switch type (organizations → people → events).
- A new map's first message always gets questions first (29 Oct); clear later turns don't.
- Verify = free "ready to save" mark; saving is a batch ("Save verified to Compass") through
  the Data Feed; never per-card instant writes. No paid check on Verify.
- Delete is **removable, never wiped** (status Rejected via the backend writer, Restore
  available); true wipes only as admin cleanup by Ismail (test/junk/privacy).
- Reject on a map = removal from that map only; Park = deliberate "not ready" (Fatima).
  Pending review = waiting for a decision.
- No typed names; `current_user()` until accounts.
- Organization sector stays free text on maps; events use the 8 sectors; saving asks a sector.
- Contact email lives in `.env`.
- Events: 12-month window by default (14 discussed, not decided).

---

## 9. Key files

- `src/map_agent/planner.py` — conversation + plan (`_SYSTEM`, `_CHAT_RULE`, `FIRST_MESSAGE_RULE`, `_FOUND_RULE`, `map_chat`).
- `src/map_agent/research.py` — resumable pipeline (rounds, `round_types`, `round_after`, editions, window, selection, profiles, rankings).
- `src/map_agent/event_dates.py` — date ranges, status, `dates_text`, `same_edition`.
- `src/map_agent/dedup.py` — merge rules (events never mix editions; `_seen_in`).
- `src/map_agent/select.py` — requirement enforcement (rules 1–8).
- `src/map_agent/save.py` — map cards → Data Feed records; check/save outcomes.
- `src/map_agent/review.py` — park/reject/ready marks, `mark_saved` (`_db_save`).
- `src/browse.py` — read-only Directory loaders (`load_actors`, `load_removed_actors`, `load_actor_profile`, hubs, events, people). Must never write (a test checks).
- `backend/app.py` — routes; `current_user()`; `/api/map/{id}/save-check|save`; `/api/browse/actors/{id}/remove|restore|profile`.
- `frontend/index.html` — single-file UI (Ask, BuildMap, Directory, RecordPage, DeletePanel, SavePanel…). Ismail's: `review.js`, `discovery.js`, `datafeed.js`, `dashboard.js`, `labels.js`.
- `src/datafeed/service.py` (platform side) · `ghus-backend/agents/datafeed/stage_import.py` (method `map`) · `ghus-backend/agents/review/admission.py` (directory decisions, on the branch).

## 10. KPIs (for the deck; recompute before presenting)

From 18 completed maps (13 Sept–20 Oct): 266 results; median 16/map; median research time
3 min (1–30); median cost $0.42/map ($0.22–1.45), 0 over the $2 cap; median $0.03/result;
337/337 records sourced.
