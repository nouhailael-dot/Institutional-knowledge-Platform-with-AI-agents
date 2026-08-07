"""Task 1A — deepen the existing map by filling missing factual fields.

The pipeline is deliberately split at the write boundary so the expensive,
hard part (finding evidence on the web) needs no database write access:

  gaps.py   stage 1  read-only: which live actors are missing which field
  agent.py  stage 2  per (actor, field): search the web -> a cited proposal
  run.py    driver:  loop the worklist -> write proposals.jsonl (DRY RUN)

Nothing here writes Postgres. Proposals land in a local JSONL file. Wiring the
sink to the `proposal` table is a later, gated step (needs write creds + RLS).
"""
