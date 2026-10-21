# Real-world hub example — candidate shortlist (WS5.3)

**A discussion document for Monday 12 Oct. Nothing here is inserted anywhere.**
No canonical record was created, changed or proposed. No database was written
to. The candidates below are suggestions for a human to review, not findings.

---

## 1. The live hub picture

The brief (D18) asks for the live hub count and says never to silently exclude
the empty one. From the committed Phase 12 evidence of 6 Oct 2026:

| Source | Figure |
|---|---|
| `phase12_dry_run_full_dump_2026-10-06.json` | **49 hub rows total** |
| `phase12_topic_proposal_summary.json` | **48 hubs with memberships, a deterministic topic and a centre** |

So: **49 hub rows, 48 of which carry memberships and a centre.** The 49th has no
memberships and is therefore absent from the topic proposal. That is exactly the
48-vs-49 discrepancy Appendix H item 9 asks GHUS to settle — the count is not
wrong, the two numbers measure different things.

> **Worth flagging.** The same dry run records `hubs.with_topic = 0`,
> `with_center = 0`, `with_radius = 0` and `reviews.hub_needs_review = 49` against
> the **pre-cutover** data, and `actors_with_topic = 0` with 965 actors blocked on
> `controlled_topic`. The topics and centres below exist because GHUS **approved
> the proposal** on 2026-10-06 (`phase12_topic_approval.json`), not because they
> were already in the data. Until that proposal is applied, this hub has an
> approved topic and centre on paper and none in the database. Anyone reading the
> shortlist should know which of the two they are looking at.

The 48 hubs span 8 of the 10 approved controlled topics: AGRI (5), AI (6),
CHEM (10), ENERGY (7), HEALTH (6), MINING (5), SUSTAIN (4), WATER (5).
CROSS and DIASPORA are used by no hub and are flagged `needs_ghus_review`
(Appendix H item 3).

## 2. The hub chosen for this example

| | |
|---|---|
| **Hub** | UC Davis / Sacramento Valley Agriculture Ecosystem |
| `hub_id` | `85cb176f-d54b-4e77-8391-31758ef48e39` |
| **Controlled topic** | `AGRI` — Agriculture (GHUS-approved 2026-10-06) |
| **Centre** | Davis, CA — 38.556147, −121.737793 (`density_center_v1`) |
| **Members today** | 18, of which 16 have coordinates |
| **Core members within 50 mi** | 14 |
| **Members outside the radius** | 0 |

Chosen for three reasons: its topic basis is deterministic and needs no GHUS
review; it has clean geography (nothing outside the radius); and it sits in the
same geography as the WS5.2 synthetic fixtures, so Monday can compare the
synthetic run and the real hub side by side.

**Radius.** The hub's own radius is not recorded in the approved proposal, so the
Architecture V2 defaults apply: **50-mile core, 200-mile cluster**. Every
distance below is measured against those.

---

## 3. Candidate shortlist

Real organisations in the Sacramento Valley agriculture ecosystem that would
plausibly match this hub's topic and geography.

**Every distance below is computed**, not estimated: city coordinates come from
the vendored Census gazetteer and the distance from
`agents.common.geography.distance_miles` (haversine), measured to the hub centre
at Davis, CA.

**Every category/type is a valid Intern Guide pair** (Appendix A), assigned by the
organisation's **main job**, not by its sector or its funder.

| # | Candidate | Category → Type | City, State | Miles to centre | Band | Public source |
|---|---|---|---|---|---|---|
| 1 | UC Davis Seed Biotechnology Center | University / Academic Institution → Research Lab / Center | Davis, CA | 0.00 | core | `sbc.ucdavis.edu/about-sbc` |
| 2 | Seed Central | Association / Consortium / Network → Innovation Consortium | Davis, CA | 0.00 | core | `seedcentral.plantsciences.ucdavis.edu` |
| 3 | AgStart (Lab@AgStart) | Innovation & Entrepreneurship (E&I) Platform → Incubator | Woodland, CA | 7.98 | core | `cityofwoodland.gov/CivicSend/ViewMessage/message/144371` |
| 4 ⚠ | Bayer Crop Science — West Sacramento (LifeHub California) — **4 Bayer records already exist, see §3.1** | Company / Corporate Actor → Subsidiary / Business Unit | West Sacramento, CA | 10.22 | core | `agfundernews.com/sacramento-making-moves-become-agtech-hub` |
| 5 | TOMRA Food — West Sacramento | Company / Corporate Actor → Subsidiary / Business Unit | West Sacramento, CA | 10.22 | core | `greatersacramento.com/business-climate/industries/agtech` |
| 6 | TurtleTree — West Sacramento R&D | Startup / Emerging Technology Company → Independent | West Sacramento, CA | 10.22 | core | `greatersacramento.com/business-climate/industries/agtech` |
| 7 ⛔ | California Department of Food and Agriculture — **already a member of this hub, see §3.1** | Government Agency / Public Authority → State | Sacramento, CA | 14.59 | core | `cdfa.ca.gov` |
| 8 | Greater Sacramento Economic Council | **needs a reviewer decision — see below** | Sacramento, CA | 14.59 | core | `greatersacramento.com` |
| 9 | The March Fund | Investor / Funding Platform → Venture Capital Firm | Sacramento, CA *(unconfirmed)* | 14.59 | core | `agfundernews.com/sacramento-making-moves-become-agtech-hub` |
| 10 | USDA ARS Western Human Nutrition Research Center | Research Center / Institute / Laboratory → Government-Affiliated | Davis, CA | 0.00 | core | `ars.usda.gov` |
| 11 | Almond Board of California | Association / Consortium / Network → Trade Association | Modesto, CA | 75.00 | cluster | `almonds.com` |

### 3.1 Checked against the map first — and two candidates fail that check

Architecture V2 rule 1 is to check what is already mapped before searching. Run
against `ghus_v2_review_redesign_test` on 9 Oct 2026, matching each candidate
name against `actor` (live rows only) and against this hub's `hub_actor` rows.
The hub has 18 members, which matches §2.

**#7 California Department of Food and Agriculture is already a member of this
hub**, stored as `California Department of Food & Agriculture (CDFA)`. The name
differs only by `&` versus `and` and a trailing acronym, which is why a
name-equality check would have missed it. Proposing it would have created a
duplicate inside the very hub it belongs to. **Remove it from the shortlist**,
or keep it marked as an existing member for comparison, but it is not a
candidate.

**#4 Bayer Crop Science already exists four times in the actor table**, none of
them in this hub:

- `Bayer Crop Science`
- `Bayer Crop Science (Midwest Presence)`
- `Bayer Crop Science (regional presence)`
- `Bayer Crop Science R&D Facilities`

Proposing `Bayer Crop Science — West Sacramento` would make it five. This is a
pre-existing entity-resolution problem in the migrated data, not something this
shortlist created, but the shortlist must not add to it. **#4 is an ER
question before it is a hub question**: the four existing records need to be
resolved against each other first, and the West Sacramento site is then either
one of them or a `unit_of` child of the resolved parent.

**The remaining nine candidates are genuinely absent** from the actor table —
no match for Seed Biotechnology, Seed Central, AgStart, TOMRA, TurtleTree,
Greater Sacramento, March Fund, Western Human Nutrition or Almond. They are new
records if GHUS wants them.

One near-miss worth naming so nobody re-finds it: `Food and Agriculture
Organization` exists as an actor. It is the UN FAO and has nothing to do with
CDFA; the substring match is a coincidence, not a duplicate.

This row of the verification table is now closed. The other two rows below
remain open and are blocked on the VPN, not on the database.

### Classification notes — the ones a reviewer has to decide

**#8 Greater Sacramento Economic Council.** This is a genuine Category 8 vs 12
case and the Guide's quick test does not settle it from the public description
alone. It convenes a membership of CEOs who each pay dues, which points to
**Category 12 → Professional Network**. It also runs its own programmes, which
points to **Category 11 → Operating Nonprofit**. It is listed here *without* a
category on purpose: under decision D3 this is a `category_doubt` item with a
one-line note, not a guess.

**#10 USDA ARS centre.** Category 2 → Government-Affiliated, **not** Category 3.
The Guide requires a formal FFRDC or charter designation for National Laboratory,
and an ARS research centre has neither. Being federally operated is not enough.

**#1 Seed Biotechnology Center.** Category 1, not Category 2: it is a unit of UC
Davis, and under decision D2 a university research centre is a University record.
It would link back to UC Davis with **Unit of**.

**#2 Seed Central.** It convenes member companies around UC Davis rather than
operating programmes itself, so Category 12. Its members link in with **Member
of**, never as children.

**#4, #5 Bayer and TOMRA.** Both are units of a larger parent company, so
Subsidiary / Business Unit with an **Operated by** or **Unit of** link to the
parent — which is a separate actor record, probably outside the mapped geography.

### Verification status — read this before using the table

| Item | Status |
|---|---|
| Distances | **VERIFIED** — computed by the haversine module from gazetteer coordinates |
| Category/type pairs valid against Appendix A | **VERIFIED** — every pair is in the catalog |
| Hub centre, topic, member counts | **VERIFIED** — from committed GHUS-approved evidence |
| Organisation names, cities, and that each is a real organisation | **UNVERIFIED** — see below |
| Source URLs resolve and say what is claimed | **UNVERIFIED** — see below |
| Whether a candidate is already one of the hub's 18 members | **VERIFIED** 9 Oct 2026 — checked against the database. **Two candidates must not be proposed as they stand: see §3.1** |

**Why.** Direct page fetches fail in this environment: every request resolves to
a `198.18.x.x` address and is refused. That is the McAfee VPN the brief names in
A3, and the brief says to report it rather than work around it, which is what
this is. The organisations and URLs above come from web **search** results, which
run server-side and did return, but no page was opened to confirm it says what
the search summary says.

**Nothing in this table should be entered anywhere until those rows read
VERIFIED.** In particular #9's city is a guess from "headquartered in Greater
Sacramento" and must be confirmed before its distance means anything.

---

## 4. How Phase 6 assignment would treat these

Phase 6 is a **topic test first, then a distance test to the hub centre**, and
its result is a **suggestion** that the reviewer accepts or overrides (decision
D6). Applied to the shortlist:

| Step | Outcome for these candidates |
|---|---|
| **1. Topic test** | Each candidate must carry the controlled topic `AGRI` **with a source**. None does yet: `actor_topic` is empty at cutover by policy, because hub membership is not topic evidence. Until Light Pull records a sourced topic, **every candidate fails the topic test and none is assignable.** |
| **2. Distance test** | Once the topic is sourced: candidates 1–10 fall inside the 50-mile **core**; candidate 11 (Modesto, 75.00 mi) falls in the 200-mile **cluster** but outside the core. |
| **3. Suggestion** | Review shows the deterministic result with its reason and distance. The reviewer chooses, or chooses **Leave Unassigned**. |
| **4. Write** | A manual choice is an **appended** membership with reviewer provenance. Historical memberships are never silently replaced, and a member outside the radius is **flagged, not removed**. |

**The finding that matters.** The blocker is not geography — it is that no actor
carries a sourced controlled topic. 965 actors are blocked on `controlled_topic`
in the dry run. Hub assignment cannot do anything useful for any of these
candidates until Light Pull populates `actor_topic` with a source. That is a
sequencing fact worth raising on Monday.

## 5. What would have to happen before any of this is real

1. **Verify the candidates.** Fix or bypass the VPN, open each source, confirm
   the organisation, its city and its main job.
2. **Deduplicate against the hub's existing 18 members** by name, alternate names
   and **website domain**. An exact match appends to the existing record; a close
   match is flagged for GHUS and **never merged automatically**.
3. **Classify properly**, from each organisation's own self-description. The
   categories above are proposals from secondary sources, which is exactly what
   the Guide says not to classify from.
4. **Source the topic.** Each candidate needs `AGRI` recorded with a source
   before hub assignment can consider it.
5. **A GHUS person decides.** Nothing here is Verified, and no agent may make it so.

---

## Appendix — the 48 hubs with an approved topic and centre

| Topic | Hubs | Example centre |
|---|---|---|
| AGRI Agriculture | 5 | Davis, CA · College Station, TX · Urbana, IL · Geneva, NY · St Louis, MO |
| AI Artificial Intelligence | 6 | Berkeley, CA · Cambridge, MA · Pittsburgh, PA · Seattle, WA |
| CHEM Specialty Chemicals | 10 | Berkeley, CA · League City, TX · Wilmington, DE · Raleigh, NC |
| ENERGY Energy Transition | 7 | Houston, TX · Golden, CO · Chicago, IL · Boston, MA |
| HEALTH Healthcare | 6 | Houston, TX · New York, NY · Bethesda, MD · Cambridge, MA |
| MINING Mining | 5 | Golden, CO · Reno, NV · Tucson, AZ · Salt Lake City, UT |
| SUSTAIN Sustainability | 4 | Chicago, IL · Seattle, WA · Boulder, CO · New York, NY |
| WATER Water | 5 | Chicago, IL · Tempe, AZ · Boulder, CO · Sacramento, CA |

CROSS and DIASPORA are approved controlled topics but no hub uses them, and both
are flagged `needs_ghus_review` in the proposal.

Source: `docs/evidence/phase12_topic_proposal.csv`,
`docs/evidence/phase12_topic_proposal_summary.json`,
`docs/evidence/phase12_topic_approval.json`,
`docs/evidence/phase12_dry_run_full_dump_2026-10-06.json`.
