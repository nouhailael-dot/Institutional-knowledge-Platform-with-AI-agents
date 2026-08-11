# UM6P Intelligence — Project Status & Chat Handoff

_Paste this into a new chat so it knows exactly where the project stands. Last updated at the end of the session that built the React + FastAPI app (Ask/Browse/doc-upload), redesigned it around a UM6P-orange research-console look, added Hubs search + Events date filtering, turned Ask into a real multi-turn chatbot, and scoped Task 1A enrichment (paused, resumable)._

---

## 1. What this project is

**UM6P Intelligence** — an internal RAG platform for the **UM6P Global Hubs US team (~4 users)**. It makes a research database of US innovation ecosystems (actors, hubs, events the team tracks for partnership-building) searchable in plain English, with **cited** answers.

- This repo is the **RAG / application layer only**. The Postgres schema and the ETL that populates it are owned and maintained separately (not by this repo). **All DB access is read-only** except the (not-yet-built) enrichment write path.
- Working directory: `/Users/ghus/Desktop/um6p-rag`
- Git remote: `github.com/nouhailael-dot/Institutional-knowledge-Platform-with-AI-agents.git`
- Current branch: `main`, HEAD = `6150606`. **One commit ahead of `origin/main`, NOT pushed** — this sandbox has no cached GitHub credential (`fatal: could not read Username for 'https://github.com'`). Push from your own terminal: `git push origin main` (macOS Keychain will prompt for a PAT), or set up `gh auth login` / SSH first. See §10.
- User: git identity `ghus`; email on file `nouhailahail12@gmail.com`.

## 2. ⚠️ Two parallel UIs exist — know which one you're editing

| | Streamlit (`app.py`) | **React + FastAPI (active)** |
|---|---|---|
| Status | Frozen reference. Untouched this whole session. | **This is where all new work happens.** |
| Run | `streamlit run app.py` → `localhost:8501` | `uvicorn backend.app:app --port 8000` → `localhost:8000` |
| Files | `app.py` (root) | `backend/app.py` (API), `frontend/index.html` (UI) |

`backend/app.py` is a thin FastAPI layer that **wraps `src/` unchanged** — same `retrieve`/`generate`/`router`/`browse` engine, same SQL-vs-semantic routing logic, nothing about the RAG core was rewritten. Only the presentation layer changed. If asked to "fix the Ask page" or "add a Browse filter," it means the React app unless told otherwise.

## 3. Environment & how to run

- Python 3.11, conda env at `~/.conda/envs/um6p` (interpreter: `~/.conda/envs/um6p/bin/python`).
- Secrets in `.env` (loaded via python-dotenv): `DATABASE_URL`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`. **The Anthropic key was rotated this session** (old one was invalid/401; a fresh key was pasted into `.env` and confirmed working).
- **Run the React app** (the active one): `uvicorn backend.app:app --port 8000` from repo root, or via the Claude Code preview tool using `.claude/launch.json` (config name `um6p-api`, already wired with `--reload`).
- Run the old Streamlit app: `streamlit run app.py`.
- Rebuild the search index (offline, after source data changes): `python -m src.embed`.
- **No Node.js / npm on this machine.** `brew install node` failed — `/opt/homebrew` is owned by a different user, `chown` needs `sudo` (the user's password, which this session can't supply). The frontend is therefore a **no-build single-file React app**: React/ReactDOM/htm/marked are loaded live from `esm.sh` via an import map in `frontend/index.html`, and FastAPI serves that file as a static asset. This works great for local demo but needs internet access and isn't a real production build. Fixing this later means either the user runs `sudo chown -R $(whoami) /opt/homebrew*` once, or installing Node another way (nvm, official pkg installer), then standing up a real Vite project.

## 4. Tech stack

- **DB**: Supabase (Postgres + `pgvector`), session pooler.
- **Embeddings**: Voyage `voyage-3` (1024-dim).
- **LLM**: Anthropic Claude. Main answer generation `claude-opus-4-8` (`src/generate.py`). **New this session**: a second, cheap model `claude-haiku-4-5` (`CONDENSE_MODEL` in `src/generate.py`) used only to rewrite follow-up questions into standalone ones for multi-turn conversation. The Task 1A enrichment agent (`src/enrich/agent.py`) uses `claude-sonnet-5` with web-search tools, isolated from both.
- **API layer** (new): FastAPI + `uvicorn[standard]` + `sse-starlette` + `python-multipart` — added to `requirements.txt`.
- **Frontend** (new): React 18 (via esm.sh CDN, no build step), `htm` for JSX-less templating, `marked` for markdown rendering. Single file: `frontend/index.html`.
- **UI (legacy)**: Streamlit (`app.py`, frozen).
- **Other**: rapidfuzz (data-quality scan), pypdf + numpy (document upload, ported to the new app too).
- **Deliberately NOT used**: LangChain (too heavy for this scale).

## 5. Architecture

**Two query flows, unchanged from the original design, now served two ways (Streamlit and the FastAPI `/api/ask/stream` endpoint):**
- **SQL route** (`src/router.py`): counting / aggregation / "how many / list all" → Claude writes a **read-only SELECT** → Postgres runs it → exact answer. RAG retrieves a fixed number of docs and so **structurally cannot count**. Safety: runs on a hardened **read-only** DB session (8s timeout) + `is_safe_select()` validation. Names matched with `ILIKE '%fragment%'`.
- **Semantic/RAG route** (`src/retrieve.py` → `src/generate.py`): hybrid pgvector cosine + Postgres tsvector keyword, fused with **Reciprocal Rank Fusion**, then Claude generates a **cited** answer (`(source: Entity Name)` inline, not `[SOURCE n]` indices). System prompt forbids outside knowledge.

**New this session — multi-turn conversation** (`src/generate.py:condense_question`, wired into `backend/app.py:/api/ask/stream` via an optional `history` query param): a follow-up question is rewritten into a standalone question using the last ~3 turns, on the cheap Haiku model, **before** it hits the SQL/semantic router. This means "which of those are in Florida?" resolves against the previous answer instead of literally searching for that string. The rewritten form is surfaced to the user ("Interpreted as: …") for transparency and debuggability. Fails open — on any error it falls back to the literal question rather than crashing.

## 6. Repo structure (file by file)

```
app.py                  Streamlit UI (FROZEN — reference only, not edited this session).
backend/app.py           FastAPI layer wrapping src/ unchanged. Endpoints:
                            GET  /api/ask/stream       SSE: SQL/semantic/doc routing, streamed cited answer,
                                                        multi-turn via ?history=<json>, ?doc_id=<id>
                            POST /api/upload            extract+embed a doc, returns {doc_id, name}
                            GET  /api/browse/actors      + hub-derived `sectors` field, sector filter options
                            GET  /api/browse/hubs
                            GET  /api/browse/events
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
                         (CONDENSE_MODEL=claude-haiku-4-5, new this session — multi-turn support).
  router.py             plan() SQL vs semantic; is_safe_select(); run_sql(); format_sql_answer().
  browse.py             Pure data module for Browse (load_*, filter_*, normalize_country() on read).
  documents/            Document-upload feature: extract.py, chunk.py, doc_store.py (per-session,
                         never writes Postgres). Now driven by both Streamlit AND backend/app.py.
  enrich/               Task 1A scaffolding (NEW, dry-run, PAUSED — see §8):
    gaps.py             Read-only gap worklist: live actors missing website/country, by tier.
    agent.py            Per-(actor,field) web-search agent -> cited proposal via a strict tool.
    run.py              Driver: loops the worklist -> writes proposals.jsonl. No DB writes.
.claude/launch.json     Preview-server config: `um6p-api` runs uvicorn backend.app:app --reload --port 8000.
```

Root docs: `Database schema.md` (live DB survey), `Tech_Summary.md`, `DATA_QUALITY_REPORT.md`, this file. (`HANDOFF.md`, stale, was deleted in an earlier session.)

## 7. The React app, feature by feature (all built this session)

### Ask — now a real chatbot
- Conversation thread with **chat bubbles**: user messages right-aligned (orange), assistant replies left-aligned with an avatar, in a `.chat` flex column, auto-scrolling to the newest turn.
- **Sticky bottom composer** (attach-doc row + input + Ask button), content scrolls underneath with a fade.
- **"＋ New conversation"** resets the thread. Empty state shows a centered welcome + example chips.
- **Multi-turn memory**: see §5. The last 3 completed turns (question + first 600 chars of answer) are sent as `history` on every follow-up.
- Mode chips per turn: `⚡ Exact · from the database` (SQL), `◎ Map search · cited` (semantic), `📎 Document + map · cited` (doc-attached).
- **Document upload**: `📎 Attach a document` → `POST /api/upload` → server extracts+embeds it, holds the store in an in-memory dict keyed by a UUID (`_DOC_STORES` in `backend/app.py`, capped at 24, oldest evicted), returns `doc_id`. Subsequent questions pass `doc_id` and the answer merges document passages with map retrieval. Nothing written to Postgres. **Verified end-to-end via the API directly** (upload → doc-aware ask, correct budget figure + citation returned); the actual browser file-picker click was not driven by automation (same limitation as Streamlit) — spot-check manually.

### Browse — Actors / Hubs / Events
- **Actors**: filters for Hub, Country, State, Min TRL (slider), name/description search, "Deeply-profiled only" checkbox, and type chips — plus a **new Sector filter**.
  - ⚠️ **Sector is DERIVED, not stored.** `actor_sector` (the real per-actor join table) is **empty (0 rows)** in the DB. The filter instead uses each actor's **hub's** `primary_sectors` (8 of 10 catalog sectors actually appear on hubs: Agriculture, AI, Specialty Chemicals, Energy, Healthcare, Mining, Sustainability, Water). Backend: `backend/app.py:_sectors_by_hub()` / `_sector_code_to_name()`. UI has a "Sector ⓘ" tooltip explaining this. Verified live: filtering "Water" narrows 872 → 67 actors.
  - Detail card shows sector chips (teal) alongside the verification-status badge.
- **Hubs**: **new search bar** (name / city / sector, case-insensitive substring, client-side over the already-loaded 49 hubs). Verified: "water" → 5 hubs.
- **Events**: **new Date filter** — Any date / Upcoming / Past / Custom range (native date pickers for range). Adds a "past" chip badge on rows before today. Keeps the existing location-contains text filter. Honest about data limits: a hint note says "Only 72 of 231 events carry a scheduled date — date filters list just those." Verified: "Upcoming" → 37 of 231 events.

### Design
- Redesigned from a first-pass teal theme into **UM6P orange as the brand accent** (`--accent`), with hub=teal, event=violet, document=slate as the secondary category colors (colour-coded entity chips throughout, e.g. in the Ask Sources panel).
- ⚠️ **The orange hex is a placeholder guess** (`#ef7d1a` light / `#f6a15c` dark), not confirmed against the real UM6P logo. Everything keys off the single `--accent` CSS variable, so correcting it later is a one-line change — **get the exact hex from the user before this goes anywhere real.**
- Editorial serif headings (`Iowan Old Style`/Georgia stack), card depth via layered shadows, light **and** dark mode via `prefers-color-scheme`, micro-transitions on hover/focus.

## 8. Task 1A — enrichment agent (scaffolded, PAUSED, resumable)

Built but **on hold** — the user asked to pause agent work and focus on the frontend; nothing here was abandoned, it's a clean stopping point.

- **`src/enrich/gaps.py`** (read-only, free): confirmed via live query — **137 actors missing website** (128 `ai_inferred` + 2 `phase_1` + 7 untiered), **19 missing country**. Small and precise, not the ~730 the original handoff assumed (an enrichment pass had apparently already run against the shared DB between sessions).
- **`src/enrich/agent.py`**: given one actor + a target field (`website` or `country`), uses Claude (`claude-sonnet-5`) with `web_search`/`web_fetch` server tools and a strict `submit_proposal` tool. Refuses (`found=false`) rather than guessing when it can't verify from a credible source. System prompt requires entity disambiguation (name + city/state/hub) before searching.
- **`src/enrich/run.py`**: driver, `python -m src.enrich.run --field website --limit N` → writes `proposals.jsonl` (dry run, **zero DB writes**). Proposal rows are already shaped to match the `proposal` table schema for a trivial later swap.
- **⚠️ Key finding from a 2-actor live pilot**: the two actors probed (*"Academic & Medical Anchors"*, *"Academic Anchors"*) turned out to be **aggregate/category-label rows**, not real organizations — the agent correctly refused to invent a website for them (guardrail working as intended). This means **before scaling the pilot, a triage/entity-resolution step is needed** to separate real-org rows from category-label rows in the 137/19 gap lists, or the agent will burn API calls failing on non-entities. This step (§ Task 1A workflow "② Triage") was designed but not built.
- **Full workflow discussion** (gap scan → triage → enrich → threshold → human review → apply → re-index, shared between Task 1 "deepen existing map" and Task 2 "map a new domain on demand") is captured in conversation but not written to a file. Consider writing `ENRICHMENT_WORKFLOW.md` if resuming this — it was offered and not yet requested.
- **Open gating question, still unresolved**: does an approved proposal write to the live DB, or hand back to the colleague's ETL/source spreadsheets? Do we have write credentials (the `proposal` table has RLS enabled)? Nothing here needs that resolved to keep prototyping — proposals stay in the dry-run JSONL until it's answered.

## 9. Context from the GHUS_RAG code-review episode (important — don't conflate repos)

Mid-session, the user pasted a long, high-quality code-review document (bug list M-01…M-08, platform items P-01…P-10, product ideas E-01…E-07, an alignment scorecard). **I verified it targets a different, colleague-owned repo (`GHUS_RAG`)** — almost every file it references (`src/sql_answer.py`, `src/observability.py`, `pages/ask.py`, `Makefile`, etc.) doesn't exist here; our router exposes `plan()`/`is_safe_select()`, not their `classify()`/`validate_sql()`. This confirms the **original handoff's still-unresolved "which repo is the platform going forward" question is now more informed but still open** — GHUS_RAG appears to be the more architecturally complete implementation (reranker, observability/query_log, Curate UI, Alembic migrations, an eval harness that's been run). If a future session is asked to "fix bug M-04" or similar, **check which repo is meant** before touching anything — see the conversation transcript for the full applies/doesn't-apply breakdown if needed.

Items from that review that **do genuinely apply to our `um6p-rag` code** (worth prioritizing if this becomes the platform of record): no authentication (P-01, biggest gap — the React app has zero auth right now), prompt-injection hardening on `doc_text` in `generate.py` (C-07), incremental/content-hash embedding in `src/embed.py` (P-03, likely re-embeds everything on every build), one-vector-per-entity retrieval ceiling (C-01), no connection pooling (P-02), no tests/CI (P-04), always-Opus cost posture with no model ladder (P-08), no distance-relevance floor on vector search (C-02), no metadata filtering in retrieval (C-03, partially mitigated for actors by the new hub-derived sector filter), and the upload-cap / "where does my document go" disclosure (D-07/D-08).

## 10. Deployment & auth — deliberately parked

The user explicitly said "let's decide on deployment later, I just need something to demo." Current state:
- **No public/hosted URL.** Everything runs on `localhost:8000` (React app) or `:8501` (Streamlit), visible only on this machine.
- **No authentication anywhere.** Explicitly deferred, not forgotten — flag before sharing a link with anyone.
- Prior conversation sketched a deploy plan (single container serving both the FastAPI API and the built React static files, fronted by an identity-aware proxy like Cloudflare Access for the ~4-user allowlist) — **not started**. Revisit when the user is ready.
- **git push is blocked from this sandbox** — no GitHub credential available (`Device not configured` error). The user needs to push `main` (currently 1 commit ahead of origin) from their own terminal, or set up `gh auth login` / SSH first. See §1 for the exact commands offered.

## 11. Known gotchas / limitations

- **No Node/npm** on this machine — see §3. The frontend is CDN-loaded React, not a real build.
- **Browser-automation flakiness observed this session**: a couple of clicks and one Enter-key submit didn't register on the first attempt during testing (had to retry via direct button click). No JS console errors accompanied it — looks like an automation-timing quirk, not an app bug, but **hasn't been independently confirmed by a human** — worth a quick manual sanity check if follow-up questions ever seem to "not submit."
- **`__pycache__`/`*.pyc` already gitignored** — confirmed clean before each commit this session.
- Sector filtering (Browse → Actors) is **hub-derived, not a real per-actor tag** — see §7. A true fix needs the DB owner to populate `actor_sector`.
- The exact UM6P brand orange is unconfirmed — see §7.
- All DB access remains `get_readonly_connection()` only; the enrichment agent's dry-run sink (`proposals.jsonl`) is the only write-shaped output anywhere, and it writes to a local file, not Postgres.

## 12. Open threads / TODO

- [ ] **Push `main` to `origin`** from a terminal with GitHub credentials (blocked in this sandbox).
- [ ] Confirm the exact UM6P orange hex and correct `--accent` in `frontend/index.html` (one-line change).
- [ ] Decide: keep the no-build CDN frontend, or fix the Homebrew permissions (`sudo chown -R $(whoami) /opt/homebrew*`) and stand up a real Node/Vite build.
- [ ] Manually verify the document-upload file-picker click end-to-end (automation can't drive native file dialogs).
- [ ] Resolve **which repo is the platform going forward** — this `um6p-rag` or the colleague's `GHUS_RAG` (§9) — before investing further in either's gaps.
- [ ] If continuing on this repo: add authentication (P-01, highest-priority gap) before sharing any link.
- [ ] **Resume Task 1A enrichment** (§8): build the triage/entity-resolution step (real-org vs. category-label) before scaling past the 2-actor probe; then run a ~10-actor metered pilot on the real-org subset.
- [ ] Resolve the enrichment write-access / apply-to-live-vs-hand-back gating question before any proposal leaves the dry-run JSONL.
- [ ] Build the review UI (approve/reject proposals with evidence) once triage + pilot look good.
- [ ] **Task 2** — new-domain mapping ("build me the fintech map"): discovery + dedup + relevance gate, same propose→approve engine. Comes after Task 1 proves the loop.
- [ ] Deployment: pick a platform + auth approach, deploy (parked per user request — revisit when asked).
- [ ] Fill the eval set (~2 → ~20 questions) and run the scorer (pre-existing TODO, still open).
