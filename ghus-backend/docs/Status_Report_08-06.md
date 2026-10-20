# GHUS Platform — Project Status Report

**Prepared by:** Ismail Sabbar
**Role:** AI Platform Intern, UM6P Global Hubs U.S.
**Date:** 2026-06-08
**Purpose:** Comprehensive handoff document. Captures everything done, all decisions made, all problems solved, and the plan forward. Designed to be shared with a new conversation so context isn't lost.

---

## 1. The mission

Build an AI-Enabled Digital Intelligence Platform for UM6P Global Hubs U.S. — a system that takes the team's scattered ecosystem-mapping spreadsheets and turns them into a queryable, AI-enriched database. End goal: anyone on the team can ask a plain-English question ("which U.S. hubs are strongest for agriculture and water?") and get a sourced, accurate answer in seconds.

The supervisor (FZ, Exec Ed lead) issued a formal capability brief — Phase 2 — listing nine required capabilities the platform must support, all rooted in the existing Phase 1 "Ecosystem Hub Intelligence Mapping" work. Sixteen-week timeline.

The team is four members plus a director who approves spending. Total Phase 2 tooling budget around $550–$4,400/year depending on tier; pilot starts at ~$550 one-time.

---

## 2. The architecture, at a glance

**Stack:**
- Supabase Postgres (with pgvector for future embeddings)
- Python (SQLAlchemy, Alembic, openpyxl, pandas)
- Anthropic Claude API (Haiku for high-volume, Sonnet for extraction, Opus for the eventual query agent)
- Future: Next.js + Vercel front-end, Streamlit admin interface

**Repository:** `Ismailsabbar/GHUS_Platform` (private). Local path: `C:\Users\Ismail\Projects\GHUS-Platform`.

**Database state:** 20 tables, all created via Alembic migrations and populated with real data (except `event_scoring` which awaits final v9 data).

---

## 3. What's been built — chronological

### Stage 1: Foundation and planning
- Written project plan (`Project_Plan_Report_v2.docx`)
- Three full slide decks: full project deck (15 slides), team intro deck (12 slides, orange UM6P theme), speaking script
- Phase 2 brief from supervisor read and analyzed — nine required capabilities mapped against schema
- LinkedIn announcement drafts

### Stage 2: Data understanding
- Profiled every source spreadsheet with ydata-profiling (HTML reports generated)
- Inspected each spreadsheet by hand to verify what the profile reports said
- Wrote `docs/data-dictionary.md` — full column-by-column documentation of every source file
- Identified key insight: spreadsheets describe data at different *granularities* (hub-level vs actor-level vs institutional-partner level), not just different shapes

### Stage 3: Schema design
- Entity model designed against both the data and the brief's nine capabilities
- ER diagram drawn in dbdiagram.io, exported to `docs/architecture/entity-model-v1.png`
- Final schema: 20 tables across four categories (core entities, strategic alignment, junction tables, supporting/reference)
- SQLAlchemy models written in `src/db/models.py`
- Alembic migrations generated and applied — every table now exists in Supabase

### Stage 4: Reference data seeded
- `scripts/seed_reference_data.py` populates the `sector` table (8 sectors: AGRI, AI, WATER, ENERGY, MINING, CHEM, SUSTAIN, HEALTH) and the `funding_source` table (9 entries)
- Idempotent: safe to re-run

### Stage 5: ETL translators built and run
Four translators written. Three have been run; the fourth awaits final data.

1. **Ecosystem Mapping translator** (`src/etl/translators/ecosystem_mapping.py`) — 52 hubs loaded with rich preserved narratives (composition, programs, talent, research, industry, international)
2. **Hub actor extractor** (`src/etl/translators/hub_actor_extractor.py`) — rule-based extraction of 797 individual actors from hub composition narratives, all marked `verification_status='needs_review'` and `confidence=0.5`
3. **UN Mapping translator** (`src/etl/translators/un_mapping.py`) — 25 UN organizations with partnership profiles, hierarchical relationships, and 113 events
4. **NutriCrops translator** (`src/etl/translators/nutricrops.py`) — created the NutriCrops challenge, ingested 144 actors with relevance scoring; ~14 actors cross-referenced from prior extractions (proving accumulation-not-duplication)
5. **UM6P Dashboard v8 translator** (`src/etl/translators/um6p_dashboard.py`) — *code complete, NOT YET RUN*; awaiting final data version

---

## 4. The architectural principles, documented

These are the decisions that hold the platform together. Each has an ADR (Architecture Decision Record) in `docs/adr/` explaining why.

- **ADR-001:** Raw data is sacred — never modify source spreadsheets
- **ADR-002:** Hub as first-class entity per Phase 2 brief, not a tag
- **ADR-003:** Strategic documents and challenges as separate entities (NutriCrops is a challenge, not a hub)
- **ADR-004:** Narrative blob fields stay as text rather than over-normalized
- **ADR-005:** Provenance fields (`source_id`, `verification_status`, `confidence`) on every entity row
- **ADR-006:** Data quality findings — documents every known issue in source data and how each is handled
- **ADR-007:** Partnership profile as a sidecar table for institutional actors (UN agencies, federal agencies)
- **ADR-008:** Event scoring as a sidecar table (same pattern as partnership_profile)

Read the ADRs before making any structural change. They explain why things are the way they are.

---

## 5. Cross-cutting design patterns

These patterns recur across all four translators. They're worth internalizing because every future translator should follow them.

- **Idempotency by natural key:** Every entity has a slug (URL-safe version of name). Translators check slug-existence before inserting. Re-running a translator produces the same result as running it once.
- **In-run dedup cache + in-transaction tracking:** Translators use both an in-memory cache (for speed) and a "pending links" set (to catch within-transaction duplicates before the database catches them).
- **Verdict per row:** Every spreadsheet row ends up in one of four buckets: inserted, updated, skipped (intentional), or failed. Every verdict is logged to a CSV in `data/interim/`.
- **Quarantine for corrupt data:** When data violates its own controlled vocabulary (e.g., the Yes/No values that bled into NutriCrops Lifecycle and Maturity columns), the value is replaced with NULL and the original is logged to a quarantine CSV for human review.
- **Loud failures:** A failed row logs the exception, continues to the next row, and the run exits with non-zero if any rows failed.
- **Transactional safety:** All inserts happen in one database transaction. Mid-run failures roll back cleanly.
- **Source-row per ingestion:** Each translator creates a Source row first; every entity inserted by that translator points back to it. Provenance is non-negotiable.

---

## 6. The hard problems faced and solved

This section documents the real difficulties encountered — both data-quality issues in the source spreadsheets and engineering problems in the platform itself. These took real time and the solutions are worth preserving.

### 6.1 Data quality issues in source spreadsheets

- **Ecosystem Mapping had 8 sectors, not the 7 in the brief.** "Sustainability Hubs" appeared as a hidden 8th section. Solution: added SUSTAIN as a sector code, escalated to supervisor for final decision on whether to treat it as a sector or a cross-cutting lens.
- **Section header rows in Ecosystem Mapping** had values only in column 1 with no other data. Translator must detect and skip them — 8 rows total at known positions.
- **22 empty "Unnamed" columns** (cols 17-38) in Ecosystem Mapping were export padding, not real data. Translator drops them entirely.
- **Four hardcoded copy-paste errors** in Ecosystem Mapping (Row 25 had analyst notes in the category field, Rows 30-31 had wrong hub names pasted in, "Helath Hubs" typo). All handled via a KNOWN_ISSUE_CORRECTIONS dictionary at the top of the translator.
- **NutriCrops Actor Category** mixed 4 official dropdown values with 12 free-text variants for federal entities, regulators, industrial partners. Solved by `data/processed/actor_type_mapping.csv` — a config file mapping raw values to canonical enum values.
- **NutriCrops Lifecycle and Maturity columns severely corrupted.** ~104 rows of Lifecycle and ~26 rows of Maturity contained Yes/No values that had bled in from a column shift after the template was edited. Solved by quarantine logic: anything not matching the controlled vocabulary becomes NULL, original value logged to quarantine CSV.
- **NutriCrops cols 13-15 were ghost columns** with no headers but populated values from the original template's nested Lifecycle subcolumns. Translator ignores them entirely.
- **TRL field had a double-space typo** ("TRL 4-5 Lab  or Pilot"). Normalized in the parsing function.
- **UN Mapping uses nested headers** (▶ for major bodies, ▸ for sub-categories). Translator uses a state machine to carry hierarchy down to entity rows.
- **UN events sheet uses continuation rows** — when the Organisation column is empty or `—`, the event belongs to the most recent named organization above. Translator tracks `current_org_actor` across rows.
- **UN entity names use four different patterns** for full name + acronym: "Full Name (ACRONYM)", "ACRONYM — Full Name", "ACRONYM : Full Name", bare acronym. Solved by `parse_un_name_acronym` utility.
- **Location fields in NutriCrops** contained multi-line addresses (parent HQ + operational footprint). Caused VARCHAR overflow when the second line exceeded 80 chars. Solved by parsing only the first line and truncating with safety limits.

### 6.2 Engineering problems faced and solved

- **Python import errors** caused by missing `__init__.py` files in `src/` and `src/db/`. Fixed.
- **ydata-profiling pkg_resources error** — fixed with `pip install "setuptools<81"`
- **GitHub authentication on Windows** — Personal Access Token via right-click paste in Git Bash
- **DATABASE_URL with special characters** — passwords with `!`, `@`, `#`, etc. must be URL-encoded. Helper command: `python -c "from urllib.parse import quote; print(quote('your_password'))"`
- **Supabase pooler URL format** — `postgresql+psycopg2://postgres.{ref}:{pwd}@aws-1-{region}.pooler.supabase.com:6543/postgres`
- **Alembic ImportError on Base** — caused by missing `__init__.py` plus needing `from src.db.base import Base` (with proper sys.path setup in `env.py`)
- **Hub actor extractor crashed on duplicate slug** ("Rice University Carbon Hub" appearing twice). Fixed by using slug as the single source of truth for dedup (the database's unique constraint and the in-memory cache must agree).
- **Hub actor extractor crashed on duplicate hub_actor link** (Russell Ranch appearing in both Composition and Programs narratives of the same hub). Fixed by adding `_pending_links: set` to track within-transaction duplicates before the database catches them.
- **NutriCrops translator location overflow** — fixed by only using first line of multi-line addresses and truncating to schema limits.
- **`.gitignore` blocked `data/processed/actor_type_mapping.csv`** even though it's a config file, not data. Fixed by adding an exception line: `!data/processed/actor_type_mapping.csv`

### 6.3 Conceptual mistakes corrected during the project

- **Initial schema treated organizations as primary** — corrected to hub-first when reading the Phase 2 brief which is hub-centric.
- **"Actor Category" column ambiguity** — same column name means *organization type* in NutriCrops but *sector classification* in Ecosystem Mapping. Caught before writing translators; documented in data dictionary as a critical warning.
- **Almost added all UN partnership fields directly to actor table** — caught in time, sidecar pattern adopted instead (ADR-007). Same lesson applied for event scoring (ADR-008).
- **First version of hub actor extractor used a different dedup function than slugify** — caused duplicate-key crashes when normalized names matched but slugs differed. Fixed by making slug the single source of truth.
- **Treated UM6P Dashboard v8 initially as a replacement for UN Mapping** — it isn't; they're complementary (UN Mapping is comprehensive org data; v8 is scored strategic events). Decision: ingest both, route differently.

---

## 7. Current database state

After the four runs (translators 1-3 + hub actor extractor; NutriCrops; UN Mapping; um6p_dashboard NOT yet run):

| Table | Rows | Notes |
|---|---|---|
| sector | 8 | Seeded |
| funding_source | 9 | Seeded |
| source | ~5 | One per ingestion plus rule-based-extraction source |
| hub | 52 | From Ecosystem Mapping; rich preserved narratives |
| actor | ~900 | 797 rule-extracted + 25 UN + 117 new from NutriCrops + parent orgs |
| hub_actor | ~860 | Hub-to-actor membership links |
| actor_sector | (sparse) | Phase 4 will populate more |
| actor_person | 0 | Awaits Phase 4 extraction from talent narratives |
| person | 0 | Awaits Phase 4 |
| partnership_profile | 25 | One per UN entity |
| organization_hierarchy | ~10 | UN system structure |
| challenge | 1 | NutriCrops Phosphogypsum |
| actor_relevance | 131 | NutriCrops scoring |
| event | ~110 | Mostly UN events; v8 events pending |
| event_sector | 0 | Awaits v8 ingestion |
| event_scoring | 0 | Awaits v8 ingestion |
| strategic_document | 0 | Future: uploaded OCP/UM6P strategy docs |
| hub_funding | 0 | Awaits Phase 4 extraction |
| hub_sector_strength | 0 | Awaits precomputation job |

---

## 8. Honest assessment of what's missing

This is the part to be straight about. Phase 2's foundation is solid; the *intelligence layer* still needs to be built. Five real gaps:

1. **Individual organizations inside hub narratives are only rule-extracted** (797 actors, 493 classified as "other" because the rule-based classifier can't recognize acronyms like NREL or Ford). Phase 4 Claude enrichment fixes this.
2. **Talent and research narratives are stored but not parsed into Person rows.** The `person` table is empty. Phase 4 extracts named researchers from these narratives.
3. **Funding sources are summarized as text on each hub, not structured.** `hub_funding` is empty. Phase 4 extracts these links.
4. **Cross-hub themes are preserved as text but not represented as cross-hub relationships.**
5. **Implicit corporate organizations** mentioned in hub narratives ("partnerships with Bayer, Syngenta...") need to be extracted and properly typed. The rule extractor got the names; types need Claude.

These gaps are **by design**. Phase 2 is the foundation that preserves all narrative source material; Phase 4 (AI enrichment) extracts structured intelligence from it.

---

## 9. The plan forward

### Phase 3 (next 2-3 weeks): consolidation and v9 ingestion
- Run UM6P Dashboard translator when final v9 data arrives
- Build small admin tools: a Streamlit page for browsing the database with sourced answers
- Hold a checkpoint demo at Week 4 (per project plan)
- Email FZ with a Phase 2 status summary

### Phase 4 (Weeks 5-9): AI extraction layer
- Build the Claude enrichment pipeline that reads hub narratives and extracts:
  - Named individual actors from composition_narrative
  - Researchers from talent_narrative → person + actor_person rows
  - Funding source links from funding_summary → hub_funding rows
  - Type classification for the 493 "other" actors
- Every extracted fact lands with `source_type='ai_inference'`, `verification_status='needs_review'`, low confidence
- Human review queue (in the Streamlit admin app) promotes candidates to `verified`

### Phase 5 (Weeks 10-13): query agent and UI
- Build the Claude-powered query agent that translates plain-English to SQL against the canonical schema
- Build a Next.js front-end deployed on Vercel
- Build the precomputed answer layer: `hub_sector_strength` populated nightly, top-actor caches, etc.

### Phase 6 (Weeks 14-16): polish and handover
- Documentation, runbooks
- Strategic scale-up memo for FZ
- Final demo

### Beyond Phase 2 (architectural improvements worth queuing)
Per the conversation on better data import patterns:
- **Refactor four translators into a generic YAML-driven translator** (one week of work; payoff: every new spreadsheet costs 15 min instead of a day). Not urgent — current architecture works fine through Phase 4.
- **Add canonical external identifiers** (`ror_id`, `orcid`, `openalex_id`) to actor and person tables. Single highest-leverage architectural change for online enrichment.
- **Build a connector framework** for online sources (OpenAlex, ROR, NSF awards, USPTO, etc.). Right approach when Phase 4 expands beyond spreadsheets.
- **Streamlit admin app** for operational edits and AI-extraction review queue.

---

## 10. Key files and locations

```
~/Projects/GHUS-Platform/
├── .env                                # DATABASE_URL, never commit
├── alembic.ini
├── docs/
│   ├── adr/                            # ADR-001 through ADR-008
│   ├── architecture/entity-model-v1.png
│   ├── data-dictionary.md
│   └── phase-4-plan.md                 # TODO: write this
├── src/
│   ├── db/
│   │   ├── base.py                     # SQLAlchemy Base
│   │   ├── session.py                  # SessionLocal factory
│   │   └── models.py                   # All 20 table classes
│   └── etl/
│       ├── common/text_cleaning.py     # clean_text, slugify, parse_un_name_acronym
│       └── translators/
│           ├── ecosystem_mapping.py
│           ├── hub_actor_extractor.py
│           ├── un_mapping.py
│           ├── nutricrops.py
│           └── um6p_dashboard.py
├── scripts/
│   ├── seed_reference_data.py
│   ├── run_ecosystem_mapping.py
│   ├── extract_hub_actors.py
│   ├── run_un_mapping.py
│   ├── run_nutricrops.py
│   └── run_um6p_dashboard.py
├── migrations/                         # Alembic
├── data/
│   ├── raw/                            # source XLSX files
│   ├── interim/                        # audit, quarantine, failure logs
│   └── processed/actor_type_mapping.csv
└── evals/                              # TODO: golden_dataset.jsonl for Phase 4
```

---

## 11. Important conventions for any new work

- **Every new translator follows the same pattern as the existing four.** Same audit logging, same quarantine pattern, same source-row creation, same idempotency by slug.
- **Never modify the source spreadsheets.** Read-only access (`openpyxl.load_workbook(..., read_only=True)`). All cleaning happens in code, not in Excel.
- **Every new schema field needs an ADR if it changes architectural meaning.** Field additions don't need ADRs; pattern changes do.
- **Every new data quality finding gets a new section in ADR-006 or a new ADR.** Don't bury issues in code comments.
- **Every value violating a controlled vocabulary gets quarantined, not silently dropped.** The quarantine CSV is the audit trail.
- **Commits use conventional format:** `feat(area): description`, `fix(area): description`, `docs: description`.

---

## 12. What a new conversation needs to know to continue

If you're a new Claude conversation reading this:

1. **The platform is real and working.** Don't suggest rewriting the foundation.
2. **The schema is locked at v1 with 20 tables.** New tables can be added but the existing ones shouldn't be changed without an ADR.
3. **The four translators are the model for future ones.** Read one of them (UN Mapping is the most complex working one) to understand the pattern before writing anything.
4. **Phase 4 is the next major build.** It needs AI extraction, human review queue, and the Streamlit admin interface. Don't start it until the v9 UM6P Dashboard data is ingested.
5. **Ismail prefers direct answers** and step-by-step code that he can paste and run. He's not afraid of complex topics but doesn't want padding or hedging. When he asks "how do I X," give the exact commands.
6. **All decisions are written down** in ADRs and the data dictionary. Read those before suggesting changes.
7. **The repo is private GitHub.** Local Windows development with Git Bash + VS Code + Python venv.

---

*End of report. Project status: Phase 2 foundation 95% complete. Ready to proceed to Phase 3 consolidation when v9 data arrives, then Phase 4 AI enrichment.*
