# ADR-002: Data quality findings from source spreadsheets

**Date:** 2026-05-19
**Status:** Accepted
**Author:** Ismail Sabbar

## Context

Direct inspection of `Ecosystem_Mapping_The_Final_UpV.xlsx` and `NutriCrops_Ecosystem_Mapping_Template.xlsx` revealed several data quality issues that must be handled during ETL. This ADR documents them and the chosen handling strategies so future maintainers understand why the cleaning code looks the way it does.

## Findings and decisions

### 1. Eighth sector category present in source data

The Ecosystem Mapping sheet contains a "Sustainability Hubs" section with 5 entries (California, NYC, Colorado, Pacific Northwest, Midwest). This is not in the Phase 2 brief's seven priority domains (Agriculture, AI, Water, Energy, Mining, Specialty Chemicals, Health).

**Decision:** Add `SUSTAIN` as an eighth sector code in the controlled vocabulary. Pending confirmation from supervisor on whether to keep as a distinct sector or re-tag with underlying primary sector. Question raised in writing on 2026-05-19.

### 2. Section header rows must be skipped during ingestion

The Ecosystem Mapping sheet uses decorative section header rows that have a value only in column 1 (Actor Name) and no other columns filled. There are 8 of them: rows 2, 8, 15, 21, 27, 34, 45, 51.

**Decision:** Cleaning code must detect these rows and exclude them from migration. Detection rule: row has a non-null value in column 1 and null values in all other columns. Log skipped rows to `data/interim/skipped_rows.csv` with reason.

### 3. Known copy-paste errors in Actor Category field (Ecosystem Mapping)

Three rows have malformed Actor Category values:

- Row 25 (Massachusetts Energy): `Ecosystem Hub (Energy – Climate Innovation) need to be part` — analyst note appended to category.
- Row 30 (Nevada Mining & Critical Minerals): Actor Category contains `Midwest Energy & Industrial Transition Hub` — wrong hub's name pasted in.
- Row 31 (Utah Mining & Metallurgy Hub): Actor Category equals the actor's own name (duplicated).

Additionally, row 51 section header reads "Helath Hubs" (typo for "Health").

**Decision:** Hardcode these four corrections in the ETL as a known-issues mapping. Do not attempt programmatic detection — manual review is more reliable for fewer than 10 rows.

### 4. Empty columns 17 through 38 in Ecosystem Mapping

Profile reports showed 22 columns labeled "Unnamed: 16" through "Unnamed: 37". Direct inspection confirmed these contain no data — they are export padding.

**Decision:** Drop columns 17 through 38 unconditionally during cleaning. Real data exists only in columns 1 through 16.

### 5. NutriCrops Actor Category exceeds its controlled vocabulary

The `Lists` sheet in NutriCrops defines 4 official actor types (University Lab, National Research Lab, Startup / New Venture, Corporate R&D / Innovation Lab). The actual data contains 12 additional free-text values for federal entities, regulators, industrial partners, etc.

**Decision:** Create an explicit mapping from free-text Actor Category values to a 9-value enum (see `data/processed/actor_type_mapping.csv`). The enum is the source of truth for the `actor.actor_type` field; the original free-text value is preserved in a sidecar column `actor.actor_type_raw` for traceability.

### 6. Structural damage in NutriCrops Lifecycle and Maturity columns

The "Primary Role in Innovation Lifecycle" column contains 49 "Yes" and 43 "No" values that are clearly answers to a different question. The "Maturity Risk" column contains 51 "No" and 39 "Yes" with the same pattern. Only roughly 30 rows in Lifecycle and 24 rows in Maturity have legitimate values from the controlled vocabulary.

The likely cause is column insertion in the template that broke dropdown alignment after analysts had already filled cells.

**Decision:** During cleaning, any "Yes" or "No" value in these two columns is treated as corrupted and replaced with NULL. The corrupted row is logged to `data/interim/quarantine_lifecycle.csv` with the actor name, original value, and column for human review and possible manual re-entry. Legitimate values (Discovery, Validation, Scale-Up, Deployment, Multiple Roles, and free-text composites) are preserved.

## Consequences

- ETL code is more complex than a naive load — it must handle section headers, hardcoded corrections, an actor type mapping, and quarantine logic.
- Roughly 90 rows of NutriCrops data have at least one corrupted field that will appear as NULL post-migration. Phase 4 enrichment must include a step to recover these from secondary sources or manual review.
- The Sustainability sector decision is pending. If supervisor decides to re-tag, this ADR will be revised.

## Related

- ADR-001: Raw data is sacred
- ADR-002: Hub as first-class entity
- `docs/data-dictionary.md` — column-by-column details
- `data/processed/actor_type_mapping.csv` — free-text to enum mapping