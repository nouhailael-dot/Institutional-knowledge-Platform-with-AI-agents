# UM6P Intelligence — Project Status & Chat Handoff

_Paste this into a new chat so it knows exactly where the project stands. Last updated 2026-08-19 — built the **"Build the Map" agent (Task 2)**: a web-scouting agent that maps a new domain into structured actors/people/events. Agent logic is built and verified end-to-end; not yet wired into the UI. See §14 for full detail._

---

## 1. What this project is

**UM6P Intelligence** — an internal RAG platform for the **UM6P Global Hubs US team (~4 users)**. It makes a research database of US innovation ecosystems (actors, hubs, events the team tracks for partnership-building) searchable in plain English, with **cited** answers.

- This repo is the **RAG / application layer only**. The Postgres schema and the ETL that populates it are owned and maintained separately (not by this repo). **All DB access is read-only** except the (not-yet-built) enrichment write path.
- Working directory: `/Users/ghus/Desktop/um6p-rag`
- Git remote: `github.com/nouhailael-dot/Institutional-knowledge-Platform-with-AI-agents.git`
- Current branch: `main`, HEAD = `9816f3d`. Pushed to `origin/main`.
- User: git identity `ghus`; email `nouhailahail12@gmail.com`.

## 2. Two UIs exist — know which one you're editing

| | Streamlit (`app.py`) | **React + FastAPI (active)** |
|---|---|---|
| Status | Frozen reference. Not maintained. | **This is where all new work happens.** |
| Run | `streamlit run app.py` → `localhost:8501` | `uvicorn backend.app:app --port 8000` → `localhost:8000` |
| Files | `app.py` (root) | `backend/app.py` (API), `frontend/index.html` (UI) |

`backend/app.py` is a thin FastAPI layer that **wraps `src/` unchanged** — same `retrieve`/`generate`/`router`/`browse` engine. If asked to "fix the Ask page" or "add a Browse filter," it means the React app unless told otherwise.

## 3. Environment & how to run

- Python 3.11, conda env at `~/.conda/envs/um6p` (interpreter: `~/.conda/envs/um6p/bin/python`).
- Secrets in `.env` (loaded via python-dotenv): `DATABASE_URL`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`.
- **Run the app**: `uvicorn backend.app:app --port 8000` from repo root, or via Claude Code preview tool using `.claude/launch.json` (config name `um6p-api`, wired with `--reload`).
- Rebuild the search index (offline, after source data changes): `python -m src.embed`.
- **No Node.js / npm on this machine.** The frontend is a **no-build single-file React app**: React/ReactDOM/htm/marked loaded from `esm.sh` CDN. Works for local demo but needs internet access.

## 4. Tech stack

- **DB**: Supabase (Postgres + `pgvector`), session pooler.
- **Embeddings**: Voyage `voyage-3` (1024-dim).
- **LLM**: Anthropic Claude. Main answer generation `claude-opus-4-8` (`src/generate.py`). Condense model `claude-haiku-4-5` (`CONDENSE_MODEL` in `src/generate.py`) rewrites follow-up questions for multi-turn. Enrichment agent uses `claude-sonnet-5` (`src/enrich/agent.py`).
- **API layer**: FastAPI + `uvicorn[standard]` + `sse-starlette` + `python-multipart`.
- **Frontend**: React 18 (via esm.sh CDN, no build step), `htm` for JSX-less templating, `marked` for markdown. Single file: `frontend/index.html`.
- **Other**: rapidfuzz (data-quality scan), pypdf + numpy (document upload).
- **Deliberately NOT used**: LangChain (too heavy for this scale).

## 5. Architecture

**Two query flows:**
- **SQL route** (`src/router.py`): counting / aggregation / "how many / list all" → Claude writes a **read-only SELECT** → Postgres runs it → exact answer. Safety: read-only DB session (8s timeout) + `is_safe_select()` validation. Names matched with `ILIKE '%fragment%'`.
- **Semantic/RAG route** (`src/retrieve.py` → `src/generate.py`): hybrid pgvector cosine + Postgres tsvector keyword, fused with **Reciprocal Rank Fusion**, then Claude generates a **cited** answer (`(source: Entity Name)` inline). System prompt forbids outside knowledge.

**Multi-turn conversation** (`src/generate.py:condense_question`): follow-up questions are rewritten into standalone queries using the last ~3 turns on the cheap Haiku model, before routing/retrieval. Surfaced as "Interpreted as: …" for transparency. Fails open on error.

**LLM prompt guardrails (added this session)**: both the SQL formatter (`router.py:format_sql_answer`) and the semantic answer generator (`generate.py`) have explicit instructions to **never explain how the search worked** — no commentary on ILIKE patterns, false positives, or query mechanics. Just state the answer.

## 6. Repo structure

```
app.py                  Streamlit UI (FROZEN — not maintained).
backend/app.py           FastAPI layer wrapping src/. Endpoints:
                            GET  /api/ask/stream       SSE: SQL/semantic/doc routing, streamed cited answer,
                                                        multi-turn via ?history=<json>, ?doc_id=<id>
                            POST /api/upload            extract+embed a doc, returns {doc_id, name}
                            GET  /api/browse/actors      + hub-derived `sectors` field, sector filter options
                            GET  /api/browse/hubs
                            GET  /api/browse/events      + event_types list
                            GET  /api/health
                            GET  /  and static mount     serves frontend/index.html
frontend/index.html      Entire React app: Ask (chatbot UI) + Browse (Actors/Hubs/Events). No build step.
data_quality_scan.py     Read-only scan → DATA_QUALITY_REPORT.md (dupes, country mess). rapidfuzz.
src/
  db.py                 get_connection() / get_readonly_connection() (read_only=True, 8s timeout).
  assemble.py           Build-time join: actor + partnership_profile + relevance + hubs → doc_text blob.
  embed.py              Voyage embedding + writes search_doc (offline build).
  retrieve.py           Hybrid vector+keyword retrieval, RRF merge. retrieve(question, top_k).
  generate.py           Claude answer generation (MODEL=claude-opus-4-8) + condense_question()
                         (CONDENSE_MODEL=claude-haiku-4-5 — multi-turn support).
  router.py             plan() SQL vs semantic; is_safe_select(); run_sql(); format_sql_answer().
  browse.py             Pure data module for Browse (load_*, filter_*, normalize_country() on read).
  documents/            Document-upload feature: extract.py, chunk.py, doc_store.py (per-session,
                         never writes Postgres). Driven by both Streamlit AND backend/app.py.
  enrich/               Task 1A scaffolding (dry-run, PAUSED — see §8):
    gaps.py             Read-only gap worklist: live actors missing website/country, by tier.
    agent.py            Per-(actor,field) web-search agent -> cited proposal via a strict tool.
    run.py              Driver: loops the worklist -> writes proposals.jsonl. No DB writes.
  map_agent/            Task 2 "Build the Map" — web-scouting agent (BUILT, verified; see §14):
    planner.py          Stage 1: single Haiku call -> search plan (entity_type + query + focus).
    discover.py         Stage 2: per-task Sonnet agent w/ web_search+web_fetch -> entity list.
    enrich.py           Stage 3: per-entity detail pass, fills missing fields (optional).
    dedup.py            Stage 4: pure-Python rapidfuzz merge of duplicate entities.
    pipeline.py         Orchestrator: plan -> discover(parallel) -> enrich(parallel) -> dedup.
.claude/launch.json     Preview-server config: `um6p-api` runs uvicorn backend.app:app --reload --port 8000.
```

## 7. The React app, feature by feature

### Ask — multi-turn chatbot
- Chat bubbles: user (orange, right), assistant (left with avatar), auto-scrolling.
- Sticky bottom composer with attach-doc row + input + Ask button.
- "+ New conversation" resets. Empty state shows welcome + example chips.
- Multi-turn: last 3 turns sent as `history`. "Interpreted as: …" shown when rewritten.
- Mode chips: `Exact · from the database` (SQL), `Map search · cited` (semantic), `Document + map · cited` (doc-attached).
- **Document upload**: attach PDF/txt/md → server extracts+embeds → subsequent questions merge doc passages with map retrieval. In-memory store (capped at 24). Nothing written to Postgres.

### Browse — Actors / Hubs / Events
- **Actors**: filters for Hub, Sector (hub-derived), Country, State, Min TRL (slider), name/description search, "Deeply-profiled only" checkbox, type chips. Detail card with sector chips and verification badge.
  - Sector is DERIVED from hub `primary_sectors`, not stored per actor (`actor_sector` table is empty).
- **Hubs**: search bar (name/city/sector, client-side substring). 49 hubs.
- **Events**: **Type filter** (Strategic event / UN event / UN key event / UNGA-Climate Week event), location-contains text filter, Date filter (Any / Upcoming / Past / Custom range). 231 events, 72 with dates.

### Design
- UM6P orange brand accent (`--accent`), hub=teal, event=violet, document=slate.
- Orange hex is a **placeholder guess** (`#ef7d1a` light / `#f6a15c` dark) — not confirmed against real UM6P branding. One-line CSS variable change to correct.
- Editorial serif headings (`Iowan Old Style`/Georgia), light + dark mode, micro-transitions.

## 8. Task 1A — enrichment agent (PAUSED, resumable)

Built but **on hold**. Clean stopping point.

- **`src/enrich/gaps.py`**: 137 actors missing website, 19 missing country.
- **`src/enrich/agent.py`**: Claude (`claude-sonnet-5`) with web-search tools + strict `submit_proposal` tool. Refuses rather than guesses.
- **`src/enrich/run.py`**: `python -m src.enrich.run --field website --limit N` → writes `proposals.jsonl` (dry run, zero DB writes).
- **Key finding**: 2-actor pilot hit aggregate/category-label rows, not real organizations — agent correctly refused. **Before scaling: build a triage step** to separate real-org vs. category-label rows.
- **Open question**: does an approved proposal write to the live DB, or hand back to the colleague's ETL? Write credentials / RLS on `proposal` table unresolved.

## 9. Recent session changes

**Most recent session (2026-08-19) — built the "Build the Map" agent (Task 2).** Full detail in §14. Summary: created the `src/map_agent/` module (planner, discover, enrich, dedup, pipeline). Agent logic built and verified end-to-end (a single discovery search returned 11 real US vertical-farming orgs). NOT yet wired into the backend/frontend — that's the next step. No existing files were changed; the module is self-contained. Also wrote `BUILD_THE_MAP_STATUS.md` (a plain-English progress file).

**Prior session (team demo):**
1. **Event type filter**: added Type dropdown to Browse > Events (4 types: Strategic event, UN event, UN key event, UNGA/Climate Week event). Backend returns `event_types` list alongside events.
2. **Suppressed verbose search explanations**: both `router.py:format_sql_answer` and `generate.py` system prompts now explicitly forbid explaining ILIKE patterns, query mechanics, or false positives. Answers state results directly.
3. **Simplified Ask welcome text**: "Ask anything about the actors, hubs, and events we track across US innovation ecosystems. Every answer is grounded in the database with cited sources."
4. **Generated demo PDF**: `UM6P_AI_Initiative_Strategy_2026.pdf` — a 5-page AI strategy document (agriculture, water, mining, healthcare, foundation models) with NO actor/hub names, designed for uploading to the platform to demo cross-referencing a strategy doc against the actor database.

## 10. Team presentation (completed)

The platform was **presented to the team**. A manager responded positively and shared an example request from the UM6P Growth Engine office — identifying actors (experts, customers, partners) for specific new ventures. This is exactly the document-upload use case the platform already supports. Some ventures fall within mapped domains; at least one (Orven) does not.

**Next step**: run a test with the Growth Engine ventures to demonstrate the platform can handle real incoming requests, and be transparent about coverage gaps for out-of-domain ventures.

## 11. GHUS_RAG — the other repo (don't conflate)

A colleague owns a separate repo (`GHUS_RAG`) with a more architecturally complete implementation (reranker, observability, Curate UI, Alembic migrations, eval harness). A code-review document was shared that targets GHUS_RAG, not this repo. **Which repo becomes the platform of record is still unresolved.** If asked to fix items from that review, check which repo is meant first.

Items from that review that **do apply to our code**: no auth (biggest gap), prompt-injection hardening on `doc_text`, incremental embedding, one-vector-per-entity retrieval ceiling, no connection pooling, no tests/CI, always-Opus cost posture, no relevance floor on vector search.

## 12. Deployment & auth — parked

- **No public URL.** Everything runs on `localhost:8000`.
- **No authentication.** Deferred — flag before sharing any link.
- Prior conversation sketched a deploy plan (single container + identity-aware proxy for ~4-user allowlist) — not started.
- Code is pushed to GitHub.

## 13. Open threads / TODO

- [x] ~~Push `main` to `origin`~~ (done).
- [ ] **Finish Task 2 "Build the Map"** — wire the agent into the app: backend endpoint + frontend page + end-to-end browser test. Agent logic is done (see §14).
- [ ] Run a test with the Growth Engine venture descriptions (manager's request).
- [ ] Confirm the exact UM6P orange hex and correct `--accent` in `frontend/index.html` (ON HOLD per user).
- [ ] Resolve **which repo is the platform going forward** — `um6p-rag` or `GHUS_RAG`.
- [ ] Add authentication (highest-priority gap) before sharing any link (ON HOLD per user).
- [ ] **Resume Task 1A enrichment**: build triage step, then scale pilot.
- [ ] Resolve enrichment write-access / apply-to-live-vs-hand-back question.
- [ ] Build the review UI (approve/reject proposals) once triage + pilot look good.
- [ ] Deployment: pick platform + auth approach (parked per user request).
- [ ] Decide: keep CDN frontend or set up a real Node/Vite build.
- [ ] Fill the eval set (~2 → ~20 questions) and run the scorer.

## 14. Task 2 — "Build the Map" agent (BUILT, verified; NOT wired into UI yet)

**Goal.** A third tab (next to Ask and Browse) called **"Build the Map"**. The user
describes a domain / venture / program to map (free text), optionally uploads a
document (PDF/txt/md), and an agent scouts the web to find relevant **actors,
people, and events** — **US only** — returned as structured records matching the
DB table columns. Results are shown **all at once when done** (user's choice, not
streamed). The agent **decides which entity types** to look for from the input.

**Naming.** Tab + page title = "Build the Map".

**Fields collected** (matched to the DB schema, system columns excluded):
- **actor**: name, actor_type, description, website, location_city, state, country, primary_technical_focus, technical_approach, current_activities, funding_summary, estimated_trl
- **person**: full_name, title, bio, linkedin_url, email
- **event**: name, event_type, description, location, website, next_date, recurring_pattern, sponsoring_orgs, thematic_focus, expected_attendance, access_type

**Architecture — 4 stages, in `src/map_agent/`:**
1. **`planner.py`** — one `claude-haiku-4-5` call. Reads the description (+ up to 6k chars of doc text) and returns a list of search tasks `[{entity_type, query, focus}]`. Uses a `submit_plan` strict tool. Cheap.
2. **`discover.py`** — one `claude-sonnet-5` agent per task. Tools: Anthropic server `web_search` + `web_fetch` (version `*_20260209`) plus a `submit_entities` tool. Loops up to `MAX_HOPS=8`, `MAX_TOKENS=8192`. Returns a list of entity dicts (each tagged `_entity_type`).
3. **`enrich.py`** — optional per-entity detail pass (`claude-sonnet-5`, `MAX_HOPS=6`, `MAX_TOKENS=4096`). Visits the entity's site / searches to fill missing fields; keeps existing values; falls back to the original entity if it can't improve it.
4. **`dedup.py`** — pure Python + rapidfuzz. Merges duplicates (same entity_type AND (name ≥85 fuzzy OR same normalized website)); keeps the longer value per field. No LLM, no cost.

**`pipeline.py`** — `build_map(description, doc_text=None, do_enrich=True)` orchestrates: plan → discover (parallel, `ThreadPoolExecutor`, 4 workers) → enrich (parallel) → dedup → group by entity type. Returns `{"tasks":[...], "counts":{...}, "entities":{"actor":[...],"person":[...],"event":[...]}}`. Per-task/per-entity failures are caught and skipped, not fatal.

**Two bugs found & fixed during testing:**
1. `strict: True` on the discover/enrich submit tools → API errors *"Schema is too complex" / "Grammar compilation timed out"* (the array-of-objects schema is too big for strict-mode grammar compilation). **Fix: dropped `strict` on those two tools** (kept it on the small planner schema). Entity extraction made defensive with `.get("entities", [])`.
2. The Sonnet agent crams all its work into one turn (it also reaches for the bundled `code_execution`/`bash_code_execution` server tools) and hit `max_tokens=4096`, **truncating the `submit_entities` call → 0 results**. **Fix: raised `max_tokens` (8192 discover / 4096 enrich); treat `max_tokens` like `end_turn` (best-effort return, don't echo a truncated tool_use); prompt now says "work lean, don't write code."**

**Verified.** Planner produces good plans; a single discovery search for "vertical farming startups USA" returned **11 real US orgs** (Oishii, Bowery Farming, 80 Acres Farms, Little Leaf Farms, Eden Green, Revol Greens, …) with names/locations/websites. Dedup unit-tested with sample data.

**Cost & speed (important).** Roughly **$2–5 per map** (vs cents per Ask question) — the agent makes many web searches/fetches and the Sonnet agent does a lot of work per turn. A map takes a **few minutes**. Flag this before opening it to the team. The `do_enrich=False` path is meaningfully cheaper if needed.

**Remaining work to ship it:**
- Backend: add `POST /api/map` to `backend/app.py` (accept `multipart/form-data`: `description` + optional `file`; reuse `src/documents/extract.py` for the upload; call `build_map`; return the grouped JSON). Long-running — consider a job/polling pattern or a generous timeout since a map takes minutes.
- Frontend: add the "Build the Map" tab to `frontend/index.html` — textarea + file upload + a "Build" button, a loading state, and result cards grouped into Organizations / People / Events.
- End-to-end test from the browser preview.
- Decide whether the detail-enrichment pass is on by default (cost vs completeness).
