# Architecture V2 cutover release package

Everything the schema owner needs to move the shared GHUS Supabase database to
the Architecture V2 contract. **No agent has connected to Supabase.** Every step
below was rehearsed end to end on a local restore of the full production dump of
28 Sep 2026 (`ghus_production_full_20260928T170256Z.dump`, SHA-256 `08d9ce68…bf424b`).

| File | Purpose |
|---|---|
| `release_manifest.json` | the 44 ordered steps, stage, action and SHA-256 (built by `scripts/architecture_v2_release.py build`) |
| `runbook.md` | cutover-day order with exact commands |
| `preflight_checklist.md` | must all be true before the first statement |
| `post_apply_checks.sql` | read-only checks after each stage |
| `rollback.md` | recovery per stage |
| `schema_owner_approval_request.md` | what is asked of the schema owner, and the approval file format |
| `ghus_decisions.md` | the GHUS decisions of 2026-10-06 and how they are applied |
| `agent3_compatibility_note.md` | what Build the Map (Agent 3) depends on |
| `owner_approval.template.json`, `topic_approval.template.json` | approval file formats the tool verifies |
| `../../../docs/architecture_v2_colleague_cutover_contract.md` | application contract (updated for Phase 12) |

Apply with `scripts/architecture_v2_release.py` only. It verifies every file
checksum, applies one stage at a time, skips steps already applied with the same
checksum, never reads `DATABASE_URL`, and refuses any non-test target without an
owner approval file for this exact manifest and host.

## Checkpoint status (local evidence)

| # | Checkpoint | Status | Evidence |
|---|---|---|---|
| 1 | Data-loss audit passes | **PASS** on the full-dump copy and on the rehearsal (21/21, Python and SQL function) | `docs/evidence/pre_cutover_data_loss_audit_full_dump_2026-10-06.json`, `..._rehearsal_2026-10-06.json` |
| 2 | Phase 12 backfill passes on a production copy | **PASS** | `docs/evidence/phase12_policy_backfill_proof_full_dump_2026-10-06.json` |
| 3 | Migration 500 succeeds locally → clean V2 schema | **PASS** with the real GHUS decisions (attestation is a local test stand-in) | `docs/evidence/phase12_cutover_rehearsal_2026-10-06.json` |
| 4 | Full backend suite green on the clean schema | **PASS** 507 passed, 0 failed, 0 skipped (+5 release-gate tests) | `docs/architecture_v2_phase12_completion.md` §6 |
| 5 | Shared platform green on it | **PASS** Python 145 passed / 1 skipped, Node 24 passed, live smoke 8 passed on pre- and post-500 copies. `search_doc` embeddings not rebuilt locally (no pgvector) | same §6 |
| 7 | Backfill and full manifest idempotent | **PASS** 480/482/484 re-run no-op; all 42 SQL steps skipped on re-run | rehearsal evidence, `tests/db/test_phase12_legacy_preservation.py` |
| 8 | No blocking category / geography / data-loss issue | **PASS**: GHUS decisions of 2026-10-06 applied (491, 486); rehearsal reaches 500 with them, only the attestation is a local test stand-in | `ghus_decisions.md` |

Migration 500 is fail-closed: it requires a passed attestation **and** re-runs
`ghus_pre_cutover_data_loss_audit()` on the live data inside its own transaction.
