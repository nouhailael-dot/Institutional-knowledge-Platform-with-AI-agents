# ADR-003: Partnership profile as a sidecar table for institutional actors

**Date:** 2026-05-21
**Status:** Accepted
**Author:** Ismail Sabbar

## Context

The UN Mapping spreadsheet introduced a new category of actor — intergovernmental organizations and UN agencies — with 13 partnership-evaluation fields (budget overview, university partnerships, funding delivery, Africa-specific mandate, key entry points, etc.) that don't apply to technical actors like university labs or startups.

Future spreadsheets are expected to follow the same pattern: federal agencies, philanthropic foundations, multilateral development banks. All are *institutional partners* being evaluated strategically, distinct from *technical actors* being evaluated against a specific challenge.

## Decision

Introduce two new tables:

1. **`partnership_profile`** — A sidecar table linked 1:1 with `actor`, holding the partnership-evaluation fields. Populated for institutional partners; left absent for technical actors.

2. **`organization_hierarchy`** — A bridge table for nested parent-child relationships between actors (UN General Assembly → Funds and Programmes → UNDP). Reusable for any hierarchical organization mapping.

Plus a small extension to the existing `event` table: a nullable `host_actor_id` foreign key to link events to the organization that hosts them.

Six new `actor_type` enum values were added: `un_agency`, `un_programme`, `un_committee`, `un_secretariat`, `multilateral_development_bank`, `intergovernmental_organization`.

## Alternatives considered

**Alternative A — Add the 13 columns directly to `actor`.** Rejected because the columns would be NULL for the ~150 NutriCrops technical actors and ~500+ actors expected from future challenge spreadsheets. A table where 80% of values are NULL signals that two different concepts have been conflated.

**Alternative B — Subclass actor into multiple inherited tables (institutional_actor, technical_actor).** Rejected because SQLAlchemy single-table inheritance reintroduces the NULL-column problem, and concrete-table inheritance creates query complexity disproportionate to the benefit at this scale.

**Alternative C — Store the extra fields as JSON in a single column on `actor`.** Rejected because the fields are queryable (e.g., "show institutional partners that fund universities"), and JSON makes those queries slower and harder to maintain.

## Consequences

- The schema now distinguishes cleanly between *what an organization is* (`actor`) and *how it is evaluated as a partner* (`partnership_profile`). Different lifecycle, different update frequency.
- Future spreadsheets that map institutional partners (foundations, federal agencies) reuse `partnership_profile` without further schema changes.
- ETL translators must know whether to populate `partnership_profile`. The decision rule: any actor whose source spreadsheet has institutional partner columns (budget overview, university partnerships, etc.) gets a profile row.
- The `organization_hierarchy` table is now available for any hierarchical structure, not only UN — e.g., USDA → ARS → specific lab.

## Related

- ADR-002: Hub as first-class entity
- ADR-006: Data quality findings
- `docs/data-dictionary.md` — UN Mapping spreadsheet entry