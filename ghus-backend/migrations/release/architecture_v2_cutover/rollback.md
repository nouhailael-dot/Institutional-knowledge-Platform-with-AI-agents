# Rollback and recovery per stage

The step-1 backup is the recovery point for every stage. Both application
releases work on the pre- and post-500 schemas, so a database restore never
forces an application rollback (proved by `tests/test_v2_cutover_smoke.py` in the
shared repo against both copies).

| Stage | What it changes | Recovery |
|---|---|---|
| baseline | one new table | `DROP TABLE architecture_v2_cutover_baseline;` |
| expand | additive tables, columns, views, functions, triggers; `review_item` kind CHECK | Leave in place (current apps ignore it), or run each step's rollback in reverse: SQL in `agents/sql/rollback/`, `migrations/proposed/deferred/rollback/`, `migrations/proposed/additive_apply_2026-09-28/rollback/`; Alembic steps `downgrade()`. Local proof: `scripts/functional_v2_schema.py <checkpoint> --rollback`. |
| gazetteer | reference rows | `TRUNCATE us_city_coord;` |
| backfill (480–489) | V2 status/category/geography columns gap-filled; append-only facts, records, reviews, events; `actor_read` view; audit function | **Restore the backup.** Append-only ledgers (facts, audit, verification events) reject DELETE by design. 488/489 alone: `deferred/rollback/488_*.sql`, `489_*.sql`. |
| validate (490) | constraints validated | `ALTER TABLE actor DROP CONSTRAINT ck_actor_status_v2, DROP CONSTRAINT fk_actor_category_type, DROP CONSTRAINT ck_actor_other_type_note;` |
| applications switched | — | Redeploy the previous application versions only if a smoke test fails; the database needs no change. |
| topic (486) | topics, hub topic/center/radius, membership topic/distance/flags (gap-fill) | Restore the backup, or targeted: `UPDATE hub_actor SET topic_id=NULL, distance_miles=NULL, outside_radius=NULL, overlap_flag=NULL, assignment_outcome=NULL; UPDATE hub SET topic_id=NULL, center_city=NULL, center_state_code=NULL, center_latitude=NULL, center_longitude=NULL, center_method=NULL, center_method_version=NULL, center_computed_at=NULL, radius_miles=NULL, center_frozen=NULL WHERE center_method_version='density_center_v1';` then the topics. |
| contract (405/410/495) | NOT NULL and CHECK constraints | `deferred/rollback/405_*.sql`, `410_*.sql`; 495: `ALTER TABLE actor DROP CONSTRAINT ck_actor_category_complete;` |
| cutover (500) | **destructive**: legacy columns and tables dropped, renames | **Point-in-time restore or the step-1 backup only.** Every dropped value is preserved before 500 in facts, `legacy_migration_record` and `actor_category_migration_audit`, so the restore is a choice, not the only copy. Applications keep running on the restored schema. |

After any restore: re-run `post_apply_checks.sql` §all and the local rehearsal
before trying again.
