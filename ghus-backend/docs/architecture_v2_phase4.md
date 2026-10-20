# Architecture V2 Phase 4 report — Geography

Date: 2026-09-29  
Repository: `C:\Users\Ismail\Projects\GHUS-Platform`  
Branch: `codex/architecture-v2`  
Starting checkpoint: `adbedc907a8f7edc4667d36f0baac288141b2b1e`

## 1. Scope and stop gate

Phase 4 was the next incomplete item after completed Phases 2 and 3 in the
approved implementation order. This change set implements geography only and
stops before Phase 5 category/type classification.

No production DDL, query, write, backup, recovery, or data mutation was run.
The validated 180–350 additive production package was not changed. The only
database changed was the isolated local `ghus_v2_test` database at
`127.0.0.1:55432`.

## 2. Implemented behavior

### 2.1 Regions and normalization

- `region_for_state` defines exactly seven regions covering the 50 states and
  District of Columbia exactly once.
- State names and USPS codes normalize deterministically.
- `DC`, `D.C.`, `District of Columbia`, and `Washington, DC` resolve to the
  Mid-Atlantic. `Washington` and `Washington State` resolve to WA and the West
  Coast/Pacific region.
- Region and coordinates are derived values. Candidate-supplied `region`,
  `region_code`, `latitude`, `longitude`, `lat`, and `lon` are discarded before
  canonical actor insertion.

### 2.2 Vendored Census Places gazetteer

- Vendored the official 2025 U.S. Census Bureau national Places Gazetteer:
  `agents/data/gazetteer/2025_Gaz_place_national.zip`.
- Source URL:
  <https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_place_national.zip>
- SHA-256:
  `49644173a453469d9bd77fb7a493b027f87567e209edaf2078aac7543ac2ee29`.
- The loader verifies the checksum and required columns and accepts only the 50
  states plus DC. The national archive's Puerto Rico rows are excluded.
- Runtime lookup is local and deterministic. It makes no network or LLM call.
- City normalization handles case, punctuation, St/Saint, Ste/Sainte,
  Ft/Fort, Mt/Mount, and Census place suffixes such as city, town, village,
  borough, municipality, CDP, and balance.
- Ambiguous normalized place names are never guessed. An exact full Census
  place-name match may disambiguate; otherwise the outcome is `not_found`.

The Census values are official internal points for Census place polygons. The
haversine acceptance examples use conventional municipal reference points so
the formula test is not distorted by boundary polygons such as San Francisco,
whose Census internal point reflects offshore territory. Gazetteer lookup and
checksum/coverage are tested separately.

### 2.3 Actor creation integration

The existing Phase 3 order remains enforced:

1. mapped first;
2. category;
3. category type;
4. geocode;
5. parent/connection;
6. hub fit;
7. light pull;
8. Parked;
9. `verify_actor`.

At the geocode step, both dry-run and live paths prepare the same deterministic
geography candidate. Single-location actors receive derived actor fields and an
`actor_location` row. Multi-location actors receive one independently geocoded
row per location and no parent actor region or coordinates.

No match, missing city, unknown state, unsupported country, or ambiguous city
produces:

- null coordinates;
- an immutable `actor_fact` with `collection_state='not_found'` and null value,
  as required by the existing fact-ledger constraint; and
- a `review_item` with existing kind `geocode` and payload issue
  `geocode_failed`, containing the diagnostic details.

The review-kind CHECK was not altered. This avoids an unapproved breaking
change to an existing table. All canonical and actor-location writes remain in
`agents/discovery/promote.py`; the writer allowlist was strengthened to cover
`actor_location` explicitly.

### 2.4 Distance

`distance_miles` is a pure haversine calculation using an Earth-radius constant
in miles. Tests cover Boston–New York at approximately 190 miles and
Sacramento–San Francisco at approximately 75 miles, each within 2%.

## 3. Additive proposal 018

Added, but never applied to production:

- `agents/sql/360_v2_city_gazetteer.sql`;
- `agents/sql/rollback/360_v2_city_gazetteer.sql`;
- logical migration `018` in `migrations/proposed/manifest.json`;
- isolated/local loader `scripts/load_us_city_gazetteer.py`.

The proposal creates only `us_city_coord` and its lookup index. It does not
alter an existing table, constraint, grant, RLS policy, trigger, function, or
default. It remains separate from the frozen 180–350 additive production apply
package.

The loader:

- defaults to a transactional dry run;
- requires explicit `--live` to commit;
- refuses every host except localhost/127.0.0.1, every port except 55432, and
  every database whose name does not end in `_test`;
- rejects passwords embedded in database URLs and never prints a connection
  string.

## 4. Isolated database proof

On `ghus_v2_test`, proposal 360 completed `up → down → up` without error.

| Existing table | Before | After second up | Result |
|---|---:|---:|---|
| `actor` | 965 | 965 | unchanged |
| `hub` | 49 | 49 | unchanged |
| `event` | 356 | 356 | unchanged |
| `actor_location` | 0 | 0 | unchanged |

After the second up, `us_city_coord` existed with zero rows. The loader dry run
processed 32,058 rows and left the table at zero. An explicit live load into the
isolated database then produced 32,058 rows, 51 distinct state/DC codes, and
only gazetteer year 2025.

Both additive-package read-only smokes passed against the isolated database:

- backend: passed, 965 actors;
- frontend compatibility: passed, 965 actors.

No shared database was contacted.

## 5. Tests

### Backend

- Full suite without live schema contracts: **325 passed, 5 skipped**, 2
  inherited SQLite datetime-adapter warnings.
- Full suite against `ghus_v2_test`: **327 passed, 3 failed**, 2 inherited
  warnings.
- Targeted Phase 3/4/schema suite without database environment: **41 passed, 5
  skipped**.
- Phase 4 targeted Ruff (`E9,F,I`): passed.
- `git diff --check`: passed.

The three database failures are the approved schema gates and were not skipped,
xfail-marked, weakened, or rewritten:

1. `test_isolated_database_contains_v2_schema` — additive schema intentionally
   still contains legacy `actor_type` and `verification_status`; their removal
   belongs to the later coordinated cutover.
2. `test_orm_columns_match_isolated_v2_database` — the same two deferred legacy
   columns intentionally differ from the final V2-only ORM shape.
3. `test_phase3_record_creation_dry_run_executes_then_rolls_back` — the existing
   `review_item` CHECK does not yet admit `verify_actor`; changing that CHECK is
   breaking and remains deferred.

The new geocode path reaches the third gate cleanly: its `not_found` fact and
`geocode` review no longer introduce an additional failure.

### Frontend

- Python suite: **54 passed**, **15 subtests passed**, 1 inherited
  Starlette/AnyIO deprecation warning.
- Node map UI suite: **9 passed**.

No frontend file changed.

## 6. Requirements satisfied

- R013–R021: fixed seven-region, 51-jurisdiction derivation and DC/WA handling.
- Actor portion of R022: regions and coordinates are derived, never candidate
  input.
- R023: immediate deterministic geography outcome, including explicit
  `not_found` and review.
- R030: checksummed static coordinates and miles-only haversine.
- R089: derived location fields, multi-location flag, and separately geocoded
  location rows.
- Dry-run default, dry/live geography parity, person discovery off, canonical
  writer boundary, and Agent 3 compatibility remain intact.

## 7. Intentionally deferred

- Legacy Hub.region UI/input cleanup remains Phase 15, completing R022 across
  every entity surface.
- Category/type classifier and coordinated actor-type cutover remain Phase 5.
- Hub assignment use of the new distance service remains Phase 6.
- Bounded Light collection and broader missing-field semantics remain Phase 9.
- Existing-data geocode/backfill remains Phase 12.
- The two legacy-column removals and `verify_actor` CHECK change remain in the
  deferred/breaking package and must deploy with matching code.

## 8. Deviations and blockers

No Architecture V2 deviation was introduced. Proposal 360 is intentionally a
new Phase 4 additive proposal rather than a change to the validated production
package. There is no new blocker. The three known schema gates remain exactly
as approved.

## 9. Stop

Phase 4 is complete and ready for review. Phase 5 has not started.
