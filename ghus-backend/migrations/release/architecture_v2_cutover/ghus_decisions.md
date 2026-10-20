# GHUS decisions (recorded 2026-10-06, approved by Ismail Sabbar)

| # | Question | Decision | Applied by |
|---|---|---|---|
| 1 | 58 proposed categories for real organizations | **Confirmed** | 491: category reviews resolved, `review_item_decision` recorded |
| 2 | 156 collections of organizations ("aggregate") | **Dropped**: GHUS rejection event per actor (status `rejected`), their 180 hub memberships archived in `hub_actor_removed` and removed. The actor rows stay because append-only ledgers (bootstrap events, migration audit, facts) reference them; every reader and `actor_read` excludes rejected actors | 491 |
| 3 | Topics | Hub topics approved as proposed (8 topics from legacy sectors, 48 hubs, density centers recomputed after decision 2). **Actor topics are left to Light Pull enrichment** (`actor_topic` needs a source) | 486 + `docs/evidence/phase12_topic_approval.json` |
| 4 | Empty "Mining Hubs" (no sector, members, location) | **Retired**: archived in `hub_removed`, row removed | 491 |
| 5 | 405 instead of 400; keep `record_verification` for person/event; drop the sync trigger in 500; `*.sql` LF rule | **Approved** | release manifest |

Consequences: 809 verified actors (732 live after merges), 156 rejected; 48 hubs;
641 memberships; 214/214 category reviews resolved. `ck_actor_category_complete`
(495) requires a category for every actor except GHUS-rejected ones.

Still pending as normal review work (not cutover blockers): 154 `geocode_failed`,
42 `relationship_review` (unsourced legacy hierarchy).
