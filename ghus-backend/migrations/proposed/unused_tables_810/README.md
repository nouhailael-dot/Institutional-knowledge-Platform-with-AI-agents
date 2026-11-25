# Migration 810: remove the tables Compass does not use

Platform owner's decisions of 24 and 25 Nov 2026. It replaces the draft numbered 750, which
was never applied: Nouhaila applied her own 750, 770 and 790 on 24 Nov, and 800 (actor
names) was applied on 25 Nov. 810 is written for the database **after 800**, so it uses the
actor names, and it refuses to run without 800.

Status: **ready, not applied.**

| Removed | Rows (25 Nov) | Why |
|---|---|---|
| `actor_ranking` and its guard function `ghus_guard_ranking_is_university` | 0 | University rankings, planned in June, never filled. |
| `actor_evaluation` | 158 | Old Phase 1 evaluations; nothing reads them. |
| `event_scoring` | 87 | Old Phase 1 event scores; nothing reads them. |
| `fetched_document` | 0 | An earlier design for fetched pages; `raw_document` replaced it. |
| `canonical_write_audit` | 0 | A planned write log; never filled. |
| `contact_collection_authorization` | 0 | Contact collection was never built. |
| `query_log` | 7 | Telemetry of the July Ask prototype; nothing writes to it. |
| `proposal` | 0 | An inbox from the first database (June); Review does this job. |
| `hub_center_review` | 0 | Hub-centre drift reviews; the code that wrote it was never called (removed with it). |
| `person_topic` | 0 | A person's topics; nothing ever wrote it (Browse now shows no topic for people). |
| `legacy_migration_record` | 19,516 | Proof of the 6 Oct move to Architecture V2. History only. |
| `actor_category_migration_audit` | 965 | How categories were mapped in October. History only. |
| `hub_actor_removed`, `hub_removed` | 180, 1 | Hub rows removed in the move to Architecture V2. History only. |
| the function `ghus_pre_cutover_data_loss_audit` | | The pre-cutover check that read the four history tables above. |
| `review_queue` | 280 | Duplicate pairs from August; `review_item` replaced it. The retired code that could still write it now refuses. |
| `alembic_version`, `schema_migrations` | 1, 4 | Markers of the June database and the July prototype. |

Kept on purpose: `compass.migration_snapshot` (800's rollback needs it), `challenge`,
`actor_relevance`, `partnership_profile` and `event_sector` (Ask and discovery still read
them), `actor_merge_log` (the duplicate model trains on it), the two cutover records, and
`strategic_document`, `strategic_entity` and `actor_strategic_connection_check` (planned).

## Archive

The structure and rows of the ten tables that have rows were saved from Supabase on 25 Nov,
after 800, to `C:\Users\Ismail\GHUS-data\backups\archive-810-removed-tables-20261125.sql`
(12.7 MB, plain SQL; outside the repository). The backup taken before applying keeps them too.

## Files

| | File |
|---|---|
| Migration | `../deferred/810_remove_unused_tables.sql` (SHA-256 in `ledger.sql`) |
| Rollback | `../deferred/rollback/810_remove_unused_tables.sql` (`pg_dump --schema-only` of Supabase on 25 Nov, after 800, with the two functions, their comments and every grant) |
| Checks | `preflight.sql` (before), `verify.sql` (after) |

The code changes ship with it and are safe before 810 too: Browse no longer reads
`person_topic`, the Data Feed contract names `staged_record.topic_id`, the old duplicate
check's `review_queue` write refuses, and the unused hub-centre review code is removed. The
deletion clean-up's `PURGE_POLICY` skips tables that do not exist, so it needs no change.

## Rehearsal (25 Nov 2026)

On `ghus_810_rehearsal_test`, a copy of `ghus_prod800_test` (the 24 Nov 23:48 backup with 800
applied; its ledger checksum matches the committed 800):

- preflight: 8 of 8 true; apply 810; ledger; verify: 6 of 6 true; a second apply refuses;
- with 810 applied, the platform reads the copy: 744 organizations, 48 hubs, 359 events and
  7 people load, an organization profile opens, and the deletion policy finds no uncovered
  link for organizations, people, events or hubs;
- rollback: the schema is identical to before 810 except the grants, which the local copy
  never had (Supabase has them, and the rollback restores them).

## Apply sequence (Supabase SQL editor; one script per run; a quiet window)

1. No Discovery, Update or Data Feed run in progress; tell Nouhaila. Fresh backup with
   `pg_dump` to `C:\Users\Ismail\GHUS-data\backups`.
2. `preflight.sql`: every row `ok = true`. Stop otherwise (the migration would refuse
   anyway, changing nothing).
3. `../deferred/810_remove_unused_tables.sql`: one transaction.
4. `ledger.sql`.
5. `verify.sql`: every row `ok = true`.

Deploy the commit that carries 810 before or after; the code works with and without the tables.

## Rollback

1. `../deferred/rollback/810_remove_unused_tables.sql`
2. `DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '810';`
3. Rows, if needed: run the `COPY ... FROM stdin` sections of the archive for those tables.

Roll 810 back before rolling back 800 or 720.
