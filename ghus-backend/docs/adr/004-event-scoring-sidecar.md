# ADR-004: Event scoring as a sidecar table

**Date:** 2026-06-08
**Status:** Accepted
**Author:** Ismail Sabbar

## Context

UM6P Dashboard v8 introduces a structured 6-criterion scoring framework for strategic events (longevity, recognition, audience scale, speakers profile, organizer credibility, geographic reach), plus a composite total and Tier 1/2/3 classification. This evaluative data is distinct from the event's own attributes (name, date, location).

Most events in the database (the 113 UN events from UN_Mapping\_\_FV.xlsx) have no scoring. Only the 13 events in v8 Event Mapping carry scoring. Adding the scoring columns directly to `event` would mean 113+ NULL rows in 18+ columns.

## Decision

Introduce a new `event_scoring` table as a 1:1 sidecar linked to `event`. Same pattern as `partnership_profile` for `actor` (ADR-007).

The scoring framework is captured per-event with the original criterion descriptions preserved alongside the numeric scores. The `scoring_methodology_version` field is currently 'v8' and is reserved for future rubric changes — different methodologies can coexist without schema changes.

The seven UM6P Priority Sectors columns from v8 are not stored on the scoring table. Instead, only the "Yes" sector tags become rows in the existing `event_sector` junction. "No" tags are not stored (absence is the signal).

## Consequences

- The 113 existing UN events have no scoring rows. That's correct — they weren't scored.
- Future scoring spreadsheets with different rubrics (v9, v10) can populate the same table, with `scoring_methodology_version` distinguishing them.
- Queries like "show me Tier 1 events relevant to Energy" become single JOINs across event, event_scoring, and event_sector.
- The "Tier" field is stored both normalized (`tier_1` / `tier_2` / `tier_3`) and raw (`🟢 Tier 1 — High-Influence Events`) so the platform can display either form.

## Related

- ADR-003: Partnership profile sidecar pattern
- `docs/data-dictionary.md` — UM6P Dashboard v8 entry
