# Architecture V2 Phase 12 corrected dry run and isolated proof

Date: 2026-10-06
Read-only source: `ghus_v2_phase12_report_test`
Isolated migration proof: `ghus_v2_phase12_policy_test`, PostgreSQL 17.5
Production: untouched

Evidence:

- `docs/evidence/phase12_dry_run_2026-10-06.json`
- `docs/evidence/phase12_policy_backfill_proof_2026-10-06.json`
- `docs/evidence/legacy_to_v2_mapping_matrix_2026-10-06.json`
- `docs/evidence/pre_cutover_data_loss_audit_2026-10-06.json`

## Corrected GHUS policy

The 965 actors already present in the canonical GHUS database migrate as
Verified. This is an explicit migration policy, not an inference from mutable
legacy status. Each receives an `existing_canonical_migration` bootstrap event
with no named reviewer, no fabricated historical decision timestamp, and a
recorded migration batch/time.

Legacy actor-category semantics map deterministically to the 12 V2 categories.
Category type remains nullable and is populated later through the Phase 5
type-only enrichment path. Missing type alone creates no review item. A migrated
Verified actor still needs an exact actor/topic `ghus_review` event for Deep
Pull; its topic-null bootstrap event does not authorize collection.

## Baseline invariants

- Actors: **965**
- Hubs: **49**
- Historical memberships: **821**
- Events: **356**
- All counts remained unchanged.

## Actor/category results

- Existing actors mapped to `status=verified`: **965**
- Existing actors mapped to `source_origin=imported_phase1`: **965**
- Legacy categories mapped deterministically: **751**
- Category review required: **214**
- Category types populated: **0**
- Category types pending later enrichment: **965**

The 214 unmappable category values are 187 `aggregate`, 13 `other`, 12 blank,
and 2 generic `Organization` values. They remain preserved in the migration
audit and review payload. No category is guessed.

## Geography and topics

- Coordinate pairs present: **0**; missing: **965**
- City missing: **59**; country missing: **32**
- Controlled state and region codes missing: **965** each
- Rows eligible for later deterministic lookup: **906**
- Actor-topic rows: **0**

No coordinate, region, or topic was invented.

## Aggregates and relationships

Of 187 aggregates, name-token triage finds eight plausible networks/consortia,
one likely mistag (`MIT Lincoln Laboratory`), and 178 unresolved cases. This is
informational only.

The copy contains zero `organization_hierarchy` rows and zero typed edges. No
relationship, cycle, or relationship provenance can be reconstructed from it.

## Hubs

All **49 hubs** and **821 GHUS memberships** remain unchanged. Every hub retains
the legacy 200-mile radius. None has a controlled topic/center, and memberships
lack topic/distance/source evidence. Geography may later add an informational
outside-radius flag but can never remove a GHUS membership.

## Facts and provenance

The copy has zero usable `actor_fact`, `actor_profile`,
`actor_capability_fact`, and `source` rows. Legacy scalar content remains:
descriptions 957, technical focus 961, approach 960, activities 965, IP notes
953, constraints 955, funding summaries 952, and estimated TRL 67.

Although 958 actors carry non-null source IDs, their referenced source rows are
absent. Scalar values must be appended later as Imported historical facts with
honest baseline migration provenance and no fabricated URL or retrieval date.
This outstanding work is why the data-loss audit correctly reports **failed**.

The audit has 20 object-level checks; 10 are currently blocking cutover:

- 958 non-null legacy status rows still need explicit preservation in the V2
  status/event/audit representation;
- 912 legacy state values still need deterministic state-code normalization;
- eight scalar fields still need append-only Imported fact-ledger preservation:
  `primary_technical_focus` (961 rows), `technical_approach` (960),
  `current_activities` (965), `technology_ip_notes` (953),
  `key_constraints` (955), `funding_summary` (952), `estimated_trl` (67), and
  `primary_lifecycle_role` (965).

Migration 500 cannot drop any of these sources until every corresponding audit
check passes and an independent cutover attestation is recorded.

## Events and review workload

All **356 events** remain, including **281 null-host events**. No organizer edge
is inferred.

Corrected proposed review workload:

- `verify_actor`: **0**
- `category_doubt`: **214**
- `geocode_failed` for insufficient legacy location: **59**
- `hub_needs_review`: **49**
- Total: **322**

## Cutover state

The category/status backfill proof passed in the isolated policy database.
Migration 500 remains locked because `pre_cutover_data_loss_audit` has not
passed or been independently attested. No Supabase DDL or data write occurred.

## Validation completed

- Phase 12 classification, Deep Pull, policy, and live isolated-backfill tests:
  **44 passed**.
- Phase 3-11 integration regression, with the application URL deliberately set
  to an unreachable address and the guarded V2 URL set to local PostgreSQL:
  **5 passed**. The integration harness now creates its sessions directly from
  the guarded `localhost:55432/*_test` URL.
- Full backend suite, with target and policy connections pinned to isolated
  local databases: **493 passed, 2 intentionally failing, 0 skipped**, with two
  unrelated SQLite datetime-adapter deprecation warnings. The intentional
  failures remain the final-schema checks for physical removal of `actor_type`
  and `verification_status`/transitional status columns.
- Shared frontend/RAG Python suite: **136 passed, 1 skipped, 30 subtests
  passed**. Shared Node suite: **23 passed**.
- Ruff and Python compilation checks passed. The migration ledger re-run
  skipped 480 and 490 by identical checksum.
- Migration 500 was executed only against the isolated policy database and
  failed closed with `pre_cutover_data_loss_audit has not passed`.

The separate additive-package gate for the Phase 3 `verify_actor` insert also
remains intentionally unmet: the production-compatible existing
`review_item` CHECK still excludes that kind. The isolated functional manifest
contains its test-only review-kind bridge; the frozen 180-350 production apply
package remains unchanged.
