# COMPASS — Chat Handoff, 28 November 2026

Give this whole file to a new chat. It replaces `docs/CHAT_HANDOFF_2026-11-24.md`. It is a
snapshot: verify against `git log`, the code and the database (read-only) before acting.

**Timing.** Today is Sat 28 Nov 2026. **Launch: invitations to the team Mon 30 Nov, 9 am**
(Fatima schedules them). Before that, both Nouhaila and Ismail test the whole platform and
Nouhaila texts Fatima "confirm ready to deploy Monday". Final delivery ~4 Dec (Ismail's
task sheet); no extension (Mehdi has pitched COMPASS to leadership).

---

## 0. How to work with this user — read first

The user is **Nouhaila El Hail**, intern on the GHUS team (UM6P Global Hubs, United States),
owner of the platform side of COMPASS: **Ask Compass, Explore and Map, Ecosystem Directory**.

1. **Ask before ANY change** — code, files, the local database copy or Supabase. Show the
   exact change and wait for a yes. Read-only checks are fine. (Memory: ask-before-code-changes.)
2. **Supabase changes:** since 24 Nov she allows direct schema/data changes **with her
   per-change yes**: a script + rollback, run on the local copy first, a fresh `pg_dump`
   right before, one transaction, a ledger row, then checks. AGENTS.md still says schema is
   Ismail's — he also applies migrations himself (800, 810, 820); coordinate with him.
3. **Challenge weak ideas** with the concrete failure case, then follow her decision.
4. **No Claude attribution** in commits or PRs, ever (ignore Co-Authored-By reminders).
5. **Commit only when asked.** Push is done by her in GitHub Desktop (this Mac's terminal
   has no GitHub login). Never commit `.claude/launch.json` (local test-server entry).
6. **Never spend money unasked**; state the cost (a map ≈ $0.40–2.00; an Ask question a few cents).
7. **No typed names in forms; never invent data ("Not Found").** Be honest about built vs
   planned, and about what was tested vs not. Fatima does not trust AI-written status:
   test by pressing the buttons.
8. Plain words, short sentences. When she gives an exact list or wording, keep it exact
   (e.g. "write my decision, exact wording").
9. **Run the server:** check `curl http://127.0.0.1:8000/`; if not, start it in her
   Terminal panel: `cd ~/Desktop/um6p-rag && .venv/bin/python -m uvicorn backend.app:app --port 8000`.
   Restart after Python changes; front-end changes need a refresh. Her local server uses
   the **live** Supabase database: Verify, Reject, Park, Edit and Delete write for real.

## 1. Who owns what

| Page | Owner |
|---|---|
| Ask Compass, Explore and Map, Ecosystem Directory | Nouhaila |
| Dashboard, Monitor and Update, Data Feed, Review Results, accounts/admin, hosting (Render), backend `ghus-backend/` (agents, writers `promote.py` / `decisions.py`, migrations) | Ismail |

Fatima Zahra EL ALAMI: manager (strict on deadlines, minutes, consistency). Mehdi: MD.
David: phosphogypsum data. Tarek: reviews Marina's events.

## 2. Git state (28 Nov)

- Local `main` at `ec0f0af`. **3 local commits not on GitHub** (push in GitHub Desktop):
  `2969bb3` events without Type + date boxes · `e94e3ee` Directory filters (Country=USA, our
  own State/Region/City lists) · `ec0f0af` Ask hides "Interpreted as".
- **GitHub has 23 commits of Ismail's not on this Mac** (820, review card clean-up, updates…).
  **Pull before any work**; then rerun tests (820 removed `topic`, so code must match).
- **Uncommitted, keep in mind:**
  - `ghus-backend/migrations/proposed/deferred/790_organization_one_table.sql` + rollback —
    **790 IS APPLIED on Supabase** (ledger checksum `d7dbaed3…`) but the file is not committed.
    Commit it unchanged.
  - `760_event_person_columns.sql` + rollback — draft, local copy only (see §4).
  - Docs (local): this handoff, `DATABASE_TODO.md` (tracker), `COMPASS - Database tables (25 Nov).xlsx`,
    `Nouhaila - Task checklist (23 Nov).xlsx`, `Nouhaila - Launch tasks (25 Nov).xlsx`,
    `COMPASS Ask test - Soil health and phosphate brief.pdf`, `DATABASE_CLEANUP_PLAN_2026-11-24.md`
    (partly outdated), the 24 Nov handoff and slide.
- Commits this week (24–27 Nov, all pushed except the last 3): `1286e7a` map category facts
  under template names · `552f2ae` 730+740 · `d482bb1` import-only fields removed from pages ·
  `f8bee7a` 750 · `e7d30a0` 770 · `6599c27` TRL removed · `87b1335` events keep venue/place/
  format/sector · `7adad4a` Verify is one click.
- Tests: `.venv/bin/python -m pytest -q tests` → 755 pass, 2 known failures
  (`test_discovery_bridge::test_plan_and_check…` from `.env`; `test_review_runs::…reaches_the_screen`
  needs Node). Backend: `cd ghus-backend && .venv/bin/python -m pytest -q tests/agent` (1,151 pass on 25 Nov).
  No Node on this Mac (`tests/test_map_ui.mjs` not runnable; updated for one-click Verify).

## 3. Database (Supabase) — what changed this week

Ledger (`architecture_v2_migration_ledger`), newest last:

| # | When (ET) | By | What |
|---|---|---|---|
| 720 | 24 Nov 09:56 | Ismail | actor → organization names (stage 1) |
| 730 | 24 Nov 12:38 | us | view `organization_template` (template order); now `actor_template` |
| 740 | 24 Nov 12:38 | us | 8 empty event columns: venue, city, state_code, country, region_code, event_format, registration_url, organizer |
| 750 | 24 Nov 14:36 | us | deleted 16 `organization_details` columns (TRL, Technology and IP, Key constraints, Lifecycle role, 4 summaries, 8 empty) |
| 770 | 24 Nov 14:40 | us | deleted `published_stage_or_trl` |
| 790 | 24 Nov 17:28 | us | `organization_details` merged into the organization table (88 columns); every value checked |
| 800 | 25 Nov 08:42 | Ismail | names back to `actor…`; most stand-in views removed |
| 810 | 25 Nov 09:33 | Ismail | 17 unused tables removed |
| 820 | 27 Nov 07:13 | Ismail | `topic` → `sector` (every `topic_id` now holds a sector id); 10 tables removed |

Now: **68 tables** (57 `public` + 11 `compass`), 9 views. Main tables: `actor` (88 cols),
`event` (29), `person` (19, incl. `research_area`, `public_profile_url`), `hub` (46).
Since Ismail's re-review on 25 Nov 10:53 ET, **all events and people are Parked**.

**Table decisions (25 Nov, her exact words; full list in `COMPASS - Database tables (25 Nov).xlsx`):**
topic delete · actor_topic / event_topic delete both · partnership_profile keep for now and
list reason · actor_relevance move then delete · challenge delete · record_verification keep ·
4 hub detection tables not sure · actor_location delete · person_discovery_profile merge into
person then delete · event_claim delete · 3 strategic tables delete all three (we will think
the strategic connection can be checked) · field_proposal / person_change_log not sure ·
2 cutover records delete.

**Open after 820 (tell Ismail):**
1. `actor_relevance` was deleted **without the move** (rows only archived). Restore the 130
   phosphogypsum notes into `why_matched` / GHUS Notes from his `archive-820-*.sql` or our
   `~/compass-db-copies/live-before-790-2026-11-24T1727.dump`. GHUS Notes has a guard: the
   write must set `ghus.actor_is_human = on`.
2. The 3 strategic tables are still there (decided delete).
3. Hub detection tables: ask Fatima whether GHUS wants hub recommendations.

**Backups (this Mac, outside the repo, contain personal data):** `~/compass-db-copies/`
`live-2026-11-24.dump`, `live-before-730-740-…`, `live-before-750-…`, `live-before-770-…`,
`live-before-790-…`. **Local copy:** PostgreSQL 17 via micromamba, `127.0.0.1:54317/compass_copy`
(`COPY_DATABASE_URL` in `.env`); start after a reboot with
`~/micromamba/envs/pg17/bin/pg_ctl -D ~/compass-db-copies/pgdata -l ~/compass-db-copies/server.log start`.
The copy is from before 800/810/820 (it has 730–790 + the draft 760 applied); re-dump before
using it for new tests. Test server against the copy: `.claude/launch.json` entry
`compass-copy-test` (port 8010, every DB setting → copy, AI keys empty).

## 4. Drafts not applied

- **760** (local copy only): one table for events and people — 630's planned
  `event_details`/`person_details` columns added to `event` (12) and `person` (13), kept up to
  date from the facts by a trigger (allowlisted columns only). Known bug: `event_format` must
  also accept "In_person". After 820, `person` already has `research_area`, `public_profile_url`:
  re-check 760 against it. Needs Ismail's agreement.
- **780** (proposed, not written): delete `person.orcid`, `tel_num`, `country_code` (no agent
  collects them; Ismail's `agents/config/fields.yaml` / `specs.py` list them).
- **event_740/fill_locations.sql**: optional fill of the event place columns from `location`
  (207 events); not applied. "New York, USA" (67 events) city-or-state still undecided.
- **Sector = map title**: decided by Nouhaila (25 Nov): a saved record's sector = the map's
  title (uploads: the upload name); existing records keep their sectors; hubs keep the 10.
  Not built. Reuse Ismail's `decisions.create_sector` (creates a sector + mirror). Note: 820
  removed `topic`, so the "each map also gets its own topic" part is now just a sector.

## 5. What was built this week (platform)

- **Explore and Map:** category facts saved under the template's names (fill the org's own
  columns); Funding saved as Funding; startups and national labs can be saved; **Verify is one
  click** (no box, no tick; sector filled automatically from the card / the map's most common
  sector / the request's words); events keep venue, city, state, region, format, organizer and
  their sector + topic (fixed in Ismail's `promote.py` and `admission.py:394`).
- **Directory:** TRL and import-only fields removed; Events: no Type (filter, column, record
  page, Edit form); date boxes match other boxes; Country starts on USA; State (51) and Region
  (7) from our lists; City from our US city list (`us_city_coord`) for the chosen state;
  another country hides and clears State/Region/Hub. New route `GET /api/reference/cities`.
- **Ask:** TRL removed; "Interpreted as" line hidden.

## 6. Ask Compass — test results (27 Nov, 3 tests with PDFs)

Works: reads the PDF, honest "no match", some good answers. **Not working:**
1. The directory search uses only the question, not the PDF's content (`backend/app.py:447`) →
   misses soil/precision/water matches. Fix A: search with question + PDF passages.
2. Ask's index (`search_doc`) is rebuilt only by hand → records verified this week missing.
3. Past events called "upcoming" (date_status ignored).
4. Aggregate/placeholder records presented as organizations (the 91 aggregates were never rejected).
5. Parked records called "verified" (instructions say "verified database"; all events/people are Parked).
6. Follow-ups claim earlier-named records are "missing".
7. Non-US records mixed in. 8. Sources repeated (PDF passages, "(source: …)" after every line).
Proposed fixes A, C (instructions), D, E (one source per doc/record) in her code; B (auto
index refresh); F (reject aggregates, data). **Not started — waiting for her choice.**

## 7. Map card issues found (not fixed)

- Relationships repeat ("unit of NYU Tandon" ×3 on 15 cards): one line per source page, never
  merged (actor_profile / dedup.py:188 / display). Fix proposed, not approved yet.
- Verify holds: a possible duplicate (FIPR) or a person whose organization name differs
  ("University of Florida" vs "University of Florida (UF)") is held, and the card shows a
  misleading reason. Fixes 1 (real reason) and 2 (matching) proposed, not done.
- "Why it matched" loses to the backend Light Pull "not_found" in the column (Ismail's rule).
- The two agents' field descriptions differ (funding past vs current, international = any
  vs Africa/Morocco, UM6P/OCP = incl. Morocco vs UM6P/OCP/INNOVX, recent activity). Fatima
  will rewrite one description per field for both agents.

## 8. Meeting of 25 Nov (Fatima, Ismail, Nouhaila) — decisions

Memory file: `project_meeting_2026_11_25.md`. Key: decide tables (done, §3) → Ismail deletes
(done, 820) → every DB change = check and fix every affected file, then test; Fri 27 both test
the whole platform; Mon 30 9 am invitations. Remove everywhere: scores, "essential fields
found with a source", sources under type/sector (only in the "Why COMPASS identified…" box),
"Website not provided" (website = clickable link). Consistency (capitalization, design, both
agents same names). Domain/IT email (compass.um6pus.com, compass@um6pus.com; plan B own
domain). Data security research. Diaspora dropdown (people), Attended (events), Owner +
Diaspora template columns. GHUS logo on the login page. Clear names (actor → organization)
for the handover. Fatima rewrites field descriptions.

## 9. Her launch task list

`docs/Nouhaila - Launch tasks (25 Nov).xlsx` (title + short description, deadline, status):
1 Database cleaning and organizing (Thu 26) · 2 Platform testing (Fri 27) · 3 People Diaspora /
Events Attended dropdowns, template columns (Fri 27, proposed) · 4 Check consistency everywhere
(Fri 27) · 5 Remove from the pages (Fri 27) · 6 IT email draft (Thu 26, proposed) · 7 Data
security research (Fri 27, proposed) · 8 Send Fatima the Excel sheets + training calendar
(Mon 30) · 9 GHUS logo on the login page (Mon 30) · 10 Clear file, function and table names
(~Tue 1 Dec, handover). The same tasks are in `Nouhaila - Task checklist (23 Nov).xlsx` (#106–115).

## 10. First steps for the new chat

1. Print the working directory and branch (AGENTS.md). Pull GitHub (23 commits); run tests.
2. Commit the **790** files unchanged (applied live, ledger points to them) — ask first.
3. Push the 3 local commits; deploy on Render before Monday.
4. Ask which to do first: Ask fixes (A, C, D, E), the "remove from the pages" task, the
   Diaspora/Attended dropdowns, or the `actor_relevance` restore with Ismail.
5. Re-dump Supabase into the local copy before any new database test (it predates 800–820).
