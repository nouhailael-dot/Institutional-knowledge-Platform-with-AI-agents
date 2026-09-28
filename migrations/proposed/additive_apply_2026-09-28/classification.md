# Architecture V2 original 16-migration classification

This classification covers logical migrations 001–016 only. Logical migration 017 (`350_v2_record_creation.sql`) was added in Phase 3 and is deliberately outside this requested package.

`ADDITIVE` means the packaged portion adds only new tables, nullable columns, indexes, views/functions/triggers supporting new objects, or reference rows. `BREAKING` means the original operation renames/drops legacy columns, adds `NOT NULL` or constraints to populated tables, changes permissions/RLS on legacy tables, or otherwise changes an existing read/write contract.

| ID | Original migration | Classification | Additive package content | Deferred breaking content / dependency |
|---|---|---|---|---|
| 001 | `190_v2_reference_data.sql` | ADDITIVE | Five new reference tables and seed rows. | None. |
| 002 | `v2a01_actor_identity.py` + `200_v2_actor_location.sql` | MIXED, SPLIT | New nullable actor columns; `actor_category` and `record_status` mirror legacy columns through compatibility triggers; indexes; new `actor_location`. | Actor/status renames; `NOT NULL`/defaults; FKs/checks on `actor`; later legacy-column drop. P5 classifier + P12 backfill; rename/drop only after P16 readers are deployed. |
| 003 | `210_v2_topics.sql` | ADDITIVE | New `topic` and `actor_topic` tables and index. | None. |
| 004 | `v2a02_hubs.py` + `220_v2_hub_center_review.sql` | MIXED, SPLIT | New nullable `hub`/`hub_actor` columns, indexes, and new center-review table. | `NOT NULL`/defaults and FKs/checks on populated hub tables. P6 implementation + P12 backfill/validation. |
| 005 | `230_v2_verification_history.sql` | ADDITIVE | New append-only verification table, function, trigger, and index. | None. |
| 006 | `240_v2_fact_ledger.sql` | ADDITIVE | New fact/resolution tables, indexes, triggers, and current view. | None. |
| 007 | `250_v2_edges.sql` | ADDITIVE | New edge table, indexes, append-only trigger, descendant view. | None. |
| 008 | `260_v2_collection_runs.sql` | ADDITIVE | New request/run/document tables and index. | None. |
| 009 | `270_v2_rankings.sql` | ADDITIVE | New ranking table and append-only trigger. | None. |
| 010 | `v2a03_people.py` + `280_v2_people_privacy.sql` | MIXED, SPLIT | Nullable `person.record_status` and `source_origin`; legacy status sync trigger; two new privacy/topic tables. | Status rename, `NOT NULL`/default, and person constraints. P14 people policy/implementation + P12 backfill; rename after P16 cutover. |
| 011 | `v2a04_events.py` + `290_v2_event_evidence.sql` | MIXED, SPLIT | Nullable event columns and new event topic/claim tables. | `NOT NULL`/defaults and FKs/checks on populated `event`. P14 events + P12 backfill. |
| 012 | `300_v2_strategic_connections.sql` | ADDITIVE | Two new strategic-connection tables and append-only trigger. | None. |
| 013 | `310_v2_hub_proposals.sql` | MIXED, DEFERRED ENTIRELY | New child tables are additive in isolation, but are not in the current apply package because their required `proposed_hub` root is absent on production. | Alterations, defaults, checks, FKs, and unique index on the expected root are breaking; migration 180 prerequisite is also absent. P7 detector/model + P15 review workflow, then P12 data checks. |
| 014 | `320_v2_review_items.sql` | ADDITIVE | New review and decision tables, index, append-only trigger. | None. |
| 015 | `330_v2_guards_and_audit.sql` | MIXED, SPLIT | New audit table/index/trigger and RLS/grants limited to the newly added `record_verification` table. | Revokes and column privileges on existing `actor`, `hub`, `event`, `person`, and `hub_actor`. P15 service/UI cutover and role audit. |
| 016 | `340_v2_compatibility_views.sql` | MIXED, REWRITTEN | New views compiled against the still-present legacy columns plus nullable V2 aliases. | The original view text assumes completed actor/status renames. Switch to the final view definitions only after P5 and P16 deployment. |

## Deferred breaking order

1. **P5 → P12:** deploy category/type code, backfill canonical category/type, add `NOT VALID` actor constraints, validate, then add required defaults/`NOT NULL` where proven safe.
2. **P6 → P12:** deploy hub logic, backfill hub/member fields, add and validate hub FKs/checks, then add defaults/`NOT NULL` where required.
3. **P7 → P15:** deploy the review-admission prerequisite/root, migrate hub proposals losslessly, deploy the detector and Review UI, then apply migration 310 constraints/indexes.
4. **P11 → P12:** deploy immutable fact resolution and complete backfills before validating actor/status/source constraints.
5. **P14 → P12 validation:** deploy people/events behavior, backfill status/origin/date fields, then apply person/event constraints and requiredness.
6. **P15:** after all callers use approved services, apply existing-table RLS/grant/revoke changes from migration 330.
7. **P16 final cutover:** deploy final RAG/Explore readers, replace compatibility views with the final renamed-column definitions, rename/drop legacy `actor_type` and `verification_status` only after compatibility telemetry is clean.

No deferred file is included in the executable additive manifest.
