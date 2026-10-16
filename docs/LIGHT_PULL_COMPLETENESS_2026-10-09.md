# Light Pull completeness — why fields looked empty, and what actually fixed it

**Date:** 9 October 2026
**Database:** `ghus_v2_demo_test` (isolated). Production Supabase not contacted.
**Committed:** nothing.

---

## 0. Two corrections first

**There are 5 real discovered actors, not 11.** The run promoted 12 records:
**5 created** as new actors and **7 routed to review** as matches against
existing ones (which is entity resolution working, not actors created). There
are also 13 synthetic `demo_fixture` actors for the hub-detection demo, kept
separate. No set of 11 exists.

**Light Pull was not the problem. It ran.** Every one of the 5 actors has 17–19
`actor_fact` rows at layer 1, written at promotion. The fields looked empty for
three other reasons, all now fixed.

---

## 1. Diagnosis, against the brief's eight causes

| Cause | Verdict |
|---|---|
| 1. Agent never collected it | **partly** — 7–9 fields per actor are genuinely `not_found` |
| 2. Light Pull did not execute | **no** — 90 facts across 5 actors |
| 3. Collected but not persisted | **YES — Sector.** See §2 |
| 4. In the database, not returned by the API | **YES — Sector.** See §2 |
| 5. Frontend reading the wrong key | **YES — Why It Matched.** See §3 |
| 6. Genuinely not applicable | no field was wrongly marked so |
| 7. Not found in permitted sources | yes, for the 7–9 per actor above |
| 8. Budget prevented collection | no — the run stopped at $2.60 of $5.00 |

So the empties split three ways: a real persistence gap (Sector), two display
bugs (Why It Matched, raw JSON), and honest `not_found` results.

---

## 2. Sector — collected, never persisted, never displayed

Two independent gaps, both now closed.

**The agent did determine sectors.** Every actor's `sector_topic` Light Pull
fact holds them:

| Actor | Sector codes in the fact |
|---|---|
| Sutter Health | `HEALTH` |
| Tech:NYC | `AI`, `CROSS` |
| California Water Efficiency Partnership | `WATER`, `ENERGY` |
| Seattle University — Institute | `ENERGY`, `SUSTAIN` |
| Greater Seattle AI Ecosystem | `AI`, `HEALTH`, `ENERGY`, `SUSTAIN` |

**Gap 1 — `promote.py` never wrote `actor_sector`.** It used the codes to match
hubs and then discarded them. `actor_sector` held **0 rows** for every
discovered actor. Added `_append_actor_sectors()` to the canonical writer, with
the source carried through. `actor_sector` was missing from the protected-table
allowlist purely because nothing wrote it; it now lists `promote.py` beside its
siblings `actor_topic` and `actor_location`. **Every other module is still
forbidden to write it.**

This also explains something larger: sector-grouped Phase 7 detection had
nothing to cluster because no actor in the entire database carried a sector.

**Gap 2 — the Review payload never read one.** `_from_v2_review_item` built no
`primary_sector`, so the dropdown was empty regardless. It now reads the actor's
sector link.

**`is_primary` only when the evidence names exactly one sector.** With several,
the agent has not ranked them and the screen does not either — the reviewer
chooses. `ux_actor_sector_primary` permits at most one primary per actor, and an
unranked set has none.

**Backfill for the 5 existing actors**, from each actor's **own recorded fact**,
keeping that fact's source. Nothing inferred, nothing invented. 10 links written:

| Actor | Sector shown |
|---|---|
| Sutter Health | **HEALTH** (primary) |
| Tech:NYC | **AI** (only active code; `CROSS` is not an active sector) |
| Seattle University — Institute | — two unranked, reviewer chooses |
| California Water Efficiency Partnership | — two unranked |
| Greater Seattle AI Ecosystem | — four unranked |

`actor_sector` turns out to be **append-only** (`ghus_guard_sector_link_append_only`),
so a link cannot be re-ranked later by UPDATE. That is correct and I did not
work around it.

---

## 3. Why It Matched — two boxes, one of them empty

The explanation **was** recorded. For Tech:NYC:

> "Found by open-web discovery for hub 'New York City AI Hub (Columbia - NYC -
> Cornell Tech)' (topic AI); the page's own sector evidence matches the topic."

But the screen had **two** "Why It Matched" boxes: a dedicated one reading
`agent_metadata.why_matched` (which discovery does not set on this path, so it
said *Not Yet Collected*) and a Light Pull row rendering the real fact as raw
JSON. One empty box beside one unreadable one.

Fixed: the dedicated box now falls back to the recorded fact
(`whyMatchedFact()`), and the duplicate row was removed from
`COMMON_LIGHT_ROWS`. It reads *Strength · Date Read · the sentence · source*.

**Nothing reconstructs an explanation.** If neither source holds one, the box
still says Not Yet Collected.

---

## 4. Structured facts rendered as raw JSON

`formatFactValue` did `JSON.stringify(value, null, 2)` for any object, so a
reviewer saw `{ "state": "not_yet_checked" }` and
`{ "reason": "Found by open-web…" }`.

Now: a single meaningful sentence renders as itself; a small object renders as
labelled lines (`State: not_yet_checked`); arrays join; JSON remains only as the
last resort. The old behaviour was pinned by a test asserting the raw JSON — I
updated that assertion to the new behaviour rather than leaving it to fail, and
added cases for each shape.

---

## 5. State — already correct, and worth saying why it looked wrong

State renders. The confusion is that **the queue holds two entries per actor**:

```
Sutter Health · Actor · Parked                       <- search_candidate, thin
Sutter Health · Actor · Awaiting Verification · Parked  <- verify_actor, complete
```

The first is the pre-promotion `search_candidate` row, which legitimately has no
classification or geography — those are created at promotion. Clicking it shows
an empty form. **For the demo, always open the "Awaiting Verification" row.**

---

## 6. Completeness, per actor

All five: 17–19 Light Pull fields, **10 found**, the rest honestly `not_found`.

| Actor | Category | Found | Not Found | Sector | Hub |
|---|---|---:|---:|---|---|
| Sutter Health | `hospital_clinical` | 10 | 7 | **HEALTH** | SF Bay Area Health & Biomedical — **20.8 mi** |
| Tech:NYC | `association_network` | 10 | 9 | **AI** | New York City AI Hub — 0.0 mi |
| Greater Seattle AI Ecosystem | `association_network` | 10 | 9 | 4 unranked | Seattle AI Hub — 0.0 mi |
| Seattle University — Institute | `university_academic` | 10 | 8 | 2 unranked | Pacific NW Sustainability Hub — 0.0 mi |
| California Water Efficiency Partnership | `foundation_nonprofit` | 10 | 7 | 2 unranked | **unassigned — no coordinates** |

**Found for all five:** official identity · category and type · website ·
description · location · sector and topic · parent connection · hub assignment ·
why matched · UM6P/OCP connection (state `not_yet_checked`).

**Genuinely Not Found for all five:** recent activity · funding signal ·
international/Africa/Morocco connection · and the category-specific fields
(clinical focus, parent or academic link, type and scale, a current initiative,
association type, member types, linked members, network scope, current
initiative or working group).

These are real results, not failures: the permitted sources were read and said
nothing on those points. **No value was invented to fill a box.**

**Hubs: 4 assigned, 1 unassigned and retained.**
**Duplicates: 0** — 5 actors, 5 distinct names, same IDs reused throughout.

---

## 7. Best examples for the demo

1. **Sutter Health** — the most complete. `hospital_clinical` /
   `nonprofit_health_system`, Santa Clara CA, **Sector HEALTH**, assigned at a
   real measured **20.8 miles**, and the four hospital-specific boxes present.
2. **Tech:NYC** — `association_network` / `trade_association`, New York NY,
   **Sector AI**, New York City AI Hub, with a readable Why It Matched naming
   the hub and topic.
3. **Seattle University — Institute for Environmental Justice & Sustainability**
   — `university_academic` / `research_lab_center`, shows the university-specific
   boxes and a two-sector case the reviewer resolves.
4. **California Water Efficiency Partnership** — the honest one. No coordinates,
   so no hub, two review items raised, record retained. Worth showing precisely
   because it does not pretend.

Different categories, three states, and both hub outcomes.

---

## 8. Where to look

| | |
|---|---|
| **Real discovery demo** | **http://localhost:8030** → Review |
| **Hub proposal demo** | **http://localhost:8031** → Review → Hub Proposals |
| Filter | Review Reason → **Awaiting Verification** |
| Banner | EXAMPLE / TEST DATA — NOT GHUS-VERIFIED PRODUCTION DATA |

The real instance on 8020 is untouched.

---

## 9. Tests

| Suite | Result |
|---|---|
| Shared app pytest | **274 passed**, 1 skipped |
| Shared app node | **54 passed** |
| Backend pytest | **664 passed**, 27 skipped, 0 errors |

Three tests added (payload refresh vs reviewer edits, readable fact values, one
Why It Matched box). One existing assertion updated from raw JSON to the
readable rendering, deliberately and in full.

## 10. Files changed

**Backend** — `agents/discovery/promote.py` (`_append_actor_sectors`),
`tests/agent/test_agents_enrichment_phase4.py` (allowlist entry).

**Shared app** — `src/review/postgres_source.py` (`primary_sector`),
`src/review/store.py` (payload refresh while untouched), `frontend/review.js`
(`formatFactValue`, `whyMatchedFact`), `frontend/taxonomy.js` (duplicate row
removed), `tests/test_review_decisions.py`, `tests/test_review_ui.mjs`.

## 11. Limitations

- **Three of five actors have no single sector.** Honest, not fixable by code:
  the evidence named several and ranking them is a reviewer's judgement.
- **`actor_sector` is append-only**, so a sector cannot be re-ranked by UPDATE
  once written.
- **Recent Activity and Funding Signal are Not Found for all five.** A second
  targeted pass might find some, at further API cost; this run did not.
- **The duplicate queue entry** (search_candidate + verify_actor for the same
  actor) is confusing in a demo. I did not change queue composition — that is a
  product decision, not a display bug.
- The backfill was a one-off SQL operation on the isolated database. The
  permanent fix is in `promote.py` and applies to every future discovery.
