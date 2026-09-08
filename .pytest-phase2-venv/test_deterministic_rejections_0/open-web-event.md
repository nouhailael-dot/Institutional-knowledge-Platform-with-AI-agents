# Open-Web Discovery Report: 52f812ac-0eab-436c-a7b9-8c522edafc33

Status: **succeeded**

## Stats

| Metric | Value |
| --- | ---: |
| absorbed | 0 |
| accepted | 0 |
| blocked_domains_skipped | 0 |
| candidates_written | 4 |
| cost_usd | 0.0 |
| created | 0 |
| deterministic_queries | 1 |
| deterministic_rejected | 4 |
| deterministic_survivors | 0 |
| failures | 0 |
| fetch_candidates | 0 |
| fetch_failures | 0 |
| llm_queries | 0 |
| new_domains_eligible | 0 |
| pages_fetched | 0 |
| pages_selected | 0 |
| queries_generated | 1 |
| queued_for_review | 0 |
| records_extracted | 0 |
| records_in_sector | 0 |
| records_out_of_sector | 0 |
| records_promoted | 0 |
| records_relevant | 0 |
| records_staged | 0 |
| reference_count | 0 |
| rejected | 4 |
| search_results | 4 |
| search_results_deduplicated | 0 |
| search_results_unique | 4 |
| searches_executed | 1 |
| skipped_unchanged | 0 |
| triage_cap_rejected | 0 |
| triage_incomplete | 0 |

## Queries

### event
- `q`

## Candidates

### event

| Score | Verdict | Domain | Title | URL | Reason | Query |
| ---: | --- | --- | --- | --- | --- | --- |
| n/a | rejected | blocked.example | Title for https://blocked.example/page | https://blocked.example/page | blocked domain: blocked.example | q |
| n/a | rejected | known.example | Title for https://known.example/events/one | https://known.example/events/one | domain already covered by configured source: known.example | q |
| n/a | rejected | seen.example | Title for https://seen.example/page | https://seen.example/page | already in raw_document; Phase 1 does not fetch pages to recompute content hash | q |
| n/a | rejected | valid.example | Title for https://valid.example/privacy/policy | https://valid.example/privacy/policy | obvious non-content URL pattern: /privacy | q |
