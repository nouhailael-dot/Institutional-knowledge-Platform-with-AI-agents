# Colleague change note — Architecture V2 additive 180–350

This package adds new V2 reference/ledger/review/collection tables, nullable compatibility columns, indexes/views, the review-admission `proposed_hub` root, hub-proposal child tables, and three Phase 3 source-origin definitions.

It does **not** rename or drop columns, add required fields/constraints/defaults to legacy production tables, change RLS/grants on legacy canonical tables, or enable `verify_actor` in the existing review-item CHECK. `actor_type` and `verification_status` remain present and legacy reads/writes continue to work. Unmapped actor types remain null in `actor_category`; legacy statuses never map to V2 `verified` or `rejected`.

The branch must not merge to `main` and Phase 3 new-actor creation must not deploy until the deferred 350 CHECK change and matching code are approved together.
