# Build the Map: saved jobs and cost tracking

Build the Map now has a controlled, resumable workflow: usage accounting, budget
reservations, bounded search, cached page excerpts, durable partial results,
cancellation, and explicit continuation. It does not certify a provider billing
ceiling; ledger values remain estimates based on reported usage and configured
prices.

## Current behavior

- The UI creates a map session before planning. Planning, discovery, enrichment,
  selection, and verification use the same session budget: $2 by default for new
  maps. An explicit, recorded approval can raise it once to $3 total. Existing
  saved budgets are unchanged, including legacy $1 maps.
- `costs.paid_message` is the only paid Messages API gateway for map modules.
  It disables SDK retries, counts input tokens, reserves an allowance, and saves
  response usage, pricing, duration, and returned evidence. Unknown model prices
  or unsupported tools are rejected before payment.
- Reservations use integer micro-dollars and SQLite transactions. Pending calls
  count against the same budget. Unknown charges retain their allowance and block
  new calls; a timeout is not assumed to be free.
- Costs are estimates at standard first-party global API rates, before taxes,
  contractual discounts, or other account activity. The configured rate snapshot
  is stored on every call. Token-count headroom is not a provider billing limit.
- Autonomous multi-search loops remain blocked. Controlled research uses
  separately dispatched Claude web-search requests with a hard `max_uses: 1`
  per request, up to four distinct topic queries, ten captured results per query,
  and up to three full-page reads per query. Each Claude search costs $0.01 plus
  model tokens. A conservative allowance for search-result input is reserved
  before dispatch; provider-reported usage is settled afterward. Claude's token
  counter does not accept server tools, so web-search requests use a conservative
  local UTF-8-size estimate plus fixed result headroom. Other model calls still
  use the free token-count endpoint.
  Search results and both successful and failed page reads are cached per map.
  Full-page reads are free HTTP operations but bounded by address, type, time,
  byte, and extracted-text limits. Redirects, private destinations, downloads,
  scripts, compression, and nonstandard ports are rejected.
- Search is organization-first. Named people already supported by organization
  evidence are retained. Selected organizations still missing people get a
  targeted official-domain search; existing pages are reused. An explicit
  affiliation and a supplied source are required before a person is attached.
- Extraction receives bounded evidence and cannot browse. Supplied pages are
  treated as untrusted data. Model-returned citations that were not in the
  supplied evidence are discarded. The UI shows coverage gaps and explicitly
  says the result is focused rather than exhaustive.
- Map uploads extract text only. Ask uploads keep their existing embedding path.
- The workflow checkpoints its cursor and visible results after every extraction.
  Each paid operation has a deterministic identifier, so an interrupted safe
  continuation replays the stored response rather than sending it again. A
  worker-attempt number prevents an older worker from spending, finishing, or
  overwriting a newly continued map.
- Stop blocks subsequent paid calls. An already-dispatched call may finish and
  be charged; its late evidence and usage are still recorded.
- Startup marks unfinished jobs interrupted and pending charges unknown. It does
  not resubmit them. Safe unfinished work can continue only after the user clicks
  Continue; unknown/pending/overrun charges and manual stops cannot resume. The
  same total budget and saved plan remain in force.

## Storage and operation

Default: `.map_runs/runs.sqlite3` (gitignored). Override with `MAP_RUN_DB` for an
isolated test/deployment. The file includes document excerpts, records, sources,
conversation text, and returned evidence. It never records API keys.

Run one API worker per SQLite store. Startup recovery assumes the previous worker
has stopped. Do not use multiple worker processes or hot reload during paid work.
There is no automatic deletion. Back up the local store if records must survive
loss of this computer. This retains the existing local single-user access model.

Read saved records with `GET /api/maps` and `GET /api/map/{id}`. Cancel through
`POST /api/map/{id}/stop`. Repeated starts of one active map return HTTP 409.
Paid verification requires the original map ID; it cannot get a separate budget.

`POST /api/map/{id}/budget-extension` with `{"approve":true}` records approval
of $3 total, without making an API call or starting/resuming work. Repeated
requests are idempotent. New approval is refused for active work, pending or
unknown charges, reservation overruns, manual stops, or legacy budgets. The UI
offers an explicit approval button only for eligible saved maps. Approval never
clears cancellation or starts work.

`POST /api/map/{id}/resume` with `{"approve":true}` explicitly continues an
eligible saved workflow. It does not create a new budget. The endpoint refuses
duplicate/active work and any unresolved charge.

## Validation without credits

```sh
.venv/bin/python -m unittest discover -s tests -v
node --experimental-vm-modules --test tests/test_map_ui.mjs
```

The Python tests use temporary stores and fake API responses. The JS tests parse
the full frontend and exercise its state transitions with fake fetches/hooks;
they are not a substitute for visual browser inspection. No test needs API keys.

Live research remains fail-closed unless `MAP_RESEARCH_ENABLED=1`,
`MAP_SEARCH_PROVIDER=claude`, and `ANTHROPIC_API_KEY` are configured. The
bounded Claude adapter is offline-tested, but no live search has been run since
this change. Do not enable it until the user explicitly approves a controlled
live test. Reconcile uncertain charges before releasing held allowance.

Pricing snapshot checked 2026-09-13:
https://platform.claude.com/docs/en/about-claude/pricing
Token-counting documentation:
https://platform.claude.com/docs/en/build-with-claude/token-counting
Claude web-search limits and pricing:
https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool
