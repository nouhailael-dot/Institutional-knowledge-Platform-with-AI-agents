# Deferred Architecture V2 package (not executable)

This directory is the held-back half of the 170–350 classification. It has no runner by design. Every item below changes an existing table contract and must ship only with the named code phase, a reviewed backfill/validation plan, and fresh schema-owner approval.

| Source file | Deferred breaking statements | Required dependency/order |
|---|---|---|
| 170 | Backfill `person_discovery_profile.needs_actor_enrichment`, add default `false`, then set `NOT NULL`. | P14 people code → P12 backfill/validation. |
| 180 | Backfill `search_candidate.review_status`, add default/`NOT NULL`; replace status CHECKs on `search_candidate`, `event_review_queue`, and `person_review_queue`. | Review callers support `deferred`; backfill before constraint replacement; P3/P15. |
| 190 | None. | — |
| 200 | Actor defaults/requiredness and FKs/CHECKs; later remove compatibility trigger and retire `actor_type`/`verification_status`. | P5 → P12; final rename/drop only in P16. |
| 210 | None. | — |
| 220 | Hub/member defaults, `NOT NULL`, FKs, and CHECKs on populated `hub`/`hub_actor`. | P6 → P12. No existing GHUS membership is removed. |
| 230–270 | None. | — |
| 280 | Person status/origin defaults, requiredness, FKs/CHECKs, and later `verification_status` retirement. | P14 → P12; final cutover P16. |
| 290 | Event status/origin/date defaults, requiredness, FKs/CHECKs. | P14 → P12. |
| 300 | None. | — |
| 310 | `proposed_hub.proposal_kind` default/`NOT NULL`; root-table topic/final-hub FKs and kind/radius/core/count CHECKs. | P7 detector + P15 Review UI → P12 validation. |
| 320 | None. | — |
| 330 | Revokes and column privileges on existing `actor`, `hub`, `event`, `person`, and `hub_actor`. | P15 caller/service-role cutover and role audit. |
| 340 | Replace compatibility views with final V2-only definitions; retire legacy actor/status columns and compatibility triggers. | P16 after all readers are deployed and telemetry is clean. |
| 350 | Drop/replace the existing `review_item` kind CHECK to admit `verify_actor`. | P3 runtime deployed together with this change. |

Exact source statements remain in `agents/sql`, `agents/sql/rollback`, and `migrations/proposed/versions`. Before later execution they must be re-generated as backfill-aware, reversible migrations; the original detached proposals are not an apply package.
