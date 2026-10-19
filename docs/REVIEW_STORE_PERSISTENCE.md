# The Review store is durable state, not a cache

**Status:** operational requirement, in force until PostgreSQL can record that a
pre-promotion candidate was decided.
**Applies to:** every environment that serves the Review screen.

---

## Why this file matters

`REVIEW_STORE_DB` is a SQLite file. It looks like a cache of PostgreSQL, and
for most of its contents it is one. For one thing it is the only copy.

**It is the only place that knows a pre-promotion candidate was rejected.**

A `search_candidate` lives in PostgreSQL. When a reviewer rejects it, the
decision is written here. PostgreSQL keeps serving that candidate on every
sync, and the only reason it does not come back is that
`sync_external_candidates` finds the row already present and declines to
re-insert it (`INSERT OR IGNORE`, and its follow-up `UPDATE` is scoped to
`WHERE status='pending_review'`).

Delete the file and nothing declines any more. The candidate returns to the
queue as new work. **Nothing errors, nothing is logged, and the queue looks
healthy** — it has simply forgotten a decision a person made. That is the worst
shape a data-loss bug can take.

This is proved both ways in `tests/test_review_decisions.py`:

- `test_a_restart_does_not_resurrect_a_rejected_candidate` — same file, new
  process: the rejection survives.
- `test_losing_the_store_file_is_what_resurrection_actually_looks_like` —
  file removed: the candidate comes back. The failure is written down so it
  cannot be rediscovered the hard way.

## Where it must live

| | |
|---|---|
| **Setting** | `REVIEW_STORE_DB`, an absolute path to a `.sqlite3` file |
| **Default if unset** | `<repo>/.review/review.sqlite3` — **inside the working tree** |
| **Why the default is wrong in production** | a deployment replaces the working tree |

Put it on storage that outlives a deployment: a mounted volume, a persistent
disk, anything that is not the application directory and not `/tmp`.

The application checks this at startup and logs a warning per problem. The
checks live in `ReviewStore.persistence_warnings()`:

1. `REVIEW_STORE_DB` not set — the in-repository default is in use.
2. The configured path is inside the repository.
3. The path is under the system temporary directory.
4. If any of the above hold **and** decisions already exist, it says how many
   would be lost.

A healthy deployment logs nothing from this check.

## Backup and recovery

**Back up:** the single file at `REVIEW_STORE_DB`. Nothing else in the Review
system holds local state.

**Cadence:** at least as often as reviewers work. A backup older than the last
review session loses decisions that were made after it.

**Taking one safely.** SQLite is being written to, so do not copy the file with
`cp`:

```bash
sqlite3 "$REVIEW_STORE_DB" ".backup '/backups/review-$(date +%Y%m%dT%H%M%SZ).sqlite3'"
```

**Before a deployment:** take a backup, confirm `REVIEW_STORE_DB` still points
outside the deployed tree, and confirm the file is there after the deploy.

**Recovery.** Restore the file to `REVIEW_STORE_DB` and restart. Decisions,
reviewer edits and the audit history come back together, because they are rows
in the same file. There is no partial recovery and nothing to replay.

**Verifying a restore:**

```sql
SELECT count(*) FROM review_decision;                       -- decisions kept
SELECT status, count(*) FROM review_candidate GROUP BY 1;   -- queue shape
```

If `review_decision` is empty on a store that has been in use, the restore took
the wrong file.

## What is safe to lose

Everything else. The mirrored candidates come back on the next sync, within
120 seconds. Only `review_decision`, and the `review_candidate` status and
`reviewed_payload` columns, are irreplaceable.

---

## The PostgreSQL contract that would end this requirement

**A proposal for the schema owner. Nothing here has been applied, and no
production migration is requested by this document.**

The requirement exists because a pre-promotion candidate has nowhere canonical
to record a decision. `review_item` covers promoted actors; a `search_candidate`
that a reviewer refused has no home. The minimum that would fix it:

```sql
CREATE TABLE search_candidate_decision (
    search_candidate_decision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    search_candidate_id uuid NOT NULL REFERENCES search_candidate(candidate_id),
    decision            text NOT NULL CHECK (decision IN ('rejected','parked')),
    rejection_reason    text,
    decided_by          text,          -- nullable: no authenticated identity yet
    decided_at          timestamptz NOT NULL DEFAULT now(),
    idempotency_key     text NOT NULL UNIQUE,
    notes               text
);
CREATE INDEX ix_search_candidate_decision_candidate
    ON search_candidate_decision(search_candidate_id);
```

Four properties it has to have, each for a reason already established here:

1. **Append-only**, with a no-delete guard like the other ledgers. A correction
   is a new row.
2. **`decided_by` nullable.** There is no authenticated identity. An unknown
   reviewer is NULL and reads as "Not Recorded" — never defaulted.
3. **`idempotency_key` unique**, so a retried decision cannot be recorded twice.
   The Review API already generates one per decision.
4. **No `approved` decision.** Approval promotes the candidate and is already
   recorded canonically by `promote()`. This table records only the outcomes
   that leave no canonical row behind, which is exactly the gap.

Once it exists, `fetch_candidates()` excludes candidates that appear in it, and
SQLite becomes a true cache: safe to delete at any time, needing no backup.

Until then, this document is the control.
