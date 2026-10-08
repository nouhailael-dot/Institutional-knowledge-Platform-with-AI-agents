# Contract change: the Intern Guide taxonomy replaces the Phase 5 catalog

**For:** Nouhaila (backend / agent contracts)
**From:** Ismail (Review interface, hub fixtures)
**Status:** proposal, applied on local `ghus_v2_*_test` databases only. Nothing
has run against production Supabase, and no production DDL is requested here.

---

## 1. What changed in one paragraph

The Phase 5 category-type catalog (12 categories, 65 types, a per-category
`other`) has been replaced by the catalog in *Actor Categories and Link Types —
Intern Guide* (12 categories, **69 types**, a per-category **`not_applicable`**).
The **12 category codes are unchanged**, so anything keyed on `actor_category`
keeps working untouched. What changed is the set of **type codes**, the
**display labels** of both categories and types, and the **catch-all code**.

---

## 2. What agents must send

### 2.1 `category_type` values

| Before | Now |
|---|---|
| One of 65 Phase 5 type codes | One of the **69** codes in `config/actor_categories.yaml` |
| `other` when nothing fits | **`not_applicable`** when nothing fits |
| `category_type` optional on new records | **Required on every new actor.** A legacy `NULL` is still readable and displays as "Pending Classification", but no new record may be written without a type. |

`not_applicable` is a deliberate choice, never a stand-in for a value the agent
failed to find. Choosing it **requires** a one-line `category_note` and raises a
`category_doubt` review item. `agents.common.actor_classification` enforces this;
a payload that omits the note is rejected before promotion.

### 2.2 Type codes that moved or disappeared

These Phase 5 codes are **retired**. They still display on the records that hold
them and still validate on read, but they are never selectable and must never be
emitted by an agent:

| Category | Retired code | What to send instead |
|---|---|---|
| `university_academic` | `branch_campus`, `community_technical_college` | a reviewer decides; see the mapping CSV |
| `research_center` | `university_affiliated_center` | **moves to `university_academic` / `research_lab_center`** — category change, review only |
| `research_center` | `research_lab_group` | a reviewer decides |
| `national_laboratory` | `doe_national_lab`, `ffrdc`, `federal_research_facility` | one of the four **operator** types: `university_operated_affiliated`, `corporate_operated`, `consortium_operated`, `government_direct` |
| `applied_facility` | `experimental_farm_station`, `pilot_demonstration_plant`, `testbed`, `field_site_living_lab` | one of the four **operator** types: `independent`, `government_operated`, `corporate_operated`, `nonprofit_operated` |
| `hospital_clinical` | `health_system`, `hospital`, `specialty_clinic_center` | one of the **ownership** types |
| `company` | `large_multinational`, `corporate_rd_center` | `public_company` or `private_company`; a corporate research centre is usually `research_center` / `corporate_operated` |
| `innovation_platform` | `innovation_center_shared_lab` | apply the Category 8 vs 12 test |
| `innovation_platform` | `tech_transfer_office` | **moves to `university_academic` / `tech_transfer_office`** — category change, review only |
| `investor` | `impact_climate_fund`, `private_equity_growth` | the capital-source type that fits |
| `government` | `regional_authority` | the jurisdiction level that fits |
| `foundation_nonprofit` | `think_tank` | `operating_nonprofit`, or `research_center` (category change) |
| `association_network` | `professional_society`, `standards_body`, `alliance_coalition` | the membership type that fits |
| *every category* | `other` | **`not_applicable`** |

Codes **reused unchanged** (only the label moved): `university_system`,
`academic_department`, `college_school`, `independent_institute`,
`academic_medical_center`, `small_mid_size`, `business_unit_subsidiary`,
`independent_startup`, `university_spinout`, `corporate_spinout`, `incubator`,
`accelerator`, `venture_studio`, `venture_capital`, `corporate_venture`,
`public_investment_fund`, `angel_group`, `federal_agency`, `state_agency`,
`local_municipal`, `public_utility`, all four foundation types,
`trade_association`, `research_consortium`, `multi_location_network`.

### 2.3 New classification-evidence field

`classification_evidence` gains one boolean:

```jsonc
"university_affiliated_hospital": true | false
```

True when the subject is a hospital, clinical system or medical center operated
by, or formally tied to, a university medical school. It encodes the Guide's
**hospital exception**: such a record stays `hospital_clinical` /
`academic_medical_center` and is never nested under University. It outranks
`medical_school`, which now resolves to `university_academic` /
**`medical_school`** rather than `college_school`.

The field defaults to `false`, so an older payload still validates — but the
classifier's category tool schema now lists it as required, and new extractions
must set it.

### 2.4 `startup_origin` enum

`independent_startup | university_spinout | corporate_spinout |
accelerator_portfolio_company | null` — `accelerator_portfolio_company` is new.

---

## 3. API and validation surface

| Layer | Behaviour |
|---|---|
| Database | `actor_category_type_definition` holds both catalogs. `active = true` is the Guide's 69; retired rows stay with `active = false`. The composite foreign key `actor.(actor_category, category_type)` is unchanged and still satisfied, because nothing is deleted. One **selectable** catch-all per category is guaranteed by `ux_actor_category_one_other` (now partial on `active`). |
| Writer | `promote.py` / `decisions.py` reject a new actor with no type, and reject any pair the catalog does not validate. No third writer was added. |
| Classifier | `classify_actor_category_type` sends the Guide's own decision rules in the category prompt, and the type prompt now carries each type's **meaning**, not just its code. |
| Review API | rejects an invalid pair with `422` and a message naming the category and the type. |
| Review UI | the Category Type dropdown is dependent on the chosen category and offers only that category's selectable types. |

---

## 4. Agent 3 impact

**Agent 3 is not edited.** It reads, and must keep reading:

- `actor_category` — **unchanged**, all 12 codes identical;
- `category_type` — **changed**, see §2.2;
- `category_note`, `category_needs_review` — unchanged in shape; `category_note`
  is now required whenever the type is `not_applicable`;
- `classification_evidence` — gains `university_affiliated_hospital` (§2.3).

Anything in Agent 3 that string-matches a retired type code, or that treats
`"other"` as the catch-all, needs updating on your side. Nothing in Agent 3
writes these values, so there is no write-path risk.

---

## 5. Files in this change

| File | What it is |
|---|---|
| `config/actor_categories.yaml` | the Guide catalog, runtime source of truth |
| `agents/common/actor_classification.py` | loader, catch-all, hard rules, prompts |
| `agents/sql/510_v2_intern_guide_taxonomy.sql` | reference-data migration **proposal** |
| `agents/sql/rollback/510_v2_intern_guide_taxonomy.sql` | its rollback |
| `scripts/taxonomy_intern_guide_mapping.py` | deterministic old → new mapping report |
| `docs/evidence/taxonomy_intern_guide_mapping.csv` | 65 pairs: 40 exact, 25 review, 2 category changes |
| `tests/agent/test_intern_guide_taxonomy.py` | Appendix A pinned byte for byte |

---

## 6. What is NOT in this change

- **No actor rows were re-mapped.** Applying the 40 `exact` rows and raising
  `category_doubt` items for the 25 `review` rows is a separate, reviewed step.
- **No production DDL**, no connection to production Supabase.
- **Nothing bundled with the V2 cutover package.** Migration 510 sits outside
  `migrations/release/architecture_v2_cutover/` by design.
- `record_count` in the mapping CSV currently reads `UNVERIFIED`: no local
  `ghus_v2_*_test` database was reachable from the session that generated it.
  Re-run `python -m scripts.taxonomy_intern_guide_mapping` with the PG
  environment variables set to fill it in.

---

## 7. Open questions for you

1. Does Agent 3 string-match any retired type code, or `"other"` as a catch-all?
2. Does any agent emit `category_type` without a `category_note` when it is
   unsure? That path now fails closed rather than writing `other` silently.
3. The 214 records flagged for category review under the Phase 5 catalog: do
   they get re-triaged under the Guide catalog, or carried over as-is?
   (This is Appendix H item 8 and needs a GHUS decision, not ours.)
