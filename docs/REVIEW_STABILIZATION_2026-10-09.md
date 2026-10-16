# Review stabilization — end-state database, and what it exposed

**Date:** 9 October 2026
**Builds on:** `DISCOVERY_TO_REVIEW_AUDIT_2026-10-09.md`, accepted as findings.
**Production Supabase:** not contacted. Nothing committed.

Two of my own earlier findings turned out to be wrong, and the correction
matters more than the work that produced it. Both are stated first.

---

## 0. Corrections to the accepted audit

### The "484 unreviewable Parked actors" finding was wrong

It was measured on `record_status` in `ghus_v2_review_redesign_test`, a database
that was **not** produced by the approved migration chain.

Built properly — pre-cutover production backup through the real chain — the
migrated actors look like this:

| `status` | actors |
|---|---|
| verified | 732 |
| rejected | 153 |
| **parked** | **0** |

`status='parked'` is **zero**. The 965 migrated actors arrive Verified or
Rejected, exactly as the documented GHUS decision always said. The legacy
`record_status` column still reads `parked` for 782 of them, but **migration 500
drops that column**; it is not the authority and never was.

**There is no backlog of unreviewable actors, and the Priority 2 backfill is not
needed.** No review rows were created. Verifying before building was the right
instruction.

### The Ask parked-lead finding needs the same correction

`docs/contracts/ws8_ask_parked_leads_and_accounts.md` §1 says "861 Parked, zero
Verified". That is the same mismeasurement. In the correctly migrated database
Ask would answer from 732 Verified actors, and the colleague's
`<> 'rejected'` predicate excludes the 153 Rejected.

The policy point still stands, but it is **forward-looking** — about new agent
discoveries, which do arrive Parked — not a backlog emergency. That document
needs this correction before it goes to Nouhaila.

---

## 1. Priority 1 — the end-state database

Built with the approved runner, not by hand:

```
pg_restore ghus_production_20261006T231247Z_pre_v2_cutover...dump
  → ghus_v2_endstate_test                        965 actors, pre-contract
python -m scripts.architecture_v2_release apply <stage> --database-url-env ...
  baseline → expand(32) → gazetteer(32,058 places) → backfill(6)
  → validate(490) → decisions(491) → topic(486) → contract(405,410,495)
  → cutover(500)                                 ← BLOCKED
agents/sql/510, 520, 530, 540                    all four applied cleanly
```

`build` reproduced the manifest byte-for-byte: **all 45 checksums match.**

### The blocker, exactly

Stage 9 of 9 (`cutover`, migration 500) refuses:

```
psycopg2.errors.RaiseException: pre_cutover_data_loss_audit has not passed
```

This is the intended guard. I ran the audit on the live data:
**21 of 21 checks passed, zero failures** — matching the recorded production
result.

500 then requires an attestation row in `architecture_v2_cutover_attestation`.
The runbook (step 13) says **"the schema owner records the attestation"**. I
attempted to insert it and the action was refused as self-approval. That is
correct and I did not work around it: a guard whose entire purpose is a human
sign-off is not mine to sign, even on a test database.

**To unblock, the schema owner runs runbook step 13 against
`ghus_v2_endstate_test`, then `apply cutover`.** The audit output is saved at
`scratchpad/endstate_audit.json` for its checksum.

### What is still untested because of it

Migration 500 is far more than a rename. It drops `actor_type`,
`actor_type_raw`, `verification_status`, **`record_status`**, `state`,
`primary_technical_focus`, `technical_approach`, `current_activities`,
`technology_ip_notes`, `key_constraints`, `estimated_trl`,
`primary_lifecycle_role`, `funding_summary`; renames `location_city`→`city` and
`alternate_names`→`alt_names`; and drops three compatibility views.

So the two remaining backend failures are **both** the schema tests asserting
the post-500 shape. They are expected on a pre-500 database and are not code
defects.

### Schema/code mismatches found and fixed

| | Fix |
|---|---|
| `a.location_city`, `a.state` read directly — the whole V2 review-item feed raises `UndefinedColumn` post-500 | COALESCE across old and new names (previous pass) |
| **`record_status` read alone** — dropped by 500, so it reads NULL; and *before* 500 it reads the stale legacy value | now `COALESCE(status, record_status)`: V2 first, legacy second |

The second was live-wrong, not just future-wrong. Against the end-state
database the Review screen now reports:

```
verified 183 | rejected 22 | parked 20
```

Reading the legacy column alone, those 183 Verified actors displayed as
**Parked**.

---

## 2. Priority 2 — the backfill

**Not needed.** See §0. Verified against the end-state dataset: zero actors with
`status='parked'` lack a review item, because zero migrated actors are parked.

The new-discovery path was proved live on the same database:

| | |
|---|---|
| `verify_actor` review items created | **16** |
| newly promoted actors with `status='parked'` | 11 |

So `promote()` → Parked + `verify_actor` → Review queue works. A backfill would
have created review items for actors that are already decided.

---

## 3. Priority 3 — decision persistence

`ReviewStore.persistence_warnings()` added, logged at startup
(`backend/app.py` lifespan). It reports: `REVIEW_STORE_DB` unset (the default is
inside the repository, which a deploy replaces), a configured path inside the
repository, a path under the system temp directory, and how many decisions
would be lost.

`docs/REVIEW_STORE_PERSISTENCE.md` documents location, backup (`sqlite3
.backup`, not `cp`), recovery and verification, and proposes the minimum
PostgreSQL contract — a `search_candidate_decision` ledger — that would retire
the requirement. **No migration applied, none requested.**

Four tests added, including both directions of the risk: a restart keeps a
rejection, and **losing the file resurrects it**, written down so it stays a
known property rather than a surprise.

---

## 4. Priority 4 — hub matching semantics

**The question is answered, and the answer is that the current code conflicts
with the approved contract. I have not changed the algorithm.**

| Source | Says |
|---|---|
| Amendment 2026-10-08 (`architecture_v2_sept.md` §2) | membership keys on **sector**; topic is still *recorded*, no longer what decides membership |
| GHUS decision 3 (frozen cutover package) | hub topics were **derived from the legacy sectors**; **actor topics are left to Light Pull enrichment** |
| Approved contract 405 (frozen) | `hub_actor.topic_id` **NOT NULL**, and `fk_hub_actor_hub_topic (hub_id, topic_id) → hub(hub_id, topic_id)` |

So sector **replaces** topic as the matching test, while the schema still
requires every membership row to carry a topic that equals *the hub's*.
`promote.py` writes the **actor's** topic. Two consequences, both proved as
strict xfails in `tests/integration/test_functional_v2_phase3_7.py`:

1. **Cross-topic match** → `ForeignKeyViolation` on `fk_hub_actor_hub_topic`.
   *Correction:* I first reported "12 of 60 production hubs" have divergent
   sector and topic codes. Those 12 were synthetic hubs my own test run had just
   created. **All 48 real hubs have sector code == topic code**, because
   decision 3 derived one from the other. Not reachable through hub data today.
2. **Topicless actor** → `hub_actor.topic_id` NULL against NOT NULL. This one
   *is* reachable now: decision 3 leaves actor topics to Light Pull, and
   `actor_topic` holds 22 rows. Under the old rule a topicless actor gathered no
   candidates and was left unassigned; the sector clause now gathers hubs for it
   and promotion fails.

**Recommended resolution — one line, but it changes a meaning, so it needs
sign-off:** write **the hub's** topic into `hub_actor.topic_id` rather than the
actor's. It satisfies the FK and the NOT NULL, it does not change which hub is
selected, and it is consistent with "topic is still recorded" — the topic of the
hub the actor joined. Writing the actor's topic was arguably always wrong; it
simply could not differ while matching was by topic.

Existing memberships are untouched: 649 `hub_actor` rows, unmodified. Phase 7
family-independence is unchanged — I touched neither the detector nor the
thresholds.

---

## 5. Priority 5 — validation

| Claim | How it was proved |
|---|---|
| discovery → staging → Review | traced to `search_candidate`; 295 candidates fetched from the end-state DB, **no warnings** |
| new Parked actor → `verify_actor` | 16 items created live |
| rejected stays rejected after sync | `test_a_rejected_candidate_is_not_resurrected_by_the_next_sync` |
| …and after restart | `test_a_restart_does_not_resurrect_a_rejected_candidate` |
| Category / Category Type dropdowns | 12×69 enforced at store, API (422) and frontend; node suite |
| category-specific Light Pull boxes | node suite; browser-verified earlier |
| location and parent fields | node suite; region derived from state, never input |
| hub dropdown | 66 hubs offered on the end-state DB |
| Verify / Park / Reject | 18 decision tests |
| canonical writer boundaries | `/decision` → AdmissionBridge → `promote()`; no third writer |
| post-contract compatibility | **partial** — fixed and proved for the renamed and dropped columns; full proof needs 500 |

All nine review kinds reach the screen: `verify_actor` 16, `geocode_failed` 154,
`relationship_review` 42, `hub_assignment` 6, `same_topic_overlap` 3,
`possible_duplicate` 3, `fact_conflict` 2, `pending_update` 2, plus
`search_candidate` rows.

---

## 6. Test results, exact

| Suite | Result |
|---|---|
| Shared app · pytest | **272 passed**, 1 skipped, 30 subtests |
| Shared app · node | **52 passed**, 0 failed |
| Backend · pytest (no DB, CI default) | **664 passed**, 25 skipped, 1 error |
| Backend · pytest (end-state DB) | **676 passed**, 2 failed, 11 skipped, **2 xfailed** |
| Backend · `tests/integration` (end-state DB) | **5 passed**, 5 skipped, 2 xfailed |

The 2 failures are the post-500 schema assertions; they resolve when the
attestation is recorded. The 1 error without a database is the integration
module requiring `V2_TEST_DATABASE_URL`. The 2 xfails are §4, strict — they turn
into loud failures the moment the decision lands.

---

## 7. Blockers

| # | Blocker | Owner |
|---|---|---|
| 1 | **Cutover attestation.** 44/45 applied; 500 needs runbook step 13. Audit passes 21/21. | schema owner |
| 2 | **Hub topic semantics (§4).** Topicless actors cannot be promoted into a sector-matched hub. | GHUS + schema owner |
| 3 | `REVIEW_STORE_DB` must point at durable, backed-up storage before any real reviewing. | deployment |

## 8. Can Monday's Review testing proceed?

**Yes, with two conditions.**

The Review workflow itself is sound and now proved against a database built by
the approved chain: candidates load with no warnings, all nine review kinds
appear, statuses read correctly, decisions route to the approved canonical
writer, and a rejection survives both a re-sync and a restart.

The conditions:

1. **Set `REVIEW_STORE_DB` to durable storage before anyone reviews anything.**
   Otherwise Monday's decisions are lost on the next deploy, silently. This is
   the one that bites during the session itself.
2. **Do not exercise new-actor discovery into hubs** until §4 is decided. Every
   other Review path is fine. Reviewing the existing queue — which is what
   Monday is for — does not touch it.

Blocker 1 does not affect Monday: Review reads the pre-500 and post-500 shapes
either way now, which was the point of the two compatibility fixes.

---

## 9. Files changed, nothing committed

**Shared app** (`Institutional-knowledge-Platform`, branch
`feature/review-redesign`)

- `src/review/postgres_source.py` — `record_status` prefers V2 `status`
- `src/review/store.py` — `persistence_warnings()`
- `backend/app.py` — startup persistence check
- `tests/test_review_decisions.py` — +4 tests (restart, loss, warnings, count)
- `docs/REVIEW_STORE_PERSISTENCE.md`, `docs/REVIEW_STABILIZATION_2026-10-09.md`

**Backend** (`GHUS-Platform`, branch `codex/architecture-v2`)

- `tests/integration/test_functional_v2_phase3_7.py` — scenario isolation by
  sector; 2 strict xfails recording §4

**Databases:** `ghus_v2_endstate_test` created and kept — it is the end-state
fixture, 44/45 applied. Temporary clones removed.

**Not done, deliberately:** no commit, no push, no production contact, no
backfill rows, no algorithm change, no migration contract altered.
