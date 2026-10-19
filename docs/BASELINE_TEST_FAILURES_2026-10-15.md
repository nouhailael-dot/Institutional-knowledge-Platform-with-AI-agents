# The remaining backend test failures — causes and decisions

Run: `python -m pytest tests` in `C:\Users\Ismail\Projects\GHUS-Platform`,
2026-10-15, against `ghus_v2_final_schema_test` (V2 + 550 + 560).
**Result: 808 passed, 5 failed, 11 skipped.** They are below. None is
caused by the discovery or Review work, and none indicates a defect in the
shipped code.

## 1. `test_anthropic_messages_payload_uses_only_pinned_sdk_params`

**Cause — the environment, not the code.** The test asserts
`anthropic.__version__ == "1.0.0"`, the version pinned in `requirements.txt`.
The interpreter in use has **0.116.0** installed:

```
AssertionError: assert '0.116.0' == '1.0.0'
```

The test exists so that the Messages payload is only ever built from parameters
the pinned SDK supports. It is doing its job: it reports that this machine does
not have the pinned version.

**Decision: fix the environment, not the test.** Whoever runs the suite should
install the pin before trusting SDK-related results:

```bash
python -m pip install "anthropic==1.0.0"
```

Do **not** change the assertion to accept the installed version: that would
silently allow payload parameters the pinned SDK does not support. If GHUS
decides to move to a newer SDK, that is a deliberate pin change — update
`requirements.txt`, this test, and re-check `build_messages_create_kwargs`
together.

## 2 and 3. `test_no_canonical_delete_path_exists_in_application_python` and `test_canonical_sql_writers_are_allowlisted`

**Cause — one uncommitted local file.** Both fail on the same thing:

```
assert ['scripts/smoke_test_actor_merge.py'] == []
```

In the repository, `scripts/smoke_test_actor_merge.py` is a **retired stub**
that refuses to run:

```python
"""Retired destructive smoke test for the pre-V2 actor merge implementation."""
if __name__ == "__main__":
    raise SystemExit("retired: V2 has no canonical DELETE path; use isolated ledger tests")
```

The working tree holds an **uncommitted 238-line restoration** of the old
pre-V2 version, which contains `DELETE FROM actor`, `DELETE FROM hub_actor`,
`UPDATE actor …` and other direct canonical writes. The two tests are the
guard rails for Architecture V2 rule 1 (only `promote.py` and `decisions.py`
write canonical data, and V2 has no DELETE path), so they correctly refuse it.

**Decision: the guard is right; the local file should go.** It is not part of
any committed work and it is not needed — the merge/revert behaviour it tested
is covered by the isolated ledger tests. Restore the committed stub when you
are ready:

```bash
git -C C:/Users/Ismail/Projects/GHUS-Platform checkout -- scripts/smoke_test_actor_merge.py
```

I have **not** run that myself: it discards an uncommitted local file, which is
yours to decide. Both tests pass as soon as it is restored (verified by
inspecting the committed version, which contains no canonical write).

If instead you want to keep that script, it must not live in `scripts/`: move
it to a test that runs only against an isolated `*_test` database, or the
allowlist test will keep failing — as designed.

## 4 and 5. `test_isolated_database_contains_v2_schema` and `test_orm_columns_match_isolated_v2_database`

**Cause — which database the suite was pointed at.** Both assert the schema
*after* the final-contract cutover: no `actor_v1_compat` /
`actor_profile_current` / `staged_record_agent3_compat` views, `alt_names` and
`city` renamed, the legacy columns dropped. That is migration **500**, which
is still in `migrations/proposed/deferred/` and fails closed until the
pre-cutover data-loss audit is attested:

```
IF NOT EXISTS (SELECT 1 FROM architecture_v2_cutover_attestation
               WHERE audit_name='pre_cutover_data_loss_audit' AND passed)
  THEN RAISE EXCEPTION 'pre_cutover_data_loss_audit has not passed';
```

Proof that it is the database and not the code: both tests **pass** against a
post-cutover database —

```bash
V2_TEST_DATABASE_URL=postgresql+psycopg://ghus_test@127.0.0.1:55432/ghus_v2_ui_test   python -m pytest tests/db/test_architecture_v2_schema.py -k "isolated_database_contains or orm_columns"
# 2 passed
```

and fail against `ghus_v2_final_schema_test` (V2 + 550 + 560, 500 deferred).

**Decision: leave both failing until 500 is applied.** They are the signal that
the cutover has not happened yet. No local database can satisfy both these and
the integration tests at once, because the integration tests need the seeded
request data that the post-cutover database does not carry — so state which
database a run used when quoting its numbers.
