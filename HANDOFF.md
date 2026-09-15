# UM6P Intelligence — Project Handoff

_Last updated: 2026-09-03. Paste this into a new chat to pick the project up cold._

---

## 0. TL;DR

An internal RAG platform for the **UM6P Global Hubs US team (~4 users)**. Three
features, all working:

1. **Ask** — chat the database, get cited answers (SQL + semantic routing).
2. **Browse** — filterable Actors / Hubs (49) / Events (231).
3. **Build the Map** — describe a domain in a chat; an agent web-scouts US
   research organizations, ranks them against what you asked for, verifies them
   on demand, and exports to Excel / PowerPoint.

Everything runs on `localhost:8000`. No auth. Nothing from a map is written to
the database. The last two features (2's export + the chat rebuild) are the
newest work; **local commits are ahead of `origin` and not yet pushed.**

---

## 1. Ground rules

- Working dir: `/Users/ghus/Desktop/um6p-rag`
- Git remote: `github.com/nouhailael-dot/Institutional-knowledge-Platform-with-AI-agents`
- Python 3.11, conda env `~/.conda/envs/um6p` (interpreter `~/.conda/envs/um6p/bin/python`)
- Secrets in `.env` (git-ignored): `DATABASE_URL`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`
- **DB is READ-ONLY from this repo.** Schema + ETL are owned separately by a colleague.
- Run the app: `uvicorn backend.app:app --port 8000` (or the `um6p-api` preview config)
- **The preview server drops on its own between turns in the agent sandbox** — if
  you want it to stay up while working, run uvicorn in a real terminal.

---

## 2. Two UIs — know which you're editing

| | Streamlit (`app.py`) | **React + FastAPI (active)** |
|---|---|---|
| Status | Frozen reference, do not edit | **All work happens here** |
| Run | `streamlit run app.py` | `uvicorn backend.app:app --port 8000` |
| Files | `app.py` | `backend/app.py` (API) + `frontend/index.html` (UI) |

`backend/app.py` wraps `src/` unchanged. The frontend is a **single-file, no-build
React app** — React/htm/marked from esm.sh CDN. Needs internet for the CDN.

---

## 3. Stack

- **DB**: Supabase (Postgres + pgvector), session pooler
- **Embeddings**: Voyage `voyage-3` (1024-dim)
- **LLM**: Anthropic Claude — `claude-opus-4-8` (Ask answers), `claude-haiku-4-5`
  (condense, planner chat, judge), `claude-sonnet-5` (discovery, enrichment,
  selection)
- **API**: FastAPI + uvicorn + python-multipart
- **Map exports**: openpyxl (.xlsx), python-pptx (.pptx)
- **Deliberately NOT used**: LangChain / LangGraph (a linear chain of plain
  functions at this scale), any scraping library (Anthropic's servers fetch pages)

---

## 4. Feature 1 & 2 — Ask and Browse (stable, unchanged this era)

**Ask** (`src/router.py`, `retrieve.py`, `generate.py`)
- SQL route: Claude writes a read-only SELECT for counting/listing → exact answer.
  Hardened: read-only session, 8s timeout, `is_safe_select()`.
- Semantic route: hybrid pgvector + tsvector, fused with RRF → cited answer.
- Multi-turn: follow-ups condensed to standalone questions (Haiku) before routing.
- Document upload: attach a PDF/txt/md, questions cross-reference it.
- Verified this session: "Which US hubs are relevant to Morocco's drought/food
  systems?" returns a strong cited answer (California Water Hub, Arizona Water
  Innovation Hub, Colorado Sustainability Hub).

**Browse** — Actors / Hubs / Events with filters. Sector is DERIVED from hub
`primary_sectors` (the `actor_sector` table is empty).

---

## 5. Feature 3 — Build the Map (the main body of recent work)

### The shape
**Chat to plan → automatic pipeline → result cards → on-demand verify → export.**

### 5a. Planning is a conversation (`planner.py`)
- You describe the map. The agent replies in prose to ask questions, or calls
  `submit_plan` when it has enough — and **decides on its own when to start; no
  approval step.** It announces what it will do in a plain-English `summary`.
- Never shows search keywords — talks about the *kinds* of organizations.
- Hard cap of **2 question rounds** (`MAX_QUESTION_ROUNDS`), then forced to commit
  (prompting alone didn't reliably stop it).
- Parses the request into a **spec**, not just a topic: `hard_filters`,
  `preferences`, `result_limit`. Filters that narrow *where* to look are also
  written into the queries.
- Backend: `POST /api/map/chat {messages, doc_id}` → `{status: reply|plan|error}`.

### 5b. Pipeline (`pipeline.py`, runs as a background job)
1. **Discover** (`discover.py`, Sonnet + `web_search`/`web_fetch`, parallel, 10
   workers) — one agent per task; records a **source URL per entity**. Detects
   server-tool errors (they return HTTP 200 with an error object, not a raise).
2. **Enrich** (`enrich.py`) — optional per-entity detail pass. **OFF by default**
   (it was the bulk of cost/time and only tops up fields). Its sources-merge bug
   is fixed (merges onto the original; never replaces).
3. **Dedup** (`dedup.py`) — rapidfuzz, free.
4. **Enforce the request** (`select.py`, one Sonnet call) — the only stage that
   sees the full candidate set + the original wording. Applies filters, ranks,
   annotates each with `_selected` / `_rank` / `_why`. **Never deletes.**
- Backend: `POST /api/map {description, plan, doc_id, enrich, actor_focus}` →
  `{job_id}`; poll `GET /api/map/{job_id}` → `{status, result, ...}`.

### 5c. On-demand verification (`verify.py`)
Triggered by "Verify" (per card) or "Verify all". Chain:
- **URL liveness** (`urlcheck.py`, free) — dead / hallucinated links.
- **Independent judge** (`judge.py`, separate Haiku call) — relevance score +
  reason. The link verdict is fed in, so a dead site counts against it.
- **Relevance floor** (`floor.py`, threshold 0.5) — flags weak matches, never hides.
- Backend: `POST /api/map/verify {entities, request}` → annotated entities + summary.

### 5d. Export (`export.py`, pure formatting — $0, no LLM)
- `to_xlsx` — one sheet per entity type, schema columns + "Why relevant" + Sources.
- `to_pptx` — cover slide + one slide per entity, **branded to the team's deck**.
- Exports **selected matches only** (or the whole list if the map had no requirements).
- Backend: `POST /api/map/export {result, request, fmt}` → streams .xlsx / .pptx.
- Frontend: "Excel" / "PowerPoint" buttons in the results bar.

### 5e. Defaults (all deliberate)
- US only.
- **~80/20 weighted to universities & national labs** (`actor_focus="research"`,
  not exposed in UI — this platform maps partners for a university).
- **Organizations only** unless you ask otherwise.
- **Events only when explicitly requested** (words like conference/summit/workshop).
- **No TRL** — judgment field, stays human-written (matches the enrichment agent's rule).
- Deep enrichment off.

### 5f. Fields collected (match DB schema; system columns excluded)
- **actor**: name, actor_type, description, website, location_city, state, country,
  primary_technical_focus, technical_approach, current_activities, funding_summary
- **person**: full_name, title, bio, linkedin_url, email
- **event**: name, event_type, description, location, website, next_date,
  recurring_pattern, sponsoring_orgs, thematic_focus, expected_attendance, access_type

---

## 6. Measured economics (NOT estimates)

| | |
|---|---|
| Cost per map | **~$4** (with enrichment off; was ~$12–14 with it on) |
| Time per map | **~12 minutes** |
| A test-day total | **$22** — 8.45M tokens in, 293K out, 242 web searches |
| Input : output | **29 : 1** — this is an *input* cost problem |
| Export | **$0** — pure local formatting |

**Pricing note:** Sonnet 5 is **$2 / $10** per MTok (not $3/$15). **Every
cost/latency figure that was ESTIMATED during development was wrong by 3–5×.**
Measure with `resp.usage`; do not estimate.

**Levers** (all input-side): `max_content_tokens` on web_fetch (currently 4000 —
highest leverage, since fetched text re-sends every hop), then `MAX_HOPS` (8), then
number of planner tasks. Reducing task *count* cuts cost but NOT time — tasks run
in parallel, so wall-clock = the slowest single task.

---

## 7. Verified by real runs

- A 58-entity map (27 orgs, 25 people, 6 events): correct cities, real founders,
  accurate titles, real venues.
- A 38-entity academic run: **every one** a university lab / national lab / research
  center / venture studio, **all with sources**, including PI-level labs (Hatton Lab
  at MIT, Amanchukwu Lab at UChicago).
- Judge caught a bank in a farming map (0.05) and a placeholder person (0.10).
- Selection excluded a lab that passed the geography filter but failed the
  technical one — with a correct explanation.
- Export: valid Office files (PK zip signature), unselected entities excluded.

---

## 8. Brand

**The real UM6P orange is `#D7410B`** — confirmed from the team's own workshop deck
(`GHUS_Workshop2_Plan.pptx`). Titles Cambria, body Calibri; card fills gray
`#EDEDED` and peach `#F6D7CB`; ink `#3D3935`.

- The **PPTX and XLSX exports use `#D7410B`.**
- The **web app still uses the placeholder `#ef7d1a`** in `frontend/index.html`
  (`--accent`). Propagating the real orange there is a pending one-line-ish change.

---

## 9. Open risks / gaps

- **No persistence.** Map results live in an in-memory job store (cap 12) and die
  on server restart. Two runs were lost this way, one ~$12. **The export feature is
  the current mitigation** — a downloaded file survives. A real fix (save maps to
  disk / a local table) is still the #1 thing to close.
- **No auth**, on endpoints that cost ~$4 per call. Do not expose beyond localhost.
- **No automated tests.** Every check has been manual → real regression risk.
- **Not re-measured** since removing the "don't write code" prompt rule and adding
  server-tool error handling (the latter verified only against synthetic inputs,
  never seen fire for real).
- **The PPTX was not visually rendered** on this machine (no LibreOffice) — verified
  structurally only. Open in PowerPoint/Keynote; long descriptions may overflow a card.
- **Document upload through the new chat flow is untested** end-to-end (refactored to
  upload-first + `doc_id`, but only tested without a file). The Growth Engine use
  case is document-driven — **test this before that demo.**

---

## 10. Git state

- Branch `main`. Last pushed commit is `9816f3d`.
- **Two local commits ahead, NOT pushed:**
  - `6833b3f` feat(map): Build the Map — conversational web-scouting agent
  - `8228dbb` feat(map): export a map to branded .xlsx / .pptx
- Push from your own terminal (`git push origin main`) — the sandbox has no reliable
  push credential and this is an outbound action left to the user.

---

## 11. Repo structure (map agent)

```
src/map_agent/
  planner.py    Chat + plan. Parses request as a SPEC. map_chat() is the entry point.
  discover.py   Per-task web-search agent. Records sources. server_tool_errors().
  enrich.py     Optional detail pass. OFF by default. Merges (never replaces).
  dedup.py      rapidfuzz merge. No LLM.
  select.py     Enforces the request against the full set. Ranks, never deletes.
  verify.py     On-demand chain: urlcheck -> judge -> floor.
  urlcheck.py   URL liveness. Pure Python, concurrent.
  judge.py      Independent relevance judge. Separate Haiku call.
  floor.py      Relevance threshold 0.5. Flags, doesn't hide.
  export.py     .xlsx / .pptx rendering. Branded. Pure formatting.
  pipeline.py   Orchestrator (build_map).
```

Backend map routes in `backend/app.py`: `POST /api/map/chat`, `POST /api/map`,
`GET /api/map/{job_id}`, `POST /api/map/verify`, `POST /api/map/export`. In-memory
job store `_MAP_JOBS` (cap 12) + doc store `_DOC_STORES` (cap 24). Nothing to Postgres.

---

## 12. Discussed, not built

- **UM6P context file** — a standing half-page (priority domains, Morocco-
  transferability lens, what makes a partner valuable) applied at the **selection
  stage only**, so discovery stays broad. Principle agreed: strategy **ranks and
  explains, never filters** — safe because selection never deletes. Blocked on the
  user's real priorities in their own words.
- **"What's new vs. our DB"** — flag each discovered entity as already-tracked or new.
- **Outreach brief** per entity (what they do, why relevant, who to contact).
- **Batch venture matching** for the Growth Engine office (several ventures → shortlists).
- **Saved maps / persistence**, **change monitoring** (re-run on a schedule).
- **Resume enrichment agent (Task 1A)** — 137 actors missing website, 19 missing country.

---

## 13. Suggested next steps

1. **Push** the two local commits.
2. **Test document upload** through the map chat (before the Growth Engine demo).
3. **Persistence** for map results — the #1 durability gap.
4. **Propagate `#D7410B`** into the web app.
5. **Run the Growth Engine venture test** (the manager's pending request).
6. Later: auth, before sharing any link; a few automated tests.

---

## 14. Other repo — don't conflate

A colleague owns `GHUS_RAG` (reranker, observability, Curate UI, Alembic, evals).
Which repo becomes the platform of record is unresolved. A code-review doc that
circulated targets `GHUS_RAG`, not this repo — check which is meant before acting
on it.
