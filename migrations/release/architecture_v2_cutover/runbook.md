# Cutover runbook (schema owner)

Run from a clean checkout of `codex/architecture-v2` at the commit that holds this
package. The target URL lives in a dedicated variable, never `DATABASE_URL`:

```bash
export GHUS_RELEASE_DATABASE_URL='<owner session-pooler URL>'   # never echo it
python -m scripts.architecture_v2_release plan                   # verifies all 43 checksums
```

Every `apply` below needs `--database-url-env GHUS_RELEASE_DATABASE_URL --owner-approval owner_approval.json`.
Run `post_apply_checks.sql` (read-only) after each stage and stop on any surprise.

## Day 1 — expand and backfill (applications keep running)

1. **Fresh verified backup.** Take a full Supabase backup, download it, record its
   SHA-256, and prove it restores into a scratch database (row counts match).
   Nothing proceeds without this.
2. `apply baseline` — records actor/hub/hub_actor/event row counts.
3. `apply expand` — 32 additive steps (190…430, 440, 470). Current apps are unaffected.
4. `apply gazetteer` — loads the vendored Census Places table (checksum-verified).
5. `apply backfill` — 480 status/category, 482 legacy preservation, 484 category
   proposals, 488 `actor_read`, 489 audit function + baseline.
6. Data-loss audit (read-only): `SELECT * FROM ghus_pre_cutover_data_loss_audit();`
   Every row must be `passed = true`. Save the output as an artifact.
7. `apply validate` — 490.

## Day 1 — switch both applications

8. Deploy the backend (`codex/architecture-v2`) and the shared platform
   (`feature/ismail-modifications`, incl. the `claude/phase12-shared-review` commits).
   Both read schema-neutrally and work before and after 500.
9. Smoke: Browse, Ask (status labels), SQL Ask via `actor_read`, Review
   (category panel lists 58 rows), Build the Map, discovery dry run.

## GHUS review window (production stays in this state until done)

10. GHUS confirms the 58 categories in Review, decides the 156 aggregate
    dispositions, approves the topic CSV and decides "Mining Hubs"
    (`ghus_decisions.md`). Then re-run step 6; it must still pass.

## Day 2 — contract and cutover

11. `apply topic --topic-approval topic_approval.json` — 486.
12. `apply contract` — 405, 410, 495. 495 fails until every category review is resolved.
13. Re-run the audit (step 6). If all rows pass, the schema owner records the attestation:
    ```sql
    INSERT INTO architecture_v2_cutover_attestation
      (audit_name, artifact_sha256, passed, approved_by, approved_at, details)
    VALUES ('pre_cutover_data_loss_audit', '<sha256 of the saved audit output>', true,
            '<schema owner name>', now(), '{"backup_sha256": "<step 1 sha256>"}');
    ```
14. `apply cutover` — 500. It refuses without the attestation and re-runs the
    audit on the live data inside its own transaction.
15. Smoke both systems again (step 9) plus `post_apply_checks.sql` §cutover.
16. Rebuild `search_doc` from the shared repo (`python -m src.embed`) so Ask
    embeds the status-labelled documents.
