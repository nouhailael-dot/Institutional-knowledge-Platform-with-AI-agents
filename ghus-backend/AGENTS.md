# AGENTS.md — GHUS Ecosystem Intelligence Platform

## What this repo is

A PostgreSQL/Supabase database mapping the UM6P Global Hubs (GHUS) ecosystem:
actors, hubs, events, people, partnership profiles. Built from spreadsheet ETL
plus an entity resolution (ER) pipeline. A sibling repo, `um6p-rag`, is a
read-only consumer that owns only three tables: `search_doc`, `query_log`,
`proposal`.

## Architecture V2 repository boundaries

- Backend: this `ghus-backend/` folder of the shared repository
  `C:\Users\Ismail\Projects\GHUS-Shared`. Architecture V2 phases 2-14,
  agents, migrations, SQL proposals, and scripts live here.
- Frontend: the root of the same repository. Architecture V2 phases 15-16 and
  all platform UI, review, browsing, Ask, retrieval/RAG, Data Feed and
  source-label behavior live there. References to Streamlit in older
  specifications mean this frontend unless explicitly stated.
- The repository root `AGENTS.md` governs both; read it first. The former
  separate checkouts (`C:\Users\Ismail\Projects\GHUS-Platform`,
  `C:\Users\Ismail\Projects\Institutional-knowledge-Platform` and the others it
  lists) are read-only archives: never edit, run, or commit there.
- Old draft: `C:\Users\Ismail\Documents\GHUS\GHUS-Platform-v2`. It is
  read-only reference material. Never edit, commit, or run migrations there.
- Isolated test database: local PostgreSQL `ghus_v2_test` at
  `127.0.0.1:55432`. Its data directory must remain outside every repository.
- Shared Supabase database: the team's one database since 2026-10-29 (decision
  of the platform owner, Ismail Sabbar). Data is written there only through the
  approved writers and the platform's own flows, never by hand; a migration
  only with the platform owner's approval, after a fresh backup, recorded in
  `architecture_v2_migration_ledger`.

At the start of every session, print the working directory and branch, and
stop if the directory is not `GHUS-Shared` (or a worktree of it).

Current state: ~872 canonical actors (reduced from 952 via ER merges), 220
events, 10 seeded sectors. A frozen ER combiner model with HIGH/LOW thresholds
and a human review queue already exist and are in production use.

We are now adding an agents layer: automated discovery of new ecosystem data,
automated gap-filling of sparse fields, and a staged interface for teammate-owned
new-sector discovery. The reporting agent is out of scope and preserved only on
branch `shelved/reporting-agent`.

## Non-negotiable constraints

These exist because violating them has already caused real damage in this
project. Treat them as compile errors, not preferences.

1. **Scraped data never writes directly to canonical tables.** It lands in
   `staged_record`. Canonical entity writes under `agents/` are permitted only
   in `agents/discovery/promote.py` and `agents/enrichment/decisions.py`. Both
   writers must enforce a gap-guarded `WHERE` clause for automatic updates, a
   `rowcount` assertion that raises on missed writes, and provenance written in
   the same transaction as the fact. No other module may write canonical entity
   tables.
2. **Entity resolution runs at ingest, before insert.** Never after. Never
   bypassed. The agents call the existing frozen combiner and the existing
   thresholds — they do not implement their own matching logic and do not
   define their own threshold constants.
3. **Dry-run is the default.** Live writes require an explicit `--live` flag.
   Dry-run must exercise the same code path as live, differing only at the
   commit boundary. A dry-run that takes a different branch validates nothing.
4. **An empty result set is a no-op, never a delete.** Any code that deletes or
   replaces rows must first assert the replacement set is non-empty. A previous
   regression removed such a guard and made a full search-index wipe possible
   with no error raised.
5. **Every written fact has a provenance row** (source URL + fetch timestamp),
   written in the same transaction as the fact itself. Missing evidence is
   recorded as `not_found`; data must never be invented. If provenance insert
   fails, the fact insert rolls back.
6. **Never overwrite a non-null value automatically.** Enrichment fills gaps
   only. A believed-wrong existing value becomes a proposal for a human.
7. **Silent failure is the worst outcome.** Prefer raising loudly. A filter that
   silently matches nothing, a log line that never fires, an index delete with
   no error — all three have occurred here. If a step can no-op unexpectedly,
   log a warning with counts.
8. **Never modify the upstream canonical schema.** Another person owns those
   tables. New tables added by this work are ours; DDL against existing tables
   requires explicit approval and must be raised as a question, not written.
9. **No secrets in code or committed files.** Read from environment. Never print
   a connection string or API key, even partially, in logs or error messages.
10. **The shared Supabase database is the team's database (2026-10-29).** Data
    is written there only through the approved writers (`promote.py`,
    `decisions.py`, the admission and staging commands). A migration runs
    there only with the platform owner's approval, after a fresh backup, and
    is recorded in `architecture_v2_migration_ledger`.
11. **Person discovery is enabled, under section 6.** Supervisor sign-off was
    confirmed by the platform owner on 2026-10-15 and recorded in
    `TARGETING_POLICY.md` section 6; `people_enabled` is on. Section 6's limits
    still bind: professional fields only, and no person record is ever
    auto-created or auto-absorbed.
12. **Preserve aggregate exclusion.** `actor_type = 'aggregate'` stays out of
    ER candidates, reference sets, and agent outputs through the
    `actor_type` -> `actor_category` transition.
13. **One Architecture V2 phase per change set.** Finish each phase with both
    repositories' relevant tests, a phase report under `docs/`, and a stop for
    approval. Do not begin the next phase without explicit approval.

## Protected decisions — do not change without asking

- ER thresholds live in exactly one module. Agents import them. Never redefine.
- `hub_overlap` is permanently excluded from the ER feature set. It produced
  false merges across multiple measurement rounds. Do not reintroduce it.
  `desc_both_present` must not be reintroduced, and no new table, field, or
  queue may be named `hub_overlap`.
- The keyword-search `&` → `|` OR rewrite in `um6p-rag` is load-bearing. A
  previous bug fix removed it and silently collapsed hybrid retrieval to
  vector-only. If you touch tsquery construction anywhere, preserve it.
- Column resolution from spreadsheets is by header name, never by position
  (`header_resolver.py`). Do not introduce positional indexing.

### Open-web discovery

- Events are seeded by three configured sources and the database. Actors and
  people are seeded by the database only; there is no reference site for them.
- `actor_type = 'aggregate'` is excluded everywhere: from the fit-scoring
  reference set, from ER candidate loading, and from anything an agent learns
  from. Aggregates are category labels ("Phosphogypsum Ecosystem Hubs"), not
  operating organisations. Agents must also never create one; a candidate that
  is a grouping, consortium listing, or category page is rejected, not staged.
- Records from a discovered domain never auto-absorb. They route to `create` or
  `review` only, until that domain has a promotion track record.
- Person discovery is on since 2026-10-15 (sign-off recorded in
  `TARGETING_POLICY.md` section 6). Every person record still routes to human
  review; none is auto-created or auto-absorbed.
- No autonomous crawling. Search results only, one level deep.
- No LLM in routing or promotion. Those stay deterministic and replayable.

## Environment

- Windows dev machine, PowerShell / Git Bash, Python venv, VS Code.
- SQLAlchemy for DB access. Supabase **session pooler** connection string with
  `?sslmode=require` — the direct connection is IPv6-only and will hang.
- Anthropic Claude for LLM calls; Voyage `voyage-3` for embeddings.
- Version control via GitHub.

## Working style expected of you

- Inspect before assuming. If a module, table, or column name matters to your
  implementation, read it from the repo. Do not invent plausible names.
- When something in the repo contradicts these instructions, stop and ask.
  Do not reconcile it silently.
- Small diffs. One concern per commit. Tests alongside code, not after.
- Commit at the end of every requested step so no work remains uncommitted
  between steps.
- State your assumptions explicitly at the top of your response, and list
  anything you could not verify.
- Do not add dependencies without naming them and why in your summary.

### Human-review admission

- `agents/review/admission.py` is an orchestration entry point, not a third
  canonical writer. It may validate decisions, write the review audit and
  proposed-hub tables, and drain the referenced source queue, but all actor,
  event, person, and relationship writes must delegate to
  `agents/discovery/promote.py`.
- The admission entry point owns the outer transaction. Promotion is called
  with `manage_transaction=False`, so canonical changes, provenance, the
  decision audit row, and the source-row status commit or roll back together.
- A new/create review decision must still pass the frozen entity resolver. A
  resolver match or ambiguity is never bypassed by the UI.
- Proposed hubs are written only to `proposed_hub`; review admission must never
  create a canonical `hub` row.
- `agents/sql/180_review_admission_workflow.sql` is emitted for owner review.
  It must not be executed by an agent session.

### Repository workflow:

- This repository is the canonical shared GHUS development repository.
- Never work from old downloaded/ZIP copies of the project.
- `main` is the shared branch, and development happens directly on it; follow
  "Working on main" in the repository root `AGENTS.md` (pull before working
  and before pushing, small commits with passing tests).
- Do not force-push or destructively reset shared work.
- Do not resolve merge conflicts by blindly choosing one side.
- Preserve existing functionality unless explicitly asked to change it.
- Never commit .env, .venv, secrets, caches, or generated temporary artifacts.
- Keep schema changes and migrations synchronized.
- Run relevant tests before considering work complete.
- Before substantial changes, inspect the current branch and repository state.
