# How COMPASS ranks and filters what it discovers

For the demo run-through, 4 November 2026. Every rule below is what the code does
today (`agents/discovery/search/actor_quality.py`, thresholds in
`agents/config/sources.yaml`). The figures come from the shared database.

## The point to make in the demo

A general chatbot returns a list. COMPASS applies GHUS's own criteria to every
result, shows the evidence behind each score, removes what is already mapped, and
records **why** each result was left out. Nothing enters the Ecosystem Directory
without a GHUS person.

## Where to show it in the platform

1. **Monitor and Update → a request → its results.**
   - Each kept organization shows **Relevance** and **Engagement priority**, why it
     matched, and **Sent to Review Results**.
   - **Not added (N)** lists every result that was left out, each with its reason.
2. **Review Results.** A person verifies or rejects what was kept.

Live example: *AI in healthcare research centers in Massachusetts* (2 November):

| Step | Count |
|---|---:|
| Web results found | 105 |
| News or press pages, left out | 21 |
| Already in the Directory, left out | 13 |
| Wikipedia and other blocked sources, left out | 8 |
| Pages of an organization already found | 10 |
| Sites that refused to be read | 7 |
| Organizations named in articles, not read (on the map already, or no official site) | 5 |
| **Read and scored** | **6** |
| **Sent to Review Results** | **5**: Massachusetts AI & Technology Center, Health AI Initiative, UMass BioNLP, Beth Israel Lahey Health, Roche |
| Rejected by its score | 1 |

The run cost $0.75. Over the last 30 days: **2,298 results → 183 sent to Review**.
Of the rest, 1,836 were filtered out, 99 were duplicates, and 114 could not be read.

## The three stages

### 1. Filter before reading (cheap)

Results are left out **before** any page is read when they are:
- a blocked source (Wikipedia, directories);
- a document repository (PDFs, filings);
- a news, press, event or careers page;
- already in the Directory;
- another page of an organization already found.

A quick check keeps only pages that plausibly belong to an organization. It does
not score anything.

### 2. Score the organization's own page: two scores, both 0 to 1

The model reads the page and marks each criterion **present** or **absent**, with
a quote from the page as evidence. The code computes the score from fixed weights,
so the model does not choose the number.

**Relevance: is this a real, in-scope organization?** This score decides what is kept.

| Criterion | Weight |
|---|---:|
| Research, development or programmes named | 0.25 |
| Its own organizational page | 0.15 |
| A real operating entity (staff, programmes, operations) | 0.15 |
| Work in the requested sector | 0.15 |
| Partnerships or technology transfer | 0.15 |
| Identity stated (own website, location) | 0.15 |

**Engagement priority: how valuable is it for GHUS?** This score only orders the
results; it never excludes one. It covers:
- GHUS use cases evidenced (0.30);
- distinctiveness, meaning few organizations already mapped in that hub and sector (0.15);
- open programmes (0.12);
- a named route in (0.12);
- partnership precedent (0.10);
- partnerships (0.10);
- networks (0.06);
- hub match (0.05).

### 3. Decide

| Outcome | When |
|---|---|
| **Filtered out** | **Any** of these, whatever the score: no organization named, unreadable page, a list, event or article, outside the requested sector or area, closed or defunct, or **relevance below 0.45** |
| **Sent to Review Results** | Relevance 0.45 or above |
| **Met every criterion** | Relevance **0.80** or above, **and** all of these: its own website, at least 5 criteria evidenced, an operating entity with concrete work, a real description, the requested sub-topic mentioned |

Meeting every criterion **still goes to Review today.** Verifying without a
person is switched off until GHUS confirms it (`GHUS_AGENT_AUTO_VERIFY`), and
it would also need engagement priority of 0.70 or above. On the Monitor page these
results read **"Sent to Review Results · met every criterion"**.

## Filtered out vs. rejected in Review

| | Filtered out by the agent | Rejected by a person in Review |
|---|---|---|
| Who decides | The ranking rules above | A GHUS reviewer |
| When | During the run, before it reaches anyone | After the agent kept it |
| Where it shows | Monitor → the request → **Not added**, with the reason | Review Results → **Rejected** |
| What is recorded | The result and its reason in the run's audit; never a Directory record | The reviewer's decision and reason, kept in the record's history |
| Can it come back? | A later run may find it again and judge it afresh | The record stays rejected and out of the Directory. Today a later discovery run can still propose the same organization again: rejected records are not used to skip results, because rejected placeholder rows share domains (energy.gov, un.org) with real organizations. **Open decision for GHUS:** skip a website a reviewer rejected. |

The agent narrows thousands of web results to a few evidenced candidates; a
person makes every final decision.
