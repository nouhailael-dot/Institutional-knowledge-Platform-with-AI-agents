# Review integration and architecture audit

**Date:** 9 October 2026
**Scope of this pass:** §5 (Review queue integration — named highest priority),
plus the parts of §2, §3 and §4 that the Review path runs through.
**Databases:** local `ghus_v2_review_redesign_test` only. Production Supabase
was not contacted.
**Changes made:** two tests added. Nothing else in this pass.

Everything below was established by reading the executed path or by running
code, not by reading documentation. Where I could not establish something, it
says so.

---

## 1. The Review path, proved end to end

The brief says: *do not assume the Review page is connected to the V2 agents
merely because it displays candidate data. Prove the connection.* Here it is,
with the line that carries each hop.

### Ingestion

```
PostgreSQL (agent output)
  └─ src/review/postgres_source.py :: fetch_candidates()        read-only
      └─ backend/app.py :: _sync_review_candidates()            every 120 s
          └─ src/review/store.py :: sync_external_candidates()  SQLite mirror
              └─ GET /api/review/candidates                     backend/app.py:797
                  └─ frontend/review.js:706                     the queue
```

**The Review store is a SQLite mirror of PostgreSQL, not the source of truth.**
Three feeds write into it: the local Build-the-Map run store, an optional second
SQLite source (`REVIEW_SOURCE_RUN_DB`), and PostgreSQL. Only the PostgreSQL feed
carries agent discoveries.

### Decision

```
frontend/review.js:857
  └─ POST /api/review/candidates/{id}/decision        backend/app.py:863
      └─ store.admission_request(...)                 validates, writes nothing canonical
      └─ src/review/admission.py :: AdmissionBridge.apply()
          └─ subprocess: python -m agents.review.admission --decision <file>
              run in GHUS-Platform, REVIEW_ADMISSION_WRITES_ENABLED=true
              └─ agents/discovery/promote.py :: promote()
              └─ agents/enrichment/decisions.py
      └─ store.record_admission_success(...)          records the outcome locally
```

**The canonical-writer rule holds.** The shared app does not write canonical
data. It serialises a decision to JSON and hands it to the backend's approved
writer as a subprocess. `agents/review/admission.py` says so in its own
docstring and imports `promote` rather than issuing SQL. Verified: the file
exists, and the import is real.

### Answers to the brief's §5 questions

| Question | Answer |
|---|---|
| Which agent creates the review candidate? | None directly. Agents write PostgreSQL; `fetch_candidates()` derives candidates from it |
| Which table stores it? | `review_candidate` in the local SQLite store; the authority stays in PostgreSQL |
| How is Light Pull represented? | `actor_fact` rows with `layer = 1`, rendered into the existing boxes |
| How is the source run identified? | `source_run_id` plus `_run_trigger(...)`; raw UUIDs never reach the screen |
| Does Verify persist reviewed or original values? | **Reviewed.** `approve()` uses `edited_payload`, else `reviewed_payload`; `original_payload` is kept separately for the audit row |
| Can a candidate be processed twice? | No — idempotency key, plus a `ReviewConflict` when status is not `pending_review` |
| Does verification create history? | Yes — one `review_decision` row carrying reviewer, timestamp, before and after payloads, evidence and notes |
| Does topic verification gate Deep Pull? | Yes, in the backend. `agents/collection/deep_pull.py :: actor_is_verified_for_topic()` requires a decision for that exact actor/topic pair, and `append_deep_pull` enforces it |
| How are candidates assigned to a reviewer? | **They are not.** There is no assignment model — see finding F3 |

---

## 2. The risk I went looking for, and what I found

A 120-second sync that re-delivers every candidate is the obvious place for
silent data loss. Two things could go wrong: it could overwrite reviewer edits,
or it could push a decided row back into the queue.

**Neither happens, and the reason is structural.** `sync_external_candidates()`
does `INSERT OR IGNORE`, and its follow-up `UPDATE` touches only `evidence`,
`agent_metadata` and `duplicate_state`, scoped to `WHERE status='pending_review'`.
A decided row is outside that scope entirely.

I did not take that on reading. I exercised it: reject a candidate, re-deliver
it unchanged, re-deliver it renamed and newly flagged as a possible duplicate.
It stays `rejected_by_reviewer`, stays out of the queue, and gains no second
decision row. The same holds for an approved candidate.

**This safety property had no test.** It does now —
`test_a_rejected_candidate_is_not_resurrected_by_the_next_sync` and
`test_an_approved_candidate_is_not_reopened_by_the_next_sync` in
`tests/test_review_decisions.py`. The brief's §12 lists "Rejected rediscovery"
as required coverage; it was the one item on that list with nothing behind it.

*(While probing this I first wrote a check that compared against the status
string `rejected` rather than `rejected_by_reviewer` and it reported a defect.
There is no defect; the check was wrong. Recorded here because the first run is
in the session log.)*

---

## 3. Findings

Classified as the brief asks. **Nothing in this section has been changed.**

### F1 — Two decision paths with different semantics · *requires a decision*

There are two ways to decide a candidate:

| | `/decision` | `/approve` + `/reject` |
|---|---|---|
| Caller | `frontend/review.js:857` | **tests only** |
| Writer | backend `promote()` via subprocess | SQLite `test_canonical_actor` etc. |
| Gate | `AdmissionBridge.configured` | `REVIEW_DEMO_MODE=1` + store inside `.demo/` |
| Fails closed | yes | yes (`ReviewNotConfigured`) |

Both are safe in isolation and both fail closed. The problem is drift: the
demo path has its own `approve()`/`reject()` with its own validation, duplicate
check and audit write, and **the shipped path does not run any of it.** A change
to the real decision semantics will not be reflected there, and
`tests/test_review.py` and `tests/test_review_decisions.py` will keep passing
against behaviour nobody ships.

Not dead code — the demo path is genuinely used offline and is well tested.
**Not safe to remove, and I have not removed it.** What it needs is a decision
about which one is authoritative, and a test asserting the two agree on the
rules they share. I would not do that before 12 October.

### F2 — The SQLite mirror holds decisions that PostgreSQL does not · *investigate*

A decision's outcome is recorded in PostgreSQL by the backend writer, but the
candidate's *local* status lives in the SQLite store. Resurrection is prevented
by the SQLite row existing. If that store is lost, pointed at a new path, or
rebuilt, every previously rejected candidate is pending again, because
PostgreSQL will re-serve it and `INSERT OR IGNORE` will no longer ignore.

The store path comes from `REVIEW_STORE_DB`. This is a real operational
dependency that is not written down anywhere, and it is not obvious from the
code that a file path is load-bearing for a correctness property.

I have not changed this. The fix is either to filter decided candidates out of
`fetch_candidates()` at source, or to treat the store as durable state with a
documented backup. That is a design decision, not a bug fix.

### F3 — No reviewer assignment model · *incomplete, by circumstance*

No `assigned_to`, no claim, no lock anywhere in the review store. Two reviewers
can open the same candidate; the second to decide gets a `ReviewConflict`
rather than a silent double-write, so it is **safe but not collaborative**.

This is downstream of there being no authentication, which the brief puts in
P3. Worth stating plainly rather than leaving as an apparent oversight.

### F4 — Duplicate haversine, correctly handled · *intentionally retained*

`src/review/postgres_source.py::_haversine_miles` duplicates
`agents/common/geography.py::distance_miles`. The two live in different
repositories and the shared app cannot import the backend, so the duplication
is forced. It is already pinned by
`test_the_review_haversine_matches_the_backend_to_a_tenth_of_a_mile`. No action.

### F5 — Root `app.py`, legacy Streamlit · *intentionally retained*

433 lines, imported by nothing in the FastAPI application, standalone. AGENTS.md
says to keep it and not add V2 features to it. Left alone. Flagged only so it is
not mistaken for live code during the next audit.

### F6 — `src/review/source.py` is live, not dead · *active*

`ReadOnlyRunStore` looked unused on a first pass. It is reachable through
`REVIEW_SOURCE_RUN_DB` at `backend/app.py:85`. Recorded so nobody removes it.

---

## 4. What this pass did NOT audit

Stated so the coverage is not overread. None of the following was traced in
this pass:

- discovery agents and orchestration, entity resolution, staging and promotion
  internals, actor classification, geography and relationship extraction —
  these live in GHUS-Platform and were examined only where the Review path
  enters them
- Browse and Ask beyond the parked-lead question already written up in
  `docs/contracts/ws8_ask_parked_leads_and_accounts.md`
- Build the Map internals
- dependency and configuration hygiene
- background jobs and scheduling beyond WS6

The brief's §4 full-lifecycle trace is therefore **partially done**: the
Review-to-canonical half is proved above; the discovery-to-Review half is not,
and I will not claim it.

---

## 5. Recommendation on sequencing

Nothing found in this pass is a Priority A correctness defect. The Review path
is sound: it delegates to the approved writer, it persists reviewer edits rather
than agent values, it fails closed without a writer, it cannot double-process,
and it cannot be made to forget a decision by the sync.

So I would not change Review code before 12 October. The items above are F1
(a decision), F2 (a design choice with an operational dependency) and F3
(blocked on auth). Each is better made deliberately than quickly.
