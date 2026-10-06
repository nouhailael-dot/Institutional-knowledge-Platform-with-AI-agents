# Architecture V2 Phase 12 — full-dump source rebuild

Date: 2026-10-06
Production: untouched (no Supabase connection, DDL or write)

Evidence:

- `docs/evidence/phase12_dry_run_full_dump_2026-10-06.json`
- `docs/evidence/phase12_policy_backfill_proof_full_dump_2026-10-06.json`
- `docs/evidence/pre_cutover_data_loss_audit_full_dump_2026-10-06.json`

The 6 Oct evidence files from `ghus_v2_phase12_report_test` /
`ghus_v2_phase12_policy_test` are kept unchanged for comparison.

## Source

`C:\Users\Ismail\GHUS-data\backups\ghus_production_full_20260928T170256Z.dump`

- SHA-256 verified: `08d9ce68efae470f553cb4d8b0324c0c570f7037450d8af38b5a43da07bf424b`
  (matches the dump manifest).
- Custom format, 682 TOC entries, dumped from PostgreSQL 17.6, alembic head
  `f6b9a8c7d2e1`.

## Isolated databases (localhost:55432, PostgreSQL 17.5)

| Database | State |
|---|---|
| `ghus_v2_phase12_full_test` | full dump → checkpoint `target_prebackfill_phase11` → 440, 470, 480, 490 |
| `ghus_v2_phase12_full_prebackfill_test` | template snapshot at `target_prebackfill_phase11` (before 440) for re-runs |

Only the `public` schema was restored (`--no-owner --no-privileges`). The
Supabase `auth`, `storage`, `realtime` and `vault` schemas were deliberately not
restored. `pgcrypto` and `uuid-ossp` were created in an `extensions` schema to
match Supabase.

Restore errors: 13, all from `search_doc` — the local cluster has no
`pgvector`, so the `vector` type, the table, its data and its indexes were not
restored. `search_doc` is a derived index rebuilt from facts in step 6.4; its
production row count is unverified here.

## Row counts (full dump vs. the 6 Oct report copy)

| Table | Full dump | 6 Oct copy |
|---|---:|---:|
| actor | 965 | 965 |
| source | **1,586** | 0 |
| actor_profile | **952** | 0 |
| actor_capability_fact | **5,712** | 0 |
| organization_hierarchy | **42** (16 parents, 41 children) | 0 |
| record_verification | table not present in production | 0 |
| actor_sector | 0 | — |
| hub_sector_strength | 0 | — |
| sector | 10 | — |
| hub | 49 | 49 |
| hub_actor | 821 | 821 |
| event | 356 | 356 |
| event_review_queue | 9 | — |
| person_review_queue | 0 | — |
| review_queue | 280 | — |
| search_doc | not restored (pgvector) | absent |

Other non-empty production tables: search_candidate 8,821, staged_record
7,286, raw_document 849, discovered_domain 295, actor_evaluation 158,
index_dirty 138, actor_relevance 130, scrape_run 120, event_scoring 87,
event_sector 87, actor_merge_log 80, partnership_profile 28, query_log 7,
schema_migrations 4, challenge 1.

## Finding: the "unrecoverable provenance" was an artifact of the copy

- 958 actors carry a `source_id`; 846 distinct; **all 958 resolve** to an
  existing `source` row. Unrecoverable provenance: **958 → 0**.
- actor_profile rows missing a source: 2 of 952.
- capability facts missing a source: 42 of 5,712; missing an evidence URL:
  894 of 5,712.

These rows must be migrated in step 3, not declared unrecoverable.

## Data-loss audit on the full copy

Backfill proof: **passed** (965 verified, 965 honest bootstrap events, 751
mapped + 214 category review, 49/821/356 invariants).

Data-loss audit: **failed**, 13 blocking checks (6 Oct: 10):

- unchanged from 6 Oct: legacy status (958), state normalization (912), and
  the eight scalar fields (961/960/965/953/955/952/67/965);
- new, because the rows now exist: `organization_hierarchy` 42,
  `actor_profile` 952, `actor_capability_fact` 5,712.

## Other differences vs. the 6 Oct copy (schema state, not data)

1. **Categories: same.** The legacy `actor_type` gives the same 214 unmappable
   values (187 `aggregate`, 13 `other`, 12 null, 2 `Organization`).
2. **Legacy status: matches the plan.** `verification_status` is 834
   `ai_inferred`, 97 `phase_1`, 27 `needs_review`, 7 null. Migration 200
   derives `record_status` from it (861 parked, 97 imported, 7 null).
3. **Hub radius: not legacy data.** The production `hub` table has no radius
   column. The 6 Oct copy's "all 49 hubs keep the legacy 200-mile radius" came
   from the canonical manifest's `v2a02_hubs` default (`NOT NULL DEFAULT 200`).
   The isolated functional manifest (`220-canonical`) adds a nullable radius,
   so the full copy has 0 hubs with a radius.
4. **Event status/origin: not legacy data.** Production `event` has no
   `record_status` / `source_origin`. The 6 Oct copy's 356 `imported/imported`
   came from the `v2a04_events` defaults; the functional manifest leaves them
   null (356 missing).
5. `alternate_names`: no content in either copy (965 empty arrays vs. 965
   nulls).

Items 3 and 4 mean the canonical manifest (`manifest.json`, 001–021) and the
functional manifest (`functional_v2_isolated_manifest.json`) produce
different data on the same source. The release package (step 7) must pick
one path. The 200-mile radius and `imported` event status are migration
policy defaults, and need to be documented as such.

## Script changes

`scripts/phase12_dry_run_report.py` and `scripts/phase12_policy_proof.py` now
accept a fixed allowlist of isolated databases (6 Oct copy and full copy),
each writing its own evidence file; the localhost/55432 guard is unchanged.
The dry run now counts unrecoverable provenance as `source_id`s whose source
row is missing, not "all source ids when the source table is empty".

## Validation

- `ruff` and `py_compile` on both scripts: passed.
- `tests/db/test_architecture_v2_phase12_policy.py` +
  `tests/integration/test_functional_v2_phase12.py`: **11 passed**.
