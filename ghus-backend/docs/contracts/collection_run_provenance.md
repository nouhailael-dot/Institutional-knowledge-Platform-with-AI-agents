# Contract change: `collection_run` records provenance, not just budget

**For:** Nouhaila (backend / agent contracts)
**From:** Ismail (Review interface, hub fixtures)
**Status:** proposal, `agents/sql/530_v2_conformance_fixes.sql`. Not applied.
Local `ghus_v2_*_test` databases only; production Supabase untouched.

---

## 1. Why

`collection_run` answers "how did the run go" — fetches, money, status. It does
not answer "where did this record come from and who asked for it". The Review
screen needs the second one, and so does every actor-update subscription.

Today the Review app derives the trigger from the run **description string** and
reports the initiator as "Not Recorded", because there is nothing better to read.
That works, and it is honest, but it is a workaround.

---

## 2. The eight new columns

All **nullable**, all additive. No existing column changes, no row is rewritten.

| Column | Type | What it records |
|---|---|---|
| `trigger_type` | `text` | `manual` · `subscription` · `scheduled_event` · `migration` |
| `cadence` | `text` | `once` · `weekly` · `monthly` · `quarterly` |
| `initiated_by` | `text` | who asked for the run |
| `config_snapshot` | `jsonb` | the configuration the run actually used |
| `found_count` | `integer` | records found |
| `deduplicated_count` | `integer` | dropped as already mapped |
| `staged_count` | `integer` | staged for review |
| `review_item_count` | `integer` | review items raised |

`trigger_type` and `cadence` are CHECK-constrained to those exact values, `NOT
VALID` so existing rows are not re-scanned.

### `initiated_by` is nullable on purpose

There is no authenticated identity in the platform yet. An unknown initiator is
**NULL**, and the Review screen shows **"Not Recorded"**. It is never defaulted
to a service account, never set to "system", and never inferred from anything.
A wrong name in an audit trail is worse than no name.

When real authentication lands (P3), this column takes the authenticated
identity and nothing else about it changes.

---

## 3. What the agents need to write

Whatever starts a run should set, at minimum:

```python
{
    "trigger_type": "manual",        # or subscription / scheduled_event / migration
    "cadence": "once",               # NULL for a one-off manual run is also fine
    "initiated_by": None,            # until auth exists; never a placeholder
    "config_snapshot": {...},        # the resolved config, not the request
}
```

and, when the run finishes, the four counts.

**`config_snapshot` should be the resolved configuration** — what the run
actually used after defaults and overrides — not the request that started it.
The point is to be able to answer "why did this run produce that" months later.

**The counts should reconcile.** `found_count` ≥ `deduplicated_count` +
`staged_count` is the expectation; if it does not hold, that is worth knowing
and the funnel check should say so rather than the numbers being quietly
inconsistent.

---

## 4. What the Review app does with them

| Field | Before | After |
|---|---|---|
| Trigger | guessed from the description text | read from `trigger_type` |
| Cadence | not shown | shown on the run chip |
| Initiator | always "Not Recorded" | the recorded name, or "Not Recorded" |
| Counts | not shown | available for the queue header |

The app **prefers the column and falls back to the derivation** when it is NULL,
so nothing breaks while the migration is unapplied and nothing needs
re-deploying on the day it is applied.

---

## 5. What this unblocks

- **WS4 task 1.** The run model stops being inferred from a string.
- **WS6.** Actor update subscriptions are specified to link each run to this
  model and record initiator, configuration, outcome and review counts. They
  cannot today.

---

## 6. Questions for you

1. **Who writes the row** — does the run writer own all eight columns, or do the
   counts get updated by whatever finishes the run?
2. **`config_snapshot` shape.** Is there an existing resolved-config object we
   should serialise, or should the contract fix a shape here?
3. **Dry runs.** A dry run already sets `dry_run = true`. Should it populate the
   counts (what it *would* have done), or leave them NULL? I would populate
   them — a dry run whose funnel you cannot read is not much of a rehearsal —
   but it is your call.
4. **Backfill.** Existing rows stay NULL. Is it worth a one-off pass setting
   `trigger_type = 'migration'` on the cutover runs, or do we leave history
   alone? Leaving it alone is the safer default and my preference.
