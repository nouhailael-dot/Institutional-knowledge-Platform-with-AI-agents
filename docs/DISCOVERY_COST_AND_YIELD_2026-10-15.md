# Actor discovery: lower cost, more actors — 2026-10-15

Everything was measured on the isolated demo database. Production Supabase
was not touched, and nothing is committed.

## Result: same October 14 candidates, same spend

The revised pipeline was replayed on **the 185 search results of the October 14
baseline run**: no new searches, the baseline's own "already seen" set, a cold
analysis cache, no database writes, and the ceiling set to the baseline's actual
spend.

| | Oct 14 baseline | Revised (replay) |
|---|---:|---:|
| Total cost | $1.286 | $1.297 |
| Search (identical results) | $0.522 | $0.522 |
| Triage | ~$0.30 (30 calls) | **$0.10** (6 calls) |
| Organisations kept (Review / added) | 8 | **13** (10 + 3 held by the 10-per-run limit) |
| Stale or junk kept | 1 (CVPS, from a 2009 SEC filing) | 0 |
| **Cost per organisation kept** | **$0.16** | **$0.10 (−38%)** |
| Organisations named in rejected news, lists and documents | thrown away | 30 named, 18 checked on their own sites |

The baseline figure flatters the baseline: 7 of its pages came from cache at no cost.

A first replay with a $1.00 ceiling kept only 4. That exposed the problems fixed
below: the budget was eaten before leads were reached, the ceiling was
overshot, and retries were blind.

## Two live runs (on the Discovery page)

| Request | Cost | Results | To Review | Notes |
|---|---:|---:|---:|---|
| Energy, Northeast (Oct 14, old pipeline) | $1.29 | 185 | 8 | baseline |
| **Water technology, Great Lakes (Oct 15, new pipeline)** | **$0.94** | 141 | **8** | under its $1.00 ceiling; 16 queries instead of 24 |

Water run finds: The Water Council (Milwaukee), the Energy & Environmental
Research Center (North Dakota), the Indiana Water Resources Research Center, NEW
Water (Green Bay), and North Dakota water associations. The WateReuse
Association was rejected because it is headquartered in Virginia, outside the
area. Each kept organisation shows its location, type, focus, current activity,
funding, why it matched, relevance, engagement priority and, for Review items,
why a person should look. Everything not added is listed with its reason.

The live run also surfaced three accuracy flaws, now fixed: a TV station
harvested from its own article, footer years missed, and "tech" not matching
"technology".

## What changed, by goal

### Lower cost

- **Page scoring stays on Sonnet; tested.** Haiku re-scored the same 34 pages for
  half the price, but agreed on the band only 15/27 times, scored 0.09 higher on
  average, failed validation on 7/34, and would have auto-verified 4 pages that
  Sonnet held, including a news article. Rejected.
- **Triage stays on Sonnet; tested.** Haiku cost $0.055 instead of ~$0.30 but let
  13 extra pages through to Sonnet (about +$0.27) and missed Enphase and United
  Illuminating. The savings came from elsewhere:
  - Answers by number instead of echoing every URL. One call measured 1,793
    output tokens, about 70% of its cost.
  - 20 results per call instead of 4.
  - A free filter for document repositories (PDFs, dockets, filings, data
    catalogues). Their titles still feed leads.
- **Classification only for kept pages, inside the page budget.**
- **No rerank** ($0.08 a run). Engagement priority orders the list at no cost.
- **Strict budget, stopped gracefully, with a ceiling that holds.** The page
  estimate learns from real page costs. Lead harvesting and classification are
  inside the budget. Shares mean direct results cannot starve official-site reads
  and leads. Pages not read get an explicit reason.
- **Targeted retry.** When the model omits the rubric (`stop=tool_use`: an
  omission, not truncation), the one retry names what was missing. A truncated
  answer gets more room.
- **16 search queries per request instead of 24**, at about $0.022 each.

### More actors

- **Leads.** Organisations named in rejected news, lists and documents are
  harvested by one cheap Haiku call per 25 results. Each lead's official site is
  confirmed for free before any money is spent on it. A missing website is
  resolved for free from the article's own link (5 in the replay). Vague names
  ("Vermont utility") and the article's own publisher are dropped.
- **Official-site reads.** The homepage and About page are read together. Strong
  candidates held only because the page wasn't their own are re-read there.
- **robots.txt per RFC 9309.** A 4xx means "unavailable", not "refused". In
  practice those sites also block the page itself, so the gain was small.
- **A malformed or over-long label no longer discards a paid page**, and neither
  does an unlisted hub name.
- **The use-case evidence bug is fixed.** It was never counted as "concrete
  work", which held CPower.

### Legitimate vs outdated or merged (free, deterministic)

- A site that now redirects to another organisation's site, which doesn't name
  it: merged, acquired or renamed → rejected.
- A page saying *this* organisation merged, was acquired or ceased operations →
  rejected. The sentence must name it.
- Newest date on someone else's page four or more years old → rejected
  (CVPS, 2011). On its own site → held for a person.
- Every finding states what was seen.

### Relevance separate from engagement priority

- **Relevance** (keep or reject) is innovation activity plus identity:
  - own page 0.15
  - operating organisation 0.15
  - in a GHUS sector 0.15
  - R&D or programmes 0.25
  - partnerships or tech transfer 0.15
  - website and location stated 0.15
- **Engagement priority** (ordering only):
  - use cases 0.30
  - open programmes 0.12
  - named contact route 0.12
  - past collaborations 0.10
  - partnerships 0.10
  - networks 0.06
  - distinctiveness 0.15
  - hub match 0.05
- Thresholds are unchanged (0.45 / 0.85, on relevance). Replayed on 105 stored
  candidates, rejections fall from 32 to 11, so 21 legitimate organisations are
  kept.
- **Verifying without a person also needs priority ≥ 0.70.** On relevance alone
  30% would be auto-verified, against 5% under the approved policy. With the
  floor it is 7 of 105. Configurable: `actor_quality.accept_min_priority`.

### Explicit reasons for exclusion

Every exclusion path records its sentence: rejected, not read (budget, share,
lead limit), superseded by an official-site read, failed to load, held back by
the per-run limit, lead already on the map, lead with no known website, lead is
the publisher, site not confirmed. A test asserts that no excluded candidate is
left without a reason. The Discovery page lists them.

### Deep Pull cannot be bypassed: verified

- The gate reads only person decisions (`ghus_review`) for the exact actor and
  topic.
- Database test: an agent-verified actor is `verified`, yet Deep Pull is refused.
  A person's verification for topic A opens topic A only.
- Guard test: only `agents/collection/deep_pull.py` writes Layer 2 facts.

## Tests

- Backend: 762 passed, 3 failed. The failures pre-date this work:
  `smoke_test_actor_merge.py` ×2, and the installed `anthropic` package version.
- Integration on a real database: 5/5.
- Platform: Discovery UI tests 14/14.
- New: `tests/agent/test_actor_retrieval_and_currency.py` (26),
  `test_actor_triage_answers_by_id_and_keeps_every_reason`, the Deep Pull
  integration test, and `scripts/evaluate_actor_pipeline.py` (the replay harness;
  reads only, local `_test` databases only).

## Spend

About $4.5 in model calls:
- two replays ($1.06, $1.30);
- one replay that crashed in the harness before finishing (spend not recorded,
  about $1);
- the live Water run ($0.94);
- the Haiku page and triage tests ($0.33);
- a triage token measurement ($0.04).

## Decisions for you

1. **Auto-verify floor (0.70).** Lower it to verify more without a person;
   0 means relevance alone.
2. **Ceiling $1.00 and 16 queries per request.** Raising either finds more, for
   more money. At $1.29 the replay kept 13.
3. **Migration 560** (agent verification origin) needs the schema owner for
   production, as 550 does.
