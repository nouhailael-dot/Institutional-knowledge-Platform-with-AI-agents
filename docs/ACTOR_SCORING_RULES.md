# How the discovery agent scores and decides on an actor

Source of truth: `GHUS-Platform/agents/discovery/search/actor_scoring.py`
(score), `actor_quality.py` (decision), `agents/config/sources.yaml`
(weights, thresholds, gate settings). Everything below is configuration
except the formula itself.

## Stage 1 — which search results are read at all

Each search result first passes a cheap **fetch gate** (Claude, one line per
URL): "is this plausibly an organisation's own substantive page worth reading?"
Aggregators, social networks, blocked domains, already-seen URLs and
privacy/legal pages are dropped before that, deterministically. Only results that
pass are fetched (at most 40 pages and 40 new domains per run).

## Stage 2 — the rubric: what the model must find on the page

The model reads the page and fills an **evidence checklist**. Rule given to it:
*"set present = true only when the page contains specific supporting evidence,
and quote or tightly paraphrase it."* Page text is treated as untrusted data;
the factual record must contain only what the page states (nulls otherwise).

| Criterion | Weight | Counts when the page shows… |
|---|---:|---|
| `use_cases` | **0.16** | concrete engagement routes, as a fraction of 8: research collaboration, learning expeditions, executive education, mentorship, student/faculty mobility, open innovation, corporate engagement, opportunity development |
| `real_operating_entity` | **0.11** | an operating organisation (staff, activities, operations) |
| `own_organisational_page` | **0.10** | the page is the organisation's own |
| `distinctiveness` | **0.10** | `1 / (1 + n)`, n = actors GHUS already maps in the same hub and sector — a new kind of actor in a thin area scores highest |
| `research_development_or_programmes` | 0.08 | active research, development, facilities, projects or programmes — *sales, catalogues, reselling and distribution alone do not count* |
| `partnerships_or_tech_transfer` | 0.08 | partnership or technology-transfer activity |
| `partnership_precedent` | 0.08 | named past collaborations |
| `named_route_in` | 0.08 | a named office or contact route for partnering |
| `open_programmes` | 0.07 | programmes outsiders can join (calls, accelerators, fellowships) |
| `sector_coverage` | 0.07 | work in at least one GHUS sector (AGRI, AI, CHEM, ENERGY, HEALTH, MINING, SUSTAIN, WATER) |
| `network_membership` | 0.04 | membership of consortia or innovation networks |
| `hub_match` | 0.03 | the page matches an existing GHUS hub |
| **Total** | **1.00** | |

**Score** = Σ weight × value, where each criterion is 1 (evidenced) or 0, except
`use_cases` (fraction of the 8) and `distinctiveness` (above). Three calibrated
example pages (a university, a foundation, a municipal department) are given to
the model as anchors.

## Stage 3 — the decision: score **and** hard gates

| Outcome | Rule |
|---|---|
| **Rejected** — never stored as an actor, never reviewed | score **< 0.45**, *or* any reject gate fails |
| **Sent to Review** — a GHUS person decides | everything between |
| **Accepted → created Verified** | relevance score **≥ 0.80** (0.85 until 15 Oct 2026) *and* every accept gate holds *and* engagement priority **≥ 0.70** |

**Reject gates** (any one → rejected, whatever the score)
1. The page names no organisation.
2. It is a list, directory, ranking, event, webinar, news, press or careers page (by its name or its URL path).
3. A request named a sector, and the page shows no evidence of it.
4. A request named an area, and the organisation is located outside it.

**Accept gates** (all must hold to accept; any failure → Review)
1. An official website is stated.
2. The page is **on** that website's domain (a page *about* the organisation on someone else's site is not enough).
3. At least **5** criteria are evidenced.
4. The page establishes an operating organisation.
5. It names concrete programmes, research or use cases.
6. A real description: at least **60** characters, 1–3 sentences, not a tagline.
7. If the request has sub-topics, the page mentions at least one of them.

Every decision stores its reasons, shown in Review and on the request's results.

## Stage 4 — what "accepted" writes (decision 2026-10-14)

An accepted actor is created **Verified**, through an `actor_verification_event`
labelled `agent_auto_accept`, `decided_by = discovery-agent`, whose reason lists
the score and every check above. It is never confused with a person's
verification (`ghus_review`), and a person can still reject it later in Review.
Setting `actor_auto_accept_status: parked` in `sources.yaml` restores the
previous flow (Parked + a verify item for a person).

## Per request

A request also caps how many organizations one run may add (default 10, max
50): accepted first, then review, by score. The rest keep their evidence on the
candidate record but are not added or queued.
