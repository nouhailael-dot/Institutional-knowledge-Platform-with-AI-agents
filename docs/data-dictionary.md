# Data Dictionary

Living document. Updated whenever a new source dataset is profiled or a finding is made during ETL.

---

## Source file: Ecosystem_Mapping_The_Final_UpV.xlsx

### Sheet: Ecosystem Mapping

- **Rows:** 61 total. 52 are real hub records. 8 are section header rows. 1 is the column header row.
- **Columns:** 39 in the file, but real data lives in columns 1–16. Columns 17–38 are empty padding and must be dropped.
- **First impression:** Hub-level intelligence. Each real row describes one geographic ecosystem (e.g., UC Davis / Sacramento Valley).

**Real columns (1–16)**

1. Actor Name — hub name
2. Actor Category — sector classification, always of the form `Ecosystem Hub (Sector)`
3. Actor Description — narrative description of the hub
4. Actor Composition — the institutions that make up the hub, free text
5. Location (City, State, Country)
6. Official Websites — multiple URLs, free-text
7. Why this actor is potentially valuable — narrative
8. Core Topic Strengths — narrative
9. Talent & Institutional Strength — narrative
10. Research and Infrastructure — narrative
11. Industry & Innovation Integration — narrative
12. Int'l Focused & Engagement — narrative
13. Programs and Labs — names of programs and labs, free text
14. Key Constraints or Dependencies — narrative
15. Fundings — narrative
16. Cross-Hub Structural Themes — narrative

**Section header rows to skip** (only column 1 filled):
Rows 2, 8, 15, 21, 27, 34, 45, 51.

**Known data quality issues:**

- Row 25 (Massachusetts Energy): Actor Category has analyst note "need to be part" appended. Strip it during cleaning.
- Row 30 (Nevada Mining): Actor Category contains the wrong hub name. Replace with `Ecosystem Hub (Mining & Critical Minerals)`.
- Row 31 (Utah Mining): Actor Category equals the actor's own name. Replace with `Ecosystem Hub (Mining & Metallurgy)`.
- Row 51 section header: "Helath Hubs" — typo of "Health Hubs".

**Cleaning tasks:**

- Drop columns 17–38 entirely (empty padding).
- Skip the 8 section header rows; log them to `data/interim/skipped_rows.csv`.
- Apply the 4 known-issue corrections above.
- Parse `Actor Category` to extract the sector portion (e.g., `Ecosystem Hub (Agriculture)` → sector = `AGRI`).
- All rows map to the `hub` table.
- Extract individual organizations from narrative fields 9, 10, 11, 13 in a later AI extraction step — not in v1 cleaning.

### Sheet: Events Name

- **Rows:** 41 total. ~18 real event rows; remainder appears to be empty padding (verify).
- **Columns:** 5. Real columns: Name, Event Type, Location, Official Website.
- **Maps to:** `event` table directly.

### Sheet: Hub Structure and Actor Interaction

- **Rows:** 3 (2 real hubs + header). Only UC Davis and Illinois Midwest are populated.
- **Columns:** 4. Hub Name, Upstream, Downstream, Integrated Flow.
- **Maps to:** `hub` table, specifically the fields `upstream_inputs`, `downstream_outputs`, `integrated_flow_description`.
- **Note:** Sparsely populated. Only two hubs have this depth of detail. The remaining 50 hubs will need this content generated via Phase 4 enrichment or manual entry.

---

## Source file: NutriCrops_Ecosystem_Mapping_Template.xlsx

### Sheet: NutriCrops Ecosystem Map

- **Rows:** 145 total. 144 are actor records (some are section headers — to be verified).
- **Columns:** 23 real columns out of 39 in the file.
- **First impression:** Actor-level intelligence, scoped to the NutriCrops/phosphogypsum challenge. Each row is one actor evaluated for relevance.

**Real columns:**

1. Actor Name
2. Actor Category — organization type (4 official + 12 free-text variants)
3. Organization Description
4. Location (City, State, Country)
5. Official Website
6. Primary Technical Focus Area
7. Specific Technical Approach
8. Relevance to Phosphogypsum
9. Current Activities / Evidence
10. Technology / IP Notes
11. Estimated TRL — controlled vocabulary, 4 values
12. Primary Role in Innovation Lifecycle — controlled vocabulary, 5 values (CORRUPTED — see below)
13. Collaboration Orientation
14. Relevance Score — 1 to 5
15. Maturity Risk — Low/Medium/High (CORRUPTED — see below)
16. Key Constraints or Dependencies
17. Why This Actor Is Potentially Valuable
18. Source Links / References
19. Analyst Notes
20. Fundings

**Critical data quality issues:**

- Actor Category contains 12 free-text values beyond the 4 official dropdown values. See `data/processed/actor_type_mapping.csv` for the canonical mapping. The original free-text value should be preserved in `actor.actor_type_raw` for traceability.
- Lifecycle and Maturity columns contain "Yes"/"No" values (likely from column shifting). Replace with NULL during cleaning, log affected rows to `data/interim/quarantine_lifecycle.csv` and `data/interim/quarantine_maturity.csv` for manual review.
- TRL has one typo: "TRL 4-5 Lab or Pilot" (double space) — normalize.

**Cleaning tasks:**

- Map Actor Category through `actor_type_mapping.csv`.
- Quarantine corrupted Lifecycle/Maturity values.
- Trim whitespace in TRL field.
- Tag every row with `challenge_id` corresponding to the NutriCrops challenge.
- All actors map to the `actor` table; relevance scores and TRL/Lifecycle/Risk fields map to `actor_relevance` table with `challenge_id = NutriCrops`.

### Sheet: Lists

Reference data — the official dropdown vocabularies. Treat as source of truth for the controlled vocabularies:

- Actor Category: 4 values (University Lab, National Research Lab, Startup / New Venture, Corporate R&D / Innovation Lab)
- TRL: 4 values
- Lifecycle Role: 5 values (Discovery, Validation, Scale-Up, Deployment, Multiple Roles)
- Maturity Risk: Low / Medium / High

## Sectors in use across source data

| Code    | Name                    | Source                      | Status                                |
| ------- | ----------------------- | --------------------------- | ------------------------------------- |
| AGRI    | Agriculture             | Ecosystem Mapping section 1 | In brief                              |
| AI      | Artificial Intelligence | Ecosystem Mapping section 2 | In brief                              |
| WATER   | Water                   | Ecosystem Mapping section 3 | In brief                              |
| ENERGY  | Energy                  | Ecosystem Mapping section 4 | In brief                              |
| MINING  | Mining                  | Ecosystem Mapping section 5 | In brief                              |
| CHEM    | Specialty Chemicals     | Ecosystem Mapping section 6 | In brief                              |
| SUSTAIN | Sustainability          | Ecosystem Mapping section 7 | Pending supervisor decision (ADR-006) |
| HEALTH  | Health                  | Ecosystem Mapping section 8 | In brief                              |

---

## Source file: UN_Mapping\_\_FV.xlsx

### Sheet: UN Mapping

- **Rows:** 42 total. 25 are real entity records. ~8 are nested section headers. Plus title row, header row, empty trailing rows.
- **Columns:** 17 real columns of partnership-evaluation data.
- **First impression:** Institutional partner mapping. Each row is a UN entity (agency, programme, committee, etc.) evaluated as a potential partner for UM6P.

**Nested hierarchical structure:**
The sheet uses nested section headers with distinct visual markers:

- `▶` indicates a MAJOR HEADER (top-level UN body): UN General Assembly, ECOSOC, Secretariat, Specialized Agencies
- `▸` indicates a SUB-HEADER (organizational category): Funds and Programmes, Functional Commissions, Departments and Offices, etc.

This hierarchy is preserved in the database via the `organization_hierarchy` table.

**Real columns:**

1. Official Name & Acronym
2. UN System Category — maps to `actor.actor_type` via mapping table
3. HQ Location — maps to `actor.location_city`, `state`, `country`
4. Main Function → `actor.description`
5. Thematic Focus → `partnership_profile.thematic_focus`
6. Strategic Plan → `partnership_profile.strategic_plan`
7. Africa-specific Structure/Mandate → `partnership_profile.africa_specific_mandate`
8. Africa-specific Details → `partnership_profile.africa_specific_details`
9. Why Potentially Valuable for UM6P? → `partnership_profile.why_valuable_for_um6p`
10. Budget Overview → `partnership_profile.budget_overview`
11. Partners with Universities? (Yes/No) → `partnership_profile.partners_with_universities`
12. Dedicated University Programmes → `partnership_profile.university_programmes`
13. Examples of Partnerships with Universities → `partnership_profile.university_partnership_examples`
14. Key Entry Points → `partnership_profile.key_entry_points`
15. Funding Delivery? (Yes/No) → `partnership_profile.funding_delivery`
16. Funding Delivery Mechanisms → `partnership_profile.funding_delivery_mechanisms`
17. Key Constraints → `partnership_profile.key_constraints`

**Cleaning tasks:**

- Detect nested section headers by the `▶` and `▸` characters and skip them as entity rows. Record them in a hierarchy stack so each entity below is linked correctly.
- For each entity row, create one `actor` + one `partnership_profile` + (where applicable) one `organization_hierarchy` row linking to the parent.
- Apply the actor_type mapping for column 2.
- Parse Yes/No into actual booleans for columns 11 and 15.
- For trailing empty rows (row 42), skip.

### Sheet: UN KEY EVENTS

- **Rows:** 114 total. 113 are real event rows.
- **Columns:** 3 — Organisation, Key Event 2026, Location.
- **Maps to:** `event` table, with `host_actor_id` linking to the UN entity hosting the event.

**Structure note:**
The "Organisation" column uses the same `▶`/`▸` section header pattern as the main sheet. When a section header appears, subsequent event rows whose Organisation column shows `—` belong to the most recent named organization above them. Carry the current organization down during ETL.

**Cleaning tasks:**

- Detect section headers and skip them as event rows.
- Carry the current organization name down through `—` placeholder rows.
- Parse the date prefix in the event text (e.g., "1 October – 25 November 2026") into structured `next_date` where possible. Free text date ranges get left in the event description.
- Resolve the organization name to an `actor.actor_id` via name lookup; fail loudly if not found, since the main UN Mapping sheet should be ingested first.
