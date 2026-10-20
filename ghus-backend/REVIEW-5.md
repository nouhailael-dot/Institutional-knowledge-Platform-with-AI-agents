# REVIEW-5.md

Adversarial review of the current branch working tree after Phase 5. No fixes were made.

Scope caveat: the repo is on `main` with a broad dirty worktree, including Phase 1-5 agent files and unrelated modified/untracked project files. I reviewed the branch state that would be merged, not only the reporting-agent files.

## Findings

### F-01 - Scheduled workflow runs live writes without an explicit human live flag

- File and line: `.github/workflows/weekly-discovery.yml:39`
- Severity: severe
- Violated constraint: Constraint 3, dry-run is the default and live writes require an explicit `--live` flag.
- Failure in production: every scheduled Monday run sets `LIVE_ARG="--live"` when `GITHUB_EVENT_NAME` is `schedule`, then passes it to discovery, enrichment, and index refresh. That means production writes happen automatically on the cron path without a human explicitly opting into a live run. A bad extraction, bad enrichment candidate, or bad index refresh would be written weekly by default.

### F-02 - Discovery dry-run does not exercise the live DB path

- File and line: `agents/discovery/run.py:114`, `agents/discovery/run.py:129`, `agents/discovery/promote.py:51`
- Severity: severe
- Violated constraint: Constraint 3, dry-run must exercise the same code path as live, differing only at the commit boundary.
- Failure in production: dry-run uses `InMemoryRunLog`/`InMemoryStageStore`, never loads live event candidates, and `promote()` returns before source insertion, canonical insert/update, or transaction handling. Dry-run can route a record as `create` against an empty candidate list while live would route against existing events, and dry-run cannot catch schema, provenance, transaction, or constraint failures that live will hit.

### F-03 - Event routing bypasses the frozen ER combiner

- File and line: `agents/common/resolve_route.py:63`
- Severity: moderate
- Violated constraint: Constraint 2, entity resolution runs at ingest before insert and agents call the existing frozen combiner/thresholds rather than their own matching logic.
- Failure in production: `route_event()` uses deterministic natural-key matching with hardcoded scores `1.0` and `0.0`, then runs those through actor ER thresholds. The frozen combiner is never called for event ingest. Any event title/date variant that is not an exact natural-key match will be created as a new canonical event rather than entering the trained ER/review path.

### F-04 - Enrichment writes canonical entity tables outside `promote.py`

- File and line: `agents/enrichment/decisions.py:280`, `agents/enrichment/actor_adapter.py:137`
- Severity: severe
- Violated constraint: Constraint 1, `promote()` is the only permitted code path to INSERT or UPDATE canonical entity tables.
- Failure in production: enrichment can directly update any configured canonical table through `_update_canonical_gap()`, and the actor adapter mutates `Actor` ORM fields directly. This bypasses the single promotion gate, so canonical writes can happen without the ingest ER/provenance/write discipline that `AGENTS.md` treats as a compile error.

### F-05 - Actor enrichment can overwrite a non-null value from stale ORM state

- File and line: `agents/enrichment/actor_adapter.py:121`
- Severity: severe
- Violated constraint: Constraint 6, never overwrite a non-null value automatically; enforce immediately before the write.
- Failure in production: the actor adapter checks `getattr(actor, field)` and then `setattr(actor, field, ...)` on an ORM object. There is no `SELECT ... FOR UPDATE` and no SQL `WHERE field IS NULL/empty` guard immediately before the flush. If another process fills the field after the actor was loaded, this path can overwrite the newer non-null value.

### F-06 - Enrichment field proposals do not create a `source` provenance row

- File and line: `agents/enrichment/decisions.py:176`, `agents/enrichment/decisions.py:188`
- Severity: moderate
- Violated constraint: Constraint 5, every written fact has a provenance row with source URL and fetch timestamp in the same transaction.
- Failure in production: `record_field_proposal()` creates a synthetic `staged_record` and a `field_proposal`, but it does not insert a `source` row. The proposal has a `source_url` string, but not the repo's provenance row with retrieval timestamp/trust metadata. A reviewer could approve a proposed fact without the required source-row provenance trail.

### F-07 - Search index refresh dry-run skips the write path

- File and line: `agents/index/refresh.py:61`
- Severity: severe
- Violated constraint: Constraint 3, dry-run must exercise the same code path as live except commit boundary.
- Failure in production: dry-run counts candidates but does not execute `_upsert_search_doc()`. It therefore cannot catch SQL errors, missing columns, conflict behavior, invalid UUID casts, or malformed `doc_text` issues that the live run will hit.

### F-08 - Search index writes derived facts with no provenance row

- File and line: `agents/index/refresh.py:178`
- Severity: moderate
- Violated constraint: Constraint 5, every written fact has provenance in the same transaction.
- Failure in production: `_upsert_search_doc()` inserts/updates `search_doc` text without recording any source/provenance row or source URL. When RAG answers cite a `search_doc` result, there is no direct trail from the derived text refresh back to the canonical rows and source rows used to assemble it.

### F-09 - Reporting tool logging writes through the same read-only session

- File and line: `agents/reporting/loop.py:134`, `agents/reporting/loop.py:150`, `agents/reporting/logging.py:37`
- Severity: severe
- Violated requirement: Phase 5 query tools require a read-only role where one exists, while every tool call/result must be logged to `query_log`.
- Failure in production: the default loop opens one `readonly_session()` and uses the same session for `QueryLogToolLogger`. A strict read-only role will reject the first `INSERT INTO query_log`, so the agent fails before or during the first tool call. If the role is granted `INSERT` on `query_log`, it is no longer strictly read-only for the session used by query tools.

### F-10 - Tool exceptions can leak secrets or connection strings into `query_log` and Claude context

- File and line: `agents/reporting/loop.py:210`, `agents/reporting/logging.py:47`, `agents/reporting/rag.py:58`
- Severity: severe
- Violated constraint: Constraint 9, never print connection strings or API keys in logs or error messages.
- Failure in production: the loop captures `str(exc)` from any tool and writes it into `query_log` and into the next Claude tool-result message. DB/driver/RAG errors can include hosts, usernames, DSNs, or other sensitive details. The RAG sanitizer only redacts secrets visible in the parent process environment, not secrets loaded by the sibling process from its own `.env`.

### F-11 - `rag_search` delegates to a subprocess that can use the sibling repo owner connection

- File and line: `agents/reporting/rag.py:32`
- Severity: moderate
- Violated requirement: Phase 5 requires curated reads and the read-only role where one exists; missing read-only connection must raise rather than falling back.
- Failure in production: `RagSearchAdapter` shells into the sibling repo and imports `src.retrieve`. That sibling DB module reads `DATABASE_URL`, not this package's read-only URL contract. The reporting loop may satisfy its own read-only check while `rag_search` still reads through whatever owner connection is configured in the sibling repo.

### F-12 - Generated DOCX/PPTX/PDF artifacts are generated from hand-rolled packages, not filled document templates

- File and line: `agents/reporting/artifacts.py:131`, `agents/reporting/artifacts.py:160`, `agents/reporting/artifacts.py:207`
- Severity: moderate
- Violated requirement: Phase 5 says document builders fill templates in `agents/reporting/templates/` rather than generating files from scratch.
- Failure in production: the builders read small XML/text fragments, but then construct `.docx`, `.pptx`, and `.pdf` package structure manually. This is not filling a real Office/PDF template, so branding/layout will not survive, and the minimal PPTX/DOCX packages may fail in PowerPoint/Word or render unpredictably.

### F-13 - `get_entity()` returns only the row-level `source_id`, not all provenance rows behind the entity/facts

- File and line: `agents/reporting/tools.py:286`
- Severity: moderate
- Violated requirement: Phase 5 `get_entity(entity_type, entity_id)` returns row plus its provenance rows; Constraint 5 expects provenance behind written facts.
- Failure in production: an actor can have capability facts, relevance rows, partnership profiles, or evidence URLs with their own provenance, but `get_entity()` only follows the entity row's single `source_id`. Reports that rely on `get_entity()` will cite incomplete provenance and make fact-level audit impossible.

### F-14 - Non-actor enrichment reports success even though no enrichment adapter exists

- File and line: `agents/enrichment/run.py:72`
- Severity: minor
- Violated constraint: Constraint 7, silent or misleading no-ops must be loud and count-based.
- Failure in production: for `hub`, `event`, and `person`, the CLI counts sparse rows, logs one warning, then closes the run as `succeeded`. A weekly or UI caller can treat that as completed enrichment even though no candidate generation, proposal creation, or review routing occurred.

## Checklist Notes

- No hardcoded deployed ER HIGH/LOW values were found under `agents/`; `agents/common/resolve_route.py` loads them from `config/er_production.json`. Test files do hardcode toy thresholds, which is acceptable for unit boundaries.
- I did not find `hub_overlap` added to the agent ER feature path.
- I did not find an SMTP/send-mail path. `draft_email()` returns an object only.
- I did not find `search_doc_2` usage in the new `agents/index/refresh.py`, but old maintenance scripts still reference it outside this phase.

## Tests Not Covering Enough

- No test proves dry-run and live execute the same DB statements and differ only by commit/rollback.
- No test catches that dry-run discovery routes against `[]` while live routes against real event candidates.
- No test blocks canonical table updates outside `agents/discovery/promote.py`.
- No test simulates concurrent enrichment where a field becomes non-null after actor load but before ORM flush.
- No test asserts every field proposal has a `source` provenance row, not only a `source_url` string.
- No test verifies `search_doc` upserts have provenance or that dry-run executes the same upsert SQL.
- No test runs the weekly workflow logic and asserts scheduled runs default to dry-run.
- No integration test uses an actual read-only DB role and verifies query tools can read while tool logs are still written.
- No test checks that tool exceptions are sanitized before being logged to `query_log` or sent back to Claude.
- No test validates `rag_search` uses a read-only connection in the sibling repo or preserves the sibling OR tsquery behavior end-to-end.
- No test opens generated `.docx`, `.pptx`, or `.pdf` files in real renderers; current tests only check file existence.
- No test verifies generated artifacts cite every numeric claim in free-text body content.
- No test verifies `get_entity()` returns sidecar/fact-level provenance rows.
- No test asserts no-op warnings are emitted and surfaced as failed/attention statuses when non-actor enrichment has no adapter.
- No test asserts secrets are absent from workflow logs, query logs, exception payloads, digest files, or artifact contents.
