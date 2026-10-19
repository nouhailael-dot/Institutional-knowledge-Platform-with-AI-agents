# Human review workflow

## Safety model

Build the Map results remain in the local `RunStore`. The review service reads
those persisted result bundles and creates stable, run-scoped candidates in a
separate SQLite store (`.review/review.sqlite3`, or `REVIEW_STORE_DB`). It never
reruns an agent and never calls a model.

Candidate identity is derived from the source run, entity type, and stable
position in the normalized result collection. A unique database constraint
prevents repeated synchronization from enqueuing the same candidate. Normalized
people are preferred over nested actor people, so the organization-first result
model does not create duplicate person candidates.

The Review list synchronizes the same persisted `RunStore` on page load, then
throttles automatic synchronization for two minutes. Detail, edit, and decision
requests never trigger synchronization. A visible **Refresh now** control forces
a new synchronization, and the page shows the last successful PostgreSQL sync.
A result
used by future map-agent executions. A result becomes reviewable when its run
reaches a terminal state (`done`, `interrupted`, `cancelled`, `cost_unknown`,
`budget_stopped`, or `error`). Active and still-changing results are not exposed
prematurely. The synchronization is idempotent, so reopening or refreshing the
Review page does not duplicate candidates and does not trigger another agent
or web-search call.

`REVIEW_SOURCE_RUN_DB` may point to the `runs.sqlite3` file of a separate agent
checkout. That optional source is opened with SQLite `mode=ro` and
`PRAGMA query_only=ON`; it is never passed to startup recovery and is never
opened by `RunStore`. The currently configured original GHUS checkout can
therefore supply future completed or safely stopped results without the Review
application changing its job state.

The original open-web discovery pipeline uses PostgreSQL instead of the Map
RunStore. `REVIEW_SOURCE_POSTGRES_ENV_FILE` may point to that checkout's private
`.env`, or `REVIEW_SOURCE_DATABASE_URL` may contain a dedicated read-only role.
Review forces `default_transaction_read_only=on`, verifies the server setting,
rolls the transaction back, and has no mutation methods. It imports rubric-band
rows from `search_candidate` plus pending `event_review_queue` and
`person_review_queue` rows. Stable source identifiers make repeated refreshes
idempotent. Queue evidence, rubric scores, reranking, qualification paths, and
person identity outcomes remain visible as agent metadata.

Optional-source failures do not erase already copied local review work. The API
returns an explicit synchronization warning and the Review page displays it;
local storage failures still fail closed with HTTP 503. Demo mode never opens
the PostgreSQL source.

The queue stores the immutable original payload separately from its editable
review payload. Evidence and agent-only metadata—verification, judge output,
ranking, uncertainties, missing fields, and map-level coverage notes—are
preserved but cannot be written into canonical entity columns.

## Decisions

Each actor, event, and person supports four explicit decisions: same as an
existing record, new record, reject, and defer. Same-existing requires a target;
reject requires one fixed reason (and free text for `Other`). Actor admission
also accepts existing hub assignments or a proposed hub. Proposed hubs enter
`proposed_hub` only and never create a canonical hub.

The detail pane shows the corrected final record, rubric evidence item by item,
score breakdown, qualification paths, rerank metadata, source URLs, and the top
existing matches with field differences. Edits are validated against the GHUS
model lengths before submission.

All decisions require reviewer attribution, confirmation, and an idempotency
key. The application sends them to `python -m agents.review.admission`, which
owns one PostgreSQL transaction but delegates every canonical entity or
relationship write to the original `agents.discovery.promote.promote()` path.
The canonical change, provenance, decision audit, and queue status therefore
commit or roll back together. Same-existing absorbs only empty fields. New
records still pass the frozen entity resolver and thresholds.

Rejection writes the exact state `rejected_by_reviewer` to both the candidate
and the durable `review_rejection` table. It never writes any canonical table.

The application does **not** treat local storage as a successful production
admission. The local candidate is finalized only after GHUS returns a committed
outcome. A failure leaves it pending and records a visible retry-safe error.
Production decisions are fail-closed unless the emitted migration has been
applied and all dedicated-writer settings are present. The SQLite canonical
mirror remains test/demo-only.

## Local demonstration with real examples

The repository includes two copied, source-backed example result bundles for
Form Energy, MIT Energy Initiative, their public leaders, The Battery Show, and
the ARPA-E Energy Innovation Summit. They retain official evidence links and
agent-style judge, verification, uncertainty, and coverage metadata.

From the project root, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_review_demo.ps1 -Reset
```

Then open `http://127.0.0.1:8000` and select **Review**. The launcher explicitly
disables `.env` loading, blanks live database and provider credentials, disables
map research, seeds `.demo/map-runs.sqlite3` and `.demo/review.sqlite3`, and
enables approval only against the local SQLite canonical mirror. `-Reset`
recreates only these two ignored demonstration database files.

## Deployment prerequisite

The database owner must review and apply `sql/review_workflow.sql` (the same
contract emitted as `agents/sql/180_review_admission_workflow.sql` in the
isolated GHUS feature branch). No migration was run by this implementation.
After applying it, configure:

- `GHUS_ADMISSION_PROJECT_ROOT` to the isolated reviewed GHUS checkout;
- `GHUS_ADMISSION_PYTHON` to that checkout's Python interpreter; and
- `REVIEW_ADMISSION_DATABASE_URL` to a dedicated least-privilege writer role.

The implemented adapter:

1. keep candidate row locking, duplicate checks, canonical inserts, provenance,
   and the review decision in one PostgreSQL transaction;
2. use the original entity-resolution implementation and thresholds;
3. use fixed per-entity column allowlists and parameterized values;
4. preserve the original verification-status vocabulary;
5. write sources and required relationship rows in the same transaction;
6. leave search indexing to the existing ETL by marking its established dirty
   queue, if applicable; and
7. uses credentials separate from the read-only source URL.

Until those prerequisites are deliberately enabled, every authoritative button
remains visibly disabled/fail-closed. No live schema or source data was changed
by this implementation.
