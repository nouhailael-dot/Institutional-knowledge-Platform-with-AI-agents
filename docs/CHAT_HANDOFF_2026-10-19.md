# UM6P Intelligence — Chat Handoff, 19 October 2026

Give this file to a new chat to pick the project up cold. It is the **current state**
and **supersedes `CHAT_HANDOFF_2026-09-29.md`** where they disagree (Reject, Park,
duplicates, map types, Ask labels and the database have all changed since).
Verify anything you act on against the code: this is a snapshot, not the code.

---

## 0. Working rules with this user — read first

These are standing instructions from the user (Nouhaila, intern on the GHUS team).
They are also saved in Claude's project memory.

1. **Never change code without asking first.** Propose the change (files + what),
   wait for an explicit yes, then edit. Reading code, running tests and read-only
   checks are fine. This includes "obvious" fixes and items on an agreed task list.
2. **Challenge weak ideas.** Say when a proposal has a flaw or a better way exists,
   naming the concrete failure case — don't agree and build quietly.
3. **Never spend money without approval.** Live map runs cost real Anthropic
   credits ($0.20–0.60 each so far). Planner-only checks cost < $0.01 — still say so.
4. **Never write to the production database.** It is read-only from this repo;
   schema and data belong to Ismail. "Do not change anything in the database" was
   said explicitly.
5. **Test destructive UI actions (Reject) on a scratch copy of a map**, then delete
   the scratch copy. Never reject on the user's real maps.
6. **Commit only when asked.** One commit per piece is preferred, but several pieces
   share `frontend/index.html`, so combined commits have been accepted. The user
   pushes from their own terminal — this environment has no GitHub login.
7. **Be honest about built vs planned.** At the 13 Oct meeting three things were
   described as done that are not (see §9). Distinguish agreed / prototype / done.
8. Leave out side conversations from meeting transcripts (admin/JVAP paperwork is
   not project work).

---

## 1. Read in this order

| Source | What it is | Trust |
|---|---|---|
| **This file** | Current state, decisions, open tasks | Current |
| `~/Downloads/Architecture V2 Sept.docx` | **Spec of record**: categories, light/deep pull, people §5.3, events §5.4, UM6P/OCP §5.5, linking §6 | Authoritative |
| `~/Downloads/Actor_Categories_and_Link_Types_Intern_Guide.docx` | **Authority for the 12 categories, their category types and link types** (written up from the 11 Oct meeting) | Authoritative |
| Claude project memory (`~/.claude/projects/-Users-ghus-Desktop-um6p-rag/memory/`) | Decisions, meeting notes, user preferences | Current, check dates |
| `docs/CHAT_HANDOFF_2026-09-29.md` | Previous handoff; architecture and cost detail still valid | Partly superseded |
| `docs/MAP_COST_TRACKING.md`, `docs/PROJECT_CHANGE_HISTORY.md` | Cost/recovery detail; narrative history | Historical |
| `Database schema.md` | August survey of the DB | **Stale** — predates the V2 migration (§4) |
| `~/Downloads/GHUS_Platform-main/` | Appears to be **Ismail's platform repo** (agents: discovery, enrichment, review, weekly_discovery; Alembic migrations). Not part of this repo. Read-only reference | Unverified |

Read docx with: `textutil -convert txt -stdout "<file>.docx"`.

---

## 2. What the platform is, and who does what

Internal research platform for the **UM6P Global Hubs US (GHUS) team**. Local tool,
no authentication, `http://localhost:8000`.

| Page | Purpose | Paid? |
|---|---|---|
| **Ask** | Question the verified database; SQL for counts, hybrid search otherwise; cited answers | Yes (small, outside the map ledger) |
| **Build the Map** | Research beyond the database: a map of **organizations, people, or events** (one type per map) | Yes — metered, $2 budget, extendable to $3 |
| **Browse** | Filter actors, hubs, events from the database | No |

Navigation order is **Ask, Build the Map, Browse** (changed 16 Oct per the 13 Oct meeting).

**People**
- **Nouhaila** (user): this repo — Ask, Build the Map, the Ask→Map bridge, light pull, review buttons.
- **Fatima Zahra EL ALAMI**: manager. Prefers frequent short check-ins over silent weeks.
- **Ismail Sabbar**: production database, schema, updating agent, hub detection, Review page.
- **David, Mehdi, Tarek**: other team members / future users. A presentation for Mehdi
  uses the critical-minerals → phosphogypsum → Southeast demo (memory: `project_mehdi_presentation.md`).

---

## 3. Running, testing, configuration

```bash
.venv/bin/python -m uvicorn backend.app:app --port 8000 --reload
.venv/bin/python -m unittest discover -s tests -p "test_*.py"
```

- Use **`.venv/bin/python`** (Python 3.12). `python` is not on PATH; pytest is not installed — tests are `unittest`.
- `.claude/launch.json` defines preview server `um6p-api` (same command). If port 8000 is
  busy it is usually the user's own terminal server — preview that instead of starting another.
- **170 Python tests pass** (with the uncommitted work in §8). All use mocks/local stores; no paid calls.
- `tests/test_hub_matching.mjs` and `tests/test_map_ui.mjs` need **Node** (`node --experimental-vm-modules tests/test_map_ui.mjs`); Node is **not installed** here, so they have not been run since the September changes.
- `.env` keys (never print values): `DATABASE_URL`, `VOYAGE_API_KEY`, `ANTHROPIC_API_KEY`, `MAP_RESEARCH_ENABLED=1` (live research on).
- Local map store: `.map_runs/runs.sqlite3` (SQLite: `runs`, `calls`, `work_cache`, `budget_approvals`, `people_tasks`). Saved maps' results are JSON inside `runs.result`; the resumable research state is `work_cache` key `workflow`.
- Browser cache: after frontend edits, the in-app browser may keep the old page — load `http://localhost:8000/?v=<anything>`. Users: Cmd+Shift+R.

**Models**
| Use | Model |
|---|---|
| Ask answers | `claude-opus-4-8` (`src/generate.py`) |
| Ask follow-up condensing | `claude-haiku-4-5` |
| Ask → Map handoff (filters from the conversation) | `claude-sonnet-5` |
| Map planner | `claude-haiku-4-5-20251001` (`planner.py`) |
| Map extraction | `claude-sonnet-5` (`research.py`) |
| Map selection | `claude-sonnet-5`, effort medium (`select.py`) |
| Verify judge | `claude-haiku-4-5-20251001` |
| Embeddings | Voyage `voyage-3` (1024-dim) |

**Money**: every paid call goes through `src/map_agent/costs.paid_message` (integer
micro-USD reservations in SQLite). Map default **$2**, explicit extension to **$3**;
per-organization people search has a separate **$3** allowance. Unknown charges block
further paid work. It is a local estimate, not a provider billing ceiling.

---

## 4. Production database (Supabase Postgres + pgvector) — read-only

The database was migrated by Ismail to **Architecture V2** (around 6 Oct). Read actors
through the **`actor_read`** view, always with `merged_into_actor_id IS NULL`.

- `actor_read`: 732 live actors, all `status = 'verified'`. Columns include
  `actor_category`, `category_type`, `category_note`, `category_needs_review`,
  `website_domain`, `is_multi_location`, `state_code`, `region_code`, `alt_names`.
- `actor_category_definition`: 12 codes (`university_academic`, `research_center`,
  `national_laboratory`, `applied_facility`, `hospital_clinical`, `company`, `startup`,
  `innovation_platform`, `investor`, `government`, `foundation_nonprofit`,
  `association_network`) with display names — **3 display names are still the old ones**
  (Innovation Platform / Incubator / …; Investor / VC / …; Industry Association / …).
- `actor_category_type_definition`: an **older type list than the intern guide** (uses
  "Other" not "Not Applicable"; tech transfer under innovation_platform; no Medical School;
  sorts many categories by a different axis). Ismail must update it and reclassify actors.
- `entity_edge_type_definition`: 11 link types in snake_case (`unit_of`, `operated_by`,
  `affiliated_with`, `member_of`, `portfolio_of`, `spinout_of`, `funded_by`,
  `collaborates_with`, `organizes`, `participates_in`, `connected_to_um6p_ocp`).
  The map uses spaced forms ("unit of") — map them when writing to the DB someday.
- `region_definition`: 7 regions, matching `REGIONS` in `actor_profile.py` exactly.
- `sector`: 10 sectors (Agriculture, Water, Artificial Intelligence, Energy Transition,
  Mining, Specialty Chemicals, Healthcare, Sustainability, African Diaspora, Cross-Thematic).
  Map `sector` is still free text — user said "not now" to restricting it.
- **`search_doc`** (what Ask's hybrid search reads) is an **offline snapshot** built by
  `python -m src.embed` and is stale: 153 indexed actors are no longer live (the
  placeholders GHUS rejected) and 13 live actors are missing. `src/retrieve.py` now
  filters to live actors (code-only fix). **Rebuilding writes to the DB → Ismail's call.**

---

## 5. Architecture

```
backend/app.py          FastAPI: Ask stream, browse, map endpoints, export, review, reopen
frontend/index.html     Single-file React 18 + htm (esm.sh); Ask / Build the Map / Browse
src/router.py           Ask: SQL vs semantic routing (schema prompt uses actor_read)
src/retrieve.py         Ask: hybrid vector + keyword search over search_doc, live actors only
src/generate.py         Ask: answers ("verified database" wording), condense, Ask→Map handoff
src/browse.py, assemble.py, embed.py   Browse data; search_doc build (offline)
src/map_agent/
  planner.py            Conversation + plan; map_type (organizations|people|events); today's date
  research.py           Controlled, resumable map run: search → extract → selection → rankings
  search_backend.py     Claude web search, bounded page reads, evidence cache
  entity_schemas.py     Extraction schemas: actor, person (org-card search), map_person, event
  actor_profile.py      12 categories + CATEGORY_TYPES (intern guide), LIGHT_GUIDANCE, regions
  select.py             Request enforcement/ranking, every exclusion has a reason
  dedup.py              Duplicate merge/flag rules
  relationships.py      People ↔ organization linking
  review.py             Park / Unpark / Reject (organizations, people, events)
  parked.py             Ask's search over parked records (Voyage embeddings, cached)
  run_store.py          SQLite jobs, budget, checkpoints, resume/reopen, edit_result
  costs.py              The ONLY paid-call gateway
  people_research.py    "Find relevant people" on an organization card ($3 allowance) — DO NOT TOUCH
  export.py             Excel / PowerPoint
  verify.py, judge.py, urlcheck.py, floor.py   The current "Verify" button (paid check)
  rankings.py           Approved ranking publishers
```

### Ask (how sources work)
1. Follow-ups are condensed into a standalone question.
2. Router: counts/lists → SQL against live DB; everything else → hybrid search (top 10)
   over `search_doc`; attached document → document chunks + 8 DB hits.
3. Parked map records close to the question (cosine distance ≤ 0.70, max 5) are added
   after DB results (`parked.py`).
4. The answer cites only sources; DB answer first, then a "Parked, not verified" part.
5. UI labels: chip "Verified database search · cited" (+ "parked organizations"),
   "Exact · verified database", "Your document + verified database". Each source tagged
   **Verified database / Parked — not verified / Your document**. SQL answers show
   "Source — verified database" (the SQL query is no longer shown, per user).

### Build the Map
- **Planner** decides map type from the request words; asks "organizations, people or
  events?" only when none is named or two are; never mixes types; a built map keeps its
  type (asking for another type → "start a new map").
- **Research phases** (`research.build_controlled_map`): `organizations` (task loop —
  name kept for all types) → `selection` → `rankings` (universities only) → `done`.
  Up to 4 searches, 10 hits, 3 page reads per search. Follow-ups append tasks; only
  newcomers are judged; rejected-in-this-map records are skipped.
- **Organization maps**: Architecture V2 light pull; category + **category type**
  (guide lists, "Not Applicable", wrong-category type → Not Applicable + note,
  old maps show "Not classified"); classification rules (university units → University;
  hospitals always Hospital; national labs always National Lab).
- **People maps** (`map_person`, V2 §5.3 light pull): name, title, organization at
  department level, organization city/state, expertise, public profile (only if the page
  is about the person — uncommitted D), evidence of relevant work, affiliation evidence
  year (> 3 years old → "unconfirmed", fails "where they work now" filters), UM6P/OCP
  status (kept only if a read source shows it), email only if asked. People without a
  spelled-out full name are dropped (uncommitted C).
- **Event maps** (V2 §5.4): type, date + date status (full date checked against today;
  "date unconfirmed" fails time windows), location, organizer, sector, topic, recurrence,
  why it matched, UM6P/OCP status, notable public claims in the description.
- **Cards**: Verify (paid link/relevance check — NOT a database push), **Park / Unpark**,
  **Reject** (in-card confirmation; browser `confirm()` is auto-dismissed in some
  browsers). "Find relevant people" only on organization cards. "Possible duplicate of X"
  notes. "Parked only" filter.
- **Stopped maps**: "Continue unfinished research" (stopped mid-research) or "Reopen this
  map" (stopped before research; free). A note under the disabled Send button says which.
- **Export**: Excel/PowerPoint per type, with Review, Category type, people/event V2 columns.

### Duplicate rules (`dedup.py`, organizations only)
Merge on: same name; shared alternate name (≥ 4 chars); short bracketed alias matching an
alternate name ("(FIPR Institute)"); same words reordered; similar name **and** same
homepage. **Mark, don't merge** ("possible duplicate"): ≥ 85% similar names without a
homepage match; one record listing the other's full name as an alternate name (often a
parent); long brackets describing a unit. A shared deep page (lab listing) never merges.
People and events keep the old fuzzy-name rule.

---

## 6. Decisions — do not relitigate

- **Taxonomy**: the intern guide's names for categories and types (user chose guide names
  over DB names; DB to be updated by Ismail).
- **One type per map**; planner asks only when unclear/mixed; organization's name on a
  person card is **text only** (no organization records created).
- **Reject** = permanent removal from that map (user chose this over hide), confirmed
  in-card. It **never** affects future/other maps. The same map's own follow-ups skip what
  was rejected there — user said keep this as is.
- **Park** = undecided; stays on the map, labelled, filterable, searchable by Ask as
  "Parked — not verified". Lives in the local map store (not the DB). No owner, no
  3-month expiry yet (need accounts).
- **Verify** stays as the paid check for now; approve-and-push to the DB waits for Ismail
  and accounts. Earlier agreed design: batch "Push all verified", one DB-write module,
  approver name once accounts exist.
- **"Find relevant people" box on organization cards must not be changed** (its schema,
  prompt and behaviour) — the people-map record is a separate schema.
- **Affiliation evidence** older than 3 years = unconfirmed; undated official profile
  page = current.
- **Ask → Build the Map**: Ask and Build the Map stay separate pages; "Research this on the
  web" (at the end of the Ask chat) condenses the conversation into editable rows; filters
  come only from what the user wrote; nothing spends until Send.
- **Ask's source of truth is called "the verified database"** everywhere.
- **Hubs**: new-hub proposals keep human review (revisit mid-December). Criteria discussed:
  same topic, several categories, ~200-mile radius, ~50-mile core. Ismail's area.
- **Updates**: monthly cadence favoured (daily rejected); "Continue discovery" button at the
  bottom of a map → separate Updates page (not Review). Ismail builds the page/agent.

---

## 7. What was built since 29 September (all on GitHub `main` up to `904e2d4`)

| Commit | Content |
|---|---|
| `b49a33f` (5 Oct) | Ask → Build the Map bridge; continuous map conversation; selection repair |
| `2ddfac0` | Guide category names + category types; classification rules; Africa/Morocco connections; "Category note" shown only when present; Multiple locations hidden; safer dedup + possible-duplicate notes; resume after manual stop + Reopen; Park/Reject + Ask parked search; Ask "verified database" labels; Ask search limited to live actors; Architecture V2 DB reads (`actor_read`) |
| `689aa02` | Note under disabled Send; forget a deleted remembered map |
| `904e2d4` | Maps about organizations, people or events; V2 light pull for people/events; planner gets today's date; affiliation-age and date-unconfirmed rules; Park/Reject/Verify on people and event cards; in-card Reject confirmation; nav order; wider handoff fields |

Live tests (16 Oct, ~$0.58): people map — 6 of 8 relevant experts (FIPR, ORNL, UF);
events map — 3 of 14 matched, past events correctly excluded. They exposed issues A–F,
now fixed (A/E/F committed, B/C/D uncommitted — §8).

---

## 8. Uncommitted work right now

Files: `src/map_agent/planner.py`, `src/map_agent/research.py`,
`src/map_agent/entity_schemas.py`, `tests/test_map_types.py`. All 170 tests pass.

- **B** planner names the type from the user's words without asking ("experts" → people;
  "conferences" → events; "universities" → organizations). Checked live on the planner.
- **C** people maps drop people without a spelled-out given name + surname; coverage notes
  count them.
- **D** people maps keep a profile link only for profile-style pages (people/faculty/staff
  paths, ORCID, LinkedIn `/in/`, Google Scholar) or the surname in the URL.

Ask the user before committing. A live rerun of a people map + events map (~$0.60) would
check C, D, E, F on real results — needs approval.

---

## 9. Known issues and risks

1. **Claims made at the 13 Oct meeting that the code does not back** — correct before the
   next presentation: Verify does **not** push to the DB; **OCP/UM6P affiliation for
   organizations is not built** (only people/event maps record a status; actor
   `um6p_ocp_status` is stripped; the master Excel from Fatima has not arrived);
   **questions beyond organizations** in a map conversation are not built.
2. `search_doc` is stale (§4) — Ask can't find 13 newest actors; text previews show
   pre-V2 type names. Needs Ismail's rebuild.
3. Browse still shows the 3 old category names (reads DB display names).
4. Many publisher pages (ACS, OSTI, ResearchGate) can't be fetched; extraction then uses
   search snippets only — thinner evidence, older affiliations.
5. The planner is Haiku and can over-ask or pick odd queries; B addressed the main case.
6. JS tests unrun (no Node).
7. The local map store is ~9 MB of JSON in SQLite; fine now, the user has raised scalability.
8. `docs` handoffs before this one describe Reject as "nothing is deleted" — superseded.

---

## 10. Open tasks (as of 19 Oct)

**Pending decision / quick**
1. Commit B/C/D (§8). Optional live rerun to check C–F (~$0.60).
2. Remove diagnostic-only UI but keep the cost display — user must say which elements
   (likely "Cost by stage", "Coverage gaps").
3. Check the Ask → Build the Map handoff live: the topic field must not repeat the filters.
4. Run the `.mjs` tests with Node.

**Before the next presentation**
5. Correct the three claims in §9.1; prepare the demo section (Ask → Map bridge, people
   and events maps); run a fresh organization map to show category types on real data;
   review the written 13 Oct minutes (team asked this before more building).

**Medium — needs a decision first**
6. Park visible/filterable in **Browse** — DB status column (Ismail) vs local store; if in
   the DB, every Ask/Browse query must exclude parked or "verified database" becomes false.
7. **"Continue discovery"** button → Updates page (topic, duration, monthly cadence) — depends
   on Ismail's page and its name.
8. **Verify → database** with confirmation / batch push — depends on Ismail + accounts.

**Big**
9. **People tab in Browse** with filters (location, topic, organization).
10. Person ↔ organization links in the DB; organization profile lists its people.
11. **Analyst notes** on actors, people, events (incl. GHUS event notes per V2 §5.4) — needs DB storage.
12. **Questions beyond organizations** in a map conversation — offer a paid in-platform
    search or a copy-paste prompt for the user's own Claude, with cost shown first.
13. **OCP/UM6P connections** for organizations — waits on Fatima's Excel; V2 §5.5 rules.

**For Ismail (database changes)**
14. Rename the 3 category display names to the guide's names.
15. Replace the category-type table with the guide's lists ("Not Applicable") and reclassify the 732 actors.
16. Rebuild `search_doc` (`python -m src.embed`).

**Later**
17. Accounts: who verified/rejected/parked; filter by person; viewer vs supervisor roles;
    delete parked after 3 months; monthly report email (owner unclear).
18. Sector as the DB's fixed 10-sector list.
19. Parked records in Ask's SQL and document modes.

**Ismail's own items (awareness)**: one layered confidence/verification rule set (he will
send a proposal); field-meaning documentation; background maintenance of existing actors
(confident → auto-update, else Review; never erase old funding); light change log/report of
new vs updated actors; updating agent redesign to opt-in topic/sector/actor scoped updates.

---

## 11. Meeting context

- **Manager meeting (undated, transcript shared 11 Oct)**: taxonomy session (12 categories +
  category types, dropdowns with "Not applicable"), Verify/Reject/Park, accounts and monthly
  report, updating agent redesign, priorities (quick fixes "this Friday", bigger work ~2
  weeks). Exact dates unknown. Memory: `project_platform_priorities.md`,
  `project_updating_agent_redesign.md`.
- **13 Oct meeting (written summary)**: hub detection (human review), updates workflow
  (monthly, Updates page), review criteria + light change log, Ask source labels, Build the
  Map demo, **people/events scope gap** (now built as map types), Browse needs People.
  Memory: `project_meeting_2026_10_13.md`.

---

## 12. Standing cautions

- **One paid-call path**: everything through `costs.paid_message`. Never treat a failed paid call as free.
- **One API worker per SQLite store.**
- **Editing files restarts the `--reload` server** and interrupts a running map.
- Operation replay keys exclude system prompts — prompt changes don't force re-payment on
  resume, but old replayed outputs may carry old field names (handled by `LEGACY_CATEGORIES`
  and defaults in `backend/app.py:public_map`).
- Measure cost/latency with real `usage`; earlier estimates were off 3–5×.
- The in-app browser auto-dismisses `alert/confirm` — use in-page UI.
- When the guide/spec and meeting notes disagree, ask the user; the intern guide is the
  authority for taxonomy, Architecture V2 for pulls and linking.
