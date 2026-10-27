# Ledger reconciliation for migrations 540, 550, 560, 570, 580

Status: **proposed. Not executed on Supabase.** Needs the schema owner's
approval and the platform owner's authorization (checklist below).
Prepared 2026-10-26. The only thing run against Supabase is read-only
inspection: `pg_dump --schema-only`, the preflight, and catalog fingerprints,
all in sessions opened with `default_transaction_read_only=on`.

## Result

All five migrations are **fully applied** on Supabase. Only their ledger rows
are missing. No schema repair is needed and none of them may be re-run.

| Migration | Purpose | Objects it owns at the end state | On Supabase | Ledger |
|---|---|---|---|---|
| 540 | opt-in actor update subscriptions: tables `actor_update_subscription`, append-only `actor_update_subscription_run` | 46, of which 2 are later replaced by 550/570 | fully applied (2 accepted deviations, below) | missing |
| 550 | Discovery-page requests: `title`, `focus_terms`, `max_new_actors_per_run`; `biweekly`; `discovery_page` | 12 (1 later replaced by 570) | fully applied | missing |
| 560 | `agent_auto_accept` verification origin | 2 | fully applied | missing |
| 570 | actor update requests: `update_options`, `max_usd_per_run` | 8 | fully applied | missing |
| 580 | event and people requests: `discovery_entity`, `discovery_options` | 7 | fully applied | missing |

None of them inserts reference data; their self-test inserts fail by design.
The object-by-object inventory per migration is in
`evidence/expected_objects_by_migration.json`.

**Method.** A fresh read-only dump of Supabase's `public` schema was restored
into the local database `ghus_v2_supabase_fresh_test`. It matches live
Supabase exactly on:

- 92 tables (including row-security flags)
- 1,042 columns
- 395 constraints (including NOT VALID)
- 196 indexes
- 37 triggers
- 20 function bodies
- 17 comments
- 4 policies

There are two known differences. Neither touches 540-580:

- `search_doc.embedding` is `text` locally, because pgvector is not installed.
- Postgres prints 6 constraints on other tables in a different format.

On a copy of that database, 580 -> 540 were rolled back with their own rollback
scripts. Then 540 -> 580 were applied from the committed files, and the
catalog was fingerprinted after every step. Every object each migration creates
is present on Supabase with an identical definition, except the two 540
deviations below.

### 540: two deviations, both accepted, no repair

1. **Row security is enabled** on `actor_update_subscription` and
   `actor_update_subscription_run`, although 540 does not enable it.
   - Supabase's own event trigger `ensure_rls` (`rls_auto_enable`, on
     `ddl_command_end`) does this for every new table; all 86 base tables in
     `public` have it.
   - It is stricter than the file, not weaker. The backend connects as
     `postgres`, the table owner, which is not bound by row security (it is
     not forced).
   - Disabling it to "match the file" would be a security regression.
2. **The function body of `ghus_guard_subscription_run_append_only()`** was
   stored with CRLF line endings (applied from a Windows CRLF checkout).
   - With the `\r` bytes removed it is identical to the committed file (same
     md5 of `pg_get_functiondef`).
   - PL/pgSQL treats `\r` as whitespace, so behaviour is identical.
   - Four functions from earlier migrations carry the same CRLF bytes:
     - `ghus_guard_no_delete`
     - `ghus_guard_notes_column`
     - `ghus_guard_ranking_is_university`
     - `ghus_guard_sector_link_append_only`
   - Out of scope; informational.

The expected-state check therefore ignores row-security flags and compares
function bodies with `\r` removed. Everything else is compared exactly.

### Dependencies

540 declares: after 190 (region reference data), 210 (topics), 260 (collection
runs), 520 (sectors).

- 190, 210 and 260 are in the ledger with checksums equal to their committed
  files.
- 520 is applied (the `sector` table exists) but is **not** in the ledger. 540
  has no foreign key to it, only `sector_codes text[]`.
- Recording 540 before 520 leaves a known gap. 520 should be reconciled
  separately, together with 170, 510 and 530.
- 550-580 each depend only on 540 and on each other, in order.

## Checksums and line endings

| id | file | committed | sha256 (committed bytes = working bytes) |
|---|---|---|---|
| 540 | agents/sql/540_v2_actor_update_subscription.sql | yes | `8a6f1dbec788694c2eca45b9e5f10b363da6a74197e40a60eaf8ac48805d6907` |
| 550 | agents/sql/550_v2_discovery_requests.sql | yes | `56dc21550fd74771915b84794a29068081f5eff367810409ad2cf95885d0e46d` |
| 560 | agents/sql/560_v2_agent_auto_verification.sql | yes | `d52c855edf804b319cf77ca4f5919d76462d0436e4a884455467e8bd0e566c4a` |
| 570 | agents/sql/570_v2_actor_update_requests.sql | yes | `ee0f192baf82ca0649fe2edc4516f41a518f4deaa6a8696b3505250ffeb01190` |
| 580 | agents/sql/580_v2_event_people_requests.sql | **no** | `63d7419e7b9511e12e7e339745bff3903c72f3ff13b55bd078aadb3f467b5f11` |

**The convention.** The ledger's `source_sha256` is the SHA-256 of the file
bytes (`scripts/functional_v2_schema.py` `_checksum`). All 45 existing rows
equal their committed (LF) bytes, and now also their working files.

**The line-ending fix (no checksum drift).**

- `.gitattributes` already pins `*.sql text eol=lf` (commit 2a8b0ad), and every
  committed `.sql` blob is LF.
- This Windows checkout still held five SQL files with CRLF, written before
  that rule existed:
  - 520, 530 and 550
  - the rollbacks of 530 and 550
- They were re-checked out from the index. Their content is unchanged, and
  their working-file checksums now equal the committed ones, including 550 =
  `56dc21...`.
- The committed blobs did not change, so no ledger row and no checksum drifts.

**580 is not committed.** Committing it stores its bytes unchanged:
`git hash-object` with and without filters gives the same blob, `b9e0f5b4...`.
So its checksum after commit is the one above. `run_ledger_step.py` refuses to
touch Supabase until it is committed.

`tests/db/test_architecture_v2_schema.py` lists the migration files. Its list
now includes 580 (580 and 31 rollbacks), so it must be committed with 580.

## `applied_at`

The five rows take the column default `now()`. That is the start time of the
reconciliation transaction, identical for all five rows.

- **It is the time of this reconciliation, not the time the schema changes
  were originally applied.** That time is not recorded anywhere.
- A rerun inserts nothing and keeps the first reconciliation's `applied_at`
  (rehearsed).
- The reconciliation prints the value. The rollback requires it, so it removes
  exactly those rows and nothing recorded at another time.

## Files

| File | Writes? | What it does |
|---|---|---|
| `run_ledger_step.py` | only with `--execute` | Runs each step with psql. Refuses unless committed bytes, working bytes and script checksums agree. Dry run by default: the session is read-only, so `reconcile`/`rollback` evaluate every precondition and are then refused by the database. Writing to Supabase also needs `--confirm reconcile-ledger-540-580`. Logs every run to `runs/`. Never prints the connection string. |
| `preflight_540_580.sql` | no | Ten GO/NO-GO checks, listed below. Exits non-zero on NO-GO. |
| `export_ledger.sql` | no | CSV backup of the whole ledger into `runs/`. |
| `reconcile_ledger_540_580.sql` | 5 inserts | One transaction. Preconditions: the 70-object end state, dependencies 190/210/260 recorded, and no 540-580 row with another checksum. Then `INSERT ... ON CONFLICT DO NOTHING`. Postconditions: 5 exact rows and one shared `applied_at`. No DDL, no table lock. |
| `verify_540_580.sql` | no | Ledger = 5 exact rows, one reconciliation time, schema still the end state. Exits non-zero on failure. |
| `rollback_reconcile_ledger_540_580.sql` | ≤5 deletes | Deletes the 5 rows only if id, checksum and `applied_at` all match and all 5 are present. A no-op if none exist. Refuses anything else. |
| `restore_ledger_from_backup.sql` | deletes | Last resort. Makes the ledger equal the export CSV, and refuses if any backed-up row changed. |
| `evidence/generate_expected_state.py` | no | Generates the 70-object expected state from a local database built from the committed files, and injects it into the scripts. |
| `evidence/catalog_fingerprint.py` | no | Whole-schema fingerprint: tables and row-security flags, columns, constraints, indexes, triggers, function bodies, comments, policies. |

The preflight's ten checks:

1. The database is the primary, not a read replica.
2. The ledger table has the expected shape.
3. The ledger has no triggers.
4. The role can insert and delete on the ledger, and row security permits it.
5. The ledger baseline is unchanged: 45 rows, last 500.
6. No 540-580 ledger row exists yet.
7. 190, 210 and 260 are recorded.
8. The objects 540 references exist.
9. The schema equals the 540-580 end state: 70 objects (30 columns, 24
   constraints, 9 comments, 5 indexes, 1 trigger, 1 function).
10. No other session holds a lock on the ledger.

**Why no table lock.** Postgres refuses `LOCK TABLE ... SHARE ROW EXCLUSIVE`
in a read-only transaction, so a lock would stop the dry run. It is also not
needed: a concurrent writer of a 540-580 row collides on the primary key,
`ON CONFLICT` skips it, and the postcondition then aborts the whole
transaction.

## Rehearsal: 33/33 passed (`evidence/rehearsal_2026-10-26.txt`)

The rehearsal used fresh copies of Supabase (`ghus_v2_supabase_rehearsal540_test`,
and `ghus_v2_supabase_neg540_test` rebuilt for each negative case). Every step
ran through `run_ledger_step.py`, exactly as in production. The logs are in
`evidence/rehearsal_runs/`.

**Normal path**

| Step | Result |
|---|---|
| preflight | GO, 10/10 |
| verify before reconciling | FAIL, as expected |
| export | 45 rows + header |
| reconcile, dry run | preconditions pass, write refused, 45 rows |
| reconcile | 45 -> 50, all five share one `applied_at` |
| reconcile again | 50 rows, rows and `applied_at` byte-identical |
| verify | PASS |
| schema fingerprint before vs after | no differences |
| preflight after reconciling | NO-GO, as expected (rows present) |

**Rollback and restore**

| Step | Result |
|---|---|
| rollback, dry run | checks pass, delete refused, 50 rows |
| rollback with a wrong `applied_at` | refused, 50 rows |
| rollback | 50 -> 45, ledger identical to before including `applied_at` |
| rollback again | nothing to roll back, 45 rows |
| reconcile + rollback once more | 50 -> 45 |
| rollback with a foreign 570 row present | refused, nothing deleted |
| last-resort restore from the CSV | ledger equals the backup |
| restore after a backed-up row changed | refused |

**Refusals.** Each of these was refused with nothing written:

- checksum conflict on 560
- checksum conflict on 540
- a correct row already recorded at another time
- 540 trigger dropped
- 540 index dropped
- 540 function body changed
- 580 rolled back (columns missing)
- 560 rolled back (older constraint)
- an extra constraint
- a changed comment
- dependency 260 not recorded

**End state.** The rehearsal database ended identical to the Supabase copy in
both ledger and schema.

## Read-only production preflight, run 2026-10-26 12:53 UTC

The preflight ran as `postgres` on PostgreSQL 17.6: **GO, 10/10**
(`evidence/supabase_preflight_2026-10-26.log`). The schema fingerprint equals
the one taken when the rehearsal database was built
(`evidence/supabase_catalog_before_2026-10-26.json`).

## Production execution (only after the checklist below is complete)

From the backend repository root, in Git Bash:

```bash
P=migrations/proposed/ledger_reconcile_540_580; PY=.venv/Scripts/python.exe
$PY $P/run_ledger_step.py preflight                                   # read-only; expect PREFLIGHT RESULT: GO
$PY $P/run_ledger_step.py fingerprint --out $P/runs/fingerprint_before.json \
    --compare $P/evidence/supabase_catalog_before_2026-10-26.json     # read-only; expect schema differences: none
$PY $P/run_ledger_step.py export                                      # read-only; ledger backup CSV in runs/
$PY $P/run_ledger_step.py reconcile                                   # dry run; expect DRY RUN OK
$PY $P/run_ledger_step.py reconcile --execute --confirm reconcile-ledger-540-580   # THE ONLY WRITE: 5 rows
$PY $P/run_ledger_step.py verify                                      # read-only; expect VERIFY RESULT: PASS
$PY $P/run_ledger_step.py fingerprint --compare $P/runs/fingerprint_before.json    # read-only; expect none
```

Stop at the first step that does not give the expected result.

**Rollback**, if verify fails or the decision is reversed. Use the
`applied_at` that `reconcile` printed:

```bash
$PY $P/run_ledger_step.py rollback --reconciled-at "<applied_at>"     # dry run
$PY $P/run_ledger_step.py rollback --reconciled-at "<applied_at>" --execute --confirm reconcile-ledger-540-580
$PY $P/run_ledger_step.py verify                                      # now expect FAIL (rows gone)
$PY $P/run_ledger_step.py preflight                                   # expect GO again (back to baseline)
```

**Last resort**, if the rollback refuses and a person has confirmed why:

```bash
$PY $P/run_ledger_step.py restore --backup $P/runs/ledger_backup_<stamp>.csv --execute --confirm reconcile-ledger-540-580
```

The migrations' own rollback scripts (`agents/sql/rollback/540..580`) are
**not** part of this change and must not be used. They would drop tables and
columns that live requests use.

## Backup requirements

1. The Supabase project has a backup or point-in-time recovery point taken
   after 2026-10-26 12:53 UTC. Check under Dashboard -> Database -> Backups and
   note its time. The change is five inserts, so this is a safeguard, not the
   rollback path.
2. The `export` step's CSV of the full ledger, taken immediately before the
   write, is kept with the run logs.
3. The `fingerprint_before.json` from the same session.

## Schema-owner approval checklist

| # | Item | Who |
|---|---|---|
| 1 | Scope accepted: five ledger rows (540-580), no DDL, no other data | schema owner |
| 2 | `applied_at` = reconciliation time, not the historical apply time, accepted | schema owner |
| 3 | 540's deviations accepted without repair: row security by `ensure_rls`; CRLF function body | schema owner |
| 4 | 540 recorded while 520 remains unrecorded accepted; 170/510/520/530 to be reconciled separately | schema owner |
| 5 | 580, its rollback and the test inventory update committed; the runner's file gate passes | platform owner |
| 6 | Backup/PITR point confirmed and its time noted | platform owner |
| 7 | Change window: no migration, deploy or agent job writing the ledger at the same time | platform owner |
| 8 | Rehearsal evidence (`evidence/`) reviewed | schema owner |
| 9 | Operator named; the run logs in `runs/` filed with the release notes | platform owner |

## Go / no-go (2026-10-26)

| Gate | State |
|---|---|
| Schema is the 540-580 end state on Supabase | **GO** (70/70 objects; 2 accepted 540 deviations) |
| Ledger baseline 45 rows, no 540-580 rows, deps recorded | **GO** |
| Production preflight | **GO** (10/10) |
| Rehearsal (normal path, idempotency, conflicts, exact rollback, restore) | **GO** (33/33) |
| Checksums 540-570 committed = working = scripts | **GO** |
| Line endings | **GO** (fixed, no drift) |
| 580 committed | **NO-GO**: uncommitted; the runner refuses Supabase |
| Schema-owner approval (items 1-4, 8) | **pending** |
| Backup point confirmed | **pending** |

**Overall: NO-GO until 580 is committed, the schema owner approves, and the
backup point is confirmed. GO after those three, with nothing else
outstanding.** Re-run the preflight immediately before executing. If anything
changed since 2026-10-26 12:53 UTC, it will say so.

## Not included

- 170, 510, 520 and 530 are applied but unrecorded. Each needs the same
  verification before it is recorded.
- The CRLF bytes in five function bodies on Supabase are cosmetic. Rewriting
  them would be DDL and is not proposed.
