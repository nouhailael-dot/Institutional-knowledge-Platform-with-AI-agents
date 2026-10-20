# GHUS Platform — Phase 4 Master Roadmap

**Consolidates** the Phase 4 plan in `GHUS_Platform_Status_Report.md`, the ML
integration plan in `GHUS_Platform_Phase_4_ML_Handoff.md`, and the enrichment
code shipped this cycle. This is the single authoritative sequence; where the
two planning docs differ on ordering, this reconciles them.

---

## 1. The one pattern under everything

Every ML/AI workstream in Phase 4 has the same shape: **cheap-and-fast generates
candidates, expensive-and-smart adjudicates the hard ones, a human review queue
is the final backstop.** TF-IDF / embeddings / a regressor handle volume; Claude
handles the ambiguous band or the final generation; the Streamlit review queue
catches what slips through. Entity resolution, event scoring, RAG, and the Claude
extractors are all instances of this. Build each as three tiers: candidate → Claude → review.

## 2. Master sequence (reconciled)

1. **Entity resolution** — priority 1, _build now_ (handoff weeks 1–5). Almost entirely key-independent.
2. **Claude enrichment pipeline** (handoff weeks 5–9) — _partially built this cycle._ Extractor #1 (re-type the 493 "other" actors) and #2 (researchers → `person`) are done; #3 (funding → `hub_funding`) and #4 (new orgs → `actor`) remain. The runs are gated on the API key.
3. **Event score prediction** (weeks 9–12) — blocked: needs v9 ingested + ≥50 scored events (≈13 today).
4. **Strategic-document RAG** — blocked: needs ≥2 strategy docs in `strategic_document`.
5. **Phase 5** (query agent, UI, precomputed answer layer) — RAG feeds the query agent.

## 3. Status of every workstream

| Workstream                  | What it does                                   | Status                       | Gated on                                       | Next action                         |
| --------------------------- | ---------------------------------------------- | ---------------------------- | ---------------------------------------------- | ----------------------------------- |
| Entity resolution           | Dedup ~900 actors via similarity + Claude band | Not started — **priority 1** | nothing (build) / key only for the Claude band | `actor_merge_log` table             |
| `actor_merge_log` table     | Audit + reversibility for merges               | Not started                  | nothing                                        | model + migration                   |
| ER gold dataset             | 300 hand-labeled pairs                         | Not started                  | manual labeling                                | stratified pair sampler             |
| Enrichment #1 (actor-type)  | Re-type the 493 "other"                        | **Built**                    | API key (to run)                               | run when key arrives                |
| Enrichment #2 (researchers) | `person` + `actor_person`                      | **Built**                    | API key (to run)                               | run when key arrives                |
| Enrichment #3 (funding)     | `hub_funding` links                            | Not built                    | API key (to run)                               | build (no key needed to build)      |
| Enrichment #4 (new orgs)    | New `actor` rows from narratives               | Not built                    | **entity resolution** + key                    | build _after_ ER integration exists |
| Review-queue writes         | Promote/reject `needs_review`                  | **Built**                    | nothing                                        | use on the existing backlog         |
| Event scoring               | Predict 6 criteria                             | Outlined only                | v9 + ≥50 scored events                         | wait                                |
| RAG                         | Retrieve entities for strategy docs            | Outlined only                | ≥2 strategy docs                               | wait                                |

## 4. Two gating rules that decide ordering

**The API key gates runs, not builds.** Essentially all of Phase 4 can be built
without the Claude key — every ML model, every eval, the merge log, the labeled
dataset, the TF-IDF/SBERT/hybrid comparison, and the enrichment code (already
written). The key is needed only to _execute_ the Claude tiers: the enrichment
extraction runs and the entity-resolution ambiguous-band verification. Auto-merge
and confirmed-different need no key. So while the key is pending, **entity
resolution is the ideal focus** — it is priority one and roughly 90% key-free.

**Entity resolution gates actor _creation_, not re-typing or linking.** The
handoff says enrichment runs after ER so new actors route through dedup. That is
true only for work that _creates_ actors — extractor #4 and any new ingestion.
Extractors #1 (re-types existing actors) and #2 (creates persons, links only to
existing actors) create no `actor` rows, so they are safe to run before ER and do
not reopen the duplicate problem. Practically: build ER now; run #1/#2 whenever
the key lands; do not build or run #4 until ER's integration step exists.

## 5. What to do next — the no-key critical path

This week, in order:

1. **Create the `actor_merge_log` table** — SQLAlchemy model + Alembic migration + apply. Smallest, purely additive first step; schema-first as the handoff insists.
2. **Generate the 300 candidate pairs for labeling** — do _not_ sample randomly (810K pairs are almost all obvious non-dupes). Stratify by TF-IDF cosine into the handoff's three bands (~100 high / ~100 mid / ~100 low) so the labeling hour is productive. The sampler doubles as the week-2 TF-IDF vectorizer.
3. **Hand-label the 300 pairs** → `data/processed/entity_resolution_gold.csv`; reserve 30% as a held-out test set. This is the slow, unskippable core — models are worthless without it.
4. **TF-IDF baseline** (sklearn, light deps) — tune the threshold on train, report P/R/F1 + confusion on test.
5. **Sentence-BERT** (`all-MiniLM-L6-v2`; heavier deps, install only at this step) — same eval, compare to baseline.
6. **Hybrid** (TF-IDF retrieve + cross-encoder rerank) — compare.
7. **Integration** (`scripts/run_entity_resolution.py`): the auto-merge tier writes merges and logs them to `actor_merge_log`; the ambiguous band is queued for Claude (needs key); confirmed-different is ignored.

Steps 1–4 need no API key; 5–6 run local models, also no key. Only step 7's middle tier uses the key.

## 6. Decisions to lock before merging anything

Three open questions from the handoff actually block step 7 and should be settled
once the gold dataset is in hand (its label distribution will inform the numbers):
how aggressive auto-merge should be (cost of a false merge vs a lingering
duplicate), whether merge reversal is built in week 5 or deferred (the log
captures intent either way), and whether there is a human-final-say tier above
Claude for the hardest pairs.
