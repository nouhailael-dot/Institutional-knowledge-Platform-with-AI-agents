# Actor Updates — Phase A (Priority 1) report, 2026-10-18

Scope: the first step of "Intelligent Actor Updates" — request builder,
single actor, topic-aware scopes, Light Refresh, the Phase 11 before/after
diff, Review integration, provenance and cost controls. Nothing is committed
or pushed; no migration was needed or applied; production was not touched.

## 1. What existed before, and its limits

| Piece | Where | Limit found |
|---|---|---|
| Actor updates panel | platform `frontend/discovery.js` | Three presets only; "Preview" paid for a read, "Update" paid for a second one |
| One-actor read and write | backend `agents/collection/actor_updates.py` | Its own outcome words (filled/updated) that did not match what the Phase 11 writer does: conflicts, GHUS protection and supersession were invisible until after writing |
| Light Pull reader | backend `light_pull_reader.py` | Reused unchanged |
| Deep Pull | backend `deep_pull.py` | The gate and the writer exist; there is no Deep Pull reader |
| Fact writer | backend `decisions.append_actor_fact` | Already raises `fact_conflict` / `pending_update` review items, but Review had no way to decide them |
| Subscriptions and runner | backend `subscriptions.py`, `subscription_runner.py`, `subscription_store.py` | The runner runs Discovery-page requests only; nothing runs actor-scoped subscriptions |
| Run ledger | `collection_request`, `collection_run` | Actor updates were not recorded; facts had no `request_id` |

## 2. What changed

The flow is now **plan → check → write**:

1. **Plan** is free: no page is read and nothing is written. It lists the boxes to read and why the others are skipped, the Deep Pull gate for this exact actor and sector, the configured cap, the historical cost and a one-paragraph summary.
2. **Check** makes one capped Light Refresh read and writes nothing to the database. It predicts, for every box, exactly what the Phase 11 writer will do: New, Changed (supersedes, history kept), Confirmed (corroboration), Conflict (current value kept → Review), GHUS value kept (pending update → Review), No change, Not found, Not yet collected.
3. **Write** applies exactly what was checked, with no second read and no second payment.
   - It goes through `append_actor_fact` and records the run in the existing ledger: cost, pages and counts. Every fact carries the run as its `request_id`.
   - One failed box does not stop the others, and a retry writes only the failed boxes.

Scopes:

- **General profile:** every box of the category schema.
- **Specific topic:** a chosen sector, plus words to steer which page is read.
- **Missing information:** empty boxes only. A "not found" is re-checked only after 90 days.
- **Outdated information:** values older than 365 days, or 180 days for time-sensitive boxes.
- **Specific changes:** the boxes you tick.

Change categories only reorder the boxes and steer page choice. Nothing outside the category schema is ever read, so an inapplicable box is never treated as missing.

**Review:**

- Fact conflicts and pending updates now show the value on the map and the value found, each with its source, read date, confidence and who set it.
- The decision is "Use the new value" or "Keep the current value". The decision runs through a new `record_fact_review_decision` in `decisions.py`, the approved writer.
- Both facts stay in the ledger either way.
- Accepting is refused if the current value changed after the item was raised.

**Rule found in live testing (CPower, today):**

- A page that only says less ("an NRG company") than what is recorded ("an NRG company; 4,600 customers, 21,000 sites") is now Confirmed, not Changed.
- Superseding would have replaced a richer value with a poorer one.

## 3. Files

**Backend** (`GHUS-Platform`, uncommitted):

- `agents/collection/actor_updates.py`: rewritten (plan, check, apply; classify mirrors `append_actor_fact`).
- `agents/collection/subscription_store.py`: `start_actor_update_run` and `finish_actor_update_run`. This is the one run-ledger writer, as the canonical-write guard requires.
- `agents/enrichment/decisions.py`: `record_fact_review_decision`.
- `agents/review/admission.py`: the `resolve_fact` decision kind.
- `agents/config/sources.yaml`: the `actor_updates` limits: $0.15 per actor, 10 actors per request, 365/180/90-day windows and a 24-hour check validity. **These values need GHUS sign-off.**
- Tests:
  - `tests/agent/test_actor_updates.py` (24)
  - `tests/integration/test_functional_actor_updates.py` (14)
  - `tests/db/test_review_item_decisions.py` (+1)

**Platform** (worktree `feature/review-redesign`, uncommitted):

- `src/discovery/bridge.py`: `plan_update`, `check_update`, `apply_update` with argument validation. Only apply sets the write switch.
- `backend/app.py`: `POST /api/discovery/actors/{id}/plan`, `POST /api/discovery/actors/{id}/check`, `POST /api/discovery/actor-checks/{check_id}/apply`. The old one-step `/update` route is removed.
- `src/review/postgres_source.py`: `fact_change` (both values) on fact review items.
- `src/review/store.py`: fact review decisions map to `resolve_fact`.
- `frontend/discovery.js` and `frontend/discovery.css`: the request builder, request preview, grouped results with filters, and the write step.
- `frontend/review.js`: "Use the new value" / "Keep the current value", the two-value table and plain labels.
- `frontend/index.html`: assets `?v=20261018`.
- `.claude/launch.json`: `ghus-actor-updates-test`, a server on port 8032 reading the disposable clone `ghus_v2_actor_updates_test`.
- Tests:
  - `tests/test_discovery_bridge.py`
  - `tests/test_review_runs.py` (+2)
  - `tests/test_discovery_ui.mjs`
  - `tests/test_review_ui.mjs` (+1)

## 4. The 26 scenarios

All database scenarios ran on `ghus_v2_actor_updates_test`, a clone of the demo database, with synthetic topics. The live scenario read CPower's real site and wrote to the clone only.

| # | Scenario | Status | Evidence |
|---|---|---|---|
| 1 | Single-actor update | Done | integration `check_predicts_and_apply_writes…`; live CPower run |
| 2 | Multiple-actor update | **Next phase** | — |
| 3 | Topic-specific update | Done | `plan_is_free…` (scope topic); focus words steer page choice |
| 4 | General profile refresh | Done | live CPower run (9 boxes) |
| 5 | Missing-field enrichment | Done | unit `missing_reads_only_empty_boxes…`; integration `missing_scope_skips_the_read…` (no read, $0) |
| 6 | Outdated-field refresh | Done | unit `outdated_reads_only_stale_values…` |
| 7 | Light Refresh | Done | all of the above |
| 8 | Unauthorized Deep Pull refusal | Done | integration: refused, explained, reader never called |
| 9 | Authorized topic Deep Pull | **Partial** | The gate permits it after a GHUS decision for that topic. No Deep Pull reader exists, so this is said, not faked |
| 10 | Same-value corroboration | Done | predicted = actual `corroborated`; reworded and "says less" cases |
| 11 | New fact insertion | Done | predicted = actual `new` |
| 12 | Stronger/newer supersession | Done | old fact kept as history, pointer moved |
| 13 | Weaker evidence conflict | Done | current kept; `fact_conflict` review item |
| 14 | GHUS fact protection | Done | GHUS pointer unchanged; `pending_update` review item |
| 15 | Before/after report | Done | findings with previous/proposed values; UI table |
| 16 | Source and confidence display | Done | per finding and in Review |
| 17 | Related-actor discovery | **Next phase** | — |
| 18 | Hub reassessment | **Next phase** | — |
| 19 | Unassigned actor preservation | Not affected | no hub is read or changed by this phase |
| 20 | One-time execution | Done | apply records a manual `once` run |
| 21 | Recurring schedule | **Next phase** | Shown in the UI, disabled |
| 22 | Pause/resume/cancel | **Next phase** | Exists for Discovery requests only |
| 23 | Cost ceiling enforcement | Done | The cap is `min(configured, requested)` and goes to the cost meter. A check is one model call; the true spend is recorded even when that one call overshoots |
| 24 | Partial failure and retry | Done | one box fails → run `attention`; retry writes only it, same run |
| 25 | No duplicate canonical actors | Done | actor count unchanged |
| 26 | No production writes | Done | apply refuses non-local without the bridge switch; every test is guarded to local `*_test` |

## 5. Test results

**Backend** (`ghus_v2_final_schema_test`, same as the baseline):

- 841 passed, 18 skipped, 4 failed.
- The 4 failures are baseline items 2–5 in `BASELINE_TEST_FAILURES_2026-10-15.md`: the retired `smoke_test_actor_merge.py` stub (×2) and the two schema checks that need deferred migration 500.
- Actor-update tests on the clone: 17 passed (14 integration + 3 review-item decisions).

**Platform:**

- pytest: 304 passed, 1 skipped.
- Node UI tests:
  - `test_discovery_ui.mjs`: 23 passed
  - `test_review_ui.mjs`: 56 passed
  - `test_hub_matching.mjs`: 6 passed
  - `test_map_ui.mjs`: 9 passed. It needs `node --experimental-vm-modules`; without the flag it fails to load, before and after this phase.

## 6. Next phase (needs approval)

1. **Recurring and batch (steps 2 and 5).** Reuse `actor_update_subscription` and the request runner; add an actor-update branch to `run_due_requests` rather than a new scheduler.
   - The request needs to store scope, depth, categories, focus and a spend cap per run.
   - The table has no place for these, so this needs a **minimal additive migration (570)**: an `update_options jsonb` and a `max_usd_per_run numeric`, plus widening `requested_via` with an `actor_updates` value.
   - It would be prepared as a proposal and tested on the clone only.
2. **Gap-aware batch selection (step 4).** Choose the actors in a group whose boxes are missing or stale, under the per-request actor cap.
3. **Related actors and hub reassessment (P2).** Route through mapped-first discovery and Review; no hub change without Review.

## 7. Open items outside this phase

- **Person discovery.** The spec says "keep person discovery disabled", but it was enabled earlier after the supervisor signed off (`people_enabled: true`). It was not changed; please confirm which applies.
- **Backend files never committed.** `agents/collection/discovery_requests.py` and `subscription_runner.py` are untracked, and `subscriptions.py` and `subscription_store.py` have uncommitted changes, so the pushed `codex/architecture-v2` branch lacks them. Actor updates depend on them.
- **Browse on production.** It still reads `a.verification_status`, which migration 500 dropped. That is the colleague's area and was not changed.
