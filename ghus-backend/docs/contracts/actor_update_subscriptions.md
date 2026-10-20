# Contract: actor update subscriptions replace the weekly actor sweep

**For:** Nouhaila (backend / agent contracts)
**From:** Ismail (Review interface, hub fixtures)
**Status:** proposal. Migration `agents/sql/540_v2_actor_update_subscription.sql`
applied to `ghus_v2_review_redesign_test` only. Production Supabase untouched.

---

## 1. What changes, and what does not

| | Before | After |
|---|---|---|
| **Actor** updates | a weekly all-sector sweep, every actor, forever | only what an active subscription asks for |
| **Event** updates | weekly, Monday 06:00 UTC | **unchanged** |

Events are time-bound and go stale on their own, so the schedule still makes
sense for them. Actors do not, and sweeping all of them every week spends budget
re-reading records nobody asked about.

A test asserts the event side did not move: the cron line, the event discovery
step in `agents/weekly_discovery.py`, and the absence of any event handling in
the subscription module.

## 2. The data model

`actor_update_subscription` — scope, period, provenance, status.

| Column | Notes |
|---|---|
| `actor_ids`, `sector_codes`, `topic_ids` | arrays, all optional |
| `country`, `state_code`, `city`, `region_code` | place, all optional |
| `start_date`, `end_date` | a subscription **always ends** |
| `cadence` | `once` · `weekly` · `monthly` · `quarterly` |
| `requested_by` | **nullable** — see below |
| `requested_via` | `map_verification` · `review_updates` |
| `origin_run_id` | the run this request came out of |
| `status` | `active` · `paused` · `expired` · `cancelled` |

**The scopes intersect, they do not union.** Sector `AGRI` plus state `CA` means
agriculture actors in California, not everything in either.

**A subscription must have a scope.** `ck_actor_update_subscription_scope`
refuses an empty one, and the migration proves the constraint bites before it
commits. Without that rule, the first unscoped row quietly restores the sweep.

**`requested_by` is nullable on purpose.** There is no authenticated identity
yet. An unknown requester is NULL and displays as "Not Recorded" — never
defaulted to a service account, never inferred from anything.

`actor_update_subscription_run` links each run to the WS4 `collection_run`, so a
discovered actor traces back to the subscription that asked for it and the run
that found it. It is **append-only**: a run is evidence, corrected by adding
another run rather than editing this one.

## 3. The scheduler contract

`agents/collection/subscriptions.py` is pure: it takes data and returns data, and
writes nothing. A test asserts it contains no `INSERT`, `UPDATE`, `DELETE`,
`session.execute` or `commit`.

| Rule | How it is enforced |
|---|---|
| Only **active, in-period** subscriptions run | `skip_reason()` returns `paused` / `cancelled` / `expired` / `not_started` / `not_due`, and `plan_subscription_run` **refuses** a non-active subscription outright |
| An expired subscription gets **no last run** | the period check precedes the cadence check |
| **Deduplicate before discovering** | `plan_subscription_run` checks the map first, case-insensitively and whitespace-trimmed, so "UC Davis" and `uc davis ` are one organisation |
| **Dry run by default** | `dry_run=True` unless asked otherwise, and dry and live load the **same** candidates so the funnel counts compare |
| **No auto Verified or Rejected** | nothing in the module writes a status at all |
| Deterministic | `due_subscriptions` sorts by id |

Counts come out of the plan ready for `collection_run`: `found`,
`deduplicated`, `staged`.

## 4. What you need to build

The planner decides *what* to run. The parts that touch the database are yours:

1. **Load** active subscriptions and their `last_run_at`.
2. **Call** `due_subscriptions(...)`, then `plan_subscription_run(...)` per
   subscription with the candidates your discovery step produced and the
   identifiers already in the map.
3. **Write** a `collection_run` row with `trigger_type = 'subscription'`, the
   cadence, `initiated_by` (NULL for now), the config snapshot and the counts —
   see `docs/contracts/collection_run_provenance.md`.
4. **Link** it with an `actor_update_subscription_run` row.
5. **Stage** `plan.to_discover` into the normal staged → review flow. Nothing is
   promoted and nothing is verified.
6. **Update** `last_run_at` and `next_due_at`, and set `status = 'expired'` once
   `end_date` has passed.

## 5. Awaiting GHUS sign-off

These live in `config/architecture_v2.yaml` under
`actor_update_subscriptions`, marked in the file itself, because they are
decisions rather than engineering choices (brief WS6 item 4):

| Setting | Proposed | Status |
|---|---|---|
| `default_cadence` | `monthly` | **not approved** |
| `allowed_cadences` | once / weekly / monthly / quarterly | **not approved** |
| `sector_rank_weight` | `0.2` | **a proposal, explicitly not an approved number** |
| `max_duration_days` | 365 | **not approved** |
| `dry_run_default` | `true` | safe default, keep |

`run_configuration()` refuses a configuration that is incomplete or
self-contradictory rather than filling in a default, so a half-made decision
fails loudly instead of running on a guess.

## 6. Not built, on purpose

- **The monthly account report.** It depends on authentication, which is P3. The
  brief says spec only, and this is the spec: once `requested_by` carries a real
  identity, the report groups runs by requester over the period and sends one
  message per requester, with a delivery audit row per send so a duplicate send
  is detectable. Nothing of it is implemented.
- **Any subscription row.** Each one is a GHUS request, not a default.
- **The scheduler itself**, for the reasons in §4.

## 7. Questions for you

1. **Where does the candidate list come from** for a sector- or place-scoped
   subscription — the existing open-web discovery entry point with a filter, or
   a separate query?
2. **What counts as "already mapped"** for dedup: canonical name, alternate
   names, and website domain, as the duplicate check elsewhere does? I would use
   the same three, so the two paths cannot disagree.
3. **Should a subscription that finds nothing still write a `collection_run`?**
   I would say yes — "we looked and found nothing" is a result worth recording,
   and its absence is indistinguishable from the run never happening.
