# Review Redesign — status report

**Against:** *GHUS Platform — Claude Code Implementation Brief* (issued Thu 8 Oct 2026)
**Covering:** WS0, WS1, WS2, WS4, WS5.2 — the Monday 12 Oct priority set
**Production Supabase:** not contacted. No DDL, no writes, no connection.
**Pushed:** nothing. Both repositories are committed locally only.

---

## Summary

| Workstream | State | Note |
|---|---|---|
| **WS0** Session start and safety check | **PASS** | Two findings below need your decision |
| **WS1** Intern Guide taxonomy | **PASS** | 12 categories, 69 types, migration proposal, mapping report, contract note |
| **WS2** Review page redesign | **PASS** | Six-box layout, smoke-tested with screenshots |
| **WS3** Verify / Park / Reject | **PARTIAL** | Mapped onto existing states with the required confirmations; the audit-row and identity work is listed below |
| **WS4** Source runs and backlog grouping | **PASS** | View-level grouping, provenance proven unchanged |
| **WS5.2** Hub detection fixtures | **PASS** | All nine scenarios against the unmodified Phase 7 algorithm |
| **WS5.3** Real-world hub example | **BLOCKED** | Needs read access to a local `ghus_v2_*_test` database |
| WS5.1, WS6, WS7, WS8 | not started | P2/P3 in the brief's own priority order |

**Tests**

| Suite | Before | After |
|---|---|---|
| Shared app · pytest | 136 passed, 1 skipped | **247 passed, 1 skipped** |
| Shared app · node | 15 passed, 1 failed | **49 passed, 0 failed** |
| Backend · pytest | 495 passed, 24 skipped, 1 error | **622 passed, 24 skipped, 1 error** |

Zero regressions. The one backend error is pre-existing and unrelated:
`tests/integration/test_functional_v2_phase8.py` needs `V2_TEST_DATABASE_URL`,
which is not set in this environment. The node failure in the baseline was also
pre-existing: `tests/test_map_ui.mjs` needs `node --experimental-vm-modules`.

---

## WS0 — two findings that need you

### 1. The Review code was not on the branch the brief names, and the branches have diverged

The brief says to branch `feature/review-redesign` from `feature/ismail-modifications`,
which is what I did, as you chose. You should know what that leaves behind:

| Branch | Commits ahead of the other | Holds |
|---|---|---|
| `feature/ismail-modifications` | `c493285` | run-label cleanup |
| `claude/phase12-shared-review` | 5 commits | bulk category confirm in Review, location and legacy relationship reviews, hiding GHUS-rejected actors from Browse/Ask, V2 final names across the cutover, Ask index pruning |

Those five commits are **not** in this branch. Neither are the three `main`-only
commits (the Ask → Build the Map bridge and the dead-code removal). Nothing is
lost — the branches still exist — but a later merge will have to reconcile
`frontend/review.js`, which I have rewritten here. If you want that merge done
before Friday, say so and I will do it as its own step.

### 2. `GHUS-Platform/.env` points `DATABASE_URL` at production Supabase

The value resolves to `aws-1-us-east-1.pooler.supabase.com` and carries a
password in the URL. Any tool in that repository that reads `DATABASE_URL`
without an override would reach **production**, and the Phase 8 docs say both
`DATABASE_URL` and `V2_TEST_DATABASE_URL` should be pinned to a local database
when running V2 tests.

I did not use it, did not connect, and did not work around it. Please repoint it
at a local `ghus_v2_*_test` database, or move the production value somewhere a
tool cannot pick it up by accident.

### Otherwise clean

- The Phase 8–12 backend work the brief flagged as possibly uncommitted on 6 Oct
  **is committed** (`7eed196`). Only `AGENTS.md` is modified, plus untracked
  `.claude/`, `CLAUDE.md`, `architecture_v2_sept.md` and `docs/codex_prompts/`.
  I left all of those alone.
- Local PostgreSQL 17 is listening on `127.0.0.1:55432`, but I could not
  authenticate: no `PGHOST`/`PGUSER`/`PGPASSFILE` are set in this session and the
  role is not `postgres`. **This is what blocks WS5.3.** Send me the role name and
  the `PGPASSFILE` location and I will finish it.

---

## WS1 — the Intern Guide taxonomy replaces the Phase 5 catalog

Backend repository. Commit `2542fd7`.

**Catalog.** 12 categories, **69 types** (was 65). The 12 category **codes** are
unchanged — `university_academic`, `research_center`, … — so canonical rows, the
hub algorithm, `config/architecture_v2.yaml` and Agent 3 are untouched. What
changed is the display labels and the type codes.

A Phase 5 type code is **reused** wherever the Guide type means the same thing in
the same category, so an already-classified record keeps its stored value and
only its label changes. Codes with no same-category Guide equivalent are
**retired** (`active = false`) and never deleted: they still display on the
records holding them, and can still be referenced, but can no longer be selected.

**`other` → `not_applicable`.** Every category now ends with Not Applicable. It
is a deliberate choice, never a stand-in for missing data: selecting it requires
a one-line note and raises a `category_doubt` review item. The DB check and the
partial unique index were widened so exactly one *selectable* catch-all exists
per category while the retired `other` rows stay valid.

**Hard rules now follow the Guide, not the earlier spec.** Three changes worth
flagging because they change behaviour:

| Rule | Was | Now |
|---|---|---|
| Medical school | `university_academic` / `college_school` | `university_academic` / **`medical_school`** |
| Hospital tied to a university | became a University record | **stays `hospital_clinical` / `academic_medical_center`**, via a new `university_affiliated_hospital` evidence flag |
| National lab with no evidenced designation | fell back to `research_center`, type unset | falls back to **`research_center` / `government_affiliated`**, which the Guide names |

**Migration.** `agents/sql/510_v2_intern_guide_taxonomy.sql` is a **proposal** for
local `_test` databases only, with a rollback that refuses to run while any actor
still holds a Guide-only type. It is deliberately **not** bundled with the V2
cutover package. It asserts its own outcome before committing: 69 selectable
types, a Not Applicable in all 12 categories, and zero actor rows left holding a
pair with no definition row.

**Mapping.** `docs/evidence/taxonomy_intern_guide_mapping.csv` — all 65 Phase 5
pairs: **40 exact, 25 review, 2 that change the actor category** and are
therefore never applied automatically (`research_center/university_affiliated_center`
→ Category 1 Research Lab / Center, and `innovation_platform/tech_transfer_office`
→ Category 1 Tech Transfer Office). The generator is deterministic and has a
`--check` mode.

> **`record_count` currently reads `UNVERIFIED`**, not 0, because no local test
> database was reachable. That is deliberate: a missing count must never look
> like "no records affected". Re-run with the PG environment variables set to
> fill it in.

**No actor rows were re-mapped.** Applying the 40 exact rows and raising review
items for the 25 is a separate, reviewed step.

**Contract note** for Nouhaila: `docs/contracts/taxonomy_intern_guide_change.md`
— the changed codes, what agents must now send, the new evidence field, the API
surface, and what Agent 3 reads. Agent 3 itself was not edited.

---

## WS2 — the Review page

Shared app. Commit `0da1e96`. Screenshots in `docs/evidence/review_redesign/`.

The column layout is replaced by the six boxes the Light Pull defines:

```
QUEUE (left rail, sticky)          │ HEADER  name · domain · run chip · badges
 filters: kind · reason · run ·    │ 1 Identity & Classification
          category · search        │ 2 Location & Parent
 ▸ Pre-Redesign Backlog            │ 3 Sector, Topic & Hub
 ▸ Run · trigger                   │ 4 Light Pull Facts  (Current / History)
                                   │ 5 Possible Duplicates
                                   │ 6 ▸ Audit & Details (collapsed)
                                   │ STICKY FOOTER  Reject · Park · Save · Verify
```

Candidate IDs, run UUIDs, raw candidate JSON and the legacy `actor_type` all
moved into box 6. None appears in the main view.

**No invalid pair can be constructed anywhere.** `frontend/taxonomy.js` and
`src/review/taxonomy.py` hold the same catalog; `tests/test_review_taxonomy.py`
loads the JavaScript module through Node and compares it to the Python one pair
by pair and label by label, so the dropdowns and the validator cannot drift. The
Category Type select depends on the chosen category; changing the category clears
an incompatible type after a confirmation; the store refuses a cross-category
pair and the API answers `422` naming both sides.

**Missingness is never guessed.** The six words mean six different things and are
never substituted:

| Word | Means |
|---|---|
| Not Found | searched, and no evidence exists |
| Not Yet Checked | this layer has not run |
| Not Provided | an optional input is absent (location) |
| Pending Classification | a legacy NULL category type |
| Not Available | there is no parent, and that is a complete record |
| Not Applicable | a deliberate reviewer selection |

The smoke test caught one real bug here: a fact row whose layer had never run was
reporting "Not Found" in its source, date and confidence columns — claiming a
search that never happened. Those columns now carry the same kind of missing as
the row they belong to, and a test pins it.

**Derived, not entered.** Region comes from the state (Appendix C, including
DC → Mid-Atlantic and WA → West Coast / Pacific) and is read-only. A client that
posts its own region does not get to keep it: the store recomputes. A non-US
record reads "Not Applicable (Non-US)"; a US record with no usable state reads
"Not Provided".

**Parent.** Only **Unit of** and **Operated by** are offered. Member of,
Portfolio of, Spinout of, Funded by and Collaborates with appear read-only under
Other Relationships. No parent reads **"Not Available"** with the explanation —
styled as a complete record, not as a gap.

**Category-specific facts.** Light Pull rows follow the actor category. TRL
appears for startups only and only when published; rankings for universities
only. A nonprofit shows neither.

**All UI text comes from one dictionary** (`frontend/labels.js`), and a test walks
every label asserting Title Case with the function words lower case and acronyms
upper case.

### Smoke test

Ran against an isolated seeded store covering a complete university record, a
startup with a published TRL, a standalone actor, a legacy record with no
category type, a non-US record, a geocode failure, an event and a person.

| Screenshot | Shows |
|---|---|
| `01-queue-and-header.jpg` | counts, fail-closed banner, queue filters |
| `02-identity-location.jpg` | grouped queue, dependent dropdowns, derived read-only region |
| `03-parent-sector-hub.jpg` | "Not Available" parent, read-only Other Relationships, Sector and Why It Matched boxes |
| `04-hub-and-light-pull-facts.jpg` | hub distance and suggestion, per-category facts table |

---

## WS4 — source runs and the pre-redesign backlog

Everything created before `REVIEW_REDESIGN_CUTOFF` (configurable, default
2026-10-08) is grouped as **Pre-Redesign Backlog**; later candidates appear under
their own run with its trigger.

This is a **view**. A test reads every stored row before and after filtering and
asserts they are byte-identical, and the original run stays visible under Audit &
Details. Grouping is deterministic around the cutoff, including exactly on it.
A run with no recorded initiator reads **"Not Recorded"** rather than being
invented, and an unrecognised trigger stays "manual" rather than being guessed.

> The authoritative `trigger_type`, `cadence` and `initiated_by` belong on the
> collection-run table in the backend (WS4 task 1). Until that reaches this app
> the trigger is derived from the run description. That additive migration and
> its contract note are **not done** — they are the next WS4 step.

---

## WS5.2 — hub detection fixtures

Backend repository. Commit `781c46c`. Report:
`docs/evidence/hub_detection_fixture_report.md`.

Thirteen `FX-` prefixed synthetic actors, 12 independent families, 10 matched
categories, one controlled topic, Sacramento Valley — plus a Greater Boston
cluster and a 200-mile boundary pair.

**The algorithm was not touched.** Where my expectation and the implemented
behaviour differed, the implemented behaviour won and is what the report records:
a cyclic parent graph excludes the two cycled actors and still proposes on the
actors it *can* resolve. That is what failing closed means here.

**No hand-estimated distances.** Coordinates come from the vendored Census
gazetteer; every distance is computed by `agents.common.geography.distance_miles`.
The boundary pair is two real cities that happen to straddle the radius: **Bishop,
CA at 199.74 miles** from Davis and **Eureka, CA at 201.22**.

| | Expected | Actual |
|---|---|---|
| S1 qualifying set | one proposal | one, 12 families / 10 categories, 13 members, centred Sacramento |
| S2 nine families | no proposal | none |
| S3 four categories | no proposal | none |
| S4 two clusters | two proposals | two, Sacramento and Worcester, no shared members |
| S5 trusted same-topic hub | suppression, not a duplicate | `existing_same_topic_hub` + 13 assignment plans |
| S6 Parked / other topic | excluded from the trigger pool | excluded |
| S7 departments / cycle | family counted once; cycle fails closed | both hold |
| S8 prior rejection | fingerprint suppresses | `existing_family_fingerprint` |
| S9 beyond the radius | not assigned | the 201-mile actor is not a member |

Detection runs **entirely in memory**, so this needed no database. Reruns are
byte-identical; the report carries no timestamp for that reason.

---

## What is not done, and why

| Item | Why |
|---|---|
| **WS5.3** real-world hub shortlist | Needs read access to a local `ghus_v2_*_test` database. Send the PG role and `PGPASSFILE` path. |
| **WS1** mapping record counts | Same blocker. The CSV is complete; only the count column is `UNVERIFIED`. |
| **WS3** audit rows and reviewer identity | The three actions are mapped onto the existing states with the confirmations the brief requires, and the existing fail-closed and idempotency tests pass. The dedicated audit-row assertions and the reviewer-identity gap report are not done. There is still no authenticated identity: the reviewer name is recorded exactly as typed and is never defaulted. |
| **WS4** collection-run migration | The additive migration and Nouhaila's contract note for `trigger_type` / `cadence` / `initiated_by`. |
| **WS5.1, WS6, WS7, WS8** | P2/P3 in the brief's own order. Not started. |

---

## Decisions I need from you

1. **The branch divergence** (WS0 finding 1). Merge `claude/phase12-shared-review`
   into this branch now, or later?
2. **`DATABASE_URL` pointing at production** (WS0 finding 2).
3. **Local test database credentials**, to unblock WS5.3 and the mapping counts.
4. **`REVIEW_REDESIGN_CUTOFF`** — I defaulted it to 2026-10-08T00:00:00Z.
   Appendix H item 10 says this is GHUS's to set.

## Open items for GHUS (surfaced, not decided — Appendix H)

1. Confirm 10 families / 5 categories / 50 miles / 200 miles still stand. The
   Architecture V2 docx text says 3 / 2; the implemented Phase 7 and the approved
   modified spec say 10 / 5. The fixtures run the implemented rules.
2. Confirm Title Case for the six † labels.
3. CROSS / DIASPORA: selectable in the Review sector box, or read-only? They are
   currently read-only, and an existing value still displays.
4. Parked archival after 90 days. No deletion in any case; none is implemented.
5. Ask: may Parked records appear as clearly labelled unverified leads?
6. Update subscriptions: trigger policy, cadence options, ranking weights.
7. Reviewer identity until authentication exists: is a typed name acceptable for
   the audit trail?
8. The 214 category-doubt records: re-triage under the Guide catalog, or carry
   over as-is?
9. Live hub count 48 vs 49 — how the empty hub is shown.
10. The `REVIEW_REDESIGN_CUTOFF` date.

---

## Commits (local only — nothing pushed)

**Shared app**, branch `feature/review-redesign` (from `feature/ismail-modifications`):
- `0da1e96` feat(review): governed Review screen on the Intern Guide catalog

**Backend**, branch `codex/architecture-v2`:
- `2542fd7` feat(taxonomy): replace the Phase 5 catalog with the Intern Guide catalog
- `781c46c` test(hubs): synthetic Phase 7 detection fixtures and their evidence report
