# Decisions only GHUS can make

Nothing below was decided by an agent. The rehearsal used clearly labelled
TEST-ONLY stand-ins, only in a local `*_rehearsal_test` database.

| # | Decision | Input | Blocks | How it is recorded |
|---|---|---|---|---|
| 1 | Confirm or change the proposed category of **58** real organizations whose legacy value could not be mapped | `docs/evidence/phase12_category_proposals.csv` (model: claude-haiku-4-5, existing evidence only, no web fetch) | 495 → 500 | Review page → "Category reviews" panel (bulk) or per record; writes `review_item_decision` + `actor` through `decisions.record_category_review_decision` |
| 2 | Disposition of **156** collections of organizations (e.g. "Water Treatment Companies"): convert to a network parent, or keep as a legacy collection excluded from actor views. **146** of them hold **180** of the 821 hub memberships | `docs/evidence/phase12_aggregate_disposition_proposal.csv` (`ghus_decision` column) | 495 → 500 | needs a GHUS-approved rule; either option still has to give each row an `actor_category` for 495 |
| 3 | Approve the controlled topic list and hub topics: 8 topics 1:1 from legacy sectors (CROSS and DIASPORA held back), 48 hub topics and density centers | `docs/evidence/phase12_topic_proposal.csv` | 486 → 405 | `topic_approval.json` (SHA-256 of the CSV), then `apply topic` |
| 4 | The empty hub "Mining Hubs": no sector, members, city or coordinates | — | 405 | assign a topic and a center, or retire the row (a retirement path does not exist yet) |
| 5 | Approve 405 instead of 400: legacy memberships keep NULL `source_id` and NULL `outside_radius` when unknown (inventing either is not allowed) | `migrations/proposed/deferred/405_v2_hub_contract_phase12.sql` | 405 | schema-owner approval |
| 6 | Approve keeping `record_verification` for person/event decisions until Phase 14 (contract §7 said DROP; dropping it would break event verification) | 500 | 500 | schema-owner approval |
| 7 | Accept that `actor_topic` stays empty at cutover (membership is not topic evidence; Light Pull fills it with sources) | contract | — | GHUS acknowledgement |

Also for GHUS information (no decision needed): 42 legacy hierarchy rows had no
source, so they are `relationship_review` items, not edges; 154 actors have a
`geocode_failed` review (57 no city, 51 outside the US, 41 city not in the Census
gazetteer, 5 unrecognized state); 55 scalar values of the 7 actors without a legacy source and 10 values of the
2 profiles without a legacy source are kept only in `legacy_migration_record`.
