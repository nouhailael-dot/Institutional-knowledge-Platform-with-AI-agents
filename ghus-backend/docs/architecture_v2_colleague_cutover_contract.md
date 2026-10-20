# Architecture V2 application cutover contract

This is the application-facing contract for the coordinated backend switch.
The old names remain only during expand/backfill; they disappear in superseding
migration 500 after both applications pass the V2 test database and the
pre-cutover data-loss audit is attested.

| Old usage | New usage | Type / join | Cutover |
|---|---|---|---|
| `actor.actor_type` / flat `actor_category` values | `actor.actor_category` | text, one of 12 controlled codes | backfill then switch; old disappears |
| no second level | `actor.category_type` | nullable text; when present join `(actor_category,category_type)` to `actor_category_type_definition` | enriched later; null is valid at initial cutover |
| no doubt metadata | `category_note`,`category_needs_review` | text, boolean | use directly |
| `actor.verification_status` or `record_status` | `actor.status` | `imported|parked|verified|rejected`; existing canonical actors bootstrap as Verified | old disappears |
| direct status UPDATE | insert through GHUS verification service | `actor_verification_event`; rejection needs reason | direct write forbidden |
| `alternate_names` | `alt_names` | text[] | renamed by 500 |
| `location_city`,`state` | `city`,`state_code` | text; state joins `region_state` | raw state disappears |
| actor scalar enrichment columns | `actor_read` view (488) for the migrated baseline values; `actor_fact_current_v2` for topic facts | baseline values are topic-null `legacy_baseline` facts on the actor's real legacy source | scalar columns disappear |
| historical enrichment | `actor_fact_history` | filter actor/topic/key, ordered by creation | new query |
| hierarchy table / implicit parent | `entity_edge` | typed edge with source, confidence, optional topic; the 42 unsourced legacy rows are `relationship_review` items, not edges | legacy hierarchy disappears |
| recursive hierarchy query | `actor_descendants` | root, descendant, depth/path | use view |
| unscoped actor relevance | `actor_topic` | join actor→actor_topic→topic; **empty at cutover** (membership is not topic evidence); hub topic is on `hub_actor.topic_id` | filled by Light Pull with sources |
| `hub_actor` without evidence | `hub_actor` plus topic/distance/outcome/source | same PK `(hub_id,actor_id)`; join hub topic; legacy rows are `legacy_membership_preserved` and may have NULL `source_id`, and NULL `outside_radius` when the member has no coordinates (405) | table remains, columns required for new assignments |
| hub city/lat/lon as informal center | hub `center_*`, `radius_miles`, `center_frozen`, method/audit fields | direct fields; memberships retain outside-radius flag | switch after hub backfill |
| multiple review queues/bridge kinds | `review_item` / `review_item_decision` | canonical kind enum and JSON payload | bridges converted before CHECK validation |
| direct collection without audit | `collection_request`→`collection_run`→`fetched_document` | request kind includes Light, Deep, Specific Ask | required for new jobs |
| read every `actor_fact` row | `actor_fact_current_v2` by default | history is separate | immediate after expand |

Queries to rewrite:

1. Actor list/detail/filter SQL: select `actor_category`, `category_type`,
   `status`, `source_origin`, `city`, `state_code`, `region_code`; stop selecting
   legacy category/status/location names.
2. Verification actions: call the GHUS verification service; never update actor.
3. Actor profiles/RAG: join current facts and their sources; label Imported and
   Parked as unverified.
4. Topic pages/search: join through `actor_topic`; do not infer topic from sector.
5. Relationships: use `entity_edge` and `actor_descendants`, always retain source.
6. Hubs: join `hub_actor.topic_id=hub.topic_id`, expose assignment outcome,
   distance and outside-radius informational state.
7. Review: use only canonical kinds; display fact conflict/pending-update history.
8. Writes: actor/fact/edge writes go only through the approved promotion/decision
   service; DELETE of canonical actors, facts, verification events and evidence
   is not an application operation.
9. Existing-actor type enrichment: pass the migrated `actor_category` to the
   type-only classifier; never ask it to casually reclassify category.
10. Deep Pull: require an exact actor/topic GHUS review event. Actor status alone,
    including migration-origin Verified, is insufficient.

Phase 12 additions:

- Read actors through `actor_read` (migration 488). It exposes the final names
  (`city`, `state_code`, `region_code`, `status`, `alt_names`) plus the migrated
  narrative fields, and stays valid before and after 500. Raw-table readers must
  be schema-neutral until 500 has run (see `src/browse.py` in the shared repo).
- `record_verification` stays for person and event decisions until the Phase 14
  conversion; it can no longer hold actor rows.
- GHUS confirms migrated categories in Review (`confirm_category`, single or bulk).
  The 156 collections of organizations need a separate GHUS disposition.
- New actors must carry a validated category: `actor_category` is NOT NULL after 500.
- Ask documents label every actor with its status.

Development can begin against checkpoint `phase12_topic_policy`. Release against
the clean contract waits for Phase 12 backfill, constraint validation, both-app
E2E, schema-owner approval, backup verification, passed data-loss audit and
coordinated migration 500.
