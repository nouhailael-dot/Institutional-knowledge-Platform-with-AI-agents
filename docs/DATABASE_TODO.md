# Database clean-up — what's left (tracker)

Started 24 Nov 2026 (Nouhaila + Claude). Kept up to date as work goes on.
A line moves to "Done" only after it has been tested.

---

## 0. Since 27 Nov (Ismail's 800, 810, 820)

- **800** (25 Nov 08:42): tables renamed back to `actor…`; most stand-in views removed.
- **810** (25 Nov 09:33): 17 unused tables removed.
- **820** (27 Nov 07:13): `topic` became `sector` (every `topic_id` now holds a sector id);
  removed `topic`, `actor_topic`, `event_topic`, `actor_location`, `actor_relevance`,
  `challenge`, `person_discovery_profile` (merged into `person`: `research_area`,
  `public_profile_url`), `event_claim`, the 2 cutover records. Database: 68 tables.
- **To raise with him:**
  1. `actor_relevance` was decided "move then delete" (why relevant -> `why_matched`,
     evidence -> GHUS Notes for the 130 phosphogypsum organizations). 820 deleted it with
     the rows only archived: nothing was moved. Restore from his archive
     (`archive-820-*.sql`) or our dump `live-before-790-2026-11-24T1727.dump`.
  2. `strategic_entity`, `strategic_document`, `actor_strategic_connection_check` were
     decided delete (25 Nov) and are still there.
  3. Open: hub detection tables (ask Fatima), `field_proposal`, `person_change_log`.
- Decisions per table: `docs/COMPASS - Database tables (25 Nov).xlsx` (Decision column).

## A. To tell Ismail

**What was applied to Supabase on 24 Nov** (each after a fresh backup on Nouhaila's Mac,
`~/compass-db-copies/`, one transaction, one ledger row):

1. **730** (12:38 ET): view `organization_template`, one row per organization in the
   Organizations template's order. Commit `552f2ae`.
2. **740** (12:38 ET): 8 empty columns on `event`: venue, city, state_code, country,
   region_code, event_format, registration_url, organizer. No data written. `552f2ae`.
3. **750** (14:36 ET): deleted 16 columns of `organization_details` (8 import-only:
   estimated_trl, technology_ip_notes, key_constraints, primary_lifecycle_role,
   identity/profile/technical/lifecycle_summary; 8 empty) and **recreated his 720
   stand-ins `actor_read` and `actor_details`** (definitions checked identical to
   production first; same access). Applied before the Render deploy, after checking
   the old code still works. `f8bee7a`; code side `d482bb1`.
4. **770** (14:40 ET): deleted `organization_details.published_stage_or_trl` (2 values,
   both "not_found") and recreated `actor_details` again. `e7d30a0`.

**Changes needed in his files**

5. **Data Feed template** (`src/datafeed/contract.py`): remove "Technology and IP",
   "Key constraints", "Lifecycle role". Until then an upload still sends them; they now
   land in `other_facts`.
6. **TRL is removed from the project (GHUS decision, 24 Nov).** Still in his files:
   - Review: `src/review/store.py:77, 1396` (editable TRL, 1–9 check),
     `frontend/review.js:1131`; Review imports `showsTrl` / `TRL_CATEGORY`
     (`frontend/taxonomy.js`, `src/review/taxonomy.py`) and the `trl` label
     (`frontend/labels.js`), kept only for that. Once Review drops them, delete them.
   - Enrichment: `agents/config/fields.yaml`, `agents/enrichment/specs.py`.
   - Ask index refresh: `agents/index/refresh.py:289` (imported-fields list).
   - Update agent: stop collecting startup "Stage or TRL" (`published_stage_or_trl`,
     `light_pull.py:70, 367`, `light_pull_reader.py:168, 577`); its column is gone (770),
     its readings go to `other_facts` until then. A startup keeps the template's
     separate "Startup: development stage".
   - Old one-off scripts in `ghus-backend/scripts/` (6 files, October migration).
   - FYI: the version tags of `taxonomy.js` and `labels.js` in his `review.js:22, 26`
     were bumped to `20261124c` (both files changed).
7. **Directory edit writer** `agents/enrichment/decisions.py` (`DIRECTORY_EDIT_ACTOR_FACTS`)
   should match `src/browse.py` `GHUS_EDIT_FACT_KEYS` (now 4 fields).
8. **People columns `tel_num`, `country_code`**: empty, no agent collects them; his
   `agents/enrichment/specs.py:166` lists them. Remove there so the columns can go.
9. **Events**: the Data Feed and the backend admission still write only `event.location`.
   They should write the new columns (venue, city, state, country, format, registration,
   organizer). Explore and Map side is Nouhaila's.
10. **Parent organization**: the Data Feed refuses a whole record when the parent is not
    in the directory (`src/datafeed/service.py:218`), so a map can't send its parent.
    Could it keep the record and drop only the parent?

**Changed in his files on 25 Nov (fix 3, events keep their place, format and sector)**

10a. `agents/discovery/promote.py`: a new event now gets venue, city, state_code, country,
     region_code (from `region_state`), event_format and organizer in the 740 columns
     (`_event_place_columns`); an update fills them only where empty; a new step
     `_append_event_sectors` links an event to its sectors (organizations had one,
     events never did). `agents/review/admission.py:394`: events now carry their sector
     codes (only organizations did, so events got no sector and no topic).
     `tests/agent/test_agents_enrichment_phase4.py`: `event_sector` added to promote.py's
     permitted writes. 5 new tests in `tests/agent/test_datafeed_origin.py`.
10b. For "Sector = map title" later: reuse his `decisions.create_sector` (creates a sector
     and its mirror topic) rather than a new database helper.

**To agree with him**

11. **One table for events and people (draft 760, local copy only)**: GHUS asked for one
    table each instead of his 630's `event_details` / `person_details`. 760 adds 630's
    columns to `event` (12) and `person` (13) and keeps them up to date from the facts.
    It replaces his 630 and its automatic copy, and the copy writes into the main tables
    (rule 1). 630 had both `format` and `event_format` for events; 760 keeps one.
12. **AGENTS.md** still says schema changes are his only. Nouhaila now applies them with
    her own go-ahead (backup + ledger each time). Update the rule together.
13. **Stage 2 of 720**: the 25 `actor_…` stand-in views still show in Supabase (the team
    sees "actor"). When does he plan to rename the code and drop them?
14. **Template fields the agents collect but the template lacks**: `rankings`,
    `why_matched`. The update agent's 60 **deep fields** have no column (they would go to
    `other_facts`): columns or not?

15a. **790 is on Supabase** (24 Nov, ~17:28 ET, backup `live-before-790-…T1727.dump`,
    applied with Nouhaila's go-ahead before his agreement): organizations are one table.
    The 62 columns of
    `organization_details` move into `organization` (values copied, checked identical
    cell by cell: 4,348 cells, 978 organizations); `organization_details` and his
    stand-in `actor_details` are removed (no code reads them; his purge skips a missing
    table); his automatic copy (620/621 `ghus_organization_details_refresh`) now writes
    into `organization`, only into those 62 columns. On Supabase: 4,348 values,
    0 differences; `updated_at` untouched; Directory, record page, Ask checked (new and
    old code). Tell him; 760 (events + people) still waits for him.

**To check / later**

15. **Stale runs**: 1 `collection_run` and 12 `scrape_run` marked "running" since
    23 Nov 15:56 UTC, with no open connection.
16. **To check**: after 720, `organization_details.organization_category_type` was renamed
    but the discovery agent's fact is still called `actor_category_type`, so new values
    may go to `other_facts` instead of that column.
17. **Imported facts** stay in `organization_fact` (12,429: `legacy_baseline` 7,680,
    `legacy_profile` 4,749) plus 67 TRL facts; only hidden. Delete later or keep as history?
18. **`organization_location`** repeats each organization's city and state (818 rows,
    all "main"). Keep for multi-site organizations, or drop?
20. **Data**: University of Florida's website in the directory is a faculty page
    (`faculty.eng.ufl.edu/timothy-townsend/`), not ufl.edu. Other organizations may
    have the same problem; worth a check with the clean-up.
19. **18 empty pipeline tables** (proposal, proposed_hub ×3, strategic_document,
    strategic_entity, organization_ranking, person_change_log, record_verification …):
    delete after a code check, after 4 Dec.

## B. Nouhaila's side (next steps)

1. **Push** (GitHub Desktop): `f8bee7a`, `e7d30a0`, `6599c27`.
2. **Deploy on Render**, then restart the local server.
3. **760 (one main table + the diary for events and people)**: agree with Ismail, then
   backup + Supabase + ledger (790, the same for organizations, is done). Commit the
   790 files. 760 detail:: agree with Ismail, then backup + Supabase +
   ledger. Existing readings (14 event, 16 person) are not copied in; decide whether to
   fill them.
4. **Events**: `event_template` view; Explore and Map save writes the new columns; the
   record page shows them; decide on the fill (`event_740/fill_locations.sql`, 207
   events) and on "New York, USA" (city or state? 67 events).
5. **People**: `person_template` view; the profile link is not in 630/760 (it lives in
   `person_discovery_profile`); the person ↔ organization link (`organization_person`)
   is never written.
6. `organization_template`: add `rankings`, `why_matched`.
7. A `directory` section in Supabase holding the 3 template views.
8. Explore and Map: send the parent only when it is already in the directory; run one
   small paid map (cost cap agreed first) to see the category facts land in their columns.
9. Update `docs/DATABASE_CLEANUP_PLAN_2026-11-24.md` (country is "USA"; outdated counts).

## C. Decisions waiting (Nouhaila / Fatima)

1. `event.access_type` (31 filled): should an agent collect it, or delete the column?
2. `person.orcid`: no agent collects it; delete column and template field?
3. `person.bio`: the agents find one but the people rules never store it; delete?
4. Later, once the code moves: delete `event.next_date` (→ `start_date`),
   `event.location` (→ the new columns), `person.verification_status` (= `record_status`).

## Done

- 24 Nov — Local copy of Supabase for testing (`compass_copy`, 127.0.0.1:54317).
- 24 Nov — Explore and Map saves category facts under the template's names (`1286e7a`).
- 24 Nov — 730 and 740 applied to Supabase (`552f2ae`).
- 24 Nov — Code side of 750: Ask, Directory, record page, edit form (`d482bb1`).
- 24 Nov — 750 applied to Supabase (`f8bee7a`); checked with the new code and the old one.
- 24 Nov — Decision: TRL removed from the project; startups keep a development stage.
- 24 Nov — 790 applied to Supabase: `organization_details` merged into `organization`
  (88 columns); every value checked identical.
- 24 Nov — 770 applied to Supabase (`e7d30a0`); TRL removed from the pages, labels and
  Ask (`6599c27`); Review checked in the browser.
