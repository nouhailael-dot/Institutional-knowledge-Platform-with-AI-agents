# AGENTS.md — GHUS Ecosystem Intelligence Platform

## What this repo is

A PostgreSQL/Supabase database mapping the UM6P Global Hubs (GHUS) ecosystem:
actors, hubs, events, people, partnership profiles. Built from spreadsheet ETL
plus an entity resolution (ER) pipeline. A sibling repo, `um6p-rag`, is a
read-only consumer that owns only three tables: `search_doc`, `query_log`,
`proposal`.

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
   written in the same transaction as the fact itself. If provenance insert
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
10. **Do not run migrations or connect to the production database.** Emit SQL
    files under `agents/sql/` for the human to run. Assume no DB access.

## Protected decisions — do not change without asking

- ER thresholds live in exactly one module. Agents import them. Never redefine.
- `hub_overlap` is permanently excluded from the ER feature set. It produced
  false merges across multiple measurement rounds. Do not reintroduce it.
- The keyword-search `&` → `|` OR rewrite in `um6p-rag` is load-bearing. A
  previous bug fix removed it and silently collapsed hybrid retrieval to
  vector-only. If you touch tsquery construction anywhere, preserve it.
- Column resolution from spreadsheets is by header name, never by position
  (`header_resolver.py`). Do not introduce positional indexing.

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
- State your assumptions explicitly at the top of your response, and list
  anything you could not verify.
- Do not add dependencies without naming them and why in your summary.
