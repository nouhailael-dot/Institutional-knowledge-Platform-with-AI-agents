# Supabase alignment check (2026-10-26)

Read-only review of the shared Supabase database against the code in both
repositories. Every query ran in a READ ONLY transaction; nothing was written,
migrated or deleted. 91 relations: 85 tables, 6 views.

## 1. Schema alignment - what would break in production

| Migration | On Supabase | Effect |
|---|---|---|
| 010-430, 530, 540 | applied | - |
| **170** person affiliation resolution | **not applied** | `promote.py` inserts `person_review_queue.affiliation_raw`; every person sent to Review fails (seen on the demo database on 2026-10-25 until 170 was applied there) |
| **520** sector dimension | **partial** | no `hub_sector`, no `sector.active` / `is_thematic`, no `actor_sector.match_strength` / `match_reason` / `is_primary`. `_append_actor_sectors` selects `sector.active` and inserts those columns: a created or admitted actor carrying sectors fails. `actor_sector` is empty on Supabase. Discovery's own `load_active_sectors` silently falls back to the seed file. |
| 550, 570, 580 | applied | present, but **not recorded** in `architecture_v2_migration_ledger` (the ledger ends at 500, 2026-10-06) |
| `search_doc` (old Ask index, `schema_migrations` 001-004) | on Supabase only | the weekly index refresh works there; it fails on the local demo database, which lacks it |

The local test databases are not representative: the demo database still has
the pre-cutover `actor` columns and compatibility views, so a test can pass
there and fail on Supabase (170 and 520 above). Supabase's `actor` is the slim
V2 table (`status`, `alt_names`, `city`); facts live in `actor_fact`.

**Needs the schema owner:** apply 170 and complete 520 on Supabase; record 550,
570 and 580 in the ledger; rebuild `ghus_v2_test` from Supabase's schema.

## 2. Duplicates

Real duplicates in canonical data:

- **Actors - 71 pairs** share the exact same website host and a near-identical
  name. Clear duplicates include: NOAA Earth System Research Labs (x2), USGS
  (x3 variants), BioSTL (x2), Bayer Crop Science (x4), Mines Mining Engineering
  Department (x2), UC Berkeley Materials Science (x2), UWM School of Freshwater
  Sciences (x2), Texas A&M Biological & Agricultural Engineering (x2), Rice
  Chemical & Biomolecular Engineering (x2), Mayo Clinic / Mayo Clinic Research,
  Cleveland Clinic / Cleveland Clinic Innovation. Some pairs are a parent and
  its department (Stanford / Stanford Chemical Engineering; Argonne / Argonne
  Catalysis Programs) and may be intended. No two active actors have the exact
  same name.
- **Events - 16 names, 47 extra rows**, almost all UN calendar entries from the
  configured UN sources, most without a date: UN High-level Political Forum x11,
  UNGA High-level Week x8 (+x4 under a second spelling), ECOSOC Youth Forum x6,
  Second Committee sessions x6, FfD Forum x4.
- **Event review queue - 3 pending titles twice** (2027 ARPA-E Energy Innovation
  Summit, 2027 Multi-State Salinity Summit, AI Health Summit). New runs no longer
  add these (pending-review check, 2026-10-23).
- **review_item - 2 groups pending twice** (one actor's relationship review; 3
  items with no entity).

Repeats by design (run logs), growing with every run:

- `staged_record` 7,357 rows: 5,602 re-stage an already staged natural key.
- `search_candidate` 11,897 rows: 5,548 are the same URL seen again by later runs.
- `raw_document`: 263 re-stored copies of an identical page; `source`: 221 repeated URLs.

Clean: hubs, hub memberships, actor locations, search_doc, discovered domains,
topics, sectors, current facts per actor/key/topic, entity edges (1 group).

## 3. Tables that serve no purpose today

No code in either repository and no database function or view uses them:

| Table / view | Rows | Note |
|---|---|---|
| `query_log` | 7 | old Ask query logging |
| `funding_source`, `hub_funding` | 0 | never built |
| `person_verification_event` | 0 | superseded by `record_verification` |
| `actor_read` (view) | 809 | cutover read view (migration 488) |
| `us_city_coord` | 32,058 | gazetteer; only scripts read it |
| `actor_descendants`, `actor_descendant_edge` (views) | 0 | one script only |

Empty and used only by one-off scripts (the feature never ran):
`canonical_write_audit`, `contact_collection_authorization`, `event_claim`,
`fetched_document`, `strategic_document`, `person_topic`, `hub_sector_strength`,
`actor_ranking`, `actor_strategic_connection_check`; `actor_evaluation` (158
rows, scripts only).

History to keep until archived (not used by the platform):
`legacy_migration_record` (19,516), `actor_category_migration_audit` (965),
`architecture_v2_cutover_*`, `architecture_v2_migration_ledger`,
`schema_migrations`, `alembic_version`.

Empty but needed - the live code writes them once the feature runs in
production: `person`, `person_discovery_profile`, `person_review_queue`,
`person_change_log`, `actor_person` (People Discovery); `actor_sector`,
`actor_topic` (blocked by 520); `proposed_hub*`, `hub_detection_run`,
`hub_assignment_evidence`, `hub_center_review` (hub detection);
`record_verification`, `review_admission_decision`, `fact_corroboration`,
`fact_resolution`, `field_proposal`, `actor_fact_current_pointer`.

## 4. Automatic and on-request runs (2026-10-25, demo database)

- Weekly Discovery, dry run as scheduled: open-web events worked (42 searches,
  16 from cache, 11 non-US results dropped, 10 known events skipped, 30 events
  would be staged, $1.95); the three UN/Climate Week sources ran; enrichment
  succeeded; index refresh failed only because the demo database has no
  `search_doc`.
- Discovery Requests, plan as scheduled: lists due organization, event and
  people requests with their searches.
- "Run now" from the app: a weekly people request ran live, recorded its run,
  stayed active (next run Nov 1), and added no duplicate to Review.
