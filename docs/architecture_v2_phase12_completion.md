# Architecture V2 Phase 12 completion report (steps 1–7)

Date: 2026-10-06. Production untouched: no Supabase connection, DDL or write.
All work ran on local PostgreSQL 17.5 (127.0.0.1:55432, `*_test` databases) built
from `ghus_production_full_20260928T170256Z.dump` (SHA-256 verified).
Release package: `migrations/release/architecture_v2_cutover/`.

## 1. Full-dump source (step 1)

See `docs/architecture_v2_phase12_full_dump_rebuild.md`. The 6 Oct "958
unrecoverable provenance" was an artifact of the CSV-built copy: the full dump has
1,586 sources (all 958 actor `source_id`s resolve), 952 profiles, 5,712 capability
facts and 42 hierarchy rows.

## 2. The 214 unmappable categories (step 2)

- **Classifier bug fixed** (`agents/common/actor_classification.py`): the hard
  rules treated placeholder answers ("UNKNOWN", "Established commercial company")
  as national-lab / startup evidence, turning BASF into a national laboratory.
  Placeholders are now ignored and the schema asks for null. Regression test added.
- Proposals use existing evidence only (name, website, legacy source URL, text
  fields minus template sentences and minus hub boilerplate shared by ≥3 actors);
  no web fetch. Model claude-haiku-4-5, cost ≈ $0.64 per run.
- Result: **58 real organizations** with a proposed category (6 high, 34 medium,
  rest low confidence) and **156 true aggregates** (buckets such as "Water
  Treatment Companies"). `docs/evidence/phase12_category_proposals.csv`.
- Migration **484** (generated from the CSV, checksum in its header) sets the
  proposed category with `category_needs_review=true` and enriches the existing
  `category_doubt` review; aggregates keep a NULL category and carry disposition
  options. I chose to populate the category before confirmation because every
  value stays flagged for review and the evidence is attached; 495 is not weakened.
- **Review can now resolve category reviews** (there was no writer at all):
  `decisions.record_category_review_decision`, admission `confirm_category`
  (batch, all-or-nothing, idempotent), and a bulk "Category reviews" panel in the
  shared Review page. Aggregates are refused there; they need a GHUS disposition.
- Aggregate list for GHUS: `docs/evidence/phase12_aggregate_disposition_proposal.csv`
  (146 of 156 are hub members, holding 180 of 821 memberships).

## 3. Data-loss audit passes (step 3)

- **480 bug fixed:** `prior_status` copied the empty V2 `status`; it now keeps the
  legacy `verification_status` — 834 ai_inferred / 97 phase_1 / 27 needs_review /
  7 null, exactly.
- **482 legacy preservation:** every value 500 removes gets a destination row or
  an explicit `legacy_migration_record` (append-only):
  - state: 858/912 normalized to state + region; 54 non-US or multi-state values
    stay NULL with the raw value recorded;
  - city coordinates: 811/906 (89.5%) from the Census gazetteer; ambiguous or
    unknown → `geocode_failed` review (154), never guessed;
  - narrative fields + description → 7,680 topic-null `legacy_baseline` facts on
    the actor's real legacy source and its real `retrieved_at` (no invented date);
    55 values of the 7 unsourced actors kept in the audit record;
  - profiles → 4,749 facts (10 unsourced values in the audit record);
  - capability facts are exact copies of the scalar fields: 5,670 linked to the
    identical fact, 42 unsourced kept in the audit record;
  - 42 hierarchy rows have no source → `relationship_review`, no invented edge.
- The SQL normalization is tested for exact parity with `geography.py` on all
  26.5k real city/state/place values.
- The audit now counts real destination rows (a record only counts if its fact or
  review exists): **21/21 pass**. It also exists as the database function
  `ghus_pre_cutover_data_loss_audit()` (489), which 500 re-runs before dropping.

## 4. Topics and hubs (step 4)

- The `topic` table is empty and no controlled list exists anywhere. Proposal
  (`docs/evidence/phase12_topic_proposal.csv`): 8 topics 1:1 from legacy sectors
  (CROSS, DIASPORA held for GHUS), 48 hub topics from their single sector tag,
  density_center_v1 centers for 48 hubs; 90 memberships fall outside 200 miles
  (informational, nothing removed). "Mining Hubs" is an empty row with no basis.
- **486** (generated, requires `topic_approval.json`) applies it; proved on a copy.
- Recommendation: hub topic/center **required** (405); actor topic **nullable**
  at cutover — `actor_topic` needs a source and membership is not topic evidence,
  so memberships carry the topic in `hub_actor.topic_id` instead.
- **405 supersedes 400:** 400 needs a source and an outside-radius value for every
  legacy membership; production has neither for some rows. 405 allows NULL only
  for `legacy_membership_preserved` / unknown distance.

## 5. Clean schema rehearsal (step 5)

`scripts/phase12_cutover_rehearsal.py` restores the dump fresh and runs every
stage through the release tool: baseline → expand → gazetteer → backfill →
validate → audit (Python + SQL, pass) → topic → TEST-ONLY decision stand-ins →
contract → TEST-ONLY attestation → **500 applied** → every SQL stage re-run: all
42 skipped by checksum. Row counts 965 / 49 / 821 / 356 at every stage.
Evidence: `docs/evidence/phase12_cutover_rehearsal_2026-10-06.json`.

Bugs found and fixed in 500: it dropped `actor_type` while the transitional sync
trigger depended on it; it dropped `record_verification`, which person/event
verification still writes (now kept with an actor-excluding CHECK).

## 6. Both applications on the clean schema (step 6)

- Backend suite on the post-500 copy: **507 passed, 0 failed, 0 skipped**, plus 5
  release-gate tests. The two schema-gate tests now pass legitimately; the ORM
  matches the final schema.
- Readers/writers switched to final or schema-neutral names: `promote`
  (status/city/alt_names), `resolve_route`, query generation, triage, person
  pages, hub detection. 488 `actor_read` gives a stable read surface.
- Shared repo: Browse, Ask documents (with status labels), SQL router (via
  `actor_read`), gap enrichment and Review read schema-neutrally. Python 145
  passed / 1 skipped; Node 24 passed; live smoke 8 passed on **both** a pre-500
  and a post-500 copy (so apps can switch before 500 and survive a rollback).
- Per surface: Review PASS, Browse PASS, Ask documents PASS, SQL Ask PASS,
  Build the Map PASS (untouched; reads no canonical tables — see
  `agent3_compatibility_note.md`), discovery dry run / Light Pull / Deep Pull
  gate + allowed path / hub assignment / fact current+history PASS (backend
  integration tests phases 3–11 on the clean schema).
- **Not done:** `search_doc` embedding rebuild — the local cluster has no
  pgvector (installing it needs your permission) and it needs the Voyage key.
  It is runbook step 16 on Supabase, which has pgvector.

## 7. Release package (step 7)

`migrations/release/architecture_v2_cutover/` with `release_manifest.json`
(43 steps + checksums), runbook, pre-flight, post-apply checks, rollback per
stage, schema-owner approval request, GHUS decisions, Agent 3 note, approval
templates; colleague contract updated. `.gitattributes` now pins `*.sql` to LF
so checksums are stable across machines.

## Checkpoints

| # | Status |
|---|---|
| 1 data-loss audit | PASS |
| 2 backfill on a production copy | PASS |
| 3 migration 500 locally | PASS (TEST-ONLY decision stand-ins) |
| 4 backend suite on clean schema | PASS |
| 5 shared platform on clean schema | PASS, except `search_doc` rebuild (not run locally) |
| 7 idempotency | PASS |
| 8 no blocking issue | BLOCKED on GHUS decisions only (`ghus_decisions.md`) |
