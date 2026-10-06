# Architecture V2 definitive database contract

Date: 2026-10-06
Status: final target approved for isolated development; production deployment not authorized
Technical manifest: `docs/evidence/v2_target_schema_manifest_2026-10-06.json`

## 1. End-state rule

The production end state is clean Architecture V2. Compatibility views and
legacy columns exist only during expand/backfill/application-switch. Both
applications must switch before superseding contract migration 500 removes them.

The authoritative state is:

- actor identity/classification/status on `actor`;
- GHUS decisions in append-only `actor_verification_event`;
- controlled topics in `topic`/`actor_topic`;
- immutable actor values in `actor_fact` with one mutable pointer, append-only
  corroboration, and explicit current/history views;
- typed sourced relationships in `entity_edge`;
- topic-scoped hubs and memberships in `hub`/`hub_actor`, with immutable
  assignment evidence;
- one unified `review_item` queue;
- audited Light, Deep and Specific Ask requests/runs/documents.

## 2. Final actor contract

`actor` final columns are:

| Column | Type | Rule |
|---|---|---|
| `actor_id` | uuid | primary key |
| `name` | text | nonempty, required |
| `slug` | text | unique where retained by the base schema |
| `alt_names` | text[] | scalar aliases, default empty; GIN index |
| `actor_category` | text | required; FK to category definition |
| `category_type` | text | nullable during initial cutover; when populated, composite FK with category |
| `category_note` | text | required when type is `other` |
| `category_needs_review` | boolean | required, default false |
| `status` | text | `imported`, `parked`, `verified`, `rejected` |
| `source_origin` | text | controlled origin, required |
| `description` | text | concise identity description; detailed claims live as facts |
| `website` | text | display URL |
| `website_domain` | text | normalized exact-identity key; indexed lower-case |
| `country` | text | controlled/normalized country value |
| `state_code` | text | FK to `region_state` where US state applies |
| `city` | text | canonical city label |
| `region_code` | text | FK to `region_definition` |
| `latitude`,`longitude` | numeric(9,6) | nullable pair with range check |
| `is_multi_location` | boolean | required; details in `actor_location` |
| `ghus_notes` | text | human-only notes |
| `source_id` | uuid | nullable identity-source FK; field facts retain their own source |
| `confidence` | numeric(3,2) | legacy identity confidence only; not fact confidence |
| `merged_into_actor_id` | uuid | retained redirect/audit pointer |
| `created_at`,`updated_at` | timestamp | required audit timestamps |

Legacy narrative columns (`primary_technical_focus`, `technical_approach`,
`current_activities`, `technology_ip_notes`, `key_constraints`,
`funding_summary`, `estimated_trl`, `primary_lifecycle_role`) are migrated to
topic-scoped immutable facts, then removed from `actor`. `actor_type`,
`actor_type_raw`, `verification_status`, `record_status`, and free-text `state`
are removed at final cutover. `alternate_names` becomes `alt_names` and
`location_city` becomes `city`.

## 3. Verification and status

`actor.status` is a guarded projection, not an independent verification log.
The 965 actors already in the canonical GHUS database start `verified` under an
explicit GHUS migration policy. Their bootstrap event is marked
`existing_canonical_migration`, has no invented reviewer or historical decision
timestamp, and records only the migration time/batch. New imports set
`imported`; completed Light Pull sets `parked`. Only an authorized verification
event may move a post-V2 actor to `verified` or `rejected`.

`actor_verification_event` has UUID PK, actor FK, optional topic FK, decision
(`verified`/`rejected`), reviewer identity, timestamp, reason, required rejection
reason for rejection, and optional source FK. It is append-only. Direct UPDATE
or DELETE is rejected. Direct table INSERT is denied to anonymous, ordinary
authenticated, and agent roles; the GHUS review service is the sole writer.

Existing `record_verification` actor decisions are migrated once with their
identity/timestamp/reason, deduplicated by their original verification ID, then
the table is removed after both applications switch. Legacy mutable status is
never used to manufacture a named human decision. The separate migration-origin
event honestly records why an existing canonical actor starts Verified.

Actor-level Verified does not authorize Deep Pull. Deep Pull requires the
latest explicit `ghus_review` decision for the exact actor/topic pair; the
topic-null migration bootstrap is excluded by query and constraint.

## 4. Final table inventory

The machine-readable manifest records every proven column/type, PK, FK, UNIQUE,
CHECK, index, view, trigger, RLS policy and grant. The final ownership contract is:

| Object | Purpose and key contract | Canonical writer | Action |
|---|---|---|---|
| `actor_category_definition` | 12 categories; unique code/name/order | schema owner | KEEP |
| `actor_category_type_definition` | 65 `(category,type)` rows; one `other`/category | schema owner | KEEP |
| `source_origin_definition` | controlled origins | schema owner | KEEP |
| `region_definition`,`region_state`,`us_city_coord` | deterministic geography reference | schema owner | KEEP |
| `source` | immutable retrieval/source identity | approved writers | KEEP |
| `actor` | canonical organization identity and projected status | `promote.py`, `decisions.py`, verification projector | MIGRATE/CLEAN |
| `actor_location` | sourced multiple physical locations, one primary | approved writers | KEEP |
| `topic` | controlled topic identity | schema owner/GHUS | KEEP |
| `actor_topic` | sourced actor-topic match with strength/reason | approved writers | KEEP |
| `actor_verification_event` | append-only GHUS actor decisions | GHUS review service only | ADD |
| `actor_category_migration_audit` | immutable legacy-category mapping and prior-value audit | schema-owner migration only | ADD |
| `architecture_v2_cutover_attestation` | independently approved data-loss gate for contract migration | schema owner only | ADD |
| `actor_fact` | immutable topic/field value and provenance | `decisions.append_actor_fact` | KEEP |
| `actor_fact_current_pointer` | exactly one current row per actor/topic/key | fact writer only | KEEP |
| `fact_corroboration` | same-value additional provenance | fact writer only | KEEP |
| `fact_resolution` | append-only supersession/conflict decisions | fact writer/GHUS review | KEEP |
| `actor_ranking` | separately sourced ranking observations | fact/ranking writer | KEEP |
| `entity_edge_type_definition` | allowed directional/symmetric edge semantics | schema owner | KEEP |
| `entity_edge` | typed, sourced actor/person/event/hub relationships | `decisions.append_entity_edge` | KEEP |
| `hub` | topic, frozen center, radius, approval and Phase-1 definition | GHUS hub service | MIGRATE |
| `hub_actor` | final actor-hub membership keyed `(hub_id,actor_id)` and topic/source/distance/outcome | GHUS hub service | KEEP/MIGRATE |
| `hub_assignment_evidence` | immutable assignment calculations | hub assignment service | KEEP |
| `hub_center_review` | center-drift proposals | hub service/GHUS reviewer | KEEP |
| `proposed_hub`,`proposed_hub_member`,`proposed_hub_decision`,`hub_detection_run` | deterministic proposals and append-only review | detector; GHUS decision writer | KEEP |
| `review_item`,`review_item_decision` | unified queue and append-only decisions | approved jobs; GHUS reviewer | KEEP |
| `collection_request`,`collection_run`,`fetched_document` | Light/Deep/Specific Ask audit, budgets and fetch provenance | collection service | KEEP |
| `canonical_write_audit` | append-only canonical writer audit | approved writers | KEEP |
| `person`,`person_topic`,`contact_collection_authorization` | retained people model; discovery remains disabled | GHUS-authorized flows | KEEP |
| `event`,`event_topic`,`event_claim` | current event functionality and sourced topic/claims | event writer/GHUS | KEEP |

Current unrelated domain objects (`sector`, challenges, funding, scoring, merge
audit, and review-source staging) remain until their owning feature is migrated.
They are not alternate canonical V2 fact, edge, status, or review systems.

## 5. Views and derived access

- `actor_fact_current_v2`: current pointer joined to immutable fact; default for
  Review, Browse, Ask and RAG.
- `actor_fact_history`: every fact plus deterministic `is_current` flag.
- `actor_descendants`: recursive parent-family traversal using only permitted
  structural edge types and cycle prevention.
- Compatibility views `actor_v1_compat`, `staged_record_agent3_compat`, and the
  old scalar `actor_profile_current` are development/cutover aids and are dropped
  by migration 500.

No materialized “current” fact duplicates the authoritative value. The pointer
is the only mutable fact-lifecycle object; fact/evidence/history rows remain
append-only.

## 6. Final review kinds

The final CHECK admits exactly:

`verify_actor`, `category_doubt`, `geocode_failed`, `hub_needs_review`,
`hub_radius_overlap`, `hub_member_outside_radius`, `hub_center_drift`,
`hub_proposal`, `possible_duplicate`, `fact_conflict`, `pending_update`,
`verify_person`, `verify_event`, `identity`, `affiliation_change`.

Bridge rows migrate as follows: `classification` with
`payload.issue=category_doubt` becomes `category_doubt`; `geocode` becomes
`geocode_failed` only when its payload records an actual failed attempt;
`hub_assignment`/`same_topic_overlap`/`new_hub` map to the matching canonical
hub kinds; `pending_human_update` becomes `pending_update`. Unknown bridge rows
block CHECK validation and are never silently discarded.

## 7. Legacy disposition

| Legacy object | Final action |
|---|---|
| `actor.actor_type` | MIGRATE to `actor_category`; DROP at cutover |
| `actor.actor_type_raw` | export for audit; DROP at cutover |
| `actor.verification_status` / `record_status` | export prior values to `actor_category_migration_audit.prior_status`; map all 965 existing canonical actors to `status=verified` under the GHUS-decided migration policy (§3), each with an `existing_canonical_migration` bootstrap event (no named reviewer, no invented decision time); never synthesize named GHUS decisions; DROP |
| scalar actor narrative fields | MIGRATE as imported facts with baseline provenance marker; DROP after parity proof |
| `record_verification` | migrate only genuine actor GHUS decisions to `actor_verification_event`; DROP |
| `organization_hierarchy` | MIGRATE evidence-backed rows to typed `entity_edge`; unresolved rows review; DROP |
| `actor_profile`,`actor_capability_fact` | MIGRATE evidence-backed values to fact ledger; DROP |
| legacy review queues/bridge kinds | MIGRATE into `review_item`; retain owning staging queues only until writer cutover |
| `hub_actor` | KEEP as final membership table; enrich/backfill rather than duplicate |
| `actor_v1_compat`,`staged_record_agent3_compat` | temporary; DROP after both apps switch |

## 8. Constraint readiness

| Constraint | Readiness | Current blocker |
|---|---|---|
| category/type reference definitions | READY BEFORE BACKFILL | none |
| source-origin enum/FK | READY BEFORE BACKFILL | none for expanded schema |
| coordinate pair/range | READY BEFORE BACKFILL as `NOT VALID` | values not populated |
| append-only facts/events/resolutions/evidence | READY BEFORE BACKFILL | none |
| one current fact pointer | READY BEFORE BACKFILL | pointer backfill supplied by 430 |
| canonical review-kind CHECK | READY BEFORE BACKFILL as `NOT VALID` | bridge rows must convert before validation |
| `actor.status` allowed values | READY AFTER BACKFILL | all 965 receive policy-authorized `verified` through honest bootstrap events |
| actor category required | BLOCKED BY UNRESOLVED DATA | 751 map deterministically; 214 legacy values require category review |
| category/type composite FK when type exists | READY BEFORE BACKFILL as `NOT VALID` | null type is allowed; invalid non-null pair is rejected |
| category type NOT NULL | DEFERRED POLICY DECISION | all 965 are pending later AI type enrichment; not an initial-release gate |
| `other` requires note | READY AFTER BACKFILL | no final `other` decisions yet |
| actor topic completeness | BLOCKED BY UNRESOLVED DATA | 0/965 actors have controlled topic |
| hub topic/center/radius NOT NULL | BLOCKED BY UNRESOLVED DATA | 49 lack topic/center; radius exists |
| membership topic/source/distance | BLOCKED BY UNRESOLVED DATA | all 821 lack these fields |
| typed edge source requirement | READY BEFORE BACKFILL for new rows | legacy hierarchy has no rows/evidence in copy |
| final review-kind CHECK validation | READY AFTER BRIDGE CONVERSION | no current review rows in copy |

## 9. Migration chain

1. **Expand:** validated 180–350 package, 360–430 superseding proposals, then
   440 and policy correction 470. Legacy readers remain. Migration ledger stores ID/path/SHA-256 and skips
   a checksum-identical applied step.
2. **Backfill/report gate:** 480 maps deterministic legacy categories, marks the
   pre-existing canonical population Verified with honest bootstrap provenance,
   leaves category type nullable for later enrichment, and reviews only
   unmappable categories. Remaining topics, geography, facts, edges, hubs and
   membership work stays gated by the data-loss audit.
3. **Validate:** apply superseding 490 for status, optional type-pair and
   verification provenance. Apply 400/410 after hub blockers, then 495 only
   after all 214 category reviews resolve. This avoids a `NOT VALID` category
   check blocking unrelated status projections on unresolved actors.
4. **Switch both applications:** deploy backend, colleague backend, Review,
   Browse, Ask/RAG and jobs against final names/current views; rebuild search
   cache; run full E2E and read-only parity checks.
5. **Contract:** superseding 500 first requires a passed, independently attested
   `pre_cutover_data_loss_audit`, then renames `alternate_names`/`location_city`
   and removes only legacy columns/tables/views proven safely migrated.

Proposals 450 and 460 are retained for history but are superseded: 450/460
incorrectly required every migrated actor to have a category type, and 460 had
no data-loss-audit gate.

The 190/370 conflict is resolved without editing frozen 190: the ordered ledger
applies 190 before 370 exactly once and refuses checksum drift. Re-running the
complete manifest skips both bodies. This was proven on the isolated target,
then later migrations were rolled back where supported and reapplied.

## 10. Rollback boundary

Expand migrations are reversible while legacy columns/tables remain. Fact and
verification history must be exported before their owning structures are
rolled back. Backfill rolls back by restoring the pre-migration local/production
backup or executing compensating idempotent mappings before application switch.
After migration 500, automatic rollback is prohibited: use the verified backup
plus exported V2 deltas, because dropping legacy structures is intentionally
contractual and potentially lossy.
