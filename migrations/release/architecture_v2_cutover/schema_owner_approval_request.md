# Schema-owner approval request — Architecture V2 cutover

**Asked of:** the GHUS shared-database schema owner.
**Not asked:** any agent action on Supabase. Agents have only used local copies.

## What you would approve

1. Applying `release_manifest.json` (43 steps) in the stage order of `runbook.md`,
   with `scripts/architecture_v2_release.py`, after a fresh verified backup.
2. Three deviations from the original V2 contract, each forced by the real data:
   - **405 supersedes 400.** Legacy GHUS memberships were curated without a
     recorded source and partly without coordinates. 405 keeps every 400 rule
     but allows NULL `source_id` only for `legacy_membership_preserved` rows and
     NULL `outside_radius` only when the distance is unknown.
   - **500 keeps `record_verification` for person/event decisions** (with a
     CHECK that excludes actors) until Phase 14 gives them V2 event tables.
     Dropping it would break event verification.
   - **500 drops the transitional actor sync trigger** before the legacy columns
     (the original 500 failed on it).
3. New objects: `legacy_migration_record` (append-only), `us_state_alias`,
   `ghus_plain_text` / `ghus_normalize_*` functions, `actor_read` view,
   `ghus_pre_cutover_data_loss_audit()`, `architecture_v2_cutover_baseline`,
   review kind `relationship_review`.
4. The repository rule `*.sql text eol=lf` so checksums are identical on every OS.

## What you would attest before 500

That `SELECT * FROM ghus_pre_cutover_data_loss_audit()` returns only passed rows
on production, with the saved output's SHA-256 in the attestation row.

## Approval file

The tool accepts a non-test target only with this file (`owner_approval.template.json`):

```json
{"approved_by": "<name>", "approved_at": "<ISO-8601>",
 "target_host": "<exact Supabase pooler host>",
 "release_manifest_sha256": "<sha256 of release_manifest.json>"}
```

Topic approval (`topic_approval.template.json`) is GHUS's, separate from this:

```json
{"approved_by": "<GHUS name>", "approved_at": "<ISO-8601>",
 "topic_proposal_sha256": "<sha256 of docs/evidence/phase12_topic_proposal.csv>"}
```
