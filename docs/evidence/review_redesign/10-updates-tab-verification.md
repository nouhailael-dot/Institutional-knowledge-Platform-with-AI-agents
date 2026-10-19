# WS6 — the Review "Updates" tab, verified in the browser

**Date:** 9 October 2026
**Database:** `ghus_v2_review_redesign_test` (local, 127.0.0.1:55432). Production
Supabase was not connected to at any point.

This is a text transcript rather than a screenshot. The app window was hidden
while the checks ran, so the browser returned blank frames; a blank image filed
as evidence would be worse than none. Everything below is read out of the live
DOM.

## What was exercised

Two subscription rows were inserted into the test database, the tab was opened,
the rendering was read back, and the rows were deleted again. They were
fabricated for this check and do not survive it — `actor_update_subscription`
is back to 0 rows, which is the correct state: a subscription is a GHUS request,
never a default.

## Three defects found, all of them only by looking at the rendered page

The static suites passed throughout. None of these would have been caught
without opening the tab.

| # | What was wrong | Fix |
|---|---|---|
| 1 | `ReferenceError: CADENCES is not defined` — the whole Review page crashed on opening Updates. The label group existed in `labels.js` but was never added to the import list in `review.js`. | import added |
| 2 | `Requested Via` printed the raw database code `map_verification`. `review.js`'s own header rule is that debug strings never reach the main view. | `REQUESTED_VIA` label group; `requestedViaLabel()` |
| 3 | The period printed ISO `2026-08-30` next to a localised `29/10/2026`, then rendered as `Monthly· 30/08/2026to 07/04/2027` once formatted — htm drops the whitespace at a template line break. | `formatDay()` for calendar dates, and the line assembled as one string in `subscriptionPeriodLabel()` |

`formatDay` splits the date into parts rather than passing the string to the
`Date` constructor, which would read it as UTC midnight and show the previous
day to a reader west of Greenwich.

## Rendered output, with the two rows present

```
Actor updates are opt-in. Each subscription keeps a stated scope current for a
stated period; nothing outside one is swept. The event update schedule is
separate and unchanged.

  Agriculture and CA                                            [Active]
  Subscription · Monthly · 30/08/2026 to 07/04/2027
    Requested by    Not Recorded
    Requested Via   Map Verification
    Last Run        Not Yet Collected
    Next Due        29/10/2026
    Runs            Not Yet Collected

  Water                                                        [Expired]
  Subscription · Weekly · 23/03/2026 to 29/09/2026
    Requested by    Not Recorded
    Requested Via   Review Updates
    Last Run        Not Yet Collected
    Next Due        Not Applicable
    Runs            Not Yet Collected
```

"Agriculture and CA" is the intersection reading: agriculture actors in
California, not everything in either. "Requested by: Not Recorded" is the
honest state — there is no authenticated identity yet, so the column is NULL
and the screen says so instead of naming a service account.

The expired subscription shows `Next Due: Not Applicable`, not a date. An
expired subscription does not get one last run.

## Rendered output with the rows removed, which is the Monday state

```
No subscriptions yet. One is created when a map is verified, or from here once
the scheduler contract is built.
```

## No regression in the Queue tab

Switching back to Queue restores, read from the DOM:

- all five filters — Record Kind, Review Reason, Source Run, Actor Category,
  Search by Name or Domain
- 255 queue rows in 3 run groups
- the four numbered sections — Identity & Classification, Location & Parent,
  Sector, Topic & Hub, Light Pull Facts
- 13 Light Pull boxes and the Decision panel

The Updates section is gone from the DOM while Queue is shown, and vice versa.

## One failure left standing, deliberately

`GET /api/browse/actors` returns 500 in this preview with
`RuntimeError: DATABASE_URL is not set`. That is Browse, which belongs to my
colleague, and the cause is my own environment: I run the preview without a
`DATABASE_URL` so that nothing can reach production Supabase. Review reads
through the `PG*` path and is unaffected. Not a code defect and not mine to
change.

## Suites

| Suite | Result |
|---|---|
| `tests/test_review_ui.mjs` | 52 passed |
| shared-app `pytest tests` | 265 passed, 1 skipped, 30 subtests |
| backend `pytest tests` | 664 passed, 24 skipped, 1 pre-existing DB-dependent error |

Each of the three defects above now has a test that fails without its fix.
