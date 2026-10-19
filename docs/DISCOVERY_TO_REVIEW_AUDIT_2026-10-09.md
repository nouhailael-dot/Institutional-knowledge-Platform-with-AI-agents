# Discovery → Review audit, and the production blocker it found

**Date:** 9 October 2026
**Completes:** the half of the lifecycle trace left open by
`docs/REVIEW_INTEGRATION_AUDIT_2026-10-09.md`.
**Databases:** local only. Production Supabase was not contacted.
**Committed:** nothing.

One production blocker was found and fixed. One regression in a backend
integration test was found and fixed. Both were proved against a real database
before and after.

---

## 1. The execution trace, end to end

```
GitHub Actions  .github/workflows/weekly-discovery.yml   cron "0 6 * * 1"
  └─ python -m agents.weekly_discovery              DRY unless --live
      ├─ agents.discovery.search.run --entity event
      ├─ agents.discovery.search.run --entity actor   ← the actor path
      ├─ agents.discovery.run --source <X> --entity event
      ├─ agents.enrichment.run --entity actor --deterministic-only
      └─ agents.index.refresh --entity all

agents/discovery/search/store.py :: write_candidates()
  └─ INSERT INTO search_candidate          (url, title, snippet, domain,
                                            triage, fit_score, score_band,
                                            record_preview, identity_outcome,
                                            duplicate_of, distinctiveness)

score_band = 'auto_high'                   score_band = 'review'
  └─ agents/discovery/run.py:749              │
      allow_create=True                       │
      └─ promote.py                           │
          ├─ actor row, record_status='parked'│
          └─ _insert_verify_actor_review()    │
              review_item('verify_actor')     │
                    │                         │
                    ▼                         ▼
        src/review/postgres_source.py :: fetch_candidates()
          ├─ search_candidate       WHERE record_preview IS NOT NULL
          │                           AND score_band='review'
          ├─ event_review_queue  + staged_record
          ├─ person_review_queue + staged_record
          └─ review_item         JOIN actor
              └─ store.sync_external_candidates()   SQLite mirror, 120 s
                  └─ GET /api/review/candidates → frontend/review.js
                      └─ POST .../decision → AdmissionBridge → subprocess
                          └─ agents.review.admission
                              ├─ agents/discovery/promote.py :: promote()
                              └─ agents/enrichment/decisions.py
```

**Live entry points, confirmed:** `agents.weekly_discovery` (scheduled Monday
06:00 UTC, dry by default; `--live` only on manual dispatch with
`LIVE_INPUT=true`). Nothing else is scheduled.

**Rule 4 holds.** `auto_high` means auto-*create*, never auto-verify. Every
created actor is written `record_status='parked'`
(`promote.py` lines 334, 877, 1849) and still needs a GHUS person.

---

## 2. The production blocker

### What breaks

`src/review/postgres_source.py` read two actor columns directly:

```sql
a.website, a.location_city, a.state, a.country
```

The V2 **contract** migration renames `location_city` → `city` and
`state` → `state_code`. Measured:

| schema | columns present |
|---|---|
| post-contract (`ghus_v2_phase12_clean_test`) | `city`, `state_code`, `alt_names` |
| pre-contract (`ghus_v2_review_redesign_test`) | `location_city`, `state`, `state_code` |

Against a post-contract database that query raises:

```
ERROR:  column a.location_city does not exist
```

**That query is the entire V2 review-item feed** — the 196 pending items
(154 `geocode_failed`, 42 `relationship_review`). And `fetch_candidates`
converts a source failure into a *warning*, not an error. So the consequence is
not an error page: **the Review queue quietly loses its V2 items and still
looks fine.**

Production is reported to be post-contract, through migration 500. All Review
work to date has been validated against the pre-contract copy, which is why
nothing caught this.

### Why it was there

Every *other* renameable column in that same SELECT already reads defensively:

```sql
NULLIF(to_jsonb(a)->>'actor_category','') AS actor_category
NULLIF(to_jsonb(a)->>'state_code','')     AS state_code
```

So the pattern was known and applied eleven times. Two columns were missed.
This is exactly the case AGENTS.md rule 9 exists for: a backend schema change
that affects a frontend read needs its compatibility alias in the same phase.

### The fix

Both columns now read through `to_jsonb` with a COALESCE across the old and new
names. Output aliases are unchanged, so nothing downstream moves.

**Proved on both schemas after the change:**

| schema | result |
|---|---|
| post-contract | `Deep Pull Actor f04b7ace / Boston / MA`, `Argonne National Laboratory / Lemont / IL` |
| pre-contract | runs, rows returned |

Before the change the post-contract query errored outright.

Regression test: `test_the_review_query_survives_the_contract_rename` in
`tests/test_review_runs.py`. It also guards the eleven columns that already had
the pattern, so none of them can regress the same way.

---

## 3. The backend regression I had introduced

`tests/integration/test_functional_v2_phase3_7.py` failed at HEAD. I confirmed
it was mine rather than assuming: I built a worktree at `e59eaee` (the commit
before the sector change) and a clone of the same database. **It passed at
baseline and failed at HEAD.**

**Cause.** The scenarios isolate themselves by *topic*. Since the 2026-10-08
decision, hub membership gates on *sector*, and I had given the `_hub` fixture a
single shared `FIXTURE_SECTOR`. Every synthetic hub therefore became a candidate
in every scenario. In the nearest-wins case a hub from an unrelated scenario sat
at the identical coordinate, tied at 2.60 miles, and won the
`(distance, hub_id)` tiebreak on lexical order.

**Why nobody saw it.** The whole module is skipped unless `V2_TEST_DATABASE_URL`
is set. It never was. **I changed hub assignment behaviour and its integration
test never executed once.** That is the more important finding than the failure
itself.

**Fix.** Each scenario now mints its own sector, exactly as it already mints its
own topic. Not a weakening: I also added an assertion that proves the *new* rule
— a hub sharing the actor's sector is evaluated even when its topic differs —
which nothing covered before.

Result: `tests/integration` **5 passed, 5 skipped, 0 failed** (was 1 failed).

---

## 4. Field-by-field payload integrity

The honest answer to "do category, location, parent, hub and Light Pull survive
every transition" is that **on the discovery path they do not exist yet**, and
that is the design rather than data loss.

| Field | At `search_candidate` | Created where |
|---|---|---|
| name, url, domain, snippet | yes | discovery |
| triage, fit_score, score_band | yes | scoring |
| identity_outcome, duplicate_of, distinctiveness | yes | ER, pre-promotion |
| `record_preview` (the draft payload) | yes, jsonb | discovery |
| actor_category / category_type | **no column** | promotion (Phase 5) |
| city / state / region | **no column** | promotion (Phase 4) |
| parent / relationships | **no column** | promotion (Phase 8) |
| hub assignment | **no column** | promotion (Phase 6/7) |
| Light Pull facts | **no column** | promotion (Phase 9) |

So a `score_band='review'` candidate reaches the reviewer as a mostly-empty
classification form, which is correct: the reviewer is the one who classifies
it. A promoted `auto_high` actor reaches Review through `review_item` instead,
and by then it has all of the above.

**Nothing is silently dropped between the two.** They are different records at
different lifecycle stages, not the same record losing fields.

---

## 5. What the real data shows

`ghus_v2_review_redesign_test`, the migrated copy:

| table | rows |
|---|---|
| `search_candidate` | 8,821 |
| `staged_record` | 7,286 |
| `review_item` | 410 |
| `event_review_queue` | 9 |
| `person_review_queue` | **0** — person discovery is off, as required |

`search_candidate` by band:

| band | preview | rows | reaches Review |
|---|---|---|---|
| *(none)* | no | 8,515 | no — triaged out before scoring |
| `analysis_failed` | no | 191 | **no — see F2 below** |
| `auto_low` | yes | 48 | no, by judgement |
| `review` | yes | **43** | **yes** (29 actor, 14 event) |
| `auto_high` | yes | 24 | via promotion as Parked |

---

## 6. Findings

### F1 — 484 Parked actors can never be reviewed · **critical**

| | actors |
|---|---|
| Parked, live | 782 |
| …with a `review_item` | 298 |
| …**with none** | **484** |

The queue is fed from `review_item`. An actor with no review item has no route
into Review, so it can never be Verified or Rejected. It stays Parked forever —
and per the WS8 Ask finding, would be answered from as though it were evidence.

`verify_actor` is the **first** allowed `review_kind` in the CHECK constraint,
and `promote.py:779` creates one. So **new discoveries are fine.** The 484 are
all one vintage (created 2026-06-07/08), from before the V2 pipeline. The
review items that do exist for that vintage are *exception* backfills —
`category_doubt` 214, `geocode_failed` 154, `relationship_review` 42. An actor
nobody flagged got nothing.

**Needs a backfill**: one `verify_actor` item per Parked actor with none. That
writes canonical data, so it belongs to `promote.py` / `decisions.py` and to the
schema owner. **I have not done it and must not.**

### F2 — 191 `analysis_failed` candidates are invisible · **maintainability**

They have no `score_band` outcome and no preview, so they match neither the
review filter nor any queue. A scoring *failure* is not a judgement that
something is irrelevant, but it is treated identically to one. Nobody can see
how many there are or retry them. Same shape as the 197 invisible review items
found earlier.

### F3 — No test database represents the intended end state · **deployment blocker**

| database | contract applied | migrations 510–540 |
|---|---|---|
| `ghus_v2_phase12_clean_test` | yes | **no** |
| `ghus_v2_review_redesign_test` | **no** | yes |

Neither is the shipping configuration, so the full backend suite has never run
green in one. Measured:

- against `phase12_clean`: 675 passed, 3 failed (`sector.is_thematic` absent)
- against `review_redesign`: 676 passed, 2 failed (contract schema assertions)

I tried to build the end state by cloning `review_redesign` and dropping the
three V1 compatibility views. **That was not sufficient** — the contract step
also renames columns, so the result still lacked `city` and `alt_names`. I
deleted that database rather than leave a misleading fixture.

Building a real one means running the frozen cutover package against a clone,
which is a release operation, not a test fixture. **Recommended before Monday,
and not something I should do unilaterally.**

### F4 — `ghus_v2_phase12_clean_test` is polluted · **maintainability**

It carries 19 topics, 11 of them synthetic leftovers from earlier integration
runs (`deep-`, `inside-`, `overlap-`, `phase8-`, `mismatch-`…). Migration 520
correctly refuses to apply there, because its guard requires every controlled
topic to have a matching sector code. The guard is right; the database is dirty.

### F5 — Entity resolution: the two regression scenarios

Checked against the live map, as asked.

**California Department of Food & Agriculture** — the shortlist's candidate #7
*is already a member* of the UC Davis hub, stored as
`California Department of Food & Agriculture (CDFA)`. The difference is `&`
versus `and` plus a trailing acronym. A name-equality check misses it; a
normalised comparison would not. **This is a true duplicate** and is now blocked
in the shortlist.

**Bayer Crop Science** — four live actor rows:

- `Bayer Crop Science`
- `Bayer Crop Science (Midwest Presence)`
- `Bayer Crop Science (regional presence)`
- `Bayer Crop Science R&D Facilities`

These are **not all duplicates**. `(Midwest Presence)` and
`(regional presence)` are parenthesised *qualifiers on the same legal entity*,
which is duplicate representation. `R&D Facilities` may be a genuine sub-unit
and the West Sacramento LifeHub is a genuine site. The correct shape is one
parent plus `unit_of` children, not four peers.

**Nothing was merged or deleted.** Per rule, resolution of existing canonical
actors is a `possible_duplicate` review item for a human, and promotion already
supports that kind.

**The general finding:** normalisation does not fold `&`/`and` or strip
parenthesised qualifiers, so both cases survive dedup today.

### F6 — Review SQLite persistence · **design decision needed**

**What it is today:** a 120-second cache of PostgreSQL that has accidentally
become authoritative for one thing — *the record that a decision was made
locally*. Rejection survives re-sync only because the SQLite row exists
(`INSERT OR IGNORE`, and the UPDATE scoped to `WHERE status='pending_review'`).
Lose the file, repoint `REVIEW_STORE_DB`, or redeploy onto fresh storage, and
every rejected candidate returns to the queue.

**Recommended design — make PostgreSQL authoritative and SQLite a pure cache:**

1. `fetch_candidates()` excludes candidates already decided, read from the
   canonical decision record rather than from local status.
2. The local store keeps only the mirror plus in-progress edits; it becomes
   safe to delete at any time.
3. In-progress reviewer edits that are not yet decisions stay local and are
   explicitly declared disposable.

This depends on a canonical place to record "this `search_candidate` was
rejected". `review_item` covers promoted actors; a pre-promotion candidate has
no such home yet. **That is the migration dependency**, and it is for the schema
owner. Until then, `REVIEW_STORE_DB` must be treated as durable state with a
documented backup — which it currently is not.

### F7 — Phase integration spot-checks

| Phase | Result |
|---|---|
| 4 geography | region derived from state, never taken from input (test present) |
| 5 classification | 12×69 enforced at store, API (422) and frontend |
| 8 relationships | `entity_edge` joined into the review payload with source URLs |
| 9 Light Pull | `actor_fact` layer 1, rendered into the existing boxes |
| 10 Deep Pull | **correctly gated** — `actor_is_verified_for_topic()` requires a decision for that exact actor/topic pair, enforced in `append_deep_pull` |
| 11 immutable facts | `actor_fact_history` + current pointer, read-only from Review |
| 6/7 hubs | unchanged algorithm; sector is now Test 1 and is proved by the new integration assertion |

---

## 7. Tests and exact results

| Suite | Before | After |
|---|---|---|
| Shared app · pytest | 265 passed, 1 skipped | **268 passed, 1 skipped, 30 subtests** |
| Shared app · node | 52 passed | **52 passed** |
| Backend · pytest (no integration DB) | 664 passed, 24 skipped, 1 error | **664 passed, 24 skipped, 1 error** |
| Backend · `tests/integration` (DB set) | **1 failed**, 4 passed | **5 passed**, 5 skipped |

Three tests added: two resurrection tests (previous pass) and
`test_the_review_query_survives_the_contract_rename`. The backend integration
test gained an assertion for the sector rule.

The remaining backend "1 error" without a database is the integration module
requiring `V2_TEST_DATABASE_URL`, which is F3.

---

## 8. Production blockers

1. **The contract rename** — fixed in this pass. Without it the Review queue
   silently loses its V2 items against production's schema.
2. **F1, the 484 unreviewable Parked actors** — needs a canonical backfill,
   schema owner's call.
3. **F3, no end-state test database** — the shipping configuration has never
   been tested.
4. **F6, `REVIEW_STORE_DB` is undocumented durable state** — a redeploy onto
   fresh storage resurrects every rejection.

## 9. Before Monday

- Decide F1. A reviewer opening the queue on Monday sees 196 items and will
  reasonably assume that is the backlog. It is 196 of 782.
- Build the end-state database (F3) and run both suites against it.
- Document `REVIEW_STORE_DB` as durable, with a backup, until F6 is designed.

## 10. Safe to defer

- F2, the 191 invisible `analysis_failed` candidates.
- F5 entity resolution: normalising `&`/`and` and parenthesised qualifiers, and
  resolving the four Bayer rows. Needs a human decision per pair.
- F6 implementation, which is blocked on the migration dependency above.
- F4, cleaning the polluted test database.
- The two decision paths (F1 in the previous audit).

## 11. Files changed in this pass

**Shared app** — `src/review/postgres_source.py` (the blocker fix),
`tests/test_review_runs.py` (+1 test), `tests/test_review_decisions.py`
(+2 tests, previous pass), this document.

**Backend** — `tests/integration/test_functional_v2_phase3_7.py` (scenario
isolation + the sector assertion), `docs/evidence/hub_real_world_shortlist.md`
(membership row closed).

Nothing is committed. Temporary databases and the baseline worktree were
removed.
