# Open-Web Discovery Report: 44be6737-5c99-44e4-86ff-cea509b0f900

Status: **attention**

Reason: max_candidates_triaged cap hit: 3 survivors, 2 sent to LLM

## Stats

| Metric | Value |
| --- | ---: |
| absorbed | 0 |
| accepted | 2 |
| blocked_domains_skipped | 0 |
| candidates_written | 3 |
| cost_usd | 0.0 |
| created | 0 |
| deterministic_queries | 1 |
| deterministic_rejected | 0 |
| deterministic_survivors | 3 |
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
| rejected | 1 |
| search_results | 3 |
| search_results_deduplicated | 0 |
| search_results_unique | 3 |
| searches_executed | 1 |
| skipped_unchanged | 0 |
| triage_cap_rejected | 1 |
| triage_incomplete | 0 |

## Queries

### event
- `q`

## Candidates

### event

| Score | Verdict | Domain | Title | URL | Reason | Query |
| ---: | --- | --- | --- | --- | --- | --- |
| n/a | rejected | three.example | Title for https://three.example/page | https://three.example/page | max_candidates_triaged cap hit before LLM triage | q |
| 0.950 | accepted | one.example | Title for https://one.example/page | https://one.example/page | matches reference set | q |
| 0.950 | accepted | two.example | Title for https://two.example/page | https://two.example/page | matches reference set | q |
