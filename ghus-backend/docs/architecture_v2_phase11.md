# Architecture V2 Phase 11 — immutable fact resolution

Date: 2026-10-06
Database: local isolated PostgreSQL 17.5 only
Production: untouched

Phase 11 uses the existing Phase 9/10 `actor_fact` ledger. It adds a unique
current pointer per `(actor_id,topic_id,fact_key)`, append-only corroboration,
lifecycle state, semantic hashing, supersession links, canonical conflict and
pending-update reviews, and deterministic current/history views.

Resolution behavior:

- first fact becomes current;
- same semantic value retains the current row and appends provenance;
- newer equal-or-higher-confidence agent evidence supersedes an agent current;
- older/weaker evidence is stored as `conflict_flagged` and reviewed;
- agent evidence never replaces a GHUS/human current fact and is stored as
  `pending_update`;
- no fact value is updated or deleted;
- pre-Phase-11 facts receive deterministic pointers without rewriting history.

Light Pull, Deep Pull and Specific Ask all call the same approved
`append_actor_fact` writer. Shared Review reads `actor_fact_current_v2` by
default and exposes `actor_fact_history` separately.

Validation:

- focused Phase 11/Light/Deep/Specific Ask suite: **34 passed**;
- full backend against target-expand database: **480 passed, 2 intentional
  cutover gates failed**;
- shared Python: **137 passed + 30 subtests**;
- shared Node: **23 passed**;
- backend/frontend read-only database smokes: passed.

The two intentional failures require final contract migration 460: physical
legacy actor columns remain, and expanded database columns therefore do not yet
equal the clean V2-only ORM contract. The former review-kind failure is no
longer a hidden exception: expand migration 440 admits both bridge and canonical
kinds, and validate migration 450 removes bridges only after conversion.
