# GHUS backend reconciliation — 22 October 2026

## Outcome and Pull Request readiness

`integration/ghus-complete` is ready for a **review Pull Request**, with the
database validation gap below explicitly disclosed. It is not verified for
deployment or production database writes. Nothing was pushed and no PR was
created or merged.

This completes the runtime follow-up planned in `GHUS_INTEGRATION_REPORT.md`.
The backend remains under `ghus-backend/`; no backend tree was merged into the
platform root. Existing discovery/promotion, enrichment, Review, frontend/API,
retrieval, person-review and aggregate-exclusion contracts remain in place.
No dependency, schema, migration, frozen ER threshold or model changed.

## Inputs and preservation

- Starting platform branch: `integration/ghus-complete`, at completed Phase 12
  merge `728813ddd38080e70e3cd729c12dff2253db84a2`.
- Imported backend: `62e4008`. The backend tree in the starting merge exactly
  matched that commit's root tree.
- Published backend: `9640da0f18cbd7162ec64aabef379d1afb3ce85e`.
  Its difference from the import contains 19 files, 931 additions and 35 deletions.
- Source checkout: `C:\Users\Ismail\Projects\GHUS-Platform`, still at `9640da0`,
  with six modified tracked files and additional untracked work. Its index,
  working files and branch were not reset, staged, overwritten or committed.
- A 29-file source snapshot was captured on 21 October in the integration
  worktree's ignored `.demo/backend-reconciliation-source/` directory. Two files
  subsequently changed in the source checkout: `agents/common/fact_parts.py`
  and `tests/agent/test_fact_parts.py`. Those 22 October revisions were separately
  snapshotted, reviewed and incorporated. The original snapshot remains intact.
- The committed [source inventory](evidence/ghus_backend_reconciliation_sources.json)
  records capture times, input SHA-256 hashes and inclusion decisions. All 29
  source paths matched the latest reviewed hashes at the final preservation check.
  The hashes describe source inputs, before the adaptations described below.
- Remote references were refreshed on 22 October. `origin/main` remains
  `ece3aaef0694c58bd814f2abcd9eb3485de7d7f2`; `origin/ghus-backend` remains
  `9640da0`. There were no new main commits outside the integration branch.

## Incorporated backend changes

Paths in this table are relative to `ghus-backend/`.

| Files | Incorporated behavior |
| --- | --- |
| `agents/collection/actor_updates.py`, `tests/agent/test_actor_updates.py` | Category-based specific updates; ordering actors by missing facts; one-time update history; inactive-topic annotations; structured comparisons and additional facts; carry-forward of facts not restated; blocked-site previews; fallback source/access records; readable failures. Existing GHUS-reviewed facts retain their protection. |
| `agents/collection/light_pull_reader.py`, `tests/agent/test_light_pull_reader.py` | Contact-page fallback, normalized US locations, dated recent-activity checks, structured fact parts, checked multi-quote evidence, required-core checks, and source/confidence annotations. Missing or rejected evidence does not become an invented fact. |
| `agents/collection/site_access.py`, `tests/agent/test_site_access.py` | Record website refusals and cooldowns; respect access refusals; try pages on the parent organisation's domain, then at most one web search when enabled; require pages to identify the organisation; distinguish official, parent, government and third-party sources. |
| `agents/common/fact_parts.py`, `tests/agent/test_fact_parts.py` | Validate individual named parts against quotes, compare numbers/names/lists, distinguish additions from changes, and mark carried-forward facts. The 22 October follow-up reduces changes caused only by reworded descriptive text or a reworded match explanation with the same strength. |
| `agents/collection/light_pull_candidates.py`, `agents/config/sources.yaml` | Connect fallback reading to the existing reader and cost meter, with the new source configuration. Existing commands still require explicit live execution for persistence. They were not executed. |
| `agents/enrichment/decisions.py`, `agents/review/admission.py`, `tests/agent/test_agents_enrichment_phase4.py`, `tests/integration/test_functional_actor_updates.py` | Human-reviewed “keep both locations” through the existing enrichment writer and admission transaction; retain the current fact pointer, add the proposed sourced location and resolve the review. Also incorporates the separate legacy-state SQL parameter fix and associated backend tests. |

## Integration adaptations and safeguards

- `backend/app.py`, `src/review/store.py`, `frontend/review.js`: add an optional
  `keep_both` flag to the existing admission API. The UI presents it only on
  location fact reviews. The store validates that restriction and translates the
  existing positive decision into `resolve_fact`, `accept=false`, `keep_both=true`.
  Existing clients retain the default `false` behavior and the existing decision
  enum/audit schema remains usable. No new canonical writer or endpoint was added.
- The enrichment writer checks the proposed fact's actor/key, source and current
  pointer; rejects stale reviews; validates US locations with the gazetteer; locks
  the actor before checking for duplicates; asserts insert/update row counts; and
  keeps review resolution in the admission transaction. Replayed resolved items
  do not write again. The current location pointer is not moved by “keep both”.
- The Light Pull reader now enforces **three fetch calls total**, including failed
  calls and parent-site probes. Fallback search is still capped at one call and
  uses the existing cost meter. Robots requests and transport-level retries are
  handled by the existing HTTP source; this is a page-fetch budget, not a count of
  individual network packets. Tests were adjusted to verify the actual bound.
- Reject more than four evidence quotes instead of accepting a value supported
  by a fifth quote that would be discarded from stored evidence. Error responses
  retain the exception type without copying raw exception text into diagnostics.
- The descriptive-word comparison requires nonempty meaningful word sets; changed
  figures remain changes. Social-site filtering matches host label boundaries.
- `frontend/discovery.js`: expose “Additional” results, one-time history,
  inactive-sector notices, source types and access attempts. Display unreadable
  source errors and label values kept from earlier readings. Update the preview
  wording to disclose fallback sources and search.
- Added `tests/agent/test_backend_reconciliation.py` for stale pointers, wrong
  actors/fields, missing sources, duplicate locations, dry runs, replay, rowcount
  failures and admission commit/rollback calls. Platform API/store tests exercise
  the real local Review store with a mocked backend bridge. JavaScript tests cover
  the eligible Review action and expanded Discovery outcome/value formatting.

## Reviewed exclusions

These inputs remain preserved in the separate backend checkout and were not
needed for the requested runtime reconciliation:

| Inputs | Treatment |
| --- | --- |
| `alembic.ini` | Keep the integration configuration; do not import a machine-specific connection setting. |
| `migrations/versions/c4e8a1d9f206_add_event_content_fields.py` | Whitespace-only difference; leave unchanged. No migration executed. |
| `src/ML/entity_resolution/er_description_features.py` | Comment-only difference; leave frozen ER code unchanged. |
| `docs/adr/002-data-quality-findings.md`, `003-institutional-partner-sidecar.md`, `docs/evidence/hub_real_world_shortlist.md`, `docs/phase-4-plan.md` | Historical architecture/data-quality material; retained at source, not represented as current integration decisions. |
| `evals/actor_type_gold.jsonl`, `entity_extraction_gold.jsonl`, `evals/run_researcher_eval.py`, `scripts/smoke_test_actor_merge.py` | Separate evaluation/operational material; not copied or run. |
| Untracked `scripts/evaluate_actor_pipeline.py`, `scripts/light_pull_second_pass.py`, `tests/demo/` | Separate evaluation, second-pass and seed utilities; not runtime dependencies; not copied or run. |
| Untracked `.claude/`, `CLAUDE.md`, `docs/codex_prompts/`, cutover attestation/audit drafts | Local agent configuration and historical drafts; left in source. |

## Validation

Final runs use synthetic/mocked inputs and the existing offline harness. It
disables dotenv loading and automatic verification, removes service credentials,
and blocks actual Python service connections. A placeholder model key permits
mock clients to initialize. The Windows event-loop private socketpair remains
available. No live model, search, discovery, enrichment or verification agent ran.

| Suite | Final result |
| --- | --- |
| Platform `tests` | **421 passed**, **30 subtests passed**, **9 skipped** |
| Backend `tests/agent` and `tests/integration` | **882 passed**, **44 skipped**, 2 existing SQLite datetime deprecation warnings |
| JavaScript `tests/*.mjs` | **106 passed**, no failures or skips |

Commands (use the platform virtual environment for the first command and the
backend virtual environment for the second):

```powershell
python scripts/test_offline.py tests -q --tb=short -rs
# From ghus-backend:
python ../scripts/test_offline.py tests/agent tests/integration -q --tb=short -rs
# From the platform root:
node --experimental-vm-modules --test --test-concurrency=1 --test-reporter=spec tests/*.mjs
```

An initial sandbox run could not access pytest's temporary directory; the final
runs had normal temporary-file access. One initial JavaScript assertion listed
only the old outcome groups; it now includes and checks “Additional”. Neither
initial run is presented as passing evidence.

### Unverified database behavior and remaining limits

- On 22 October, the isolated `127.0.0.1:55432` port was reachable, but a bounded
  read-only PostgreSQL connection to `ghus_v2_test` failed with `OperationalError`.
  Neither isolated-test URL was configured. No production URL was loaded to
  substitute for it, no credentials were printed, and no database was modified.
- All 44 backend skips require isolated PostgreSQL settings: 2 architecture
  proofs plus 42 integration cases. The 9 platform skips are the V2 Review API
  proof and 8 pre/post-cutover smoke cases. **Skipped tests are unverified, not
  passed.** SQL type compatibility, row locking/concurrency, real rollback and
  migration-ledger compatibility remain unverified. Mock rollback assertions
  establish orchestration behavior only.
- An authenticated isolated database with the expected schema/fixture snapshot
  is required before merge/deployment approval. Check its migration ledger and
  run the matching actor-update/Review database tests. Do not blindly reapply
  existing migrations or execute historical operational scripts.
- Structured comparison uses deterministic word/number heuristics, not semantic
  proof. Descriptive rewording with sufficient overlap may count as corroboration.
  Fallback page identity and evidence checks reduce ambiguity but do not establish
  that every third-party page is authoritative. No live-service evaluation or
  browser acceptance session was performed.
- “Keep both” can place US locations only. Unsupported/non-placeable locations
  fail explicitly and retain the existing Review choices.

Final checks cover an empty unmerged index, whitespace/conflict markers, changed
file credential patterns and source preservation. The implementation is committed
locally on the integration branch. Publishing the branch, opening its review PR
and satisfying the isolated-database gate are the remaining handoff steps.
