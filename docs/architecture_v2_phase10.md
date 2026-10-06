# Architecture V2 Phase 10 report — Deep Pull and specific asks

Date: 2026-10-05

Backend: `C:\Users\Ismail\Projects\GHUS-Platform`, branch
`codex/architecture-v2`

Shared Review: `C:\Users\Ismail\Projects\Institutional-knowledge-Platform`,
branch `feature/ismail-modifications`

## Safety and authorization

No production connection, DDL, or data write occurred. Deep Pull authorization
uses only the latest append-only GHUS `record_verification` decision for the
actor and requested topic. Legacy mutable status and every non-Verified latest
decision fail closed. Legacy live actor enrichment is retired and refuses to
run; its dry-run analysis remains available.

## Deep collection

`agents/collection/deep_pull.py` defines Deep fields for all 12 actor
categories. A request requires actor/topic/request UUIDs, requester identity,
and a unique selected field set belonging to that category. Selecting the
entire category row is rejected: verification authorizes focused enrichment,
not an exhaustive profile. Values append as Layer 2 `deep_pull` facts through
`append_actor_fact`, with the same provenance and dry-run default as Layer 1.

The isolated PostgreSQL proof created a topic-scoped Parked actor, demonstrated
Deep Pull rejection before verification, appended the GHUS Verified decision,
proved dry-run wrote nothing, then appended and read back a sourced Layer 2
fact.

Selected linked sub-entities are capped at five per request and receive an
explicit parent relationship before being handed to the normal actor-mapping
callback. They do not create unsourced hierarchy.

## Specific asks

Layer 3 has no autonomous scheduler or default trigger. Its writer requires an
explicit requester, request text, request UUID, and explicit values. The ask is
retained with each result fact. The user-facing action remains Phase 15.

## Review and validation

Shared Review separates Layer 2 evidence from Light Pull evidence and shows
value, collection state, confidence, read date, and source.

- Focused Phase 10 contract plus isolated database proof: **10 passed**.
- Complete backend agent/integration regression: **463 passed**, with 2
  inherited SQLite adapter warnings.
- Complete shared Node suite: **23 passed**.
- Shared Review Python suite: **34 passed, 1 isolated-DB test skipped, 6
  subtests passed** in the UI-only run; the preceding configured complete
  shared suite remained **137 passed, 30 subtests passed**.

The frozen 180--350 package, Agent 3, person-discovery default,
canonical-writer boundary, production database, and the three approved
breaking schema gates are unchanged.

## Deferred

Fact corroboration, supersession, conflict, and current/history resolution are
Phase 11. Existing-data migration is Phase 12. Controlled UM6P/OCP matching is
Phase 13. Specific-ask UI is Phase 15. Physical legacy-column removal and final
RAG cutover remain Phase 16.
