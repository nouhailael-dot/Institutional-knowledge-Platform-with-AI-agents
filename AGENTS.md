# AGENTS.md - GHUS Institutional Knowledge Platform

## Repository boundaries

- One repository: `C:\Users\Ismail\Projects\GHUS-Shared`, a clone of
  `https://github.com/nouhailael-dot/Institutional-knowledge-Platform-with-AI-agents`.
  All Claude Code and Codex development happens here, directly on `main` (see
  "Working on main" below).
  - Repository root: the platform. Architecture V2 phases 15-16, the platform
    UI, FastAPI routes, review/curation, browsing, Ask, retrieval/RAG, Data Feed
    and source labels. Older references to Streamlit mean this platform unless
    explicitly stated otherwise.
  - `ghus-backend/`: the backend. Architecture V2 phases 2-14, agents,
    migrations, schema proposals and scripts. It is part of this repository,
    never a separate repository or a second copy; the platform reaches it
    through the bridges in `src/` (see `scripts/run_demo_server.py`).
- Retired folders, kept only as read-only archives: never edit, run, commit or
  migrate from them. `C:\Users\Ismail\Projects\GHUS-Platform`,
  `C:\Users\Ismail\Projects\Institutional-knowledge-Platform` (and its
  `.claude\worktrees`), `C:\Users\Ismail\Projects\GHUS-Complete-Integration`
  and `C:\Users\Ismail\Projects\Institutional-knowledge-Platform-with-AI-agents`.
  Their unmerged work of 27 Oct 2026 is preserved on `backup/wip-2026-10-27-*`
  branches in those folders.
- Old draft: `C:\Users\Ismail\Documents\GHUS\GHUS-Platform-v2`. It is
  read-only reference material. Never edit, commit, or run migrations there.
- Isolated test database: local PostgreSQL `ghus_v2_test` (and other
  `ghus_v2_*_test` databases) at `127.0.0.1:55432`; its data directory stays
  outside all repositories.
- Shared Supabase database: read-only. Never execute DDL or writes there.

At the start of every session, print the working directory and branch. Stop if
the directory is one of the retired folders.

## Working on main

Ismail and Nouhaila both work directly on `main`; there are no long-lived
feature branches.

- Before starting work, `git switch main` and `git pull --ff-only origin main`,
  so every change builds on the other person's latest commits.
- Commit in small, self-contained steps, each with its tests passing.
- Before pushing, `git pull --rebase origin main` (or a merge if the rebase
  conflicts), rerun the relevant tests, then `git push origin main`.
- Never force-push, never reset or rewrite pushed commits, and never resolve a
  conflict by blindly taking one side: keep both people's changes.
- Pushing to GitHub happens only when the user asks for it.
- A large or risky change (a migration, a shared frontend rewrite) may still go
  through a short-lived branch and Pull Request for Nouhaila's review.

## Architecture V2 standing rules

1. Canonical entity writes exist only in backend
   `agents/discovery/promote.py` and `agents/enrichment/decisions.py`. Frontend
   code must not become a third canonical writer; mutation endpoints must
   delegate to the approved backend workflow.
2. Canonical schema changes are proposals for the schema owner. Never apply
   DDL or writes to shared Supabase.
3. Every new job and script defaults to dry-run. Live execution requires an
   explicit manual dispatch.
4. Person discovery is enabled: supervisor sign-off was confirmed by the
   platform owner on 2026-10-15 and recorded in the backend's
   `TARGETING_POLICY.md` section 6. Every person record still routes to human
   review; none is auto-created or auto-absorbed.
5. `aggregate` remains excluded from ER candidates, reference sets, and agent
   outputs through the `actor_type` -> `actor_category` rename.
6. `hub_overlap` remains excluded from the ER model. Do not reintroduce
   `desc_both_present`, and do not name a new table, field, or queue
   `hub_overlap`.
7. Never invent data. Missing evidence is represented as `not_found`.
8. Work one Architecture V2 phase at a time. End each phase with tests for
   the platform and for `ghus-backend/`, a phase report, and a stop for
   approval. Do not begin the next phase without explicit approval.
9. A backend schema change that affects frontend reads must ship in the same
   phase as its frontend compatibility change or a compatibility alias.
10. Commit at the end of every requested step so no work remains uncommitted
    between steps.

## Current application shape

- `frontend/` is the browser UI served by the FastAPI application.
- `backend/app.py` owns HTTP routes.
- `src/db.py` owns PostgreSQL connections.
- `src/assemble.py`, `src/embed.py`, and `src/retrieve.py` own retrieval index
  assembly, embedding, and hybrid retrieval.
- Root `app.py` is the legacy Streamlit interface; do not add V2 UI features
  there.

