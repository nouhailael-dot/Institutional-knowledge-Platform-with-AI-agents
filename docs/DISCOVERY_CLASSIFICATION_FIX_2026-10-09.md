# Discovery classification defect — root cause, fix, and a working end-to-end run

**Date:** 9 October 2026
**Database:** `ghus_v2_demo_test` (isolated, 127.0.0.1:55432). Production Supabase
not contacted. Nothing committed.

**Result: fixed and proved.** A bounded real discovery run now goes all the way
from open-web search to actors Parked in the Review queue with hub memberships.

---

## 1. Root cause

Not what the first diagnosis said. The classifier was never missing — it was
being **thrown away on the cache path**.

`agents/discovery/search/actor_scoring.py` has two routes to a page analysis:

| route | what happens | category? |
|---|---|---|
| fresh page | `extract()` → `validate_actor_analysis` (narrows to `ACTOR_RECORD_FIELDS`) → **`classify_actor_category_type`** → merged | **yes** |
| cached page | `read_analysis_cache()` → `validate_actor_analysis` (narrows the same way) → **returned directly** | **no** |

`validate_actor_analysis` deliberately narrows a record to `ACTOR_RECORD_FIELDS`,
because on the fresh path the model sometimes volunteers classification keys
that carry no authority, and the real Phase 5 call happens straight afterwards.
That is correct for a fresh page.

Replaying a **cache** through the same filter stripped the authoritative
classification that had already been computed and written — and the cached
branch never re-classified. The first run reported
`actor_rubric_cache_hit_rate: 0.969`, so **97% of actors took the path that
loses the category**, arrived at `promote()` with none, and were refused by
`ck_actor_category_complete`. One refusal aborted the entire run.

`classification_enabled=True` was already set at the construction site
(`phase2.py:466`), which is why the setting looked correct while the behaviour
was not.

## 2. The fix

Three changes, each small and each addressing one of the brief's requirements.
**No new classifier, no schema change, no constraint weakened.**

**a. The cache keeps what it stored** — `actor_scoring.py::read_analysis_cache`
narrows as before, then restores the `ACTOR_CLASSIFICATION_FIELDS` the cached
payload actually holds. Added `needs_classification(analysis)` to report when a
record still has no category (a cache written before classification existed
has none).

**b. The Phase 5 call is reusable** — `ActorRubricExtractor.classify(analysis)`
split out of `extract()`, so a cached analysis can be completed **without
re-fetching the page**: the classifier needs only the name and the official
self-description, both already cached. `phase2.py` calls it when
`needs_classification(...)` is true, then rewrites the cache so the work is paid
for once.

**c. A candidate that cannot be classified is preserved, not inserted** —
`agents/discovery/run.py` refuses to promote a `create`-zone actor with no
`actor_category`, records `staged_unclassified` in the audit with the reason,
counts it, and **continues with the other candidates**. The staged record
survives for review or retry. This never touches an existing actor, whose
approved category is already canonical (brief §3).

Classification failures are caught per candidate in `phase2.py` too
(`actor_classification_failures`), so one failure cannot abort a run.
`CostLimitExceeded` is deliberately re-raised — a budget stop must still stop.

### Files changed

| File | Change |
|---|---|
| `agents/discovery/search/actor_scoring.py` | cache preserves classification; `needs_classification()`; `classify()` extracted |
| `agents/discovery/search/phase2.py` | classify a cached analysis before staging, with per-candidate failure handling |
| `agents/discovery/run.py` | never promote an unclassified new actor; preserve and continue |

## 3. The proving run

```bash
DATABASE_URL="postgresql+psycopg2://ghus_test@127.0.0.1:55432/ghus_v2_demo_test" \
python -m agents.discovery.search.run --entity actor --live \
  --report-out fixed-report.md --audit-out fixed-audit.csv
```

Run id `783a1911-3638-4eff-b38e-9c0de3396755`. **Status: `attention`** (budget
and page caps reached) — **not `failed`**, which is the whole point.

| Metric | Before the fix | After |
|---|---|---|
| Status | **failed** | **attention** |
| Searches executed | 52 | 52 |
| Already-mapped domains skipped | 541 | **541** |
| Domain duplicates collapsed | 17 | 22 |
| Deterministically rejected | 177 | 212 |
| Records extracted / staged | 7 / 7 | **12 / 12** |
| **Records promoted** | **0 — run aborted** | **12** |
| Cost | $3.03 | **$2.60** |

### Where the 12 went

| Zone | Count | Meaning |
|---|---|---|
| `create` | **5** | new actors, promoted Parked |
| `review` | **7** | matched an existing actor closely enough to need a human — **not** auto-created as duplicates |

Plus 24 pages that could not be fetched or read, and 1 record validation
failure — all recorded in the audit, none fatal.

### The five actors, exactly as the pipeline produced them

| Actor | Actor Category | Category Type | Location | Coords |
|---|---|---|---|---|
| California Water Efficiency Partnership | `foundation_nonprofit` | `operating_nonprofit` | CA | **none** |
| Greater Seattle AI Ecosystem | `association_network` | `not_applicable` | Seattle, WA | yes |
| Seattle University — Institute for Environmental Justice & Sustainability | `university_academic` | `research_lab_center` | Seattle, WA | yes |
| Sutter Health | `hospital_clinical` | `nonprofit_health_system` | Santa Clara, CA | yes |
| Tech:NYC | `association_network` | `trade_association` | New York, NY | yes |

Every pair is a valid Intern Guide pair. Every actor is `status='parked'`.
Classification came from name and official self-description only — not sector,
funding, fame or age. Nothing was auto-verified.

### Hub assignment, from the same run

| Actor | Assigned hub | Distance |
|---|---|---|
| Greater Seattle AI Ecosystem | Seattle AI Hub (University of Washington – Big Tech AI – Greater Seattle) | 0.0 mi |
| Seattle University — Institute | Pacific Northwest Sustainability Hub (Seattle – Portland – Corvallis) | 0.0 mi |
| Sutter Health | San Francisco Bay Area Health & Biomedical Innovation Hub | **20.8 mi** |
| Tech:NYC | New York City AI Hub (Columbia – NYC – Cornell Tech) | 0.0 mi |
| California Water Efficiency Partnership | **none — retained unassigned** | no coordinates |

**4 assigned, 1 retained.** The unassigned one was not forced into a hub: with
no coordinates every hub evaluated to `needs_review_location` (12 of them), and
it raised both a `geocode` and a `hub_assignment` review item. It stays in the
database, searchable, and available to future detection runs.

Every membership row satisfies `ha.topic_id = h.topic_id` — the hub's topic,
which is what `hub_actor.topic_id` means. That is this week's other fix working
in the real pipeline rather than only in tests.

## 4. The twelve required proofs

| # | Claim | Evidence from this run |
|---|---|---|
| 1 | Actor discovered | 52 searches → 48 fetch candidates → 12 records |
| 2 | Existing-actor check performed | 541 already-mapped domains skipped; `EntityResolver ready: 744 canonical actors`; 7 routed to review instead of created |
| 3 | Classification executed | 5 of 5 classified; 2 raised `classification` review items |
| 4 | Valid Actor Category produced | all 5, all valid Intern Guide pairs |
| 5 | Category Type handled | 4 specific types, 1 honest `not_applicable` |
| 6 | Geography derived | 4 with coordinates + region; 1 without, recorded as such |
| 7 | Light Pull executed | `actor_fact` layer 1 written at promotion |
| 8 | Promoted to Parked | all 5 `status='parked'` |
| 9 | `verify_actor` created | **5** |
| 10 | Visible in Review | **all 5**, queue at 288 candidates |
| 11 | Existing-hub assignment evaluated | 52 evidence rows across the 5 |
| 12 | Unassigned retained | California Water Efficiency Partnership, in the database, unassigned, reviewable |

## 5. Phase 7 grouping — stated explicitly, not changed

Asked for directly, so answered directly:

```
HubDetectionConfig().cluster_dimension == 'sector'
```

**Phase 7 detection is currently SECTOR-grouped.** The 8 October amendment
changed the detector's partition from `topic_id` to sector code, documented in
`docs/decisions/2026-10-08-hub-membership-keys-on-sector.md`. Unchanged: 10
independent families, 5 matched categories by maximum bipartite matching, the
50-mile core, the 200-mile cluster, family independence, centre-finding,
determinism, and proposal-only.

**I did not change it.** It is one config value (`"sector"` / `"topic"`), and
the original 49-test Phase 7 suite still runs in `"topic"` mode so the earlier
rule stays proven. If GHUS meant the amendment to govern assignment only, the
default is wrong today — worth settling before Monday.

**Hub proposals generated: 0.** No proposal was expected or produced: detection
needs Verified eligible actors, and nothing in this run was verified. Five new
actors across three cities is far below 10 independent families and 5 matched
categories. The thresholds are proved by the fixture suite, not by this run.

## 6. Test results

| Suite | Result |
|---|---|
| Hub detection (Phase 7 + fixtures) | **62 passed** |
| Backend, no database | **664 passed**, 27 skipped, 0 errors |
| Backend integration (end-state DB) | **7 passed**, 5 skipped |
| Shared app pytest | **272 passed**, 1 skipped |
| Shared app node | **52 passed** |

No test was weakened and no constraint relaxed.

## 7. Where to see it

```bash
python -m scripts.run_demo_server --port 8030 --database ghus_v2_demo_test
```

**http://localhost:8030 → Review**, behind the
**EXAMPLE / TEST DATA — NOT GHUS-VERIFIED PRODUCTION DATA** banner.

Filter **Review Reason → Awaiting Verification** for the five new actors. Each
shows its category and type in the controlled dropdowns, its location and
region, its Light Pull boxes, its sources, and its hub. The real instance stays
on port 8020 and is untouched.

Suggested order for Monday:

1. **Tech:NYC** — discovered, classified `association_network / trade_association`,
   assigned to the New York City AI Hub, and carrying a `same_topic_overlap`
   review item.
2. **Sutter Health** — assigned at a real measured distance, 20.8 miles.
3. **California Water Efficiency Partnership** — the honest failure: no
   coordinates, so no hub, two review items, and the record kept.

## 8. Remaining blockers

1. **Cutover attestation** — schema owner's, unchanged.
2. **`REVIEW_STORE_DB`** — still unset; must point at durable storage before
   anyone reviews anything for real.
3. **Phase 7 grouping decision** (§5) — sector today; confirm that is intended.
4. 24 of 48 fetched pages failed to read in this run. Not a defect, but worth
   looking at if discovery yield matters.
