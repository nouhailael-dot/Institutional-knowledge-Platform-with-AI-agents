# AGENTS.md - GHUS Institutional Knowledge Platform

## Repository boundaries

- Frontend: `C:\Users\Ismail\Projects\Institutional-knowledge-Platform`.
  Architecture V2 phases 15-16 live here, together with the platform UI,
  FastAPI routes, review/curation, browsing, Ask, retrieval/RAG, and source
  labels. Older references to Streamlit mean this platform unless explicitly
  stated otherwise.
- Backend: `C:\Users\Ismail\Projects\GHUS-Platform`. Architecture V2 phases
  2-14, agents, schema proposals, and scripts live there.
- Old draft: `C:\Users\Ismail\Documents\GHUS\GHUS-Platform-v2`. It is
  read-only reference material. Never edit, commit, or run migrations there.
- Isolated test database: local PostgreSQL `ghus_v2_test` at
  `127.0.0.1:55432`; its data directory stays outside all repositories.
- Shared Supabase database: read-only. Never execute DDL or writes there.

At the start of every session, print and verify both Projects repository paths
before touching files. Stop if either path differs.

## Architecture V2 standing rules

1. Canonical entity writes exist only in backend
   `agents/discovery/promote.py` and `agents/enrichment/decisions.py`. Frontend
   code must not become a third canonical writer; mutation endpoints must
   delegate to the approved backend workflow.
2. Canonical schema changes are proposals for the schema owner. Never apply
   DDL or writes to shared Supabase.
3. Every new job and script defaults to dry-run. Live execution requires an
   explicit manual dispatch.
4. Person discovery remains feature-flagged off until supervisor sign-off.
5. `aggregate` remains excluded from ER candidates, reference sets, and agent
   outputs through the `actor_type` -> `actor_category` rename.
6. `hub_overlap` remains excluded from the ER model. Do not reintroduce
   `desc_both_present`, and do not name a new table, field, or queue
   `hub_overlap`.
7. Never invent data. Missing evidence is represented as `not_found`.
8. Work one Architecture V2 phase at a time. End each phase with tests for
   both repositories, a phase report, and a stop for approval. Do not begin the
   next phase without explicit approval.
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

