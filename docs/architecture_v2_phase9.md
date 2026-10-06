# Architecture V2 Phase 9 report — Light Pull

Date: 2026-10-05

Backend repository and branch: `C:\Users\Ismail\Projects\GHUS-Platform` on
`codex/architecture-v2`

Shared Review repository and branch:
`C:\Users\Ismail\Projects\Institutional-knowledge-Platform` on
`feature/ismail-modifications`

## Scope and safety

Phase 9 replaces the prior placeholder that copied arbitrary staged payload
fields and called them Light Pull facts. No production connection, DDL, or data
write was performed. The frozen 180--350 package, Agent 3 compatibility,
person-discovery default, canonical-writer boundary, and deferred breaking
schema work are unchanged.

## Collection contract

`agents/collection/light_pull.py` defines one common Layer 1 schema and one
category-specific schema for each of the 12 Phase 5 categories. Collection is
restricted to those keys and one topic. Unknown keys fail closed. The optional
page reader accepts already-read documents and an injected robots-aware
fetcher, deduplicates URLs, and performs at most three network fetches. Normal
promotion reuses staged evidence and performs no surprise crawl.

Every schema key produces an immutable ledger fact with `found`, `not_found`,
or `not_yet_collected`, plus source URL, source origin, date read, confidence,
layer, creator, and request ID. The approved `append_actor_fact` writer is the
only new canonical fact path. Unscoped legacy bridge inputs remain compatible
but are not falsely labeled as topic-scoped Light Pulls.

## Ordered actor pipeline

The existing mapping order remains unchanged. Classification and geography
are validated before collection. The Light plan includes derived region and
coordinates, explicit typed relationships or a complete standalone state, and
the Phase 6 hub plan with all evaluated distances, radii, outcomes, and the
selected hub. The facts are appended before the new actor is left Parked and a
`verify_actor` item is created. Dry-run remains the default and executes the
same plan/write path under rollback.

## Evidence safeguards

- Descriptions must contain 1--3 sentences.
- Match strength is only strong/moderate and its reason is 1--2 sentences.
- Recent activity, when found, requires a date and description.
- Rankings exist only in the university schema. Exact QS, THE, U.S. News, and
  ARWU ranking-name pairs are enforced, with year, ranked entity, and position
  required; subject rankings require a subject/specialty.
- College/school and academic-department records cannot inherit a
  university-wide ranking.
- Startup stage or TRL remains `not_found` unless explicit published evidence
  is supplied. It is never estimated.
- No people fields or people discovery were added.

The controlled UM6P/OCP entity list required for the definitive matcher is not
available in the repository and remains Phase 13. Phase 9 therefore records
`not_yet_checked` unless upstream extraction supplies explicit evidence; it
does not turn absence into a negative claim or launch a dedicated search.

## Review visibility

The shared Review page now presents Layer 1 facts separately, with readable
collection state, value, confidence, date read, and source link. It explains
that `not_found` means absent from pages read rather than nonexistent. Review
and admission decisions were not changed.

## Validation

- Focused strengthened Phase 9 plus ordered promotion proof: **23 passed**.
- Complete backend agent/integration regression: **452 passed**, with 2
  inherited SQLite adapter warnings.
- Complete shared Review/map Node suite: **22 passed** (using its required
  `--experimental-vm-modules` flag).
- Complete shared Python suite against the isolated local database: **137
  passed, 30 subtests passed**.
- The first shared Python invocation used the system interpreter and produced
  10 import failures because `python-pptx` was absent; rerunning in the
  repository's managed runtime produced the clean result above.

The broad historical schema test file is not the three-gate acceptance subset:
against the functional integration manifest it also reports the intentional
post-390 proposal 420 and tables not installed by that partial manifest. No
test was skipped, weakened, or edited to hide those differences.

## Deferrals

The three approved breaking gates remain deferred: physical removal of
`actor_type`, physical removal of `verification_status`, and expansion of the
existing production-compatible `review_item` CHECK for `verify_actor`. Phase 9
does not alter them. Deep Pull is Phase 10; existing-data backfill is Phase 12;
the controlled UM6P/OCP matcher is Phase 13; ranking context persistence and
final database guards remain P15/P16.
