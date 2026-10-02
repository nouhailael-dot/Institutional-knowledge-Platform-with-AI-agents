# Architecture V2 Phase 7 report — New-hub detection

Date: 2026-10-01

Backend repository: `C:\Users\Ismail\Projects\GHUS-Platform`

Backend branch: `codex/architecture-v2`

Starting backend checkpoint: `2adfa93f3864e318be1e51b1204e8d7979964d65`

Frontend/RAG validated branch: `codex/architecture-v2` at `44376e1a87eeaea10ba866187fb91e5749d5c75b`

## 1. Scope and safety boundary

Phase 7 implements new-hub detection and proposal decisions only. Production
was not contacted or modified. No canonical hub is ever created by the
detector or decision service. Canonical membership writes are disabled unless
explicitly requested and, when enabled, delegate to the Phase 6 canonical
writer in `agents/discovery/promote.py`.

The frozen 180--350 additive package, teammate-owned Agent 3, all 821 legacy
memberships, and the three intentionally deferred schema gates are unchanged.
Phases 8, 9, 12, 15, and 16 were not started.

## 2. Eligible pool and family resolution

Detection runs per controlled topic. The default pool contains only Verified,
unmerged, non-aggregate actors with deterministic city coordinates, complete
category/type classification, and no assigned membership on that same topic.
Memberships on other topics do not exclude an actor. Imported actors are
reported in a separate comparison computed from the same snapshot; they do not
trigger the default result.

Family ancestry uses only sourced V2 `entity_edge` rows whose relationship is
`unit_of` or `operated_by`. Legacy `organization_hierarchy` and inference from
names, domains, categories, locations, sectors, membership, or narrative text
are never consulted. No qualifying parent means the actor is its own family.
Cycles, multiple roots, and ambiguous qualifying ancestry fail closed and are
reported in `unresolved_hierarchy`.

## 3. Center, cluster, matching, and repeat behavior

For each fixed working pool, candidate cities are ranked by:

1. independent families represented within 50 miles, descending;
2. mean raw actor distance within 200 miles, ascending;
3. normalized city, state, and coordinates for deterministic ties.

The candidate cluster contains every pool actor within the configured radius.
Its category diversity is a deterministic maximum-cardinality bipartite
matching between independent families and the categories represented by that
family's cluster members. Both the matching size and stable family/category
pairs are retained as evidence.

A candidate that fails either threshold removes nothing; later ranked centers
are still evaluated against the same pool. Actors leave the pool only after a
proposal, an existing family-fingerprint suppression, or routing to a trusted
same-topic hub. Centers are recomputed after every terminal removal. The
explicit highest-ranked-fails/later-center-passes and two-cluster fixtures pass.

## 4. Fingerprints and proposal evidence

The membership fingerprint is SHA-256 over only the sorted set of top-level
family IDs. Topic is the separate uniqueness dimension. Actor/unit order,
additional units in an existing family, center, and algorithm version do not
affect the fingerprint. Fingerprint and method versions are stored separately.
Any prior deterministic-cluster proposal, including a rejected one, suppresses
the unchanged family set. A changed family set can be reconsidered.

Each proposal reuses `proposed_hub` and stores its topic, suggested name,
center, 50/200-mile radii, raw member distances, category/type/family evidence,
family count, maximum-matching count and pairs, independence statement,
configuration snapshot, method/fingerprint versions, and detection run.
Historical legacy proposal rows are preserved.

## 5. Existing hubs and decisions

Only a hub with controlled same-topic identity, deterministic center, and
usable radius can suppress a proposal. Missing values on the current 49 hubs
are never inferred. A covered candidate routes its actors through the Phase 6
assignment planner. The detector contains no direct `hub_actor` write.

The decision service is dry-run by default and supports approve, rename,
reject, and radius decisions. Decisions append to `proposed_hub_decision`.
Under the production-compatible bridge, status remains
`pending/accepted/rejected`; deferred proposal 410 converts Phase 7 rows to
`open/approved/renamed/rejected`. Neither path creates a canonical hub. A
canonical hub still requires the later GHUS-controlled workflow.

## 6. Schema proposals

Logical proposal 021, `390_v2_hub_detection.sql`, is outside the frozen
180--350 package. It adds a `hub_detection_run` ledger and nullable evidence
columns to the existing proposal/member tables. It changes no canonical table,
legacy query, grant, RLS rule, or membership.

Deferred proposal 410 is breaking and schema-owner-only. It replaces proposal
310's fixed 10/5/50 contract with the stored runtime thresholds, enforces Phase
7 member evidence, and converts only marked Phase 7 status rows to the final
status vocabulary. Its rollback converts only canonical-contract rows, strips
its marker, and refuses a lossy rollback of a renamed row or any row that the
frozen contract cannot represent. Frozen 180--350 remains unchanged.

## 7. Isolated PostgreSQL proof

Local PostgreSQL 17.5 database `ghus_v2_test` at `127.0.0.1:55432` was used.
Proposal 390 completed `up -> down -> up`. Existing canonical counts stayed:

| Table | Rows |
|---|---:|
| `actor` | 965 |
| `hub` | 49 |
| `hub_actor` | 821 |
| `event` | 356 |

A separate disposable clone, `ghus_v2_phase7_test`, supplied ten controlled
synthetic actors across five categories. Dry and live runs both computed one
identical candidate; dry wrote zero rows. Live wrote one run, one proposal, and
ten proposal members while hub and membership counts remained 49 and 821.
Approval changed only proposal/decision rows. Deferred 410 completed exact
status `up -> down -> up` (`approved -> accepted -> approved`) without a
canonical hub or membership write.

The production-copy prerequisite audit is intentionally non-demonstrative:

| Prerequisite | Available rows |
|---|---:|
| Actors | 965 |
| Controlled actor-topic mappings | 0 |
| Authoritative `unit_of` / `operated_by` edges | 0 |
| Verified actors | 0 |
| Imported actors | 97 |
| Complete category/type classifications | 0 |
| Deterministically geocoded actors | 0 |
| Trusted topic/center/radius hubs | 0 |

Accordingly, the real-copy dry run produced zero eligible actors and zero
proposals. P8 supplies authoritative graph writers; P12 owns existing-data
topic/classification/status/geography/hub backfills.

## 8. Validation

- Phase 7 planned detector matrix: **42 passed**.
- Phase 7 service/decision checks: **9 passed** (**51 focused checks** including
  the 42-case matrix); the canonical-writer boundary audit also passed.
- Phase 3--7 regression selection: **133 passed, 5 skipped**.
- Complete backend suite without live schema contracts: **418 passed, 5
  skipped**, with 2 inherited SQLite adapter warnings.
- Complete backend suite on `ghus_v2_test`: **420 passed, 3 failed**, with 2
  inherited SQLite adapter warnings. The failures are exactly the approved
  physical `actor_type` gate, physical `verification_status` gate, and deferred
  `verify_actor` review CHECK.
- Frontend/RAG `codex/architecture-v2` Python suite from a clean archive: **56
  passed, 15 subtests passed**.
- Frontend/RAG Node hub/map suite: **15 passed**.
- Backend and frontend credential-safe read-only database smokes: passed with
  965 actors.
- Ruff and `git diff --check`: passed.

The active frontend worktree had independently moved to
`integration/background-work`; it was neither switched nor modified. Phase 7
frontend validation used a clean temporary archive of the preserved
Architecture V2 commit.

## 9. Intentional deferrals and known rollout issue

The three approved schema gates remain failing by design: final physical
removal of `actor_type` and `verification_status` belongs to Phase 16, and the
`verify_actor` CHECK expansion remains a deferred breaking migration.

The pre-existing 190/370 full-manifest idempotency conflict is unchanged:
proposal 370 makes `definition` non-null, then frozen 190 replays an insert that
omits it and fails before `ON CONFLICT`. Frozen 190--350 was not changed and the
acceptance requirement was not weakened. Migration ordering, a superseding
migration, or final rollout design must resolve it before Architecture V2
migration acceptance.
