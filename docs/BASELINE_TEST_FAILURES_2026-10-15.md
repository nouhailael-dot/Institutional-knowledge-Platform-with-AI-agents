# The three remaining backend test failures — causes and decisions

Run: `python -m pytest tests` in `C:\Users\Ismail\Projects\GHUS-Platform`,
2026-10-15, against `ghus_v2_final_schema_test` (V2 + 550 + 560).
**Result: 804 passed, 3 failed, 11 skipped.** The three are below. None is
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
