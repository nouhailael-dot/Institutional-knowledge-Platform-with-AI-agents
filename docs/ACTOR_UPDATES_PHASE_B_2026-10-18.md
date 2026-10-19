# Actor Updates — Phase B (batch and recurring) report, 2026-10-18

Phase B lets you keep **several actors**, or **one actor on a frequency**, up to date. It reuses the existing request scheduler; there is no new one. Everything was built and tested on the isolated clone `ghus_v2_actor_updates_test`. Production is untouched, and **migration 570 is a proposal that is not applied there**.

## 0. Before Phase B: preservation and the compatibility fix

**1. The pushed backend branch did not import.**

From a clean copy of `codex/architecture-v2` at `309f6ff`, `phase2.py`, `run.py` (the whole open-web discovery pipeline) and `light_pull_reader.py` failed with `ModuleNotFoundError`. The modules they import (`actor_currency`, `actor_official`, `discovery_request`) were never committed. They are now:

- `5faa9f0` commits them with the Discovery-request workstream they belong to: the request CLI and runner, migrations 550/560, the workflow, and the weekly sweep removal.
- `0e3f036` commits backend Phase A.

Both commits were checked from a clean copy of the tree: every module imports, and the agent suite passes (771, then 784).

**2. Everything else that was uncommitted is preserved, not committed.**

It is in a local backup branch, `backup/uncommitted-2026-10-18` (`b95d91c`), which holds the whole working tree including untracked files. Your branch and working files were not changed. The files left uncommitted on purpose, because they are outside this workstream and their origin predates this session:

- ADRs, `docs/phase-4-plan.md`, evidence notes
- eval data and the eval script
- the ER description features
- `alembic.ini` and one Alembic version
- `scripts/smoke_test_actor_merge.py`, the documented retired stub that breaks two guard tests
- two scripts, `tests/demo/`, `CLAUDE.md`, `.claude/`

**3. Browse on production (`2552a9c`, platform).**

After migration 500, Browse's actor query selected dropped or renamed columns (`verification_status`, `location_city`, `state`, `estimated_trl`). It raised `UndefinedColumn`, so the actor list was empty. Each column is now read through `to_jsonb`, with its V2 name as the fallback. After 500, the trust chip shows the V2 status (verified / parked / rejected) as recorded. This was verified on post-500 and pre-500 local copies.

Two other files still name the old column:
- `src/enrich/gaps.py`, which is used only by an offline enrichment script.
- `src/router.py`, the Ask SQL planner's schema text (the colleague's Ask area).

Neither was changed.

## 1. What Phase B adds

- **A request = one actor or a bounded group, once or on a frequency.**
  - Frequencies: weekly, every two weeks, monthly, quarterly.
  - Limits: a start date, a period (at most the configured 365 days), up to 10 actors per run, and a spend ceiling per run (at most $1.50, configurable).
  - It is stored as an `actor_update_subscription` with `requested_via = 'actor_updates'`.
  - A group needs a sector, so a request never sweeps the map. Type and state narrow it further.
  - Deep enrichment is refused for saved and group requests; it is asked for one actor at a time.
- **Gap-first selection.** A run reads the actors with the most missing or out-of-date boxes for the request's scope first. An actor with nothing to read is not read at all and costs $0. Actors over the cap wait for the next run. The preview says, actor by actor, who waits and why.
- **One scheduler.** `subscription_runner.run_due_requests` now runs Discovery requests and actor-update requests alike. The daily workflow stays plan-only, and live runs happen only on manual dispatch or "Run now".
- **The spend ceiling is enforced.** Each actor's read is capped at the smaller of the per-actor cap and what is left of the run's ceiling. When less than a cent is left, the run stops and says how many actors it did not reach. The true spend is recorded, and if one read overshoots, that is stated rather than hidden.
- **Partial failure.** One actor that cannot be read (for example a 403) does not stop the others. The run is "completed with limits" and gives the reason.
- **History.** Each run is one record in the run ledger, with its cost, pages, counts and per-actor results. Every fact it wrote carries the request. History is shown on the request card.
- **Aggregates never updated.** Aggregate placeholders are never updated (AGENTS rule 5). They are excluded from groups and refused for a single actor.

## 2. Where it is in the UI

Discovery → Actor updates:

- **One actor / Several actors.** Several: pick actors one by one, or choose a sector in the filters and tick "Update the whole group". The tick box sits above the search box, so the suggestions can never cover it.
- **The same "what to update" builder.** In this mode it also has the frequency, start, period, actors per run, spend ceiling and an optional name.
- **Request preview (free):** what will happen, how many actors match, who is read first and why the others wait, the cost from past reads, and the number of runs.
- **Save request / Save and run now.**
- **Update requests list:** status, next run, Run now / Pause / Resume / Cancel, and run history with each actor's result.

Choosing "Once" for one actor keeps the Phase A flow: check, review the findings, write.

## 3. Proven on the clone (live, real websites)

A request for Energy Transition companies, missing information, 2 actors, $0.10 ceiling, once, saved and run with "Run now" through the existing runner:

| Actor | Result | Spent |
|---|---|---|
| Chevron | 5 new facts, 4 recorded as not found | $0.031 |
| ArcelorMittal USA | site returned 403; reported, nothing written | $0.00 |

The run total was $0.031 against the $0.10 ceiling. It is recorded as "completed with limits", and the one-time request is now finished.

## 4. Migration 570 (proposal; apply only with approval)

Files:
- `GHUS-Platform/agents/sql/570_v2_actor_update_requests.sql`
- `GHUS-Platform/agents/sql/rollback/570_v2_actor_update_requests.sql`

It is additive:

- `update_options jsonb` (default `{}`)
- `max_usd_per_run numeric(8,4)`, with an outer bound of $5
- `requested_via` widened with `'actor_updates'`
- a check that an actor-update request always has a scope and a ceiling

Tested on the clone: it applies, re-applies cleanly, rolls back, and applies again. The rollback refuses to run if any actor-update request exists.

The application works without 570. The single-actor flow is unchanged, and saving a request says that 570 is needed. To apply 570 to production, use the same PowerShell setup as `DEPLOYMENT_550_560_2026-10-15.md`: pgpass file and `PGHOST` etc., never a password on the command line. Then:

```powershell
psql -Atc "SELECT 'has_570=' || (SELECT count(*) FROM information_schema.columns WHERE table_name='actor_update_subscription' AND column_name IN ('update_options','max_usd_per_run'));"
psql -v ON_ERROR_STOP=1 -f "C:\Users\Ismail\Projects\GHUS-Platform\agents\sql\570_v2_actor_update_requests.sql"
psql -Atc "SELECT 'has_570=' || (SELECT count(*) FROM information_schema.columns WHERE table_name='actor_update_subscription' AND column_name IN ('update_options','max_usd_per_run')) || ' via_check=' || (SELECT count(*) FROM pg_constraint WHERE conname='ck_actor_update_subscription_update_request');"
```

Expect `has_570=0` before, and `has_570=2 via_check=1` after. To roll back:

```powershell
psql -v ON_ERROR_STOP=1 -f "C:\Users\Ismail\Projects\GHUS-Platform\agents\sql\rollback\570_v2_actor_update_requests.sql"
```

## 5. Tests

Results:

- **Backend** (`ghus_v2_final_schema_test`, as the baseline): 860 passed, 24 skipped, 4 failed. The 4 failures are the documented baseline: the uncommitted `smoke_test_actor_merge.py` ×2, which are absent from the committed tree, and the two schema checks needing deferred migration 500.
- **On the clone with 570:** 24 passed, 7 skipped (actor updates, review decisions, request runner).
- **Platform:** pytest 307 passed, 1 skipped. Node UI tests: 25 + 6 + 9 + 56, all passed.

New tests:

- **Backend:**
  - request validation: unbounded, past-dated or deep requests are refused, as are a missing ceiling and a missing migration
  - plan ordering by gaps
  - save, pause, resume, cancel
  - a runner live run recorded as one run
  - spend-ceiling stop
  - partial failure
  - plan-only runner writes nothing
  - aggregates refused
- **Platform:**
  - request drafts for one actor, picked actors and a group
  - plain-language request and run lines
  - bridge write switch only on writes
  - route validation and Run now

## 6. Not done (needs a decision or a later phase)

- **Sign-off on the limits:** $1.50 per run, 10 actors per request, the 365/180/90-day freshness windows.
- **Related-actor discovery and hub reassessment (P2).** Not built.
- **Adaptive scheduling, notifications and personal ownership (P3).** Deferred, as planned.
- **No Deep Pull reader exists yet** (unchanged from Phase A).
- **The group preview takes about 15–20 seconds** for an 83-actor group, because it checks each actor's gaps. Acceptable for now; it could be cached later.
- **The pushed GitHub branch** still lacks the commits above until you push.
