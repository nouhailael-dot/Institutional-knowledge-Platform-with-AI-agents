# UM6P Intelligence Platform — Project Handoff

> **Purpose of this file:** hand a new AI chat (or teammate) the full state of this
> project so it understands exactly what exists, how it works, what's been discovered
> about the data, and what's next — without re-deriving anything. Read this top to
> bottom first. The original product spec is in `CLAUDE.md` (authored by the project
> owner); this file is the *current state* as of the last working session.

---

## 1. What this is (one paragraph)

An internal RAG platform for the **UM6P Global Hubs US** team (~4 users). It makes their
research database of US innovation ecosystems searchable in plain English, with **cited**
answers. The user (owner) is building the **RAG/search layer**; a **colleague** owns the
**Postgres database + the ETL migration** from spreadsheets. Non-negotiable principle from
the spec: *answers must cite sources and must refuse rather than guess* ("a confidently-wrong
answer is worse than no answer").

---

## 2. Current status — WHAT WORKS

- **v0.1 (Ask / RAG) — DONE and working.** Ask a plain-English question → hybrid retrieval →
  Claude writes a cited answer. Refuses out-of-scope questions honestly.
- **v0.2 (SQL router) — DONE and working.** Counting/aggregation questions are routed to
  exact SQL instead of RAG (RAG structurally can't count).
- **Runs locally** via Streamlit at `http://localhost:8501` (localhost only — **NOT deployed**,
  no public URL yet).
- **Code is on GitHub** (private repo — see §9).

Nothing is broken. The two known *limitations* (not bugs) are documented in §7.

---

## 3. How to run it (exact commands)

The machine is locked down (see §10) — use the **conda env at `~/.conda/envs/um6p`** directly
by full path; `conda` is NOT on the shell PATH.

```bash
cd ~/Desktop/um6p-rag

# Run the app (opens browser to localhost:8501):
~/.conda/envs/um6p/bin/streamlit run app.py

# Run any module (ALWAYS from project root, as a module):
PYTHONPATH=~/Desktop/um6p-rag ~/.conda/envs/um6p/bin/python -m src.retrieve "who works on phosphogypsum?"
PYTHONPATH=~/Desktop/um6p-rag ~/.conda/envs/um6p/bin/python -m src.router "how many actors at TRL 6+?"

# Rebuild the search index (after data changes):
PYTHONPATH=~/Desktop/um6p-rag ~/.conda/envs/um6p/bin/python -m src.embed
```

Imports use `from src.db import ...`, so modules must be run as `python -m src.X` from the
project root (not `python src/X.py`).

---

## 4. Tech stack (decided — do not substitute without reason)

| Layer | Tool | Notes |
|---|---|---|
| Language | Python 3.11 | conda env `um6p` |
| Database | Supabase (Postgres + pgvector) | **Session pooler** connection (`aws-1-us-east-1.pooler...`), NOT the direct `db.*` host (that's IPv6-only and won't resolve) |
| Embeddings | Voyage `voyage-3` | 1024-dim; paid tier active |
| LLM | **Claude API `claude-opus-4-8`** | the decided stack; `MODEL` constant in `src/generate.py` and `src/router.py` — swap to `claude-sonnet-5`/`claude-haiku-4-5` for cost |
| UI | Streamlit | `app.py` |
| Keyword search | Postgres `tsvector` | half of hybrid retrieval |
| Dedupe | rapidfuzz | installed, not yet used |

Note: `groq` (free Llama tier) was used briefly as a free fallback and is still in
`requirements.txt` / `generate.py` history, but **the platform currently runs on Claude**.

### Credentials (in `.env`, gitignored — never commit)
`DATABASE_URL` (Supabase session pooler), `VOYAGE_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`
(unused now). `.env.example` is the committed template.

---

## 5. File map

```
um6p-rag/
├── CLAUDE.md              # original product spec (owner-authored) — READ for full vision
├── HANDOFF.md             # this file
├── Tech_Summary.md        # NOT created by the AI assistant — origin unknown, added by user side
├── .env / .env.example    # secrets (gitignored) / template
├── requirements.txt
├── app.py                 # Streamlit UI — routes SQL vs semantic
├── sql/search_doc.sql     # the RAG index table (pgvector + tsvector)
├── src/
│   ├── db.py              # Postgres connection + get_readonly_connection() (for SQL router)
│   ├── assemble.py        # join colleague's tables → one doc_text blob per entity
│   ├── embed.py           # Voyage embeddings → search_doc  (shared embed_texts() helper)
│   ├── retrieve.py        # HYBRID retrieval: vector + keyword, merged with RRF  (CORE FILE)
│   ├── generate.py        # Claude, cite-your-sources system prompt, streaming
│   └── router.py          # v0.2 SQL side-path: plan() decides SQL vs semantic; runs read-only SQL
└── evals/
    ├── questions.json     # eval set — only ~2 seeded; team must fill to ~20 known-answer Qs
    └── run_evals.py       # recall@10 scorer
```

---

## 6. Architecture — how a question is answered

```
question ─► router.plan()  (one Claude call: "structured or semantic?")
   ├─ SQL path (counts/aggregations/membership/filter-by-structured-field):
   │     Claude writes a read-only SELECT
   │       → is_safe_select() validates (single SELECT, no write keywords)
   │       → run_sql() on a READ-ONLY session (conn.read_only=True, 8s timeout)
   │       → format_sql_answer() phrases it; UI shows the SQL + "⚡ exact" badge
   └─ Semantic path (meaning/topic/description):
         retrieve()  = vector search (pgvector cosine, top 20)
                     + keyword search (tsvector, top 20)
                     → Reciprocal Rank Fusion → top 10
         → generate() = Claude with cite-your-sources prompt (streaming)
```

**Build flow (offline, re-run when data changes):**
`Postgres tables → assemble.py (join) → embed.py (Voyage) → search_doc`

**`search_doc` table** (my only added table): `entity_id, entity_type ('actor'|'hub'|'event'),
name, doc_text, embedding vector(1024), doc_tsv tsvector`. ~1037 rows (899 actors + 49 hubs
+ 89 events). It's a denormalized, rebuildable cache — `DROP` and re-run `embed.py` anytime.

**How the router decides (important):** LLM judgment, not keyword rules. Criterion = *"is the
answer a value in a structured column (number/category/link) → SQL, or is it meaning in free
text → semantic?"* Examples that route to SQL: "how many actors at TRL 6+", "list all actors
in the Bay Area AI Hub", "which hubs have no actors". Route to semantic: "who works on
phosphogypsum", "tell me about Mosaic".

---

## 7. Known limitations (documented, not bugs)

1. **Counting was RAG's failure — now fixed by the SQL router.** RAG only sees ~10 retrieved
   chunks, so it undercounts: it answered "4" for TRL 6+ (real = 34) and "8" for a hub (real
   = 14). The SQL router now returns the exact numbers.
2. **SQL router is non-deterministic** (Claude writes SQL fresh each time). One real bug hit
   and fixed: it sometimes wrote `ILIKE 'name'` without `%` wildcards → exact match → wrong
   **0** (hub names carry suffixes like "California Water Hub (UC Davis...)"). Fixed by
   hardening the planner prompt to always use `ILIKE '%fragment%'`, plus a 0-result "nothing
   matched" safety net. Verified stable.
3. **SQL path is sensitive to typos IN THE DATA** (not in the question — Claude corrects
   those). E.g. the DB literally contains "U.S. Geological Surevy" and both "USA"/"United
   States"; exact-substring SQL can miss these. RAG is typo-tolerant (embeddings capture
   meaning). → argues for data normalization + an `aliases` field (in the spec).
4. **Hybrid questions lose their exact filter.** "Which *national labs* (structured) work on
   *phosphogypsum* (text)?" routes to semantic and approximates the "national labs" filter
   rather than enforcing it. A true fix (v0.3) = SQL-filter then semantic-rank within that set.
5. **Trust is NOT surfaced in answers.** See §8 — this is the single highest-value improvement
   not yet done.

---

## 8. THE DATA (most important context — read carefully)

The database is a **merge of THREE source spreadsheets** (in `~/Downloads/`), migrated by the
colleague. Understanding this explains all the data-quality quirks:

| Source spreadsheet | ~rows | Became | Notes |
|---|---|---|---|
| `NutriCrops_Ecosystem_Mapping_Template.xlsx` | ~145 actors | `actor` + `actor_relevance` + TRL | The **deeply-profiled** phosphate/phosphogypsum actors. "NutriCrops" = the phosphate/fertilizer/ag domain. |
| `Ecosystem_Mapping_The_Final_UpV.xlsx` | ~61 hub rows | `hub` + **~730 AI-split actors** | The AI split the "Actor Composition" of each hub into individual actor rows, **each inheriting the parent hub's context**. This is where the breadth (AI/water/mining/biomed) comes from. |
| `UN_Mapping__FV.xlsx` | ~42 UN bodies | `actor` (un_agency/IGO types) + **`partnership_profile`** + UN events | Its columns map almost 1:1 to `partnership_profile` (`why_valuable_for_um6p`, `africa_specific_mandate`, etc.). **This is why partnership_profile is UN-heavy and sparse.** |

### The defining fact: the data is TWO TIERS
- **~130 actors are `phase_1`** (hand-curated): rich — have TRL (40%), partnership_profile (16%),
  country (90%), full descriptions. These give excellent cited answers.
- **~730 actors are `ai_inferred`** (extracted from hub narratives): thin — name + a
  description that is really the *hub's* generalization, **0% TRL, 0% partnership_profile**,
  only 36% have a country. Good for discovery, shallow for specifics.
- ~14 `needs_review`. (Counts shift slightly session-to-session — the colleague is **actively
  merging/reclassifying** in the live DB.)

`actor.verification_status` ∈ `ai_inferred | phase_1 | needs_review`. `source.trust_tier` is
mostly `candidate` (746) vs only 4 `verified`.

### ⚠️ The biggest opportunity: SURFACE TRUST
The RAG currently does **NOT** include `verification_status` in `assemble.py`'s doc_text or in
the UI. So an AI-guessed actor and a hand-verified one look **equally authoritative** in
answers. Fixing this (add verification_status to the assembled docs + show it in the source
panel/prompt, e.g. "⚠️ AI-inferred") is the **highest-value quality improvement** and directly
serves the spec's "trust the answer" principle. **Not yet done.**

### Scope of the map (it is NOT just phosphate)
**49 hubs** across ~8 domains: mining/critical minerals, water, AI & robotics, chemistry &
materials, energy/climate transition, agriculture/AgriTech, health/biomedical, sustainability.
(Early demo questions over-focused on phosphate — use the full breadth.)

### Other data-quality facts
- **`sector` table is EMPTY** → the planned Browse "filter by sector" (v0.2) has no data.
- **~476 of ~950 actors have no `country`**; "USA" (182) vs "United States" (138) stored as
  different strings → Browse-by-region is incomplete + buggy until normalized.
- Duplicate/typo'd entities exist (e.g. two USGS records, one typo'd "Surevy").
- `review_queue` (~86 pending pairs) = the colleague's dedup workflow. **It already implements
  the "score → human decides" pattern the spec wants for the missing `proposal` table** (v0.3
  Inbox) — extend it, don't rebuild.
- ~half the tables are **built but empty** (person, funding_source, event_scoring,
  hub_sector_strength, etc.) — schema built ahead of data.

### Tables
~23 tables total: ~22 are the colleague's (per spec "21 tables" + `actor_merge_log`,
`review_queue`, `alembic_version`); **`search_doc` is the only one the RAG added.** Do NOT
modify the colleague's schema — `search_doc` is additive and disposable.

---

## 9. Assessment results (from a 9-question test run)

**Strong:** rich cited answers on profiled domains (phosphogypsum, USGS, UN funders, Mosaic);
genuine cross-domain breadth; hybrid search catches acronyms (USGS); honesty guard solid
(correctly refused "who works on quantum computing?"); generation ignores retrieval noise.
**Weak (both known):** counting (now fixed by SQL router); data-quality leaking into answers
(e.g. DeepMind wrongly placed in the Bay Area hub — a *data* issue).

---

## 10. Environment & operational quirks (so you don't repeat the pain)

- **Locked-down Mac, no admin.** Homebrew is owned by an `administrator` account (can't
  `brew install`). Anaconda lives at `/opt/anaconda3` (admin-owned) — so the working env was
  created at `~/.conda/envs/um6p` with `CONDA_PKGS_DIRS`/`CONDA_ENVS_DIRS` pointed at `$HOME`.
  Use `~/.conda/envs/um6p/bin/python` directly.
- **Supabase**: must use the **session pooler** connection string. The direct `db.<ref>.supabase.co`
  host is IPv6-only and won't resolve on this network.
- **GitHub**: repo = `https://github.com/nouhailael-dot/Institutional-knowledge-Platform-with-AI-agents`
  (private). The **user pushes via the GitHub Desktop app** — terminal `git push` has no
  credentials (the user logs into GitHub via Google; no Personal Access Token set up). The AI
  can `git commit` locally but **cannot push**. History was rewritten once (to strip a
  co-author trailer) and force-pushed via Desktop. Commit identity: `ghus
  <nouhailahail12@gmail.com>`. **User preference: NO `Co-Authored-By` trailer in commits.**
- **App**: run manually; `localhost:8501` only; not deployed.

---

## 11. Roadmap / what's next (pick up here)

1. **Deploy to Streamlit Community Cloud** → shareable URL. Needs a small tweak: on Cloud there's
   no `.env`; read secrets from `st.secrets` into `os.environ` at the very top of `app.py`
   **before** importing `src.*` (because `db.py` reads `DATABASE_URL` at import time).
2. **Surface trust** (§8) — highest-value quality fix.
3. **Fill the eval set** (`evals/questions.json`) with ~20 team-known answers, then `run_evals`.
4. **Data-quality scan** for the colleague: near-duplicate names, typo variants, "USA"/"United
   States" normalization.
5. **v0.3** (per spec): `proposal` table + Inbox (extend `review_queue`); discovery/gap-filling
   agents; Radar alerts; Browse tab (blocked on empty `sector` + missing `country`); policy/
   criteria layer.
6. **Hybrid router path** for "filter + topic" questions (SQL filter → semantic rank).

---

## 12. Working conventions

- Model = `claude-opus-4-8` (swap the `MODEL` constant to trade quality for cost).
- Never modify the colleague's schema; `search_doc` is additive/disposable.
- Run modules as `python -m src.X` from the project root.
- AI commits locally; **user pushes via GitHub Desktop**. No `Co-Authored-By` trailer.
- Keep functions small/readable — a non-technical successor must maintain this.
```
