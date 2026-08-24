# Agent Targeting & Scraping Policy

Applies to all agents in the GHUS platform: discovery (Agent 1), enrichment
(Agent 2), and sector discovery (Agent 3, teammate-owned).

Status: draft for review. Sections 2 and 6 need sign-off from the internship
supervisor before any live run at scale.

---

## 1. Purpose

The platform maps the ecosystem relevant to UM6P's Global Hubs in the United
States. Agents exist to close the gap between what that ecosystem contains and
what the database currently holds.

This document defines **what agents pursue**. It does not define what they do
with what they find — routing, entity resolution, and provenance are governed by
`AGENTS.md`.

---

## 2. Scope of interest

Three dimensions define whether something belongs in this database. A record
should satisfy at least two.

**Thematic.** The seeded sectors in the `sector` table are the authoritative
list. They are not restated here on purpose — a hardcoded copy in a document
drifts from the database and then quietly becomes wrong. Agents read the live
list:

```sql
SELECT code, name FROM sector ORDER BY code;
```

`CROSS` (cross-thematic) is not a catch-all. An entity earns `CROSS` only by
demonstrably spanning two or more named sectors. An entity matching no sector
gets an empty sector list — see §4.

**Geographic.** The US ecosystem is the centre of gravity: US-based
organizations, events held in the US, and US institutions. Two deliberate
extensions: entities anywhere with an existing or plausible UM6P partnership,
and international convenings that the US ecosystem attends — UNGA and Climate
Week NYC are the current examples.

**Relational.** Entities that plausibly connect to UM6P's mission: research
institutions, funders, ventures, policy bodies, and conveners operating in the
seeded sectors. A commercial vendor with no research or partnership dimension
is out of scope even if its sector matches.

---

## 3. Targeting happens before filtering, not instead of it

A common misreading: "only search in our sectors" cannot mean "discard
everything else." Three distinct levels:

| Level                          | Question                          | Governed by                 |
| ------------------------------ | --------------------------------- | --------------------------- |
| Source selection               | Which sites do we scrape at all?  | this policy, `sources.yaml` |
| Within-source targeting        | Which pages, categories, filters? | this policy, adapter config |
| Post-extraction classification | Does this record match a sector?  | `relevance.py`              |

The first two are where "target our sectors" applies. A source whose content is
overwhelmingly outside our sectors should not be in `sources.yaml`. Within a
source, prefer category or filter URLs that align with our sectors over
scraping everything.

The third level classifies but **does not discard**. See §4.

---

## 4. Out-of-sector records are staged, never dropped

Every extracted record is staged. Those matching no sector are marked
`sector_match = 'out_of_sector'` and go no further into routing or promotion.

They are kept for three reasons:

1. **Agent 3's input.** The sector-discovery agent reads
   `staged_record WHERE sector_match = 'out_of_sector'` looking for clusters
   that suggest a sector we have not seeded. Discarding them starves it.
2. **Auditability.** "What did the filter reject last week" must be answerable.
3. **Error detection.** A misconfigured extractor that mislabels sectors is
   visible as an anomalous out-of-sector rate. If nothing is ever rejected,
   the filter is not working — that condition has already occurred here, when
   `CROSS` was used as a fallback and made `out_of_sector` unreachable.

**Health check:** an out-of-sector rate of exactly zero across a run is a
defect signal, not a success signal. Real-world sources always contain
irrelevant content.

---

## 5. Gap-driven prioritization

The database knows where it is thin. Agents should target sparsity rather than
accumulating more of what is already well covered.

**Sector coverage** — which sectors have few actors or events:

```sql
SELECT s.code, s.name,
       count(DISTINCT a.actor_id) AS actors,
       count(DISTINCT e.event_id) AS events
FROM sector s
LEFT JOIN actor_sector asx ON asx.sector_id = s.sector_id
LEFT JOIN actor a ON a.actor_id = asx.actor_id
LEFT JOIN event_sector es ON es.sector_id = s.sector_id
LEFT JOIN event e ON e.event_id = es.event_id
GROUP BY s.code, s.name
ORDER BY actors + events ASC;
```

**Field sparsity** — which fields are missing across existing records. This is
Agent 2's queue, and `agents/config/fields.yaml` already defines what counts as
enrichable.

**Structural gaps.** Two are known and standing:

- `person` and `actor_person` hold zero rows. The database has no named
  contacts at all. This is the largest single gap, and also the one with the
  strictest constraints (§6).
- Actor descriptions were sparse before enrichment raised coverage
  substantially. Sparse descriptions degrade entity resolution directly, since
  description features drive a large share of match coverage.

**Priority order** for discovery targeting, highest first:

1. Sectors with the fewest entities
2. Entities that would connect existing isolated records — an event whose host
   is already an actor, an actor already linked to a hub
3. Recency: events in the next 6–12 months over historical ones
4. Breadth within a well-covered sector

**Review cadence:** rerun the coverage query monthly and adjust source
priorities. Coverage shifts as the database grows, so a static priority list
goes stale.

---

## 6. Personal data

Stricter than everything above, and the section that most needs supervisor
sign-off.

**Permitted:** name, professional affiliation, role or title, public
professional profile URL, stated research area. Only where published by the
person or their institution in a professional context.

**Not permitted:** personal email addresses, phone numbers, home or personal
addresses, biographical detail beyond professional role, anything from social
media not published in a professional capacity, and anything behind
authentication.

**Handling:** person records are never auto-created and never auto-absorbed.
Every one routes to human review regardless of match score, enforced in
`promote()` rather than by convention. No ER model exists for people, and name
collisions are far more damaging for individuals than for organizations.

**Before scraping named individuals at scale**, the lawful basis must be
documented and approved. UM6P is an institution and the people involved are
identifiable researchers. This is a decision for the supervisor, not a technical
default.

---

## 7. Source admission

A source enters `sources.yaml` only when all of the following hold:

- content is predominantly within the scope of §2
- `robots.txt` permits the paths to be fetched
- terms of service do not prohibit automated access
- a rate limit is set, and the User-Agent carries a monitored contact address
- content is server-rendered or reachable through a documented endpoint —
  discovered by inspection, not assumption

That last point is not procedural. A source was added on guessed URLs, and the
first live run fetched five marketing pages, extracted nothing, and reported
success. Inspect before adding.

**Current sources:** `unga_programme`, `unga_guide`, `climate_week`. All three
are convening-driven and cluster around September. Deliberate for now; a
year-round source should be added before the platform is judged on continuous
coverage.

---

## 8. Per-agent application

**Agent 1 — discovery.** Chooses sources and within-source targets per §2, §3,
§5, §7. Stages everything, promotes only in-sector.

**Agent 2 — enrichment.** Targets gaps per §5 on entities already in the
database. Never expands scope; it deepens what exists. Fills gaps only, never
overwrites, and proposes anything below its confidence floor.

**Agent 3 — sector discovery (teammate).** Reads the out-of-sector staging pool
per §4. Its output is a _proposal_ that a new sector exists, for human decision.
It does not seed sectors autonomously — the sector list is what all other
targeting derives from, so changing it changes everything downstream.

---

## 9. Change control

Adding or removing a seeded sector changes the behaviour of every agent. Such
changes are human decisions, recorded with reasoning in `agents/README.md`.

This policy is reviewed when: a source is added or removed, the sector list
changes, coverage priorities shift after the monthly query, or the personal-data
position is revised.
