# Architecture V2 Phase 6 report — Hubs: structure and deterministic assignment

Date: 2026-10-01  
Backend repository: `C:\Users\Ismail\Projects\GHUS-Platform`  
Frontend/RAG repository: `C:\Users\Ismail\Projects\Institutional-knowledge-Platform`  
Branch in both repositories: `codex/architecture-v2`  
Starting backend checkpoint: `ba0d24b0e29bebb96447bcec6dc0745eef59393c`

## 1. Scope and safety boundary

Phase 6 implements hub assignment, assignment evidence, density-center preview,
and frozen-center decision boundaries. No production connection, DDL, write,
backup, or data mutation was performed. The validated 180–350 package and
teammate-owned Agent 3 files were not changed. Phases 7, 12, 15, and 16 were not
started.

The real 49 hubs still lack controlled topic mappings and latitude values; one
also lacks a primary city. No topic, coordinate, eligible status, or final
center was inferred. All 821 existing memberships remain authoritative and
unchanged.

## 2. Assignment contract

`agents/common/hub_assignment.py` is a pure deterministic evaluator using the
Phase 4 `distance_miles()` function:

1. Compare controlled topic IDs before any distance work.
2. A topic mismatch or missing controlled topic yields `needs_review_topic`,
   low priority, and does not evaluate distance.
3. A topic match with either coordinate pair missing yields
   `needs_review_location`.
4. A topic match outside the hub radius yields `needs_review_location` and the
   canonical review target `hub_needs_review`.
5. Passing candidates are ordered by distance and then hub UUID; the nearest is
   assigned. Every in-radius candidate remains in immutable evidence. Multiple
   in-radius same-topic hubs produce the canonical `hub_radius_overlap` review
   target without changing nearest-center selection.
6. Separate topic evaluations can produce separate memberships for the same
   actor. Input ordering never changes a result.

`agents/discovery/promote.py` computes the plan at the existing `hub_fit` step
and is still the sole discovery path allowed to insert a canonical membership.
Dry-run and live execution share the same pure plan and persistence path.

## 3. Center calculation and freeze

`agents/common/hub_centers.py` considers only Verified and Imported actors with
controlled coordinates. Parked, Rejected, merged, aggregate, and ungeocoded
actors are excluded. Candidate centers are member city coordinates. They are
ranked by the number of eligible members within 50 miles, mean distance for
eligible members within 200 miles, then a stable state/city/coordinate key.

The result is a preview tagged `density_center_v1`. A frozen center is never
mutated by preview. A shift greater than 25 miles requests review evidence.
`record_hub_center_drift_review()` records the proposal; only an approved review
can reach `apply_hub_center_decision()` in the approved manual decision writer.
Phase 15 authorization is not implemented.

No Phase 7 family counting, category matching, cluster extraction, naming, or
hub proposal creation exists in this change set.

## 4. Existing membership protection

`legacy_membership_assessment()` always returns
`membership_preserved=true` and `legacy_membership_preserved` evidence. Missing
prerequisites never reject a membership. When a trustworthy assessment is more
than 200 miles, its only canonical review target is informational
`hub_member_outside_radius`; the membership is neither deleted, moved, replaced,
nor rejected.

The production baseline remains:

| Object | Count | Phase 6 action |
|---|---:|---|
| Hubs | 49 | no data changes |
| Hubs with memberships | 48 | no data changes |
| Memberships | 821 | preserved exactly |
| Actors | 965 | no data changes |
| Events | 356 | no data changes |

`Mining Hubs` is the 49th row and has no location or memberships. The Phase 1
hub audit in the gap analysis still lists all 49.

## 5. Schema proposals

Logical proposal 020 is outside the validated 180–350 production package:

- `v2a05_hub_assignment.py` adds nullable `hub.center_method_version` and
  `hub.center_computed_at` audit columns.
- `380_v2_hub_assignment_evidence.sql` creates an immutable evidence table.
  It is audit storage, not a canonical actor/hub writer.
- V2-only ORM metadata mirrors both additions and remains isolated from
  application/Alembic metadata.

Deferred proposal 400 contains the breaking final hub and membership contract.
It depends on the P12 topic, coordinate, source, status, and membership
backfill. It was not applied.

## 6. Review-kind compatibility

The current production-compatible CHECK accepts `hub_assignment` and
`same_topic_overlap`, but not the final Phase 6 review kinds. Marked bridge rows
therefore carry all of:

- `compatibility_bridge=true`;
- `canonical_review_kind`;
- `canonical_outcome` (so `needs_review_topic` is never semantically collapsed
  into a location failure);
- complete deterministic evidence;
- `method_version=hub_assignment_v1`.

Deferred proposal 390 adds `hub_needs_review`, `hub_radius_overlap`, and
`hub_member_outside_radius`. It converts only explicitly marked bridge rows and
adds a migration marker. Its rollback converts only those migration-marked
rows. The validated Phase 5 `category_doubt` proposal is unchanged.

## 7. Isolated database proof

On local `ghus_v2_test` at `127.0.0.1:55432`, Phase 6 proposal 020 completed an
exact `up → down → up`. Existing rows after the second up were unchanged:

| Table | Rows |
|---|---:|
| `actor` | 965 |
| `hub` | 49 |
| `hub_actor` | 821 |
| `event` | 356 |
| `hub_assignment_evidence` | 0 |

The full-manifest idempotence command also exposed an inherited Phase 5 runner
conflict: after proposal 370 makes `definition` non-null, re-running frozen
proposal 190's seed insert omits that column and PostgreSQL rejects the insert
before `ON CONFLICT` handling. Frozen 190–350 was not modified. Phase 6 was
therefore proven independently; the full-manifest re-run remains a migration
tooling issue to resolve without changing the validated package.

### Unresolved migration/rollout acceptance item: proposals 190 and 370

- Phase 5 proposal 370 makes
  `actor_category_type_definition.definition` non-null.
- Re-running frozen proposal 190 afterward attempts a reference-data seed
  insert that omits `definition`.
- PostgreSQL enforces the non-null column before proposal 190's `ON CONFLICT`
  handling can make that insert idempotent, so the repeated manifest run fails.
- Frozen proposals 190–350 must remain unchanged at this checkpoint.
- The schema owner must resolve this through migration ordering, a superseding
  migration, or the final rollout design before Architecture V2 migration
  acceptance.
- This is an explicit unresolved acceptance item. It must not be silently
  worked around, and the final idempotency acceptance requirement must not be
  weakened.

Both repository read-only smokes passed against the isolated copy with 965
actors.

## 8. Validation

- Backend full suite without live schema contracts: **367 passed, 5 skipped**,
  with 2 inherited SQLite adapter warnings.
- Backend full suite on `ghus_v2_test`: **369 passed, 3 failed**, with 2
  inherited SQLite adapter warnings. The three failures are the approved gates:
  physical `actor_type` removal, physical `verification_status` removal, and
  the deferred `verify_actor` review CHECK. The schema-contract subset was
  **10 passed, 3 failed**.
- Focused Phase 3/4/5/6 and schema set: **82 passed, 5 skipped**.
- Frontend/RAG Python suite: **56 passed**, 15 subtests passed, with 1 inherited
  Starlette/AnyIO warning.
- Frontend Node hub/map suite: **15 passed**.
- Backend and frontend read-only isolated-database smokes: passed, 965 actors.
- Phase 6 proposal 020: `up → down → up` passed.
- Existing canonical row counts: unchanged.

## 9. Deferred dependencies

- P7 may reuse the center primitive, but owns cluster discovery, family and
  category criteria, repeated extraction, naming, and proposals.
- P12 owns real hub topic mapping, eligible status/geography resolution, center
  population, the final membership backfill, and deferred proposal 400.
- P15 owns review authorization UI.
- P16 owns the final physical legacy-column cutover and matching readers.

The three approved schema gates remain failing by design. No new runtime or
architecture blocker was introduced by Phase 6; the inherited full-manifest
idempotence limitation is documented above.
