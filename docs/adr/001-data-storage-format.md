# ADR 001: Raw data is preserved unmodified in data/raw/

## Status
Accepted

## Date
2026-05-10

## Context
The original spreadsheets are the canonical source of truth.

## Decision
- data/raw/ is read-only and never modified.
- Transformations produce outputs in data/interim/ or data/processed/.

## Consequences
- Re-running the pipeline always produces the same result.
- We can always recover the truth.
