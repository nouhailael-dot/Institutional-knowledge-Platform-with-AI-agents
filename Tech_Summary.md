# UM6P Intelligence Platform

## What this is

An internal AI platform for the UM6P Global Hubs US team (~4 core users). It makes their
accumulated ecosystem-mapping research searchable in plain English, keeps it current, and
eventually helps them produce new mappings automatically.

UM6P is a Moroccan university tied to OCP (the phosphate group). The Global Hubs US team maps
US institutions, national labs, funders, ventures, and events, and builds partnerships. Today
that research lives in spreadsheets and PowerPoints, takes 4-8 weeks per mapping, goes stale,
and is not queryable.

**The one-line goal:** so the team can ask this map a question and trust the answer.

---

## Current status

- Postgres schema designed (21 tables) — DONE
- ETL migration from three spreadsheets into Postgres — DONE (some records dropped due to
  non-uniform source data; being recovered with AI assistance)
- ML-based dedupe logic — DONE
- **RAG system — IN PROGRESS. This is what I'm building now.**
- Target: **v0.1 (search + UI preview) by end of next week**
- Phase 1 complete: end of August

I own the RAG. A colleague owns the database/migration. Don't modify his schema — build
alongside it.

---

## The three core functions (the platform's job)

1. **Query / Ask** — pull actionable info from stored data ("show me partners past TRL 4",
   "find labs with patents on this problem"). ← **v0.1, what I'm building now**
2. **Fill gaps** — an agent finds partners/funders/events/actors the team missed in a domain,
   surfaces them for human approve/reject. ← v0.3
3. **Maintain** — an agent flags facts that are outdated, changed, or missing. ← v0.3

## The four user-facing features

- **Ask** — plain-English search over the database. ← **v0.1**
- **Browse** — filter the dataset by sector and geography (country/state/region). Two distinct
  use cases: region-based search for planning expeditions/hosting, AND a general scan that
  surfaces important actors anywhere worth flying to.
- **Radar** — agent monitors upcoming events and potential funders, pushes alerts (email/
  WhatsApp) on approaching deadlines. Scoped to domains/sectors initially.
- **Inbox** — holding area where agent-proposed additions/changes wait for human review and
  approve/reject before entering the database.

---

## Non-negotiable principles

- **The agent proposes; a human approves.** Nothing auto-writes to the trusted map. Every
  proposal carries its evidence URL and snippet.
- **Never auto-write judgment fields** (`why_valuable_for_um6p`, relevance scores). The agent
  can flag that they may need review. A human writes them. These require knowing UM6P's
  internal strategy and are the most valuable content in the map.
- **Answers must cite their source.** Every fact traces back to an entity/row.
- **`last_verified` on records**; anything over 90 days shows as stale. A confidently-wrong
  stale answer is worse than no answer.
- **Ship rough, improve from real use.** v0.1 ugly and working beats v1.0 late.
- **80/20** — deliver the 20% of functionality giving 80% of value first.
- The platform must be usable by **non-technical people** and must **outlive the current team**
  (several leave Dec/Jan). Maintainability is a design requirement.

---

## Tech stack (decided — don't substitute)

| Layer | Tool |
|---|---|
| Language | Python 3.11+ |
| Database | Supabase (Postgres + pgvector) — already populated |
| Embeddings | Voyage AI `voyage-3` |
| LLM | Claude API (`anthropic` SDK) |
| UI | Streamlit |
| Keyword search | Postgres `tsvector` |
| Dedupe | rapidfuzz |
| Scraping (later) | httpx + trafilatura |
| Scheduling (later) | GitHub Actions cron |
| Email (later) | Resend |

**Explicitly avoid:** LangChain / LlamaIndex (unnecessary abstraction at this scale), a separate
vector DB (pgvector is correct for ~300 entities), Docker / Kubernetes / Terraform / staging
environments (overkill for 4 users), heavy unit-test suites (the eval set is the test that
matters).

---

## RAG architecture

Two flows.

**Build flow (offline, run once; re-run when data changes):**
```
Postgres tables -> assemble.py (join) -> embed.py (Voyage) -> search_doc table
```

**Query flow (live, per question):**
```
question -> router
   |- semantic  -> embed -> hybrid retrieve (top 10) -> Claude -> cited answer
   |- counting  -> Claude writes SQL -> run on Postgres -> exact number
```

### Why a separate index table

The searchable text is scattered across `actor`, `partnership_profile`, `actor_relevance`,
`hub`/`hub_actor`, `sector`/`actor_sector`. Assemble it ONCE into one blob per entity, embed
that, store text + vector together in a dedicated `search_doc` table. This pays the join cost
at build time instead of query time, and keeps my work separate from my colleague's schema.

**Critical:** `why_valuable_for_um6p` lives in `partnership_profile`, NOT in `actor`. It is the
single most important text in the dataset. If the assembly join misses it, search loses the
thing the team cares about most.

```sql
CREATE TABLE search_doc (
  entity_id   uuid PRIMARY KEY,
  entity_type text,           -- 'actor' | 'hub' | 'event'
  name        text,
  doc_text    text,           -- assembled searchable blob
  embedding   vector(1024)
);
CREATE INDEX ON search_doc USING ivfflat (embedding vector_cosine_ops);
```

### Hybrid retrieval (do not ship pure vector)

Every query runs two searches in parallel and merges them:

1. **Vector search** (pgvector, cosine) — matches *meaning*. Finds "nutrient management" when
   asked about "soil health". Returns top 20.
2. **Keyword search** (Postgres tsvector) — matches *exact terms*. Finds the literal "USGS" row.
   Returns top 20.
3. **Merge + re-rank** — combine scores, dedupe, keep top 10.

**Why this matters here specifically:** the dataset is dense with acronyms — USGS, SRNL, IFAD,
TRL, IIT, BARC. Pure vector search ranks these poorly because acronyms carry little semantic
weight. Keyword search catches them. Neither alone is sufficient.

Reciprocal rank fusion is a fine merge strategy. Start simple, tune against the eval set.

### The SQL side-path

RAG retrieves ~10 chunks, so it **structurally cannot count or aggregate** — it will produce
confident wrong numbers. The Postgres schema is clean and relational, so route structured
questions to SQL instead:

- "Who works on phosphogypsum immobilization?" -> RAG
- "How many actors at TRL 6+?" -> `SELECT count(*) FROM actor WHERE estimated_trl >= 6`
- "Which hubs have no capital actor?" -> SQL join through `hub_actor`

Build RAG first. Add the router when counting questions appear in real use.

---

## Existing database schema (colleague's work — read, don't modify)

21 tables. The ones the RAG cares about:

**Entity tables:**
- `actor` — actor_id, name, slug, actor_type, actor_type_raw, description, website,
  location_city, state, country, primary_technical_focus, technical_approach,
  current_activities, technology_ip_notes, key_constraints, estimated_trl,
  primary_lifecycle_role, source_id, verification_status, confidence, created_at, updated_at
- `hub` — hub_id, name, slug, primary_city, state, country, region, latitude, longitude,
  description, upstream_inputs, downstream_outputs, integrated_flow_description,
  constraints_summary, funding_summary, cross_hub_themes, primary_sectors, secondary_sectors
- `event` — event_id, name, event_type, location, website, recurring_pattern, next_date,
  sponsoring_orgs, host_actor_id, source_id
- `person`, `sector`, `funding_source`, `challenge`, `source`, `strategic_document`

**Junction tables:** `hub_actor` (hub_id, actor_id, relationship_type, is_primary),
`actor_sector`, `actor_person`, `event_sector`, `hub_sector_strength`, `hub_funding`,
`organization_hierarchy`

**Detail tables:**
- `partnership_profile` — actor_id, thematic_focus, strategic_plan, africa_specific_mandate,
  africa_specific_details, **why_valuable_for_um6p**, budget_overview,
  partners_with_universities, university_programmes, university_partnership_examples,
  **key_entry_points**, funding_delivery, funding_delivery_mechanisms, key_constraints
- `actor_relevance` — actor_id, challenge_id, relevance_score, maturity_risk,
  collaboration_orientation, **why_relevant**, current_evidence, additional_validation_needed
- `event_scoring` — elaborate event scoring model (not used in v0.1)

Every table carries `source_id` for provenance, plus `verification_status`, `confidence`,
`created_at`, `updated_at`.

## Tables I need to ADD (not in colleague's schema)

```sql
-- The agent's pending changes, awaiting human approval. The Inbox reads this.
-- This is the missing workflow layer. Add before building agents.
CREATE TABLE proposal (
  proposal_id      uuid PRIMARY KEY,
  entity_id        uuid,
  table_name       text,
  field            text,
  old_value        text,
  new_value        text,
  evidence_url     text,
  evidence_snippet text,
  status           text,        -- pending | approved | rejected
  reviewed_by      text,
  created_at       timestamp
);

-- New entities discovery found, awaiting approval (v0.3)
CREATE TABLE candidate (...);
```

Also add to `actor`: `aliases text[]` (dedupe/search variants like "SRNL" vs "Savannah River
National Laboratory") and `last_verified date` (staleness flag, distinct from `updated_at`).

---

## File structure

```
um6p-rag/
├── .env                    # secrets, never committed
├── .env.example            # template, committed
├── .gitignore
├── requirements.txt
├── app.py                  # Streamlit — the Ask tab
├── sql/
│   └── search_doc.sql      # CREATE TABLE for the index
├── src/
│   ├── db.py               # Postgres connection; everything imports this
│   ├── assemble.py         # join tables -> one doc_text per entity
│   ├── embed.py            # doc_text -> Voyage -> search_doc
│   ├── retrieve.py         # question -> top 10 (hybrid). THE CORE FILE.
│   ├── generate.py         # entities + question -> cited answer
│   └── router.py           # (v0.2) semantic vs SQL decision
└── evals/
    ├── questions.json      # 20 known-answer questions
    └── run_evals.py        # runs them, prints a score
```

**Dependency order:** `db.py` -> `assemble.py` -> `embed.py` -> `retrieve.py` -> `generate.py`
-> `app.py`

The two files that matter most: `assemble.py` (touches the colleague's schema; a column rename
breaks it) and `retrieve.py` (retrieval quality IS answer quality).

---

## Build order

**v0.1 — this week (the current task)**
1. Enable pgvector in Supabase
2. Create `search_doc` table
3. `db.py` — connection
4. `assemble.py` — the join. Build the doc_text blob per actor:
   `name + description + current_activities + key_constraints +
    partnership_profile.why_valuable_for_um6p + key_entry_points + africa_specific_mandate +
    actor_relevance.why_relevant + [hub names] + [sector names]`
   Same pattern for hubs and events.
5. `embed.py` — Voyage, store vectors
6. `retrieve.py` — start pure vector, then add keyword + merge
7. `generate.py` — Claude with a cite-your-sources prompt
8. `app.py` — Streamlit Ask tab, streaming
9. `evals/` — 20 questions with known answers

**v0.2 — after v0.1 ships**
- Hybrid retrieval tuning against evals
- SQL router for counting questions
- Browse tab (sector + geography filters)
- Policy/criteria layer (see below)

**v0.3 — ~3 weeks out**
- Discovery/gap-filling agents -> `proposal` table -> Inbox tab
- Freshness crawler
- Radar push alerts (email/WhatsApp)

---

## The criteria layer (v0.2 — important context)

The team's key conclusion from their planning meeting: **the platform is only as good as the
criteria defined up front.** Unlike an ad-hoc ChatGPT conversation, this needs pre-fixed,
structured policy so every search reflects what matters to UM6P.

Four things the team is drafting (their homework, not mine):

- **Policy** — UM6P/OCP priorities, gaps, challenges, priority sectors. Shared across all users;
  tells the platform what "relevant to UM6P" means.
- **Categories & criteria** — actor categories (academic institutions, national labs, new
  ventures, corporate partners) and what makes a *good* one, not just *a* one: TRL level,
  existing collaboration, patents held, openness to partnership.
- **Structure** — what columns the output should contain (players, funders, top research topics,
  value-chain fit). Effectively the schema of an answer. Lets the platform build a mapping for a
  brand-new domain by following a preset column structure.
- **Format** — spreadsheet, slides, or document.

Implementation when I get there:
- A `policy` table holding shared criteria; loaded into every generation prompt.
- Setup questions at query time (3-5 questions) to capture task-specific criteria, injected
  into the prompt. General policy in the platform's "brain"; task criteria gathered per query.
- Template/structure configs per deliverable type.
- A non-technical UI for editing policy/criteria (requirement: platform must outlive the team).

**Do not build this in v0.1.** It layers on top of a working retriever.

---

## Quality gate

**The eval set is non-negotiable.** 20 questions where the answer is already known, e.g.:

- "Which actors work on phosphogypsum at TRL 6+?" -> known: these 8
- "Which UN bodies fund university research and have an Africa mandate?" -> known: these 4

Run after every change to retrieval or prompts. Without it, tuning is guesswork. Build it early,
not after.

Note: RAG answer quality is capped by data quality. If `why_valuable_for_um6p` is sparse because
of the migration drops, answers will look thin — that's a data problem, not a retrieval problem.
Diagnose accordingly.

---

## Working conventions

- Git with branches + PRs; never push directly to `main`.
- Secrets in `.env` (gitignored); `.env.example` committed as the template.
- Deploy via Streamlit Community Cloud (push to `main` -> live).
- Keep functions small and readable; a non-technical successor has to maintain this.
- Comment the non-obvious parts, especially the assembly joins and the merge logic.

---

## What NOT to build

Explicitly parked by the team to prevent scope creep:

- Project/task management, Gantt views, per-person deadlines (that's Asana)
- Learning-expedition budget automation (later phase)
- HubSpot / CRM integration (being evaluated, not a priority)
- Expansion to new domains like chemistry or fintech (after the foundation is stable)
- Cross-team sub-accounts, connecting other tools together
- Cost optimization via cheaper LLMs or self-hosting (ship first, optimize later)
