# People and Event Discovery: quality pass (2026-10-22)

Scope: the open-web People and Event discovery agents (`agents/discovery/search/phase2.py`
and the two rubric scorers), their Review presentation in the platform, and a labelled
evaluation. Nothing was committed, pushed, migrated, or written to shared Supabase.
People Discovery's authorisation state and the weekly Event Discovery schedule
(`.github/workflows/weekly-discovery.yml`) are unchanged.

## 1. Weaknesses found (audit, demo database `ghus_v2_demo_test`)

| Area | Finding |
|---|---|
| Reading | Both scorers sent the model the first 16,000 characters of **raw HTML**. On the 150 stored event pages that is a median **6%** of the page's text (people: 11%); on 59 event pages the model saw under 200 characters, essentially the title. Dates, places and organisers were missing because they were never read. |
| Completeness | Of 57 analysed events, 17 had a start date and 13 a place. No organiser, registration, format or status was collected at all. People had five fields; no department, expertise or named work. |
| Scoring | A single weighted rubric score decided Accept/Review/Exclude. A news article, an event listing (10times, tethys) or a name in a staff list could reach `auto_high`. Cancelled events were not detected. |
| Duplicates | The same event (ARPA-E Summit 2027) was found and paid for 9 times across runs; events already on the map were re-read. |
| Cost | Events: $33.20 over 94 runs for 11 `auto_high` records (about $3.02 each). People: $4.36 over 4 runs for 8 `auto_high` (about $0.55 each). 104 event analyses failed (62 null-evidence, 12 shape errors, all from 2026-09-21; that validator rule was already removed). |
| Evidence | Record fields carried no quote; the reviewer could not see where a value came from. |

## 2. Search and extraction improvements

- **The model reads the page, not its scripts** (`page_facts.page_text`): title and
  description, main text, footer, schema.org `Event`/`Person` JSON-LD (dates, place,
  organiser, `eventStatus`), and registration/agenda/LinkedIn links; same 16,000-character
  cap as before, so no larger prompts. Prompt versions bumped (`event_rubric_record_v4`,
  `person_rubric_record_v3`) so old caches are not reused.
- **Facts with evidence**, in the same tool call (no extra AI call): events gain organizer,
  registration link and deadline, format, status, themes and `page_kind`; people gain
  department, expertise, up to three named works, any UM6P/OCP link. Each fact needs a quote
  that is checked on the page (`verify_facts`); a fact whose quote is not there is dropped
  and listed as dropped, never kept as a guess. A registration link must be in the HTML.
- **Deterministic before AI**: events already on the map are matched by name and year
  (`held_event_match`) and skipped before fetching; a dated title against an undated series
  is read as a new edition.
- Provenance uses the existing path: facts and gate results travel in
  `search_candidate.record_preview` and `staged_record.payload` with source URL, date read
  and the run; no parallel fact store.

## 3. Mandatory fields and separate gates (`agents/discovery/quality_gates.py`)

Each gate is reported separately; a gate can only **lower** the score band (`cap_band`).

**People** - mandatory: name; identity source (official profile page that names the
person and is institution/self-published, or a matched LinkedIn link on such a page);
current affiliation stated on the page; GHUS relevance. Any missing means Exclude, with
the evidence kept. Accept also needs a role plus at least 3 of: role, expertise,
department, profile link, relevant work (`person_min_priority_fields`, default 2, beyond
the role); otherwise Review. Every accepted person still goes to human Review
(AGENTS rule 11); nothing is auto-created.

**Events** - fatal (Exclude): not an official source (news, listing or aggregator page),
no single identifiable event, no GHUS relevance, cancelled. Review: date or place/format
unconfirmed, postponed, conflicting dates. Accept: all of the above plus at least 2
priority fields (organizer, registration, type, description, themes;
`event_min_priority_fields`). Thresholds are in `config["discovery_quality"]`.

## 4. LinkedIn

Never fetched, never searched behind sign-in. A LinkedIn URL is kept only when the
official page itself links a `linkedin.com/in/` profile whose slug contains the
person's family name and given name or initial; two candidates means none is kept. A
LinkedIn result on its own is a social source and cannot establish identity or
affiliation.

## 5. Event checks

Official source (`source_kind` + `page_kind`), identity, status (facts or
cancelled/postponed wording), freshness against the run date, place or online format,
relevance, and date conflicts (end before start).

## 6. Duplicates

Held events are skipped before fetch and counted (`held_event_skips`). Ambiguous
matches are not merged; a new edition of a recurring event is read as new. Existing
canonical writers (`promote.py`, `decisions.py`) are untouched.

## 7. Before / after

**Labelled set** (`evals/people_events_gold.jsonl`, 22 cases; the labels were written
with the gates, so this checks behaviour, not independent accuracy):

| | Events before | Events after | People before | People after |
|---|---|---|---|---|
| Accept precision | 0.25 | 1.0 | 1.0 | 1.0 |
| Junk filtered | 0.25 | 1.0 | 0.0 | 1.0 |
| Useful recall | 1.0 | 1.0 | 1.0 | 1.0 |
| Kept but should be excluded | 3 | 0 | 4 | 0 |
| Review workload | 5 | 5 | 7 | 3 |
| Exact decision match | 0.4 | 0.9 | 0.67 | 1.0 |

**Stored real pages** (150 events, 34 people; old cached extractions, new gates):
events - 11 Review moved to Exclude (10 because the page is not an official source),
5 Accept to Review, 1 Accept to Exclude; people - 7 Review to Exclude, 2 Accept to
Review. No band was raised.

**Live re-read** of the same stored pages with the new reading (bounded, paid):

| Page | Record fields before -> after | New facts | Decision |
|---|---|---|---|
| ausimm critical-minerals-2026 | 7/8 -> 8/8 | 4/5 | review -> accept |
| tethys ARPA-E 2027 (listing) | 3/8 -> 7/8 | 1/5 | review -> exclude (listing, not official) |
| awwa WaterSmart Innovations | 3/8 -> 8/8 | 4/5 | review -> accept |
| health-ai-summit.com | 3/8 -> 7/8 | 3/5 | review -> accept |
| ceitraining.org event 1104 | 8/8 -> 8/8 | 4/5 | review -> review |
| newyork.theaisummit.com | 7/8 -> 8/8 | 4/5 | accept -> accept |

Events: 31/48 -> 46/48 record fields; 20/30 new facts, 33 quoted. People (6 pages):
27/30 record fields, 16/24 new facts; 4 stay Accept, 2 move to Review. Both are staff
listings where the old prompt, seeing only the HTML head, had taken a section heading
("Associated Graduate Program Faculty") for the person's title; the new reading
correctly treats a name on a listing as insufficient.

## 8. Cost

- Live sample: events $0.1257 for 6 pages (about $0.021 a page), people $0.1047 for 6
  (about $0.017), `claude-sonnet-5`. The same 6-page event sample with the raw-HTML
  prompt cost $0.1691.
- Facts come in the existing call; held-event skips remove fetch and AI cost for
  re-found events. Costs stay tracked per run and per entity in the existing ledger;
  no new spending ceiling was added. No cheaper model was introduced: none was tested
  for accuracy here.
- Cost per useful record after the change needs a full scheduled run to measure;
  baseline is about $3.02 per `auto_high` event and $0.55 per `auto_high` person.

## 9. Tests

- Backend: `tests/agent/test_quality_gates.py` (35 tests: every labelled case, `cap_band`
  never raises a band, LinkedIn matching, source kinds, held-event and edition matching,
  an invented UM6P fact dropped, page reading without scripts and with footer/JSON-LD).
  Full suite: 973 passed, 18 skipped, 4 failed - all pre-existing and outside this change
  (two allowlist tests flag `scripts/smoke_test_actor_merge.py`; two schema tests compare
  against the demo database, which has compatibility views and lacks `actor.city`).
- Platform: 335 pytest passed; `test_review_ui.mjs` 70, `test_discovery_ui.mjs` 31,
  `test_hub_matching.mjs` 6 pass; `test_map_ui.mjs` needs Node's VM-modules flag
  (colleague-owned, unchanged).
- Evaluation: `python scripts/evaluate_people_events.py [--stored] [--live-sample N]`
  (dry by default; `--live-sample` is paid and capped at 10 pages per kind).

## 10. Files changed

Backend: `agents/discovery/quality_gates.py` (new), `agents/discovery/page_facts.py`
(new), `agents/discovery/search/{event_scoring,person_scoring,rubric_scoring,phase2}.py`,
`evals/people_events_gold.jsonl` (new), `scripts/evaluate_people_events.py` (new),
`tests/agent/test_quality_gates.py` (new), this report.

Platform: `src/review/postgres_source.py` (facts and checks lifted into the candidate's
metadata), `frontend/review.js` + `frontend/review.css` ("Collected information":
completeness, each check, what is missing or conflicting, one box per fact with its
quote, source link and date read), `tests/test_review_ui.mjs`.

## Remaining limitations

- No person or event fact tables in the V2 contract: facts live in staging payloads
  until a schema proposal adds them. That needs the schema owner.
- Biography text and personal location are not collected (policy). Publications and
  projects are Light-Pull "relevant work" titles only; Deep Pull is out of scope.
- Parent-site fallback is applied to actor updates, not yet to people and events.
- `TARGETING_POLICY.md`, cited by AGENTS rule 4/11, is not in the repository.
- Stored-page metrics use the old cached extractions; the live re-read covers 12 pages.
  A full scheduled run is needed for final completeness and cost-per-useful-record
  figures.
- Nouhaila's People/Event work was not modified; these changes sit in the shared
  scorers and gates and should be reviewed with her before merge.
