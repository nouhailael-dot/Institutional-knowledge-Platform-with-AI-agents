# Phase 4 — AI Extraction Layer

**Goal:** turn the narrative text preserved in Phase 2 into structured rows,
without ever silently trusting the model. Every AI-produced fact is a *candidate*
until a human promotes it.

## Non-negotiable contract for every extractor

1. Each run creates one `Source` row with `source_type='ai_inference'` and
   `trust_tier='low'`. Every row it writes points back to that `source_id`.
2. Everything lands as `verification_status='needs_review'` with the model's
   `confidence` stored. Nothing is born `verified`.
3. Output is validated and clamped in code before it touches the DB — a bad
   model reply can never corrupt a row.
4. A per-row audit CSV goes to `data/interim/`. One transaction; roll back on
   dry-run. Loud failure: log the row, continue, exit non-zero if any failed.
5. **Eval gate:** an extractor is not run on the full set until its golden eval
   clears the bar (>= 85% overall, no class at 0%).

## Order of extractors (lowest risk first)

| # | Extractor | Reads | Writes | Risk | Status |
|---|-----------|-------|--------|------|--------|
| 1 | Actor-type classification | `actor.name` + `description` of the ~493 'other' actors | updates `actor.actor_type` (needs_review) | low — no new rows | **built** |
| 2 | Researcher extraction | `hub.talent_narrative` | new `person` + `actor_person` rows | medium — entity resolution | next |
| 3 | Funding links | `hub.funding_summary` | new `hub_funding` rows | medium | after #2 |
| 4 | Implicit corporate orgs | `hub.*_narrative` | new `actor` rows + types | high — dedup against ~900 actors | last |

Each step reuses the harness in `src/enrichment/` — `claude_client.py` for the
call, one module per extractor, one runner per extractor in `scripts/`.

## Model strategy

- Classification (#1): Haiku — high volume, cheap, the task is simple.
- Entity extraction (#2–#4): Sonnet — richer reasoning over messy narrative text.
- Always override per call; never hardcode in the extractor logic.

## Human-in-the-loop

The Streamlit Review queue page lists `needs_review` rows today (read-only).
The immediate follow-on to extractor #1 is wiring its promote-to-verified
write path: a single transactional UPDATE setting `verification_status='verified'`
on confirmed rows. That is the only place the admin app should ever write.

## Files

```
src/enrichment/
├── claude_client.py              # call + JSON parse + retry (reusable)
└── extractors/
    └── actor_type.py             # extractor #1
scripts/
└── run_actor_type_enrichment.py  # runner #1 (dry-run by default)
evals/
├── golden_dataset.jsonl          # hand-labelled, reconcile labels to DB vocab
└── run_eval.py                   # the gate
```