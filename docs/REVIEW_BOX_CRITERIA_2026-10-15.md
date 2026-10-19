# What each Review box is based on — 2026-10-15

For every box a reviewer sees on an actor in Review: **where its value comes
from**, **the rule or criterion that decides it**, and **what "Not Found" means
there**. All rules are in code; the file is named so each one can be checked.

Two kinds of source feed the boxes:

| Source | What it is | Cost |
|---|---|---|
| **Discovery page** | The single page the discovery run scored (search result, official re-read, or lead). Read once by the actor rubric model (Sonnet), which must quote evidence for each criterion. | Inside the $1.00 discovery budget |
| **Light Pull read** (new, 2026-10-15) | Up to **three** of the organisation's own pages — homepage, About page, one topic page — read once by `agents/collection/light_pull_reader.py` (Sonnet) for every box of its category. | Separate cap, `light_pull_max_usd_per_run` $0.50; measured ≈ $0.035 per organisation |

**Two rules apply to every Light Pull box:**
1. A value counts only if the model copies a quote of ≤ 30 words from the page
   it names, **and that quote is found on that page** (`quote_on_page`). An
   answer whose quote is not on the page is refused and recorded in
   `rejected_answers`; the box stays Not Found.
2. The value must pass the Light Pull's own evidence rules
   (`agents/collection/light_pull.py::_validate_evidence_rule`): description
   1–3 sentences; why-matched 1–2 sentences, strong or moderate; recent activity
   needs a date **and** a description; rankings only QS/THE/U.S. News/ARWU with
   publisher, name, year, entity and position; stage/TRL only with the
   published sentence.

**The three missing states** (never merged):
- **Not Stated on the 3 Pages Read** — the Light Pull read the listed pages and
  none of them states it. Each box links the pages it checked.
- **Not Found** — the layer ran for this record but has no fact for this box.
- **Not Yet Collected** — no layer has run for this box yet.

A box is never filled from the organisation's category, sector, fame, funder,
outside knowledge or a guess (Architecture V2 rule 7).

---

## Identity

| Box | Based on | Criterion |
|---|---|---|
| **Name / Official Identity** | Discovery page, rubric model's `record.name` | Must be a specific proper name (`is_specific_name` for leads). Rejected if empty (`no_name`) or if it reads as a list/event/article — "directory", "database", "top 10", "webinar", "press release"… (`not_an_organisation`, `actor_quality.py`). A page with **no name and no evidence at all** is now `unreadable_page`, and its site's homepage + About page are read once instead. |
| **Website** | Discovery page `record.website` | Must be stated on the page. Accept gate `website_unverified` if absent; `third_party_page` if the page read is on another domain than the stated site. An official-site read is accepted only if the site names the organisation near the top (`site_is_official`: ≥ 2 name tokens, or the acronym, in the first 3,000 characters). |
| **Description** | Discovery page `record.description` (reviewer-editable) | 60+ characters, 1–3 sentences, not a tagline (`weak_description`). **New:** held for a person if it describes a web page rather than an organisation — "A regional web portal…", "Overview of…", "A directory site…" (`describes_a_page`). |
| **Category and Type** | Classification model on the kept page (`agents/common/actor_classification.py`) | Decided by the organisation's **main job** in its own words — never by funder, sector, age or fame. Hard rules: university-affiliated hospital → Hospital / Academic Medical Center; medical school → University / Medical School; National Laboratory only with a formal FFRDC/charter designation, otherwise Research Center / Government-Affiliated; Startup only with an evidenced development stage, otherwise Company; public utility → Government / Public Utility; investor-owned utility → Company. Operates programmes → E&I Platform; convenes members → Association. Unsure → Not Applicable + one-line note + `category_doubt` review item. |
| **Parent or Connection** | Relationships stated in the record (`actor_relationship_requests`) | Only "Unit of" and "Operated by" are parenthood. No parent = "Not Available", which is a normal, complete state. |

## Location

| Box | Based on | Criterion |
|---|---|---|
| **City / State / Country** | Discovery page `record.location_city/state/country`; filled from the Light Pull read only if the record has none | Must be stated on a page. Requests with an area reject anything located outside it (`outside_requested_region`). |
| **Region** | Derived from the state, never typed (decision D8) | Fixed state → region table. |
| **Geocoded** | Geocoding at promotion (`prepare_actor_geography`) | City + state must resolve; otherwise a `geocode_failed` review item. |

## Sector

| Box | Based on | Criterion |
|---|---|---|
| **Primary Sector** | Reviewer's choice; default = first sector the page evidenced | The reviewer's choice always wins and is marked primary at admission ("Chosen as the primary sector by the GHUS reviewer at admission."). |
| **Sector and Topic** | Rubric `sector_codes`, each with a quoted evidence sentence | Only sectors in the active GHUS list (`load_active_sectors`); unlisted ones are dropped (`_drop_unlisted_matches`). A request's sector must be evidenced or the page is rejected (`outside_requested_sector`); its focus terms must appear (4-letter word stems) or it is held (`focus_unconfirmed`). No sector fits → "+ Add a New Sector…", which creates sector + topic through `decisions.create_sector`. |

## Why it matched

| Box | Based on | Criterion |
|---|---|---|
| **Why Matched** + strength | Rubric `match_reason`; if absent, composed from the page's own sector evidence quote; the Light Pull read fills it only when the record has none | 1–2 sentences that cite what the page says the organisation does on the topic. **Strong** = the topic is its main work (or the page's own sector evidence); **Moderate** = one part of its work. |

## Hub

| Box | Based on | Criterion |
|---|---|---|
| **Current Hub Memberships** | `hub_actor` rows | Shown as memberships; never confused with suggestions. |
| **Suggested Hubs** | Deterministic: same sector as the hub **and** within the hub's radius of its centre (haversine, miles shown) | Suggestion only; a person chooses. The rubric's model-named hubs (from the canonical hub list only) are shown as page evidence. |
| **Choose a Hub / Propose a New Hub** | Reviewer | A chosen hub is written at admission. A proposed hub becomes a `proposed_hub` row, status `pending`, for the hub owner — never a hub by itself. |
| **No hub** | — | The actor stays eligible for **automatic new-hub detection** (`agents/common/hub_detection.py`): Verified, geocoded (city, state, coordinates), classified, not already in a hub of that sector. A proposal needs ≥ 10 actor families and ≥ 5 categories within 50 mi (core) / 200 mi. |

## Light Pull — common boxes (every category)

Criteria are the exact text given to the reader (`FIELD_CRITERIA` in `light_pull_reader.py`).

| Box | Criterion |
|---|---|
| **Recent Activity** | One dated, specific thing it did recently (programme launched, facility opened, project started, report published, award made), with the date the page gives. Undated or generic activity does not count. |
| **Funding Signal** | One specific funding fact about this organisation: an amount, a named funder, a grant, a round or a budget. Donation buttons and "supported by partners" do not count. |
| **International / Africa / Morocco Connection** | A named partner, office, programme or project outside the United States that a page states. |
| **UM6P / OCP Connection** | Any link a page states with UM6P, OCP Group or Morocco: partnership, project, member, office. (Before this read it was "Not Yet Checked".) |

## Light Pull — category boxes

| Category | Box → criterion |
|---|---|
| **University** | Relevant School/Department/Lab → the unit working on the topic and what it does · Public or Private → as stated · Land-Grant or Other Designation → only if stated · Rankings → only QS, THE, U.S. News, ARWU, fully attributed; a department never inherits a university-wide ranking · Main Relevant Centers and Programs → named centres/institutes/programmes on the topic |
| **Research Center** | Parent and Center Type (e.g. "NSF ERC at Texas A&M") · Research Focus on the Topic · Active or Recent Projects (named) · Main Funders (named) |
| **National Laboratory** | Sponsoring Agency (DOE, NASA, NIST…) · Formal Designation Confirmed (as stated, e.g. "DOE national laboratory", "FFRDC") · Relevant Program Area |
| **Applied Facility** | Facility Type and Operator · What It Tests or Demonstrates · A Current Project (named) |
| **Hospital** | Clinical or Research Focus on the Topic · Parent or Academic Link · Type and Scale (beds, sites, patients as stated) · A Current Initiative (named) |
| **Company** | Public or Private, and Size (employees, revenue, sites as stated) · Relevant Business Segment or Product · Where It Operates in the Mapped Geography |
| **Startup** | Technology and Problem Addressed · Founding Year and Location · Stage or TRL (only with the published sentence) · Funding Stage · Pilot or Customer Evidence (named) |
| **E&I Platform** | Type and Operator · Sector Focus · What It Offers · Scale Indicator (a number the page gives) |
| **Investor** | Type and Headquarters · Sector and Stage Focus · Geographic Focus · Fund Size (published) · Investment Thesis on the Topic |
| **Government** | Jurisdiction and Parent Agency · Relevant Mandate or Program · Visible Funding Programs (grants, rebates, loans listed) |
| **Foundation / Nonprofit** | Mission and Sector Focus · Geographic Focus · Relevant Program (named) · Program or Grant Themes |
| **Association / Network** | Association Type · Sector and Geographic Scope · Member Types · Current Initiative or Working Group · Linked Members (named) · Network Scope / Locations |

## Scores and the decision

| Box | Based on | Criterion |
|---|---|---|
| **Relevance** | Rubric, weights in `sources.yaml` | Own organisational page .15 · operating entity .15 · sector coverage .15 · R&D/programmes .25 · partnerships/tech transfer .15 · identity stated (website .5 + location .5) .15. Possible values are discrete: …, 0.75, 0.775, 0.85, 0.925, 1.00. |
| **Engagement Priority** | Rubric | Use cases .30 · open programmes .12 · named route in .12 · partnership precedent .10 · partnerships/tech transfer .10 · network membership .06 · distinctiveness .15 (1 / (1 + actors already covering it)) · hub match .05. Never excludes anyone. |
| **Band** | Both + gates | Rejected < 0.45 or any reject gate · Review between · **Auto-Verified** relevance ≥ **0.80** *and* every accept gate *and* priority ≥ 0.70. Auto-verification is recorded as `agent_auto_accept` and **never** authorises Deep Pull — only a GHUS person's topic decision does. |
| **Reasons / Gates** | `actor_quality.assess_actor`, `actor_currency` | Every rejected, held or unread candidate keeps an explicit reason. Currency: site redirects to another organisation's domain that does not name it → merged/renamed (rejected); a defunct statement must name the organisation; newest year ≥ 4 years old → outdated (third-party page: rejected; own site: held). |

## Duplicates (entity resolution)

| Box | Based on | Criterion |
|---|---|---|
| **Possible Matches** | `route_actor` (`agents/common/resolve_route.py`) | Exact website domain, or exact name / alternate name → it **is** the existing actor: facts are appended to it, nothing is created. Several exact matches → possible-duplicate review. A fuzzy model score ≥ LOW → possible-duplicate review, never an automatic merge. **Fixed 2026-10-15:** Review admission now applies the exact domain/name rule too (it used only the fuzzy score). |
