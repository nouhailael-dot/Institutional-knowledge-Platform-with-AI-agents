# Architecture V2 schema conformance audit (WS7)

**Question asked:** does the database architecture suit what the agents will
bring — is everything on the same page, and is anything in need of change?

**Method.** Read-only, against the committed target-schema export
`docs/evidence/v2_target_schema_manifest_2026-10-06.json` (41 tables, 6 views,
checkpoint `target_final_expand`, database `ghus_v2_target_test`,
`production_deployed: false`), cross-checked against what the agents actually
write (`agents/discovery/promote.py`, `agents/enrichment/decisions.py`,
`agents/collection/light_pull.py`, `agents/common/actor_classification.py`) and
what the Review app reads.

**Nothing was changed in the database.** No connection was opened, no DDL was
run, no row was written. Every recommendation below is a proposal for the schema
owner.

> **Caveat on the evidence.** The manifest is a snapshot taken on 2026-10-06, not
> a live read — the local test database was unreachable in this session (no
> credentials). Everything below is therefore **conformance of the committed
> target schema**, which is what the cutover will produce. Re-run against the
> live `_test` database before treating any PASS as proof of the deployed state.

---

## Headline

The schema is in good shape and genuinely enforces the hard rules: facts are
append-only, a non-`found` fact physically cannot carry a value, verification
events are append-only with RLS and cannot be forged by an agent, edge cycles
are blocked by a trigger, and only two writer modules may appear in the write
audit. Those are the parts that matter most and they are right.

Five things are **not** on the same page, and four of them I have already fixed
in the Review app today because they were defects in code I shipped this session.
The fifth is a genuine schema gap that blocks WS4 and WS6.

| # | Finding | Verdict | Blocking? |
|---|---|---|---|
| F1 | `collection_run` carries none of the WS4 run fields | **GAP** | **Yes** — blocks WS4 task 1 and WS6 |
| F2 | `fk_actor_category_type` is absent from the deployed target | **GAP** | Yes for "no invalid pair possible in the DB" |
| F3 | Fact state is `not_yet_collected`; the Review app read `not_yet_checked` | **FIXED** | was yes |
| F4 | Link code is `connected_to_um6p_ocp`; Appendix B writes `…_entity` | **FIXED** | no |
| F5 | 6 of 21 `review_kind` values had no label in the Review app | **FIXED** | no |
| F6 | `match_strength` / `confidence` stored lower case, displayed raw | **FIXED** | no |
| F7 | No `person_verification_event`: people have no separate verification | **GAP** | no (person discovery is off) |
| F8 | `actor_ranking` has no university-only rule in the schema | **GAP** | no (code enforces it) |
| F9 | `hub_actor` has no membership history or state | **GAP** | no, but see below |
| F10 | `actor` carries three overlapping status columns | **DEVIATION** | no (transitional by design) |
| F11 | `actor_fact.lifecycle_state` uses `accepted`, the spec says `active` | **DEVIATION** | no |
| F12 | Several constraints are `NOT VALID` | **DEVIATION** | no |

---

## Requirement-by-requirement

| # | Requirement (source) | Found | Verdict | Evidence | Recommended fix | Blocking |
|---|---|---|---|---|---|---|
| 1 | One category from 12; type constrained to its category by composite FK; type nullable for legacy only | `actor.actor_category`, `actor.category_type` (both nullable); `actor_category_type_definition(category_code, type_code)` PK; **no `fk_actor_category_type` on `actor`** | **GAP** | manifest `tables.actor.constraints` lists only `source_id` and `merged_into_actor_id` FKs | The composite FK is created by `migrations/proposed/deferred/380`, re-added `NOT VALID` then validated by `450`/`490`. Until that chain runs, pair validity rests on the API and UI only. Apply it, then `VALIDATE`. | **Yes** |
| 2 | `status ∈ {imported, parked, verified, rejected}`; no path to verified/rejected outside GHUS events or the approved bootstrap | `actor.status` + trigger `actor_status_verification_guard`; `actor_verification_event` with `ck_actor_verification_event_origin` requiring either (`ghus_review` + `decided_by` + `decided_at`) or a `migration_batch_id` | **PASS** | `tables.actor.triggers`, `tables.actor_verification_event.constraints` | — | No |
| 3 | Verification record append-only (who, when, notes); agents cannot write it | `actor_verification_event_append_only` trigger, `actor_verification_event_project_status` trigger, **2 RLS policies** (`…_ghus_insert`, `…_read`) | **PASS** | only table in the schema with RLS — appropriately so | — | No |
| 4 | Location: country, state (normalized), city, region **derived**, coordinates from gazetteer, multi-location flag | `actor_location(country, state_code→region_state, city, region_code→region_definition, latitude, longitude)`, `CHECK ((latitude IS NULL) = (longitude IS NULL))`, `actor.is_multi_location` | **PASS** | `tables.actor_location` | Region is FK-constrained but not *generated*: a writer could still store a region inconsistent with its state. Consider a trigger or generated column. Low priority — the app derives it. | No |
| 5 | Region mapping matches Appendix C exactly, incl. DC → Mid-Atlantic and WA → West Coast | `region_state` seeded by `agents/sql/190`; verified against Appendix C by `tests/test_review_taxonomy.py::test_region_mapping_matches_appendix_c_exactly` | **PASS** | 51 rows, DC `is_district` true, mapped to `mid_atlantic`; WA → `west_coast_pacific` | — | No |
| 6 | Fact ledger: value, layer, source URL, origin, date read, confidence, supersedes, is_current, state | `actor_fact(fact_value jsonb, layer CHECK 1/2/3, source_id→source, source_origin→source_origin_definition, retrieved_at, confidence CHECK high/medium/low, supersedes_fact_id, collection_state, lifecycle_state)` + `actor_fact_current_pointer` + views `actor_fact_current_v2`, `actor_fact_history` | **PASS** | `tables.actor_fact` | Note `lifecycle_state` is `accepted`/`conflict_flagged`/`pending_update`, where the spec says *active*. Naming only — see F11. | No |
| 6b | A missing fact cannot carry a value | `actor_fact_check`: `collection_state = 'found' AND fact_value IS NOT NULL OR collection_state <> 'found' AND fact_value IS NULL` | **PASS** | the "never invent" rule enforced in DDL, which is the right place for it | — | No |
| 7 | No-delete guards on canonical tables; rejected records retained | append-only triggers on 15 tables: `actor_fact`, `entity_edge`, `actor_verification_event`, `actor_ranking`, `canonical_write_audit`, `event_claim`, `fact_corroboration`, `fact_resolution`, `review_item_decision`, `proposed_hub_decision`, `contact_collection_authorization`, `actor_category_migration_audit`, `hub_assignment_evidence`, … | **PARTIAL** | `tables.*.triggers` | **`actor`, `person`, `event`, `hub`, `hub_actor`, `actor_topic`, `actor_location` have no delete guard.** The evidence tables are protected; the records themselves are not. Add no-delete triggers, or revoke DELETE from the application role. | No |
| 8 | 11 Guide link types; source required; `affiliated_with` person→org only; `organizes`/`participates_in` actor→event only; `portfolio_of`/`member_of` never parenthood; recursive descendants view | `entity_edge_relationship_type_check` lists exactly the 11; `source_id NOT NULL`; `entity_edge_type_definition(subject_types, object_types, establishes_actor_family)`; triggers `entity_edge_validate` and `entity_edge_prevent_family_cycle`; view `actor_descendants` | **PASS** | `tables.entity_edge`, `views.actor_descendants` | — | No |
| 8b | The stored code for the UM6P/OCP link | `connected_to_um6p_ocp` — **without** the `_entity` suffix Appendix B uses | **DEVIATION** | `entity_edge_relationship_type_check` | Fixed in the Review app: the DB code is canonical, the Guide spelling is accepted as an alias, and the Guide's label is displayed. No schema change needed. | No |
| 9 | Topic table + `actor_topic` (strength, reason); sector many-to-many | `topic(code unique, name unique, active)`, `actor_topic(match_strength CHECK strong/moderate, match_reason CHECK 1–1000 chars, source_id NOT NULL)`, plus `event_topic`, `person_topic` | **PASS** | `tables.actor_topic` | A topic claim requires a source and a reason. Exactly right. | No |
| 10 | Hub: topic, center, radius (default 200), frozen flag; `actor_hub` keeps history/state; proposals with family/category evidence and rejection fingerprint | `hub(topic_id, center_city, center_state_code, center_latitude, center_longitude, radius_miles, center_frozen, center_method, center_method_version, center_computed_at)`; `proposed_hub(independent_family_count, category_count, membership_fingerprint, independence_statement, detection_method_version, fingerprint_version, trigger_statuses, minimum_families_required, minimum_categories_required)`; `hub_detection_run`; `hub_assignment_evidence` (immutable) | **PASS** for hub and proposals | `tables.hub`, `tables.proposed_hub` | — | No |
| 10b | `hub_actor` keeps history and state | `hub_actor(hub_id, actor_id, topic_id, distance_miles, assignment_outcome, outside_radius, overlap_flag, source_id, created_at)` — **no `is_current`, no `ended_at`, no delete guard** | **GAP** | `tables.hub_actor` | "Historical memberships are never silently replaced" currently depends on nobody issuing a DELETE or UPDATE. Add an `is_current`/`superseded_at` pair, or a no-delete trigger plus append semantics, before WS5.1 writes manual assignments. | No, but **fix before WS5.1** |
| 11 | Rankings: publisher, name, year, subject, ranked unit, position; **University only**; department never inherits | `actor_ranking(publisher CHECK QS/THE/U.S. News/ARWU, ranking_name, ranking_year CHECK, subject, ranked_entity_name, position_text, context_actor_id)`, append-only | **GAP** | `tables.actor_ranking` | Nothing in the schema stops a ranking row on a non-university actor. `light_pull.py` raises `rankings are collected only for university actors`, and the Review UI hides the row — but a direct writer could still insert one. Add `CHECK` via a trigger that the actor's category is `university_academic`. | No |
| 12 | UM6P/OCP entity list + 3-state check per actor and layer | `entity_edge` object type `strategic_entity` + the `connected_to_um6p_ocp` relationship; the 3-state answer lives in `actor_fact` as `um6p_ocp_connection` with `collection_state` | **PASS** | `tables.entity_edge`, `light_pull.COMMON_LIGHT_FIELDS` | The three states map onto `found` / `not_found` / `not_yet_collected` cleanly. | No |
| 13 | Events: type, dates, temporal state, recurrence, organizer link, claims with source, GHUS-only notes not writable by agents | `event(event_type, start_date, end_date, next_date, date_status, recurring_pattern, host_actor_id→actor, ghus_notes)`; `event_claim` append-only | **PARTIAL** | `tables.event`, `tables.event_claim` | `event.ghus_notes` has **no RLS and no trigger** stopping an agent writing it, unlike `actor_verification_event`. The agent code never writes it, but the schema does not enforce that. Same for `actor.ghus_notes`. Add a trigger or column-level privileges. | No |
| 14 | People: separate records, discovery flag off, **separate verification** | `person` table exists and is separate; `person_topic`; discovery flag is config, not schema — **there is no `person_verification_event`** | **GAP** | `tables` list has `actor_verification_event` only | Person verification currently has nowhere to go. Not urgent while person discovery is disabled, but it must exist before people can be verified. | No |
| 15 | Source-origin labels keep Imported / Discovered / GHUS document distinct | `source_origin_definition` with `imported`, `newly_found`, `uploaded_document`, `ghus_manual`; `actor_fact.source_origin` NOT NULL FK; `actor.source_origin`, `person.source_origin`, `event.source_origin` | **PASS** | `agents/sql/190`, `tables.actor_fact` | — | No |
| 16 | Review item kinds cover the 13 listed | `ck_review_item_kind` allows **21**: the 13 required, plus `identity`, `affiliation_change`, `classification`, `geocode`, `hub_assignment`, `same_topic_overlap`, `new_hub`, `pending_human_update` | **PASS** (superset) | `tables.review_item.constraints` | The constraint is `NOT VALID`. Validate it. The Review app now labels all 21 — six of them did not have a label this morning (F5). | No |
| 17 | Collection runs carry the WS4 fields | `collection_run(collection_request_id, job_name, dry_run, status, fetch_budget, fetch_count, max_usd, spent_usd, started_at, finished_at, status_reason)` | **GAP** | `tables.collection_run` | **See F1 below.** | **Yes** |
| 18 | Duplicate check by name, alternate names and **website domain**, indexed and normalized | `ix_actor_website_domain` on `lower(website_domain)`, `ix_actor_name_normalized` on `lower(name)`, `ix_actor_alternate_names_gin` on `alternate_names` | **PASS** | `tables.actor.indexes` | — | No |

---

## F1 — `collection_run` cannot describe a run (blocking)

This is the one real blocker and it is worth stating plainly.

The brief's WS4 asks every run to expose a stable id, a human-readable date, a
`trigger_type` (manual / subscription / scheduled_event / migration), a cadence,
an `initiated_by` (nullable until auth, **never invented**), a configuration
snapshot, an outcome, and counts of found / deduplicated / staged / review items.

`collection_run` has **none of them**. It is a *budget and execution* record —
how many fetches, how much money, did it succeed — not a *provenance* record.

| WS4 field | In `collection_run`? |
|---|---|
| stable run id | yes (`collection_run_id`) |
| human-readable run date | partial (`started_at`) |
| `trigger_type` | **no** |
| cadence | **no** |
| `initiated_by` | **no** |
| configuration snapshot | **no** |
| outcome | partial (`status`, `status_reason`) |
| counts (found / deduped / staged / review) | **no** |

**Consequence today.** The Review app derives the trigger from the run
description text and reports `initiated_by` as "Not Recorded". That is honest,
but it is a workaround, and it is why WS4 task 1 is still open.

**Consequence for WS6.** Actor update subscriptions are specified to link each
run to this model and to record initiator, configuration, outcome and review
counts. They cannot, as the table stands.

**Recommended fix.** An **additive** migration adding `trigger_type` (CHECK
against the four values), `cadence`, `initiated_by` (nullable), `config_snapshot
jsonb`, and the four count columns — plus a contract note for Nouhaila, since
the agents are what will populate them. Additive, so it is safe to propose
alongside the cutover rather than inside it.

---

## F3–F6 — four mismatches between the schema and the Review app, now fixed

These were defects in code written this session. The audit is what found them.

| | The database stores | The app expected | Now |
|---|---|---|---|
| F3 | `collection_state = 'not_yet_collected'` | `not_yet_checked` / `not_checked` | all three map to **Not Yet Checked** |
| F4 | `connected_to_um6p_ocp` | `connected_to_um6p_ocp_entity` | DB code is canonical, Guide spelling is an accepted alias, Guide label displayed |
| F5 | 21 `review_kind` values | 15 labelled | all 21 labelled, each distinct |
| F6 | `match_strength`/`confidence` lower case | rendered raw | displayed through the label dictionary |

F3 was the serious one. A fact row with `collection_state = 'not_yet_collected'`
carries a NULL value by the DB's own CHECK, so the Review screen would have
shown a blank cell where it should have said **Not Yet Checked** — exactly the
"never mix the kinds of missing" rule the brief is built around, broken by a
vocabulary mismatch.

Each fix is pinned by a test that quotes the DB constraint it follows, so the
two cannot drift apart again silently.

---

## Does the schema suit what the agents bring?

Taking the agent output shapes one at a time:

| What an agent produces | Where it lands | Fits? |
|---|---|---|
| Light Pull facts (13 common + per-category keys) | `actor_fact` with `layer = 1`, `fact_key` free text | **Yes.** `fact_key` is unconstrained text, so the 69-type catalog change needed no fact-schema change. |
| Deep Pull facts | `actor_fact` `layer = 2` | Yes |
| Classification (`actor_category`, `category_type`, note, needs_review, evidence) | `actor.actor_category`, `.category_type`, `.category_note`, `.category_needs_review`; evidence → `actor_fact` `fact_type='classification'` | Yes, **once F2's composite FK is applied** |
| Sourced relationships | `entity_edge`, source required, cycles blocked | Yes |
| Topic match | `actor_topic` with strength, reason and source | Yes |
| Geocoding | `actor_location` + `us_city_coord` (gazetteer year and SHA-256 recorded) | Yes — the gazetteer provenance is recorded, which is better than required |
| Hub proposals | `proposed_hub` + `hub_detection_run` + `hub_assignment_evidence` | Yes, and richly |
| Hub memberships | `hub_actor` | **Weak** — no history, see F9 |
| Review items | `review_item` (21 kinds) | Yes |
| Write audit | `canonical_write_audit`, writer module CHECK-limited to the two approved writers | Yes — this is the guardrail made structural |
| Person facts | `person`, `person_topic` | Partly — no verification event, see F7 |

**The honest summary:** the fact ledger, the edge model, provenance and the hub
proposal machinery are well matched to what the agents emit. The run model is
not, and membership history is thin. Nothing about the Intern Guide taxonomy
change required a structural schema change, which is a good sign that the
category/type design was right.

---

## Recommended changes, in priority order

| Priority | Change | Why | Owner |
|---|---|---|---|
| 1 | Apply the deferred composite FK `fk_actor_category_type` and `VALIDATE` it | Until then "no invalid pair is possible" is true in the API and UI but not in the database | schema owner |
| 2 | Additive migration: `collection_run` gains `trigger_type`, `cadence`, `initiated_by`, `config_snapshot`, and the four counts | Unblocks WS4 task 1 and WS6 | schema owner + Nouhaila |
| 3 | `hub_actor`: membership history and state, or a no-delete guard | Before WS5.1 writes manual hub assignments | schema owner |
| 4 | No-delete guards on `actor`, `person`, `event`, `hub`, `actor_topic`, `actor_location` | The evidence tables are protected; the records are not | schema owner |
| 5 | Protect `ghus_notes` on `actor` and `event` from agent writes | Currently convention, not enforcement | schema owner |
| 6 | `VALIDATE` the `NOT VALID` constraints | `ck_review_item_kind`, `ck_actor_fact_creator_class`, `ck_actor_fact_lifecycle_state`, `ck_proposed_hub_*`, the `proposed_hub` FKs | schema owner |
| 7 | Add `person_verification_event` | Before person discovery is ever enabled | schema owner |
| 8 | Trigger restricting `actor_ranking` to university-category actors | Code-enforced today | schema owner |
| 9 | Retire `actor.verification_status` once the cutover settles | Three status columns and a sync trigger is transitional by design, but it should not be permanent | schema owner |

**None of these is applied here.** Items 1–9 are proposals requiring schema-owner
approval, a verified backup, a tested rollback and a coordinated deployment,
exactly as Part C of the brief requires.

---

## What this audit did not check

- **The live database.** The manifest is a 6 Oct snapshot. Re-run against the
  live `_test` database when credentials are available.
- **Row-level data conformance** — orphans, invalid pairs already stored, status
  distribution. All of that needs a live read.
- **Grants in practice.** The manifest shows `ghus_test` holds full DML on
  `actor`, including DELETE. Whether the production application role is
  narrower was not verifiable from here.
