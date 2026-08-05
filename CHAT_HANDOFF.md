# UM6P Intelligence — Project Status & Chat Handoff

_Paste this into a new chat so it knows exactly where the project stands. Last updated at the end of the session that added document upload, the Browse hub redesign, and scoped the enrichment-agent phase._

---

## 1. What this project is

**UM6P Intelligence** — an internal RAG platform for the **UM6P Global Hubs US team (~4 users)**. It makes a research database of US innovation ecosystems (actors, hubs, events the team tracks for partnership-building) searchable in plain English, with **cited** answers.

- This repo is the **RAG / application layer only**. The Postgres schema and the ETL that populates it are owned and maintained separately (not by this repo). **Historically this code has been read-only against that database.**
- Working directory: `/Users/ghus/Desktop/um6p-rag`
- Git remote: `github.com/nouhailael-dot/Institutional-knowledge-Platform-with-AI-agents.git`
- Current branch: `main`, HEAD = `bc76f37`, **in sync with `origin/main`** (this session's work is committed AND pushed).
- User: git identity `ghus`; email on file `nouhailahail12@gmail.com`.

## 2. Environment & how to run

- Python 3.11, conda env at `~/.conda/envs/um6p` (interpreter: `~/.conda/envs/um6p/bin/python`).
- Secrets in `.env` (loaded via python-dotenv): `DATABASE_URL`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`.
- Run the app: `streamlit run app.py` (currently runs on `localhost:8501`).
- Rebuild the search index (offline, after source data changes): `python -m src.embed`.

## 3. Tech stack

- **DB**: Supabase (Postgres + `pgvector`), session pooler.
- **Embeddings**: Voyage `voyage-3` (1024-dim).
- **LLM**: Anthropic Claude, model `claude-opus-4-8` (isolated in `src/generate.py` + `src/router.py`; swap the `MODEL` constant to `claude-sonnet-5` / `claude-haiku-4-5` to cut cost).
- **UI**: Streamlit.
- **Other**: rapidfuzz (data-quality scan), pypdf + numpy (document upload).
- **Deliberately NOT used**: LangChain (too heavy for this scale) and dedicated DevOps/containers (Streamlit Cloud handles deploy). Both were discussed and ruled out.

## 4. Architecture

**Two query flows in the Ask tab, deliberately separate:**
- **SQL route** (`src/router.py`): counting / aggregation / "how many / list all" questions → Claude writes a **read-only SELECT** → Postgres runs it → exact answer. Exists because RAG retrieves a fixed number of docs and so **structurally cannot count**. Safety: LLM-written SQL runs on a hardened **read-only** session (8s timeout) AND is validated by `is_safe_select()` (single SELECT/WITH, no write/DDL keywords). Names are matched with `ILIKE '%fragment%'` because entities carry long suffixes.
- **Semantic/RAG route** (`src/retrieve.py` → `src/generate.py`): hybrid retrieval — pgvector cosine (meaning) + Postgres tsvector keyword (acronyms like USGS/SRNL), fused with **Reciprocal Rank Fusion** — then Claude generates a **cited** answer. System prompt forbids using outside knowledge and requires "the map doesn't contain enough information" rather than guessing.

**Three UI surfaces (all in `app.py`, two tabs):**
- **Ask tab** — the question box (routes as above), PLUS an **optional document attachment** (see §6).
- **Browse tab** — structured, filterable lists of Actors / Hubs / Events. Pure DB reads, no LLM. In-memory filtering (whole live set is <1000 rows).

## 5. Repo structure (file by file)

```
app.py                  Streamlit UI: Ask tab (SQL/RAG + doc upload) + Browse tab. Global CSS polish.
data_quality_scan.py    Read-only scan → DATA_QUALITY_REPORT.md (dupes, country mess). rapidfuzz.
src/
  db.py                 get_connection() and get_readonly_connection() (read_only=True, 8s timeout). Reads DATABASE_URL at import.
  assemble.py           Build-time join: actor + partnership_profile + relevance + hubs → one doc_text blob per entity.
  embed.py              Voyage embedding + writes search_doc (offline build). embed_texts() shared with retrieve.
  retrieve.py           THE core: hybrid vector+keyword retrieval, RRF merge. retrieve(question, top_k).
  generate.py           Claude answer generation (MODEL=claude-opus-4-8). stream_answer(). Citation rules in system prompt.
  router.py             plan() decides SQL vs semantic; is_safe_select(); run_sql(); format_sql_answer(). SCHEMA string for the planner.
  browse.py             Pure data module for Browse. normalize_country() (on read, never writes DB). load_actors/hubs/events, filter_*, actor_filter_options.
  documents/            Document-upload feature (this session):
    extract.py          bytes → clean text. PDF (pypdf, no OCR) / txt / md. Detects scanned/encrypted PDFs.
    chunk.py            Overlapping char-based chunks (~300 tok, 50 overlap).
    doc_store.py        Per-session in-memory Voyage-embedded NumPy cosine store. build_store(), search_chunks(). Never writes Postgres.
```

Root docs: `HANDOFF.md` (STALE — predates Browse & everything after), `Tech_Summary.md`, `DATA_QUALITY_REPORT.md`, this file.

## 6. Document upload (built & committed this session)

- **Where**: optional attachment **inside the Ask tab** (expander "📎 Attach a document").
- **Behavior chosen by the user**: an attached document is answered from the **document AND the database together** — doc passages are merged with hybrid map retrieval into one cited answer (doc chunks tagged `uploaded_document`).
- **Types**: PDF, .txt, .md. Nothing is written to Postgres — the doc store lives in `st.session_state`, cleared when the file is removed.
- Uses a Streamlit **form** so opening the Sources expander doesn't re-fire a paid answer.
- **Verified**: extract/chunk/embed/retrieve/merge tested headlessly with real API keys (pulled the budget passage + relevant actors). **NOT** manually verified: the actual browser file-picker click (the automation tool can't drive a native OS file dialog) — user should upload a file once to confirm the UI end-to-end.

## 7. Browse hub redesign + CSS polish (this session)

- Hub detail is now a **card**: metric tiles (Live actors · Primary sector · Confidence), location subtitle, two-column details grid, long write-ups in **Narratives** expanders, and an **"Actors in this hub"** table. Replaced a raw field/value dataframe (which also fixes an Arrow `Decimal` serialization error).
- **Global CSS** (`app.py` top): centered reading width, bolder tabs, bordered metric tiles/expanders. Theme-safe (no hard-coded colors → works light & dark).
- **Verified**: render path exercised headlessly across all 49 hubs (no errors, Arrow-clean). Global CSS confirmed visually on the Actors card. **NOT** screenshotted: the hub card itself — the browser automation tool **cannot toggle Streamlit radio buttons**, so the Hubs sub-view couldn't be driven. User should eyeball Browse → Hubs.
- User was offered the same treatment for Actors/Events detail views and **declined** (chose "leave it here").

## 8. Data model reality (what the data actually supports)

Live counts (merged duplicates excluded): **872 live actors, 49 hubs, 169 events** (only ~35 events carry a date; 134 dateless).

- **Two-tier verification** (`actor.verification_status`): `phase_1` (hand-curated, ~96, richest), `ai_inferred` (extracted from hub narratives, ~761, thin), `needs_review`. Only ~8% of actors carry a TRL rating.
- **`country` is messy** (from `DATA_QUALITY_REPORT.md`): 214 "USA" + 178 "United States" (same country, two spellings), 6 US states stored as country, 19 free-text/description leaks. `browse.normalize_country()` cleans this **on read** for the UI; the DB is untouched. 8 near-duplicate name pairs flagged.
- **Sector browsing is impossible**: `sector` table has 10 rows but the join tables (`actor_sector`, `event_sector`, `hub_sector_strength`) are **empty** — nothing is linked to a sector.
- **Landing-zone tables already exist** (currently ~0 rows): `proposal` (agent workflow) and `query_log` (usage/feedback analytics). `review_queue` has ~277 rows. `search_doc` (~1010 rows) is the index; `search_doc_2` is an unexplained second copy.

`merged_into_actor_id IS NULL` = the row is live. ALWAYS filter on it when counting/listing actors.

## 9. Key decisions locked in

- **Deploy target**: **Streamlit Community Cloud** (free, auto-deploys on git push, `st.secrets` for credentials, Google-email allowlist for the ~4 users). **NOT DONE YET** — needs a small `st.secrets`→`os.environ` shim placed BEFORE the `src.*` imports in `app.py`, plus a `runtime.txt` pinning `3.11`.
- **Deploy first, then keep designing** was the agreed sequencing.
- **Model cost lever**: stay on Opus for user-facing answers; use a cheaper model for bulk/background work.

## 10. Cost / budget (already worked out with the user, for their manager)

- **Runtime** (team usage): ~$0.02–0.04 per question on Opus; a 4-person team is ~$5–30/month. Negligible.
- **Build + test credits to request now: ~$140** ($120 Anthropic + $20 Voyage). The dominant build cost is iterating on the enrichment agents.
- **Enrichment full pass** (~730 thin actors): **~$20 on Haiku+Batch to ~$220 on Opus without batching** — a ~10× swing on model + batching choice.
- **Voyage is always negligible** (index rebuild ≈ cents). Levers: cheap model for the agent, **Batch API (−50%)**, cap `web_fetch` content, prompt-cache the agent instructions, meter a ~50-entity pilot first.

## 11. CURRENT FOCUS — Web-scraping agents (feature #2)

The next big build: agents that gather information from the web and grow the map. The user defined **two distinct tasks** for this feature. Both run on the **same engine** — `find/fill → propose with evidence → human approves → apply` — they differ only in what they're pointed at.

### Task 1 — Deepen the existing map (START HERE)

Work the domains **already** in the DB:
- **Enrich existing actors** — fill missing factual fields on the ~730 thin `ai_inferred` actors (primarily **country** and **website**; also city/state, actor type, a short factual description). Also fix the messy `country` values (USA vs United States, states-as-country).
- **Top up existing hubs/sectors** — add **new actors that belong to hubs/sectors already in the DB** (e.g. a hub with only 8 actors → find more that fit it).

This is the **safe, verifiable** case ("does this org have a website?" is a fact with a source), so it's where we prove the whole loop.

### Task 2 — Map a new domain on demand (LATER, same machinery)

A human names a **new topic/sector the DB doesn't cover yet** — e.g. *"build me the fintech map"* — and the agent:
- **discovers** the actors in that field (companies, labs, funders, universities, events),
- **populates** them **following the existing structure** — same columns, same schema. It's a new *sector's worth of rows*, **NOT** a schema change / new columns.

Three things get heavier in Task 2 vs Task 1:
- **Volume** — many new-actor proposals at once → this is the expensive path (~$20–220 range); wants **Batch API + a cheap model + a metered pilot**.
- **Dedup** — a "fintech" actor may already be in the DB under another label; must check before proposing it as new.
- **Relevance judgment** — "is this actually a fintech actor worth tracking?" needs a human gate.

> **New-entity support is already in the schema:** the `proposal` table's `entity_id` is **null when proposing a NEW entity**, so Task 2 (and adding actors in Task 1) reuse the same table — no rebuild.

### The shared 5-stage pipeline

1. **Find** — Task 1: read-only query for actors missing a field. Task 2: seed from the named topic.
2. **Agent gathers evidence** — searches/scrapes the web for the value + a **source URL + snippet**.
3. **Proposes** to the `proposal` table — `entity_id` (null = new actor), `field`, `old_value → new_value`, `evidence_url`, `evidence_snippet`, `proposed_by`, `status='pending'`. **Never writes live tables directly.**
4. **Human reviews** pending proposals (with evidence) in a new review UI → approve / reject.
5. **Apply** approved changes.

### Guardrails (agreed, both tasks)

Agent proposes, human approves — no auto-writes; **every proposal carries a citation** (the `proposal` table makes `evidence_url` / `evidence_snippet` NOT NULL); **factual fields only** — judgment fields (`why_valuable_for_um6p`, relevance scores, TRL) stay human-written; cheap model (Haiku/Sonnet) + Batch API + capped `web_fetch` + **metered ~50-actor pilot before any full run**.

### OPEN GATING QUESTION (not yet resolved)

Everything so far has been read-only. This phase needs to **write** (to `proposal`, and on approval to live tables). Unresolved: (a) do we have **write credentials** (the `proposal` table has **row-level security** enabled), and (b) does an approved proposal **write to the live DB**, or get **handed back to the owning ETL/source spreadsheets**? — patching the DB but not the source means the next ETL run overwrites the fix (the data-quality report deliberately routed fixes to the source spreadsheets for this reason).

### AGREED NEXT STEP (safe regardless of the above)

Run a read-only **"gap scan"** for **Task 1** — count live actors missing country vs. website vs. both, split by verification tier. Pure SELECT, same safe pattern as the data-quality scan. It sizes both the agent's work and the pilot cost before spending anything.

## 12. Known gotchas / limitations

- **Browser automation cannot toggle Streamlit radio buttons or drive native file-pickers**, and debounced text inputs are flaky — verify those UI paths manually or headlessly (this is why the hub card & file upload weren't screenshotted).
- `st.dataframe(..., use_container_width=True)` throws a **deprecation warning** (removed after 2025-12-31 → switch to `width='stretch'`). Pre-existing, harmless for now.
- **`HANDOFF.md` is stale** (predates Browse and everything after). This file supersedes it.
- All DB access is via `get_readonly_connection()` (physically rejects writes) except where a future write path is deliberately added for the enrichment phase.

## 13. Open threads / TODO

- [ ] **Run the read-only gap scan** (immediate next step — Task 1).
- [ ] Resolve the write-access / apply-to-live-vs-hand-back gating question before any proposal is written.
- [ ] **Task 1** — build the agent (enrich existing actors + top up existing hubs) on a metered ~50-actor pilot (Haiku/Sonnet + Batch + capped fetch).
- [ ] Build the review UI (approve/reject proposals with evidence) — shared by both tasks.
- [ ] **Task 2** — new-domain mapping ("build me the fintech map"): discovery + dedup + relevance gate, same propose→approve engine. Comes after Task 1 proves the loop.
- [ ] **Deploy to Streamlit Cloud** (st.secrets shim + runtime.txt; user-side: Cloud account, connect repo, paste secrets, set allowlist).
- [ ] Manually confirm the document-upload file-picker end-to-end, and eyeball the redesigned Hub card.
- [ ] Fill the eval set (~2 → ~20 questions) and run the scorer.
