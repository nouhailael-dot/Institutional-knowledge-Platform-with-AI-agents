# GHUS Agents Layer

Phase 1 is a single vertical slice: one source adapter (`climate_week`), one entity type (`event`), and deterministic event routing. Phase 2 adds weekly unattended execution, content-hash change detection, replay from stored raw content, and a short weekly digest. Phase 4 adds the generalized enrichment policy layer and incremental `search_doc` refresh.

The reporting agent is out of scope. Agent 3 is new-sector discovery, owned by a teammate. Reporting code is preserved on branch `shelved/reporting-agent`.

## Run

Dry-run is the default:

```powershell
python -m agents.discovery.run --source climate_week --entity event
```

Use `--out path/to/audit.csv` to choose the audit CSV path and `--digest-out path/to/digest.md` to choose the weekly digest path. Use `--limit N` to cap discovered URLs. `--live` is the only flag that enables database writes.

## What Dry-Run Does

Normal dry-run uses the configured database for run logging, raw-document storage, staging, and candidate loading. That is intentional: dry-run must route against real candidates and exercise the same promotion statements as live. Canonical promotion and `search_doc` refresh differ from live only at the final boundary: dry-run rolls back and live commits.

Use `--offline` only for tests and local fixture runs. Offline mode uses fixture URLs, fixture extraction responses, in-memory run/stage stores, and no database session.

## Replay

Replay re-extracts from `raw_document.storage_path` and does not call the source adapter or network:

```powershell
python -m agents.discovery.run --replay <run_id>
```

`--source` and `--entity` are optional in replay mode when the original `scrape_run` row is available. Replay is dry-run unless `--live` is explicitly supplied.

## Change Detection

Before extraction, the runner checks whether `(url, content_hash)` already exists in `raw_document`. If it does, extraction is skipped and the run increments `skipped_unchanged`. This is the weekly cost control path: unchanged pages should produce zero LLM calls.

Fetched content is written under the configured `raw_storage_dir` and the path is stored in `raw_document.storage_path`, so extraction can be replayed without refetching.

## Weekly Schedule

`.github/workflows/weekly-discovery.yml` runs every Monday at 06:00 UTC and can also be started manually. Scheduled runs are dry-run. Live writes require manual `workflow_dispatch` with the `live` input set to true. The workflow runs discovery, deterministic actor profile enrichment, then incremental `search_doc` refresh. It uploads the discovery audit CSV and digest as artifacts.

## Sector-Discovery Handoff

Discovery stages every extracted record. Records whose `sector_codes` match the seeded sector list continue to routing with `sector_match = 'in_sector'`. Records with no seeded-sector match are staged with `sector_match = 'out_of_sector'` and `status = 'out_of_sector'`; they are never routed or promoted.

The teammate-owned sector-discovery agent reads `staged_record WHERE status = 'out_of_sector'`. It does not write to any table owned by this pipeline.

## Enrichment

Generalized enrichment entry point:

```powershell
python -m agents.enrichment.run --entity actor --field-set profile --limit 10
```

`agents/config/fields.yaml` defines enrichable fields and per-field auto-apply floors. Fields without a floor are proposal-only. Person fields are proposal-only. Low-confidence or human-review candidates with a `source_url` become `field_proposal` rows in live mode.

The actor adapter preserves the existing `ActorEnrichmentCandidatePipeline` candidate generation and cost tracking. Other entity types currently have field policies and sparse-row gap detection, but no candidate adapter yet, so the CLI logs counts and attempts no writes for them.

## Search Index

Incremental refresh targets `search_doc` only:

```powershell
python -m agents.index.refresh --entity all --limit 500
```

Rows are selected when their canonical `updated_at` is newer than the visible `search_doc.updated_at`/`indexed_at` column, or when no `search_doc` entry exists. If the current `search_doc` table has no timestamp column, the refresh logs a warning and selects missing entries only. Zero candidates is a logged no-op and never deletes rows.

TEMPORARY: `index_dirty` exists because `event` currently has no `updated_at`, so successful agent creates/absorbs need a safe way to become visible to the incremental `search_doc` refresh without changing upstream canonical tables. Promotion marks `(entity_type, entity_id)` in `index_dirty` in the same transaction as the canonical write; refresh unions those rows into its candidates and clears each marker only after that row is successfully upserted into `search_doc`. Remove this table and fallback once the upstream `event.updated_at` column exists and the normal stale-row comparison covers event changes.

## Do Not Change Without Discussion

1. Scraped data lands in `staged_record`; canonical entity writes under `agents/` belong only in `agents/discovery/promote.py` and `agents/enrichment/decisions.py`. Both enforce gap-guarded automatic updates, rowcount assertions, and provenance in the same transaction. No other module may write canonical entity tables.
2. Entity resolution/routing runs at ingest before any canonical insert.
3. Dry-run is the default; live writes require explicit `--live`.
4. Empty result sets are no-ops, never deletes or replacements.
5. Entity writes and provenance writes happen in one transaction; provenance failure aborts the entity write.
6. Never overwrite a non-null value automatically; fill gaps only and propose suspected corrections for humans.
7. Event routing deliberately does not use the frozen ER combiner. That combiner was trained on actor name/profile features; applying it to events would be a training/deployment distribution mismatch, the same class of failure that previously forced `desc_both_present` out of the actor model when production null patterns diverged from the gold set.

## Phase 1/2 Notes

- The existing frozen combiner is trained on actors, so event routing does not use it. Events exact-match on `natural_key = normalized title + start date`; same-date fuzzy title matches go to the agent-owned `event_review_queue`.
- The existing `review_queue` table is actor-pair specific. Event review rows go to `event_review_queue` instead of extending that upstream table.
- The canonical `event` table has no `verification_status`, `confidence`, or `updated_at` columns, so Phase 1 cannot set `needs_review` on event rows without changing upstream schema.
- The agent SQL files are emitted under `agents/sql/`; the CLI does not run them.
