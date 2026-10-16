# Demo run report — real agent discovery, and the blocker it found

**Date:** 9 October 2026
**Purpose:** prepare visible demonstration data for Monday's Review and
hub-detection session.
**Production Supabase:** not contacted. Nothing committed.

The agents were run for real. They worked, they cost real money, and they found
a **production blocker in the actor discovery path**. That blocker is the main
result of this run, and it is reported before anything else because it changes
what Monday can and cannot show.

---

## 1. Environment, proved not assumed

| | |
|---|---|
| Backend repo / branch | `GHUS-Platform` · `codex/architecture-v2` |
| Shared app / branch | `Institutional-knowledge-Platform` · `feature/review-redesign` |
| **Demo database** | **`ghus_v2_demo_test`** on `127.0.0.1:55432` |
| Built from | `ghus_v2_cutover_test` (pre-cutover production backup → approved chain → 510-540) |
| Baseline | 965 actors · 48 hubs · 641 memberships · 8 sectors · 8 topics |
| Network | clean — no `198.18.x.x` VPN interception this time |
| Search provider | `claude` (`ClaudeWebSearchProvider`, uses `ANTHROPIC_API_KEY`) |

**The target was proved before the agent ran**, not assumed from `.env`:

```
current_database : ghus_v2_demo_test
server           : 127.0.0.1:55432
```

`src/db/session.py` calls `load_dotenv(...)` with the default
`override=False`, so an explicit `DATABASE_URL` wins over `.env`. The agent
process could not reach production.

## 2. Entry points executed

```bash
# dry run (default; no --live)
DATABASE_URL="postgresql+psycopg2://ghus_test@127.0.0.1:55432/ghus_v2_demo_test" \
python -m agents.discovery.search.run --entity actor \
  --report-out dryrun-report.md --audit-out dryrun-audit.csv

# live run, same bounded configuration
DATABASE_URL="postgresql+psycopg2://ghus_test@127.0.0.1:55432/ghus_v2_demo_test" \
python -m agents.discovery.search.run --entity actor --live \
  --report-out live-report.md --audit-out live-audit.csv
```

Run identifiers: `336e78c6-af09-4235-b4f8-353315794e4e` (dry),
`10b94bb1-b5a5-41a9-b11f-167079d23b2b` (live).

Bounded by `agents/config/sources.yaml`, unmodified: `max_usd_per_run: 5.0`,
`actor_query_limit: 40`, `actor_max_searches: 52`, `max_pages_fetched: 40`.
No nationwide sweep; no config was loosened.

## 3. What the run actually did

| Metric | Dry run |
|---|---:|
| Query grid | 294 |
| Searches executed | **52** |
| Fetch candidates | 67 |
| Pages analysed | 25 |
| Rubric LLM calls | 76 |
| Rubric cache hit rate | 0.969 |
| Deterministically rejected | 177 |
| Domain duplicates collapsed | 17 |
| **Already-mapped domains skipped** | **541** |
| **Records staged** | **7** |
| Candidates written | 0 (dry) |
| **Cost** | **$3.03** of the $5.00 budget |
| Status | **failed** |

The live run wrote **961 `search_candidate` rows** and fetched 132 pages before
failing at the same point.

Real entity resolution ran: `EntityResolver ready: 744 canonical actors,
HIGH=0.960 LOW=0.189`, and 541 candidate domains were skipped because the
organisation is already mapped — Architecture V2 rule 1, working.

### The seven real actors it staged

Real organisations, real URLs, real geography from the gazetteer:

1. Sustainable CUNY (City University of New York)
2. Phoenix Water Services Department
3. Boulder Foundation
4. Department of Chemical Engineering, University of Illinois Chicago
5. Department of Chemistry & Biochemistry, Loyola University Chicago
6. Great Lakes Native American Research Center for Health (GLNARCH)
7. Great Lakes Medical Research, LLC

Example of what the pipeline produced for one, unedited:

```
name        Great Lakes Native American Research Center for Health (GLNARCH)
website     https://www.mcw.edu/departments/epidemiology/research/...
city/state  Lac du Flambeau, WI        region  midwest_great_lakes
coordinates 45.962279, -89.896865      origin  claude_discovered
status      parked
```

## 4. The blocker

**Open-web actor discovery cannot complete against the post-contract V2 schema.**
Reproduced in both the dry and the live run:

```
psycopg2.errors.CheckViolation: new row for relation "actor"
violates check constraint "ck_actor_category_complete"
```

```sql
CHECK (NULLIF(btrim(actor_category),'') IS NOT NULL OR status = 'rejected')
```

Migration 495 (contract stage) requires every non-rejected actor to carry
`actor_category`. The actor arriving at `promote()` has none.

### Why, exactly

Three facts that only line up when you run the thing:

1. `agents/discovery/extractors/actor.py` deliberately separates the sets:
   `ACTOR_RECORD_FIELDS` (facts) and `ACTOR_CLASSIFICATION_FIELDS`
   (`actor_category`, `category_type`, `category_note`,
   `category_needs_review`, `classification_evidence`). `actor_record_schema()`
   says why: *"Return factual actor fields; Phase 5 classification is a later
   ordered call."*
2. `agents/discovery/search/actor_scoring.py::validate_actor_analysis` filters
   the model's record to `ACTOR_RECORD_FIELDS`, so any classification the model
   volunteers is dropped. The run logged this 7 times:
   `actor record dropped unknown fields … ['actor_category', 'category_type', …]`
3. `agents/discovery/promote.py:597` does
   `classification = classification_from_payload(staged.normalized_payload)` —
   it **expects the classification to already be in the staged payload**.

So promote expects classification in the payload, extraction strips it, and
**nobody makes the "later ordered call"**. `agents/discovery/run.py::_extract_stage_route_promote`
runs `classify_sector_matches` — *sector* classification — and then promotes.
Actor-category classification never happens.

This is not a regression from the Review work: it is a pre-existing integration
gap that `ck_actor_category_complete` turns from silent into fatal. It was
invisible until discovery was run against a post-contract database, which this
is the first time anyone has done.

### The fix, not applied

Call the designed step. After extraction and before staging, run
`agents/common/actor_classification.py::classify_actor_category_type(llm_client,
name=…, self_description=…)` and merge `classification.as_payload()` into the
record. The function already implements the required ordered sequence —
record kind → category → hard rules → type.

**I did not apply it.** It adds LLM calls inside the canonical promote path and
changes agent behaviour; it deserves its own task with its own tests, not an
improvised edit at the end of a session. Monday is about Review, which this does
not block.

## 5. What this means for the demo

| Demo element | Status |
|---|---|
| Review interface and all its modifications | **working** — see §6 |
| Real agent run, provenance, cost, ER, geography | **proved** — §3 |
| Real discoveries visible as Review candidates | **blocked** — the run aborted before score banding, so no new row has `score_band='review'` |
| Hub assignment and new-hub detection | **proved by the fixture cohort**, not by this run |

**The agents did not discover enough actors to create a hub, and this run does
not claim otherwise.** Seven staged records in one bounded run is nowhere near
the thresholds (10 independent families, 5 matched categories), and that is the
expected result of a small bounded run, not a defect.

## 6. Where to see it — the demo instance

A second instance, isolated, on its own port and its own store:

```bash
python -m scripts.run_demo_server --port 8030 --database ghus_v2_demo_test
```

| | |
|---|---|
| URL | http://localhost:8030 → **Review** |
| Database | `ghus_v2_demo_test` (isolated) |
| Review store | `.demo/review-demo.sqlite3` — **not** the real store |
| Banner | **EXAMPLE / TEST DATA — NOT GHUS-VERIFIED PRODUCTION DATA**, first element on the page |
| Candidates | 266 |

`scripts/run_demo_server.py` refuses any target that is not
`127.0.0.1:55432/*_test`, so it cannot be pointed at production even by mistake.
It also clears `DATABASE_URL` and `REVIEW_ADMISSION_DATABASE_URL` from its own
environment, so the demo cannot write canonically.

The real instance stays on port 8020 and is untouched, so the two never mix.

### What the supervisor can see there

- The Review queue with run grouping and the five filters
- Actor Category (12) → Category Type (69, dependent) — an invalid pair is
  refused with a 422
- Country (196), State (51), Primary Sector (8 + Not Applicable)
- **Hub dropdown — 49 options** (48 real hubs + "Not Applicable — No Hub")
- The four numbered sections and 13 Light Pull boxes
- Verify / Park / Reject with confirmation, and fail-closed admission
- The Updates tab (WS6 subscriptions)
- Correct statuses — Verified actors now read Verified, not Parked

## 7. Test results

| Suite | Result |
|---|---|
| Hub detection (Phase 7 + fixtures) | **62 passed** |
| Shared app pytest | **272 passed**, 1 skipped |
| Shared app node | **52 passed** |
| Backend (no DB) | **664 passed**, 27 skipped, 0 errors |
| Backend (end-state DB) | **678 passed**, 2 failed (post-500 schema, attestation-blocked) |

### The 16 required scenarios

| # | Scenario | Evidence |
|---|---|---|
| 1 | matches an existing hub | `test_s5_a_trusted_same_sector_hub_suppresses_instead_of_duplicating` |
| 2 | matches no hub | `test_an_actor_in_a_different_sector_never_joins` |
| 3 | missing coordinates | `test_s9_an_actor_beyond_the_radius_or_without_coordinates_is_not_assigned` |
| 4 | sector mismatch | `test_an_actor_in_a_different_sector_never_joins` |
| 5 | overlapping hubs | `test_s4_two_separate_clusters_give_two_deterministic_proposals` |
| 6 | **no actor topic, sector rule** | `test_an_actor_with_a_sector_and_no_topic_can_still_be_promoted` |
| 7 | **different topic, hub-topic persistence** | `test_a_same_sector_hub_is_assignable_even_when_its_topic_differs` |
| 8 | unassigned actor retained | `test_s6_parked_actors_are_excluded_but_a_different_topic_no_longer_excludes` |
| 9 | reruns reconsider unassigned | `test_detection_is_deterministic_across_reruns` |
| 10 | 10 families + 5 categories → proposal | `test_21_exact_ten_families_and_five_matched_categories_pass` |
| 11 | 9 families → none | `test_22_nine_families_fail_threshold_without_removal_side_effect` |
| 12 | 4 categories → none | `test_23_four_category_matching_fails_threshold` |
| 13 | units of one university = one family | `test_s7_one_family_with_several_departments_counts_once_and_cycles_fail_closed` |
| 14 | rejected cluster not re-proposed | `test_s8_a_previously_rejected_family_set_is_suppressed_by_its_fingerprint` |
| 15 | no hub auto-created | `test_detection_never_creates_a_canonical_hub` |
| 16 | no production data changed | production never contacted; all writes in `ghus_v2_demo_test` |

Scenarios 6 and 7 are the ones this week's work added.

## 8. Sector vs topic — the §7 confirmation

Asked for explicitly, so stated explicitly. The 8 October amendment **did**
change the detector, not only assignment, and it is documented rather than
silent — `docs/decisions/2026-10-08-hub-membership-keys-on-sector.md` has the
before/after table:

| | Before | After |
|---|---|---|
| Partition | one per `topic_id` | one per **sector code** |
| Test 1 | actor topic == hub topic | actor sector == hub sector |
| Topic | the gate | **recorded on the proposal** as `topic_mix` + dominant topic |

**Unchanged:** 10 families, 5 matched categories by maximum bipartite matching,
50-mile core, 200-mile cluster, family independence, centre-finding,
determinism, proposal-only.

It is reversible without a code edit: `HubDetectionConfig.cluster_dimension`
takes `"sector"` or `"topic"`, and the original 49-test Phase 7 suite still runs
in `"topic"` mode, so the earlier rule stays proven.

**If GHUS intended the amendment to govern assignment only and leave detection
grouped by topic, the default is currently wrong** and the switch is one config
value. That is worth confirming before Monday.

## 9. Remaining blockers

1. **Actor discovery cannot promote** (§4). Needs the Phase 5 classification
   call wired into the discovery path.
2. **Cutover attestation** — unchanged, schema owner's.
3. **`REVIEW_STORE_DB`** — still unset; must point at durable storage before
   anyone reviews anything.

## 10. Reproducing the demo

```bash
# 1. the isolated database
psql -c "CREATE DATABASE ghus_v2_demo_test TEMPLATE ghus_v2_cutover_test;"

# 2. the demo instance
cd C:/Users/Ismail/Projects/Institutional-knowledge-Platform
python -m scripts.run_demo_server --port 8030 --database ghus_v2_demo_test
# open http://localhost:8030 and choose Review

# 3. the hub algorithm, end to end
cd C:/Users/Ismail/Projects/GHUS-Platform
python -m pytest tests/agent/test_hub_detection_fixtures.py \
                 tests/agent/test_architecture_v2_hub_detection.py -v
```
