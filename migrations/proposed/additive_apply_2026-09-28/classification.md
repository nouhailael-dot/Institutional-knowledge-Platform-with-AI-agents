# Architecture V2 additive/deferred classification: agents/sql 180–350

Prepared 2026-09-29 against the restored production schema. `ADDITIVE` here means a new table, nullable column, index, reference row, or support object that does not change an existing application contract. Constraints/defaults/requiredness, existing-table RLS or grants, renames/drops, and the final actor/status cutover are deferred.

Production already contains the 010–160 objects required by 180. File 170 has one drift item: `person_discovery_profile.affiliation_raw`, `person_discovery_profile.needs_actor_enrichment`, `person_review_queue.affiliation_raw`, and `ix_person_discovery_profile_actor_enrichment` are absent. The package adds the three columns as nullable plus the index; `needs_actor_enrichment DEFAULT false NOT NULL` is deferred.

| File | Class | Executable additive portion | Deferred breaking portion and dependency |
|---|---|---|---|
| 180 review admission | MIXED | New `proposed_hub` and `review_admission_decision`; nullable review columns; indexes. | Existing-table default/`NOT NULL` and replacement status CHECKs. Review callers + backfill, P3/P15. |
| 190 reference data | ADDITIVE | Five new definition tables and initial rows. | None. |
| 200 actor/location | MIXED | Nullable actor V2 columns, non-raising compatibility functions/trigger, indexes, `actor_location`. | Requiredness/defaults/FKs/CHECKs P5→P12; legacy actor/status retirement P16. |
| 210 topics | ADDITIVE | New topic/membership tables and index. | None. |
| 220 hubs | MIXED | Nullable hub/member columns, indexes, new center-review table. | Defaults/requiredness/FKs/CHECKs P6→P12. |
| 230 verification | ADDITIVE | New append-only verification table/function/trigger/index. | None. |
| 240 facts | ADDITIVE | New fact and resolution ledger, triggers, indexes, current view. | None. |
| 250 edges | ADDITIVE | New sourced-edge table, trigger, indexes, descendant view. | None. |
| 260 collection runs | ADDITIVE | New request/run/document tables and index. | None. |
| 270 rankings | ADDITIVE | New ranking table and append-only trigger. | None. |
| 280 people/privacy | MIXED | Nullable person status/origin, safe compatibility trigger, new privacy/topic tables. | Requiredness/defaults/FKs/CHECKs P14→P12; status retirement P16. |
| 290 events/evidence | MIXED | Nullable event V2 columns and new event topic/claim tables. | Requiredness/defaults/FKs/CHECKs P14→P12. |
| 300 strategic connections | ADDITIVE | Two new tables and append-only trigger. | None. |
| 310 hub proposals | MIXED | Nullable root extensions, unique index, new member/decision tables and new-table trigger. | Root default/`NOT NULL`, FKs and CHECKs P7+P15→P12. |
| 320 review items | ADDITIVE | New review item/decision tables, index and trigger. | None. |
| 330 guards/audit | MIXED | New audit table/index/trigger and RLS/grants only on package-created `record_verification`. | Existing canonical-table revokes/column privileges P15. |
| 340 compatibility | MIXED, REWRITTEN | Legacy-safe views while `actor_type` and `verification_status` remain. | Final V2-only views and actor/status cutover P16. |
| 350 record creation | MIXED | Three new source-origin rows. | Existing `review_item` CHECK replacement for `verify_actor`, deployed with P3 runtime. |

Exact held statements and dependencies are recorded under `deferred/`. That directory deliberately has no runner.

## Later breaking order

1. P3 runtime and deferred 350 CHECK together.
2. P5 actor classifier, then P12 actor backfill/validation.
3. P6 hubs and P7 hub proposals, then P12 hub validation; retain all GHUS memberships.
4. P14 people/events, then P12 backfills and constraints.
5. P15 Review/service-role cutover, then deferred 180/330 contract and permission changes.
6. P16 readers, then final 340 views and legacy `actor_type`/`verification_status` retirement.
