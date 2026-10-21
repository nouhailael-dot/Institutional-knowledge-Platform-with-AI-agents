# GHUS integration report — 2026-10-21

## Git state and scope

Workspace: `C:\Users\Ismail\Projects\GHUS-Complete-Integration`.
Branch: `integration/ghus-complete`.

The session began with an unfinished merge of `claude/phase12-shared-review`
(`edba0fb4474d0dfdee782f4b1466b21f110d229d`) into `ece3aae`.
The common ancestor is `8c6ce39`. Five Phase 12 commits were incoming.
The four cleanly staged files were the expected incoming changes, not unrelated
user edits: `src/embed.py`, `src/review/store.py`, `tests/test_review.py`, and
`tests/test_v2_cutover_smoke.py`. Ten files were unmerged.

Fetching origin confirmed that `origin/main` remains `ece3aae` and
`origin/feature/review-redesign` remains `ed41cc6`; both are already included.
`origin/ghus-backend` advanced from `62e4008` to `9640da0`.
The existing merge was resolved in place, without resetting or repeating it.
The merge commit containing this report has parents `ece3aae` and `edba0fb`.
No branch was pushed, no PR was opened or merged, and no deployment occurred.

Both canonical Projects checkout paths were verified. The Documents/GHUS
checkout is not the integration repository and was not modified.

## Conflict resolutions

| File | Resolution |
| --- | --- |
| `backend/app.py` | Retained all Discovery, actor-update and scheduled-request routes; added Phase 12 category and review-item decision endpoints. Unique-route and startup tests pass. |
| `frontend/review.css` | Kept the redesigned responsive layout, queue rail and sticky footer; added only the bulk-category styles. |
| `frontend/review.js` | Kept the redesigned component, taxonomy controls, grouping and existing workflows. Added bulk category confirmation and dedicated location/legacy-link forms. Modern sourced relationship proposals retain their existing relationship type and two-way workflow. Saved category edits refresh the bulk list. |
| `src/assemble.py` | Kept the `actor_read` view, full state names, aliases and fact-backed narrative fields. Added status labels and explicit rejected-actor filtering; preserved the `city` result key consumed by assembly. |
| `src/browse.py` | Kept display categories, state names, safe TRL parsing and the existing API shape, including People browsing. Added verification labels and rejection filtering; V2 status takes precedence. |
| `src/enrich/gaps.py` | Preserved its deliberate removal in `a298744`: the legacy scaffold was unused and superseded by backend enrichment. |
| `src/enrich/run.py` | Same documented retirement; did not resurrect an incomplete second enrichment implementation. Original code remains in Git history. |
| `src/review/postgres_source.py` | Retained sector fields, fact comparisons, hub and relationship proposal data, actor-update grouping and the full review-kind list. Added rejected-actor exclusion and legacy related-actor names. |
| `src/router.py` | Kept the current detailed SQL Ask schema, mandatory `actor_read` and merged-actor filtering. Added the V2 status vocabulary. |
| `tests/test_review_ui.mjs` | Retained the redesigned UI suite and added Phase 12 tests without duplicate imports. Added a regression test for modern relationship proposals. |

The incoming Review store methods and API tests remain included. Search-index
pruning from `src/embed.py` remains included, with guards that refuse empty
assembly or incomplete embeddings before opening the writer. Regression tests
verify the guards and successful replacement/pruning with mocked connections.

## Functionality and validation

Offline tests cover Review validation, decision persistence and failure handling;
Discovery requests; Actor, Event and Person workflows; Build Map planning,
selection, budgets and reopening; taxonomy and relationships; Browse and Ask
compatibility; FastAPI startup and route coexistence; and frontend rendering.
Canonical mutations still delegate to the approved backend workflows.
No third canonical writer or duplicate application root was introduced.

Run from the integration root, using the existing platform virtual environment:

```powershell
& 'C:\Users\Ismail\Projects\Institutional-knowledge-Platform\.venv\Scripts\python.exe' scripts/test_offline.py tests -q --tb=short
node --experimental-vm-modules --test --test-concurrency=1 --test-reporter=dot tests/*.mjs
```

Results: **415 Python tests passed, 9 skipped, 30 subtests passed; 105 frontend
tests passed.** The Python suite includes six new index/startup safety cases.
The frontend suite includes real component renders of location, legacy link,
modern link and category workflows. `node --check frontend/review.js` also passed.

Run from `ghus-backend`, using the existing backend virtual environment:

```powershell
& 'C:\Users\Ismail\Projects\GHUS-Platform\.venv\Scripts\python.exe' ../scripts/test_offline.py tests/agent -q --tb=short
```

Result: **826 passed, 2 skipped**, with two Python SQLite datetime-adapter
deprecation warnings. These are tests of the imported backend, not the dirty
separate checkout or the unintegrated `9640da0` changes.

The offline runner disables dotenv loading, removes service credentials and
sets `GHUS_AGENT_AUTO_VERIFY=0`. A placeholder key allows mocked AI clients to
initialize. Python socket connections are refused, except the private socketpair
needed by Windows event loops. No live discovery or embedding job was run.

Earlier unsuccessful validation attempts were test-environment issues:
- An empty Anthropic key prevented 25 existing mocked tests from initializing
  their client; a Node subprocess also failed under sandbox memory restrictions.
- The initial network guard blocked Windows' internal event-loop socketpair.
  The guard now allows that private pair, while refusing service connections.
- The Build Map UI test requires the documented `--experimental-vm-modules` flag.
All final suites above pass; no remaining integration regression was observed.

### Database limits

A bounded connection attempt to local `127.0.0.1:55432/ghus_v2_test` failed with
`OperationalError`. Therefore live SQL execution, production-equivalent schema
compatibility and database-backed admission transactions were **not verified**.
The nine platform skips are the opt-in V2 Review database test and eight
pre/post-cutover smoke tests. The two backend skips are not counted as passing coverage.
The smoke tests have historical fixture counts and need their matching snapshot.

Migrations 530, 540, 550 and 560 already exist in the imported backend and were
not applied or reapplied. Migration 570 is also present in that source tree;
its application status was not assumed. No database was modified.

## Backend comparison and integration plan

The `HEAD:ghus-backend` tree is byte-for-byte identical to the root tree at
`62e4008`. The common ancestor of the platform and current backend tip is also
`62e4008`. Main's import commit `d58c9d9` therefore already contains the full
backend through that point: agent discovery/enrichment, approved writers,
review admission, schema proposals, migrations and services. Phase 12's new UI
endpoints already have corresponding handlers in that imported version.
Do not merge the backend root into the platform root again.

`9640da0` changes 19 files (931 insertions, 35 deletions). This report prepares
the requested plan; it does **not** execute an additional backend merge.
All paths below are relative to `ghus-backend/` in the integration repository.

| Files | Recommended treatment |
| --- | --- |
| `agents/collection/actor_updates.py`, `tests/agent/test_actor_updates.py` | Incorporate together in a follow-up: category-based specific updates, gap-priority ordering, one-time history and inactive-topic annotations. Verify the current Discovery UI contract. |
| `agents/collection/light_pull_reader.py`, `tests/agent/test_light_pull_reader.py` | Incorporate together: bounded contact-page fallback, recent-activity checks and normalized locations. Preserve fetch caps and source evidence. |
| `agents/enrichment/decisions.py`, `agents/review/admission.py`, `tests/agent/test_agents_enrichment_phase4.py`, `tests/integration/test_functional_actor_updates.py` | Adapt together. The new `keep_both` location decision needs an explicit frontend/API/store action and local transaction, provenance, duplicate and stale-pointer checks. Preserve existing fact choices. The legacy-state parameter typing fix can be evaluated separately. |
| `alembic.ini` | Leave the integration configuration unchanged; do not import a machine-specific connection setting. Configure secrets outside Git. |
| `migrations/versions/c4e8a1d9f206_add_event_content_fields.py` | Leave unchanged: the difference is trailing whitespace, not a schema change. Do not run it. |
| `src/ML/entity_resolution/er_description_features.py` | Leave unchanged: only explanatory text differs; preserve frozen ER behavior. |
| `docs/adr/002-data-quality-findings.md`, `docs/adr/003-institutional-partner-sidecar.md`, `docs/evidence/hub_real_world_shortlist.md`, `docs/phase-4-plan.md` | Review restored historical material for relevance and consistency before incorporating. It is not needed to resolve Phase 12 runtime conflicts. |
| `evals/actor_type_gold.jsonl`, `evals/entity_extraction_gold.jsonl`, `evals/run_researcher_eval.py`, `scripts/smoke_test_actor_merge.py` | Review separately as restored evaluation/operational material. Do not execute the database-changing smoke script during integration. |

The separate checkout at `C:\Users\Ismail\Projects\GHUS-Platform` is at
`9640da0` but also has six modified tracked files and untracked work. These
include actor updates, Light Pull candidate/reader changes, source configuration,
site access, fact parts, evaluation scripts, tests and draft documentation.
They are not part of `origin/ghus-backend`. Their content was not copied,
staged, committed, tested as a completed stream or discarded. Reconcile them
with their owner before selecting a later committed backend source.

## Security and final checks

A local credential-pattern scan examined every changed-file snapshot in the
five incoming Phase 12 commits plus the final integration changes. No private
key, provider-token or non-placeholder database-credential pattern was found.
No environment files, caches, generated HTML, databases or archives are in the
outgoing change list. Test cache directories are ignored and remain local.
This is a local scan, not a claim that GitHub secret scanning was run.

Conflict-marker checks, staged whitespace checks and an empty unmerged index
are required before the merge commit. No force push, history rewrite, branch
removal, production access, production SQL, migration or deployment occurred.

## Before publication

1. Make the isolated database available with a known schema snapshot. Verify
   the existing migration ledger, without reapplying 530/540/550/560, then run
   the opt-in V2 smoke/admission tests against that local database only.
2. Review the backend plan above. Implement that follow-up only from reviewed
   commits, with the matching frontend contract and isolated database tests.
3. Refresh remote state and verify the final commit/diff:

```powershell
Set-Location 'C:\Users\Ismail\Projects\GHUS-Complete-Integration'
git fetch origin
git status --short --branch
git log -1 --format='%H %P %s'
git diff --check origin/main...HEAD
git diff --stat origin/main...HEAD
git log --oneline HEAD..origin/main
```

If the last command reports newer main commits, reconcile and retest them.
When ready, the owner can publish only the integration branch and open a PR:

```powershell
git push -u origin integration/ghus-complete
gh pr create --repo nouhailael-dot/Institutional-knowledge-Platform-with-AI-agents --base main --head integration/ghus-complete --title 'Integrate Phase 12 Review workflows with the shared GHUS platform' --body-file docs/GHUS_INTEGRATION_REPORT.md
```

If GitHub CLI is unavailable, open the PR in GitHub after pushing the branch.
Final publication and PR approval remain with the owner.
