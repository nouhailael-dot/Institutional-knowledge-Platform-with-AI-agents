# Architecture V2 Phase 8 report — Typed relationships

Date: 2026-10-06 (written retroactively; the Phase 8 code landed in commit
`abf78f8` "feat: implement architecture v2 phases 8-12" without a report)

Backend repository and branch: `C:\Users\Ismail\Projects\GHUS-Platform` on
`codex/architecture-v2`

Shared repository: not touched by Phase 8.

This report describes only what exists in the code, the SQL proposals and the
tests. Anything not verified is marked **UNVERIFIED**.

## Scope and safety

Phase 8 defines the typed edge contract between actors, people, events and
strategic entities, and the recursive parent-family view. No production
connection, DDL or data write was made. Frozen proposal 250 is not edited;
420 supersedes its contract. Agent 3 is not touched.

## Files

| File | Role |
|------|------|
| `agents/common/relationships.py` | Storage-free contract: vocabulary, endpoint pairs, request validation, payload → edge requests |
| `agents/enrichment/decisions.py` (`append_entity_edge`, `append_network_locations`) | The only edge writer; dry-run by default |
| `agents/discovery/promote.py` (lines ~541, ~658–665) | Validates edge requests before dry-run/live actor creation; writes them live through `append_entity_edge` |
| `agents/sql/250_v2_edges.sql` (frozen) | `entity_edge` table, append-only trigger, `actor_descendant_edge` recursive view |
| `agents/sql/420_v2_edge_contract.sql` | Superseding contract (below) |
| `agents/sql/rollback/420_v2_edge_contract.sql` | Exact rollback; refuses if `connected_to_um6p_ocp` rows exist |
| `tests/agent/test_architecture_v2_relationships.py` | Phase 8 tests |

## Edge types

Eleven types, identical in `RELATIONSHIP_ENDPOINTS` (Python) and
`entity_edge_type_definition` + the CHECK constraint (SQL 420):

| Type | Subject → object | Establishes actor family |
|------|------------------|--------------------------|
| `unit_of` | actor → actor | **yes** |
| `operated_by` | actor → actor | **yes** |
| `affiliated_with` | person → actor | no |
| `member_of` | actor → actor | no (membership is not ownership) |
| `portfolio_of` | actor → actor | no (portfolio is not ownership) |
| `spinout_of` | actor → actor | no |
| `funded_by` | actor → actor | no |
| `collaborates_with` | actor → actor | no |
| `organizes` | actor → event | no |
| `participates_in` | actor/person → event | no |
| `connected_to_um6p_ocp` | actor/person/event → strategic_entity | no |

420 renames 250's `connected_to_strategic_entity` to `connected_to_um6p_ocp`.
It refuses to run if any deprecated `connected_to_strategic_entity` row exists,
so applying 420 after 250 has received writes needs an explicit rollout step.

## Rules enforced

- **Source required.** `entity_edge.source_id uuid NOT NULL REFERENCES source`
  (250); the Python validator requires a UUID `source_id`.
- **Endpoint pairs.** Python `validate_entity_edge` and the SQL trigger
  `ghus_validate_entity_edge` (BEFORE INSERT) both reject pairs not listed for
  the type. The trigger also checks that both endpoint rows exist.
- **No self-edges.** Python check plus 250's CHECK.
- **Confidence** must be `high`, `medium` or `low`.
- **Append-only.** 250 trigger `entity_edge_append_only` rejects UPDATE/DELETE.
- **Idempotent.** 420 adds `uq_entity_edge_identity` (with `topic_id` NULL
  coalesced); the writer uses `ON CONFLICT DO NOTHING` and returns the existing
  edge id.
- **No family cycles.** 420 trigger `ghus_prevent_actor_family_cycle` refuses
  a `unit_of`/`operated_by` insert that would make the subject its own
  ancestor.
- **No inferred parents.** `actor_relationship_requests` returns only edges
  present in the payload (`parent_connection` must be `unit_of` or
  `operated_by`, plus an explicit `relationships` list). With no edges,
  promotion records `parent_connection = {"state": "standalone", "parent": null}`
  — a complete standalone actor. Nothing is inferred from name, domain, hub,
  sector or location.

## `actor_descendants`

420 creates `actor_descendants` (root_actor_id, descendant_actor_id, depth,
path) as a thin view over 250's recursive `actor_descendant_edge`. Recursion
follows **only** `unit_of` and `operated_by` edges and stops on repeated path
members. `portfolio_of`, `member_of`, `funded_by` and every other type are
never parenthood and never appear in descendants.

## Network = parent + locations

`network_location_requests` / `append_network_locations` link each physical
location actor to a network parent with one sourced `unit_of` edge (location →
parent). The location keeps its own geography; network reach is not copied to
sites (the request carries no location data).

**UNVERIFIED / not yet used:** `append_network_locations` has no caller outside
its definition. No production path converts former `aggregate`/network actors
or legacy `organization_hierarchy` rows into edges yet — that is Phase 12
work (contract §7; this plan's Step 3.5).

## Tests

`tests/agent/test_architecture_v2_relationships.py`, 9 test functions, 22 test
cases after parametrization. Run on 2026-10-06:

- Without a database: **21 passed, 1 skipped**.
- With `V2_TEST_DATABASE_URL` and `DATABASE_URL` both pinned to local
  `ghus_v2_target_test` (127.0.0.1:55432): **22 passed**.

The database test proves: idempotent append (same id twice), two-level
descendants through `unit_of` then `operated_by`, cycle refusal, missing
endpoint refusal; all rolled back.

Local `ghus_v2_target_test` holds 8 `unit_of` edges created 2026-10-06 with
source description "architecture v2 actor create" (from earlier isolated
promotion tests; not production data).

## Gaps found while writing this report

- `docs/architecture_v2_gap_analysis.md` R161 names
  `test_portfolio_not_parent` and R086 names
  `test_light_parent_or_complete_standalone`; neither test exists under those
  names. The behavior is covered by
  `test_exact_relationship_vocabulary_and_family_boundary`,
  `test_parent_requires_explicit_structural_type_and_source_identity` and
  `test_standalone_actor_is_complete_and_no_parent_is_invented`.
- No test inserts a `portfolio_of` edge into a database and checks it is
  absent from `actor_descendants` (covered only by the view's SQL text).
- 420 is classified as part of the additive package with 250 + 300, but its
  CHECK replacement is breaking once 250 has rows (stated in 420's header).
