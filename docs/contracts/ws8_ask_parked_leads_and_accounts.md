# WS8 — Ask parked-lead policy, Build the Map handoff, accounts, archival

**For:** Nouhaila (Ask, Build the Map, Browse)
**From:** Ismail (Review, hub fixtures)
**Date:** 9 October 2026
**Status:** audit and specification. **No code in Ask, Build the Map or Browse
was changed.** Those are yours; this says what I found and what I propose.

WS8 is P3 in the brief and has four items. One of them turns out to be a live
correctness problem rather than polish, so it is first.

---

## 1. Ask must not answer from Parked records — and today it would

### The rule

Architecture V2 rule 5: sources never mix. Imported, Parked/Verified and
uploaded GHUS/UM6P/OCP documents are always labelled. The brief's WS8 wording:

> answer from Verified facts by default. Parked records may appear only as
> clearly labeled "Unverified Discovery Leads", never mixed into verified
> evidence or recommendations.

### What the code does

There are two versions of this, and the difference matters.

On `feature/review-redesign`, `src/assemble.py::assemble_actors()` has **no
status filter at all**:

```sql
FROM actor a
...
WHERE a.merged_into_actor_id IS NULL
```

On `claude/phase12-shared-review` — your branch, and the one with the later
work — your commits `c133a33` and `f92f407` added one:

```sql
WHERE a.merged_into_actor_id IS NULL
  ...
  AND COALESCE(to_jsonb(a)->>'status', '') <> 'rejected'
```

**That is an exclusion of Rejected, not a restriction to Verified.** It closes
the rejected-actor hole, which was the right fix for what it was aimed at, and
it leaves the Parked case open: a Parked actor has `status <> 'rejected'` and
passes the filter.

So on both branches, `record_status` still never reaches `src/generate.py`, and
the answer cannot label anything even if it wanted to. The prompt tells the
model to cite sources by entity name and nothing else.

I audited the no-filter branch first and originally wrote this up as "no status
filter at all". That was wrong about your branch, and the correction is above.
It does not change the conclusion below, because the filter that exists does
not cover Parked.

### Correction, 9 October 2026 — read this before the numbers below

**The counts in this section are wrong and are kept only to show what was
corrected.** They were measured on `record_status` in a database that was not
built by the approved migration chain. Rebuilt properly — the pre-cutover
production backup through the real chain — the migrated actors are
**732 Verified and 153 Rejected, with zero Parked**, and `record_status` is a
legacy column that migration 500 drops.

So this is **not** a backlog emergency: Ask would answer from Verified actors,
and your `<> 'rejected'` predicate already excludes the Rejected ones.

**The policy point still stands, forward-looking.** New agent discoveries *do*
arrive Parked (proved: 16 `verify_actor` items, 11 new actors with
`status='parked'`). Once they accumulate, an unfiltered index answers from them.
The fix below is still the right one — it is just not urgent, and the status
column to filter on is `status`, not `record_status`.

Details in `docs/REVIEW_STABILIZATION_2026-10-09.md` §0.

### Why this matters now rather than later

Measured against the migrated copy in `ghus_v2_review_redesign_test`
(885 live actors of 965 total):

| `record_status` | `verification_status` | Actors |
|---|---|---|
| parked | ai_inferred | 834 |
| imported | phase_1 | 97 |
| parked | needs_review | 27 |
| *(null)* | *(null)* | 7 |

**861 Parked. Zero Verified.**

So if the Ask index is rebuilt against the migrated database as it stands, Ask
answers almost entirely from unverified discovery leads and presents them as
verified evidence, unlabelled. The Ask index rebuild is still outstanding after
the Phase 12 migration, which makes this a pre-deployment blocker rather than a
P3 polish item.

The backend gap analysis already reaches the same conclusion from the other
direction — `docs/architecture_v2_gap_analysis.md` says to rebuild the index
"from current-fact/source/status views in Phase 16". Status is already
understood to belong in the index; what follows is only that the rebuild must
not happen before it does, or Ask starts answering from 861 leads.

I have not rebuilt the index and have not changed Ask.

### What I propose

Three changes, all in files you own.

**1. Carry the status into the index.** In `assemble_actors()`, select
`a.record_status` and keep it on the document, so retrieval can filter and the
answer can label. This is additive to your existing `<> 'rejected'` predicate —
keep that; a Rejected actor should stay out of the index entirely, whereas a
Parked one needs to be *in* it and labelled. Nothing else about the query
changes.

**2. Filter at retrieval, not at assembly.** Keep Parked records *in* the index
and exclude them from the default answer path, rather than never indexing them.
Two reasons: an unverified lead becomes answerable the moment a reviewer
verifies it, with no reindex; and "Unverified Discovery Leads" needs those
documents available to show on request.

**3. Label at generation.** A Parked source is rendered under a separate
heading and cited as a lead, never interleaved with verified facts. Suggested
wording, matching the Review vocabulary already in `frontend/labels.js`:

> **Unverified Discovery Leads** — found by the agent, not yet reviewed by
> GHUS. Not evidence.

### Acceptance, as I would test it

- An actor whose `record_status` is `parked` never appears in an answer's
  verified evidence, and never in a recommendation.
- With leads switched on, a Parked actor appears only under the labelled
  heading, and the label survives in the cited output.
- An actor moved from Parked to Verified in Review becomes answerable without
  a reindex.
- With every actor Parked — the current state of the data — Ask says the map
  has no verified answer rather than answering from leads. This is the case
  worth testing first, because it is today's data.

**Default:** leads **off**. A reader who does not ask for unverified material
should not receive it.

---

## 2. Build the Map — handoff, resume, ownership, source labels

Audited, not changed.

| Brief item | What exists today | Gap |
|---|---|---|
| Handoff from Ask | `POST /api/map/session` returns a `job_id`; Ask does not create one | no handoff path |
| Resume | `GET /api/maps` lists recent maps and `GET /api/map/{id}` returns one, so resume is **already possible** by id | needs an entry point, not a mechanism |
| Run ownership | none — no `owner`, `user_id` or `account` field anywhere in `backend/app.py` or `src/map_agent/` | depends on §3 |
| Source labelling | same gap as §1: nothing carries `record_status` | see §1 |
| "Also Found" cleanup | **the term does not exist in this codebase.** No match for `Also Found` or `also_found` in `frontend/`, `src/` or `backend/` | appears to be from the Streamlit interface. Please confirm whether it is still a requirement before anyone builds it |

The brief's "Continue Updating This Map?" entry point belongs in Build the Map,
which is yours, so I have left it. It is the natural place to create a WS6
subscription: the Review → Updates tab reads subscriptions but deliberately
does not create them, and `requested_via = 'map_verification'` exists in the
schema for exactly this.

---

## 3. Accounts — specification only

The brief says spec only, because this depends on authentication that does not
exist. Confirmed: no auth, login or session handling in `backend/app.py`. Map
sessions are anonymous job ids.

**This is a dependency, not a task.** Until it lands:

- `actor_update_subscription.requested_by` stays **nullable** and displays as
  "Not Recorded". It is never defaulted to a service account and never
  inferred. The Review Updates tab already does this.
- `review_decision` records the reviewer the same honest way.
- Account-based filtering is not simulated. A fake owner column that everyone
  shares is worse than no column.

**The monthly email, specified and not built:**

1. Group `collection_run` rows by `initiated_by` over the period, joined to
   `actor_update_subscription_run` for the subscription each run served.
2. One message per requester. A requester with no runs gets no message rather
   than an empty one.
3. **A delivery audit row per send** — recipient, period, run ids, sent-at. A
   duplicate send must be detectable after the fact, which means the audit row
   is written in the same transaction as the send attempt, not after a success.
4. Append-only, like every other ledger here. A correction is a new row.
5. Dry-run by default, as every job is.

Nothing of this is implemented, deliberately: a monthly report that cannot name
who requested anything would be fabricating its own primary key.

---

## 4. Parked archival policy — a GHUS decision, surfaced not taken

The brief says this waits for GHUS, so it stays open. What a decision needs to
answer, so it can be made once:

1. **After how long** does an un-reviewed Parked record become stale? There is
   no proposal here; any number I offered would be invented.
2. **What does archival mean?** Never deletion — guardrail 4 and the no-delete
   guards in migration 530 both forbid it. The options are a status, a flag, or
   exclusion from the queue's default filter.
3. **Does an archived record stay in the Ask index** as an unverified lead, or
   leave it? §1 makes this a real question rather than a theoretical one.
4. **Who can un-archive, and is that a reviewable decision** with an audit row?

My recommendation on 2 only, because it follows from rules already agreed:
archival is a **filter default**, not a state change. The record keeps its
status and its history; the queue stops showing it unless asked. That needs no
migration, no new status value, and nothing to undo.

---

## Summary of what is and is not done

| Item | State |
|---|---|
| Ask parked-lead policy | **audited — defect found and specified. Not fixed: Ask is yours** |
| Build the Map handoff | audited and specified. One requirement ("Also Found") appears obsolete — please confirm |
| Accounts + monthly email | specified only, as the brief requires. Blocked on authentication |
| Parked archival | open GHUS decision, with the questions it needs to answer |

The one thing I would not leave until after 12 October is §1.
