# For schema-owner review: migration 710, record deletion with 30-day retention

**Request:** review and, when approved, apply migration 710 to Supabase (after a
fresh backup and a ledger entry). Nothing has been applied; the current guards
stay in force until then.

| | |
|---|---|
| Policy | Approved by GHUS on 17 Nov 2026: delete hides at once; 30 days under Pending Deletion (Dashboard card and page, separate from Review's Rejected), restorable by Admins and Editors/Reviewers; then permanent removal by a scheduled cleanup |
| Migration | `ghus-backend/migrations/proposed/deferred/710_record_deletion_retention.sql` |
| Rollback | `ghus-backend/migrations/proposed/deferred/rollback/710_record_deletion_retention.sql` (refuses once any deletion exists; restores the four guard functions and `actor_read` exactly as they were) |
| Depends on | Migration 700 (`compass.user_profile`) |
| Replaces | The earlier review-only draft `migrations/proposed/review/710_permanent_deletion.sql` (removed) |

## What 710 changes

| Object | Change |
|---|---|
| `compass.deleted_record` (new) | One row per deletion: record type and id, name, snapshot of the row and its link counts, reason (≤ 500), `deleted_by` (an account), `deleted_at`, `purge_after` (≥ 30 days later, checked), `restored_at/by`, `purged_at`, `purge_report`. One pending deletion per record (partial unique index). RLS on, no browser grants. |
| Guard on `compass.deleted_record` | Never deleted; who/when/why/deadline never change; a row only moves to *restored* (before the deadline, checked) or *purged* (after it); a closed row is frozen. |
| `compass.purge_door_open()` (new) | True only while the approved writer's transaction has set `ghus.permanent_delete` to the id of a pending deletion **whose 30 days are over**. |
| `ghus_guard_no_delete`, `ghus_reject_mutation`, `ghus_guard_sector_link_append_only`, `ghus_guard_subscription_run_append_only` | Unchanged, except a `DELETE` passes while the door is open. `UPDATE` stays refused everywhere; any other `DELETE` stays refused. |
| `actor_read` view | Same definition plus "not pending deletion". |

Nothing is deleted by the migration, and no verification decision or status is
changed by a deletion: hiding comes from the tombstone, so a restore brings the
record back exactly as it was.

## Who writes

Only the backend's approved writer, `agents/enrichment/decisions.py`:
`delete_record`, `restore_record`, `purge_record`, called through Review's
admission process (`delete_record` / `restore_record` decision kinds) and the
cleanup job `python -m agents.review.purge` (dry run unless `--live` and
`REVIEW_ADMISSION_WRITES_ENABLED=true`). The platform never writes these tables.

## What the purge removes (explicit per-table policy)

`delete` = the row goes with the record; `detach` = the column is set to NULL and
the row stays; `block` = the purge stops and reports. A foreign key to the record
that the policy does not list also **blocks** the purge (checked from
`pg_constraint` each time), so a new table can never be emptied by surprise.

| Record | Removed with it | Detached | Blocks |
|---|---|---|---|
| Organization (`actor`) | details (620/621), facts (and their pointers, corroborations, resolutions, write audit), capability facts, locations, profile, rankings, relevance, sectors, topics, strategic checks, evaluations, category-migration audit, legacy migration records, people links, hub memberships and hub evidence, parent/child links, partnership profile, discovery profiles, proposed hub members, review-queue pairs, merge log rows (their review items detached), verification events | `collection_request.actor_id`, `event.host_actor_id` | another organization merged into it |
| Person | facts (600), details (630, when applied), organization links, contact authorizations, change log, discovery profile, topics, verification events | `person_review_queue.candidate_person_id` | — |
| Event | facts (600), details (630, when applied), claims, scoring, sectors, topics | `event_review_queue.candidate_event_id` | — |
| Hub | memberships, assignment evidence, center review, funding, sectors, sector strength | `proposed_hub.final_hub_id` | — |

No other record is touched: other organizations, people, events and hubs only
lose the link rows listed above.

## What is kept after the purge

The `compass.deleted_record` row, permanently: who deleted, when, why, the
deadline, the purge time and the per-table row counts removed. Its snapshot is
reduced to the record type, id, website/domain and country. A person's name is
replaced by "Deleted person" and nothing personal is kept; the platform also
keeps person names out of the permanent audit history.

## Tests

- Backend, on the isolated demo database in one rolled-back transaction:
  `ghus-backend/tests/agent/test_record_deletion.py` (11 tests, on a restore of the 5 Nov 2026 Supabase backup: hiding,
  deadline, restore, refusal after expiry, merged/duplicate refusals, guards
  still refusing everything else, purge timing, policy coverage and blocking,
  dry run equal to the live report, idempotence, person anonymization, the
  cleanup job's dry default and retry safety, every foreign key covered).
- Platform, on the isolated accounts database with 710's compass section:
  `tests/test_accounts_phase6.py` (15 tests).
- Rehearsal of 700 + 710 together on that production copy: 28/28 checks; apply order,
  ledger rows with checksums, read-only preflight and verify, rollback in
  `ghus-backend/migrations/proposed/accounts_700_710/README.md`.

## Decisions needed

1. Approve 710 as written (or name changes).
2. Confirm the per-table policy above, in particular that verification events
   and the fact history go with the record at the purge (they are kept, unchanged,
   during the 30 days).
3. Then apply it: fresh backup → apply 710 → ledger entry (see
   `docs/ACCOUNTS_ACTIVATION.md`, section 8).
