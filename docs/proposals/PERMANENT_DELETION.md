# Proposal for schema-owner review: permanent deletion of records

> **Superseded (17 Nov 2026).** GHUS approved a different policy: delete hides at once,
> 30 days restorable under Pending Deletion, then a scheduled permanent purge.
> It is implemented as migration 710 (`migrations/proposed/deferred/710_record_deletion_retention.sql`);
> see `docs/schema-review/02_PERMANENT_DELETION.md`. This document is kept for the record.

Status: **proposal only.** Nothing here is applied; the current guard
(`ghus_guard_no_delete`: "is never deleted: reject the record and keep it, with
its reason") stays in force on `actor`, `person`, `event` and `hub`. Draft SQL:
`ghus-backend/migrations/proposed/review/710_permanent_deletion.sql`, outside
the deferred track so it cannot be applied with the others by mistake.

## Why it needs a decision

The multi-user brief asks that Admins and Editors/Reviewers can permanently
delete records, while respecting the Architecture V2 governance rules. Those
rules made deletion impossible on purpose: a record is rejected and kept, with
its reason, and its facts and verification history are append-only.

What a record is tied to (foreign keys, all "no action", so the database
refuses rather than cascades):

| Record | Referencing tables | Includes append-only history |
|---|---|---|
| Organization (`actor`) | 31 columns in 28 tables | `actor_fact`, `actor_verification_event`, `actor_merge_log` |
| Person | 7 | `person_verification_event`, `person_change_log` |
| Event | 5 | `event_claim` |
| Hub | 8 | `hub_center_review` |

## Recommendation: delete only what has no history; remove everything else

1. **Permanent deletion is allowed only for a record with no dependent
   history**: typically a record created by mistake minutes ago. The only rows
   removed with it are its own association rows (sectors, topics, hub
   membership, locations), listed and shown before confirmation.
2. **Anything else stays "Remove from Directory"** (the existing, reversible
   rejection), and the delete dialog explains why: "This organization has 14
   facts and 2 verification decisions; those are kept by the governance
   rules. Remove it from the Directory instead."
3. **One writer.** The delete runs only in the backend's approved writer
   (`agents/enrichment/decisions.py`), never from the platform: it locks the
   record, re-checks every reference inside the transaction, removes the
   association rows, writes a tombstone, then deletes the row.
4. **The guard stays and gets one door.** The trigger still refuses every
   delete unless the same transaction declared
   `SET LOCAL ghus.permanent_delete = '<entity id>'` *and* wrote the tombstone.
   A stray `DELETE` from any other code or the SQL editor is still refused.
5. **Tombstone (kept forever).** `compass.deleted_record`: entity type and id,
   name, a JSON snapshot of the row, who deleted it, when, the reason, and the
   association rows removed. Permission `records.delete_permanent`
   (Admin and Editor/Reviewer); an audit entry `record.deleted_permanently`.

## Alternative (not recommended now)

Erasure in place: keep the id and history, blank the descriptive fields
("Deleted record"). It satisfies "nothing linked is lost" but is not a true
deletion, and every reader would need to hide such rows.

## Decision needed from the schema owner

- Approve recommendation 1 to 5 (or the alternative), and which association
  tables may be removed with a record.
- Then: apply 710 in an isolated database, run its tests, apply to Supabase
  after a backup with a ledger entry. Phase 6 builds the writer and the dialog.
