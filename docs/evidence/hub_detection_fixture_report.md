# Hub detection fixture report (WS5.2)

Synthetic fixtures, run against the implemented Phase 7 detection with only the
change GHUS decided on 2026-10-08: clustering keys on **sector**, and topic is
recorded as secondary evidence. The thresholds, the family rule, the centre
method and the determinism guarantee are untouched.
The algorithm was not changed to make any scenario pass. Where a fixture
expectation and the implemented behaviour differ, the implemented behaviour is
what is recorded below.

| | |
|---|---|
| Thresholds | 10 independent families · 5 matched categories (maximum bipartite matching) · 50-mile core · 200-mile cluster |
| Trigger pool | record status in ('verified',) |
| Clustering dimension | **sector** (GHUS decision 2026-10-08; topic is secondary evidence on each proposal) |
| Method version | `hub_proposal_v1` |
| Fingerprint version | `hub_family_set_v1` |
| Data | synthetic, `FX-` prefixed, in memory only. No database was written, read or contacted. |
| Coordinates | vendored Census gazetteer (`agents/data/gazetteer`) |
| Distances | `agents.common.geography.distance_miles` (haversine). None is hand-estimated. |

## Base fixture

| # | Fixture actor | Category → Type | City | Miles from Davis, CA | Family |
|---|---|---|---|---|---|
| 1 | FX University Alpha | university_academic → university_system | Davis, CA | 0.00 | F1 root |
| 2 | FX Alpha Dept. of Plant Sciences | university_academic → academic_department | Davis, CA | 0.00 | F1, same family as the university |
| 3 | FX Valley Crop Institute | research_center → independent_institute | Sacramento, CA | 14.59 | F2 |
| 4 | FX Delta Field Station | applied_facility → nonprofit_operated | Dixon, CA | 8.84 | F3 |
| 5 | FX AgriCorp | company → private_company | Woodland, CA | 7.98 | F4 |
| 6 | FX Irrigation Systems | company → small_mid_size | Elk Grove, CA | 21.44 | F5 |
| 7 | FX SoilSense | startup → independent_startup | Sacramento, CA | 14.59 | F6 |
| 8 | FX SeedGen | startup → university_spinout | Davis, CA | 0.00 | F7, spinout of the university but its own family |
| 9 | FX Ag Accelerator | innovation_platform → accelerator | Sacramento, CA | 14.59 | F8 |
| 10 | FX Harvest Ventures | investor → venture_capital | Roseville, CA | 26.98 | F9 |
| 11 | FX County Ag Department | government → local_municipal | Woodland, CA | 7.98 | F10 |
| 12 | FX Farm Futures Foundation | foundation_nonprofit → private_foundation | Sacramento, CA | 14.59 | F11 |
| 13 | FX Growers Association | association_network → trade_association | Stockton, CA | 46.32 | F12 |

Thirteen actors, twelve independent families: FX Alpha Dept. of Plant Sciences is
a `unit_of` the university and therefore shares its family. FX SeedGen is a
`spinout_of` the university, which the Intern Guide is explicit is **not**
parenthood, so it counts as its own family.

## The 200-mile boundary

Two real gazetteer cities that straddle the cluster radius, so the boundary is
measured rather than asserted:

| Fixture | City | Miles from Davis, CA | Inside the 200-mile cluster |
|---|---|---|---|
| FX Boundary Inside | Bishop, CA | 199.74 | yes |
| FX Boundary Outside | Eureka, CA | 201.22 | no |

## Scenarios

### S1 — A qualifying set yields one proposal and creates no hub

**Input.** The 13-actor base fixture: one controlled topic, Sacramento Valley, all Verified.

**Expected.** One proposal, with centre, distances, family and category matching and evidence. No automatic hub creation.

**Actual.**

- Proposal centre: **Sacramento, CA** (38.567694, -121.468161)
  - Suggested name: Sacramento AGRI Hub
  - Independent families: **12** (threshold 10) · matched categories: **10** (threshold 5)
  - Members: 13
  - Independence statement: 12 independent families from 10 matched categories work in AGRI, concentrated around Sacramento, with every proposed member within 200 miles. Its most common topic is FX Precision Agriculture (13 of 13 members).
  - Membership fingerprint: `fe8719e3735dad01…`

  | Member | Category | Type | Family | Distance to centre |
  |---|---|---|---|---|
  | FX-ag-accelerator | innovation_platform | accelerator | FX-ag-accelerator | 0.00 mi |
  | FX-agricorp | company | private_company | FX-agricorp | 16.77 mi |
  | FX-alpha-plant-sciences | university_academic | academic_department | FX-university-alpha | 14.59 mi |
  | FX-county-ag-department | government | local_municipal | FX-county-ag-department | 16.77 mi |
  | FX-delta-field-station | applied_facility | nonprofit_operated | FX-delta-field-station | 20.97 mi |
  | FX-farm-futures-foundation | foundation_nonprofit | private_foundation | FX-farm-futures-foundation | 0.00 mi |
  | FX-growers-association | association_network | trade_association | FX-growers-association | 41.75 mi |
  | FX-harvest-ventures | investor | venture_capital | FX-harvest-ventures | 16.13 mi |
  | FX-irrigation-systems | company | small_mid_size | FX-irrigation-systems | 11.49 mi |
  | FX-seedgen | startup | university_spinout | FX-seedgen | 14.59 mi |
  | FX-soilsense | startup | independent_startup | FX-soilsense | 0.00 mi |
  | FX-university-alpha | university_academic | university_system | FX-university-alpha | 14.59 mi |
  | FX-valley-crop-institute | research_center | independent_institute | FX-valley-crop-institute | 0.00 mi |

  Family/category matching used for the threshold:
  - `FX-ag-accelerator` → `innovation_platform`
  - `FX-agricorp` → `company`
  - `FX-county-ag-department` → `government`
  - `FX-delta-field-station` → `applied_facility`
  - `FX-farm-futures-foundation` → `foundation_nonprofit`
  - `FX-growers-association` → `association_network`
  - `FX-harvest-ventures` → `investor`
  - `FX-seedgen` → `startup`
  - `FX-university-alpha` → `university_academic`
  - `FX-valley-crop-institute` → `research_center`


### S2 — Nine independent families make no proposal

**Input.** The base fixture minus three singleton families, so the department folding into its university leaves 9 families.

**Expected.** No proposal.

**Actual.**

- Proposals: **none**

### S3 — Four matched categories make no proposal

**Input.** The base fixture with every actor rewritten onto four categories, keeping the family count unchanged.

**Expected.** No proposal.

**Actual.**

- Proposals: **none**

### S4 — Two separate clusters give two deterministic proposals

**Input.** The base fixture plus a Greater Boston cluster, 2640 miles away.

**Expected.** Two proposals, with no shared members.

**Actual.**

- Proposal centre: **Sacramento, CA** (38.567694, -121.468161)
  - Suggested name: Sacramento AGRI Hub
  - Independent families: **12** (threshold 10) · matched categories: **10** (threshold 5)
  - Members: 13
  - Independence statement: 12 independent families from 10 matched categories work in AGRI, concentrated around Sacramento, with every proposed member within 200 miles. Its most common topic is FX Precision Agriculture (13 of 13 members).
  - Membership fingerprint: `fe8719e3735dad01…`

  | Member | Category | Type | Family | Distance to centre |
  |---|---|---|---|---|
  | FX-ag-accelerator | innovation_platform | accelerator | FX-ag-accelerator | 0.00 mi |
  | FX-agricorp | company | private_company | FX-agricorp | 16.77 mi |
  | FX-alpha-plant-sciences | university_academic | academic_department | FX-university-alpha | 14.59 mi |
  | FX-county-ag-department | government | local_municipal | FX-county-ag-department | 16.77 mi |
  | FX-delta-field-station | applied_facility | nonprofit_operated | FX-delta-field-station | 20.97 mi |
  | FX-farm-futures-foundation | foundation_nonprofit | private_foundation | FX-farm-futures-foundation | 0.00 mi |
  | FX-growers-association | association_network | trade_association | FX-growers-association | 41.75 mi |
  | FX-harvest-ventures | investor | venture_capital | FX-harvest-ventures | 16.13 mi |
  | FX-irrigation-systems | company | small_mid_size | FX-irrigation-systems | 11.49 mi |
  | FX-seedgen | startup | university_spinout | FX-seedgen | 14.59 mi |
  | FX-soilsense | startup | independent_startup | FX-soilsense | 0.00 mi |
  | FX-university-alpha | university_academic | university_system | FX-university-alpha | 14.59 mi |
  | FX-valley-crop-institute | research_center | independent_institute | FX-valley-crop-institute | 0.00 mi |

  Family/category matching used for the threshold:
  - `FX-ag-accelerator` → `innovation_platform`
  - `FX-agricorp` → `company`
  - `FX-county-ag-department` → `government`
  - `FX-delta-field-station` → `applied_facility`
  - `FX-farm-futures-foundation` → `foundation_nonprofit`
  - `FX-growers-association` → `association_network`
  - `FX-harvest-ventures` → `investor`
  - `FX-seedgen` → `startup`
  - `FX-university-alpha` → `university_academic`
  - `FX-valley-crop-institute` → `research_center`

- Proposal centre: **Worcester, MA** (42.269478, -71.807783)
  - Suggested name: Worcester AGRI Hub
  - Independent families: **12** (threshold 10) · matched categories: **10** (threshold 5)
  - Members: 12
  - Independence statement: 12 independent families from 10 matched categories work in AGRI, concentrated around Worcester, with every proposed member within 200 miles. Its most common topic is FX Precision Agriculture (12 of 12 members).
  - Membership fingerprint: `224682f1e66bf439…`

  | Member | Category | Type | Family | Distance to centre |
  |---|---|---|---|---|
  | FX-bay-accelerator | innovation_platform | accelerator | FX-bay-accelerator | 40.63 mi |
  | FX-bay-field-station | applied_facility | nonprofit_operated | FX-bay-field-station | 0.00 mi |
  | FX-bay-state-university | university_academic | university_system | FX-bay-state-university | 40.63 mi |
  | FX-charles-crop-institute | research_center | independent_institute | FX-charles-crop-institute | 35.96 mi |
  | FX-coastal-foundation | foundation_nonprofit | private_foundation | FX-coastal-foundation | 36.74 mi |
  | FX-county-extension-office | government | local_municipal | FX-county-extension-office | 0.00 mi |
  | FX-greenline-bio | startup | corporate_spinout | FX-greenline-bio | 38.96 mi |
  | FX-harbor-agri | company | private_company | FX-harbor-agri | 36.74 mi |
  | FX-harbor-ventures | investor | venture_capital | FX-harbor-ventures | 40.63 mi |
  | FX-mill-irrigation | company | small_mid_size | FX-mill-irrigation | 35.60 mi |
  | FX-northeast-growers | association_network | trade_association | FX-northeast-growers | 124.93 mi |
  | FX-rootdata | startup | independent_startup | FX-rootdata | 35.96 mi |

  Family/category matching used for the threshold:
  - `FX-bay-accelerator` → `innovation_platform`
  - `FX-bay-field-station` → `applied_facility`
  - `FX-bay-state-university` → `university_academic`
  - `FX-charles-crop-institute` → `research_center`
  - `FX-coastal-foundation` → `foundation_nonprofit`
  - `FX-county-extension-office` → `government`
  - `FX-greenline-bio` → `startup`
  - `FX-harbor-agri` → `company`
  - `FX-harbor-ventures` → `investor`
  - `FX-northeast-growers` → `association_network`


### S5 — A trusted same-sector hub suppresses instead of duplicating

**Input.** The base fixture, with an existing 200-mile hub in the same sector centred on Sacramento.

**Expected.** An assignment plan and a suppression, not a duplicate proposal.

**Actual.**

- Proposals: **none**
- Suppression: **existing_same_sector_hub** at Sacramento (13 actors)
  - Covering hub: `FX-existing-hub`
  - Assignment plans prepared: 13
  - Family fingerprint: `fe8719e3735dad01…`

### S6 — Parked actors are excluded; a different topic no longer excludes

**Input.** The base fixture with FX SoilSense set to Parked and FX Harvest Ventures moved to a different controlled topic.

**Expected.** The Parked actor never triggers detection. The other-topic actor now JOINS, because it is in the hub's sector, and its topic is recorded in the proposal's topic mix instead of excluding it.

**Actual.**

- Proposal centre: **Davis, CA** (38.556147, -121.737793)
  - Suggested name: Davis AGRI Hub
  - Independent families: **11** (threshold 10) · matched categories: **10** (threshold 5)
  - Members: 12
  - Independence statement: 11 independent families from 10 matched categories work in AGRI, concentrated around Davis, with every proposed member within 200 miles. Its most common topic is FX Precision Agriculture (11 of 12 members).
  - Membership fingerprint: `2140395a074615f6…`

  | Member | Category | Type | Family | Distance to centre |
  |---|---|---|---|---|
  | FX-ag-accelerator | innovation_platform | accelerator | FX-ag-accelerator | 14.59 mi |
  | FX-agricorp | company | private_company | FX-agricorp | 7.98 mi |
  | FX-alpha-plant-sciences | university_academic | academic_department | FX-university-alpha | 0.00 mi |
  | FX-county-ag-department | government | local_municipal | FX-county-ag-department | 7.98 mi |
  | FX-delta-field-station | applied_facility | nonprofit_operated | FX-delta-field-station | 8.84 mi |
  | FX-farm-futures-foundation | foundation_nonprofit | private_foundation | FX-farm-futures-foundation | 14.59 mi |
  | FX-growers-association | association_network | trade_association | FX-growers-association | 46.32 mi |
  | FX-harvest-ventures | investor | venture_capital | FX-harvest-ventures | 26.98 mi |
  | FX-irrigation-systems | company | small_mid_size | FX-irrigation-systems | 21.44 mi |
  | FX-seedgen | startup | university_spinout | FX-seedgen | 0.00 mi |
  | FX-university-alpha | university_academic | university_system | FX-university-alpha | 0.00 mi |
  | FX-valley-crop-institute | research_center | independent_institute | FX-valley-crop-institute | 14.59 mi |

  Family/category matching used for the threshold:
  - `FX-ag-accelerator` → `innovation_platform`
  - `FX-agricorp` → `company`
  - `FX-county-ag-department` → `government`
  - `FX-delta-field-station` → `applied_facility`
  - `FX-farm-futures-foundation` → `foundation_nonprofit`
  - `FX-growers-association` → `association_network`
  - `FX-harvest-ventures` → `investor`
  - `FX-seedgen` → `startup`
  - `FX-university-alpha` → `university_academic`
  - `FX-valley-crop-institute` → `research_center`

- Prerequisite exclusions:
  - `AGRI:FX-soilsense`: status_not_enabled

### S7a — One family with several departments counts once

**Input.** The base fixture plus three more departments of the same university.

**Expected.** More members, the same independent-family count.

**Actual.**

- Proposal centre: **Davis, CA** (38.556147, -121.737793)
  - Suggested name: Davis AGRI Hub
  - Independent families: **12** (threshold 10) · matched categories: **10** (threshold 5)
  - Members: 16
  - Independence statement: 12 independent families from 10 matched categories work in AGRI, concentrated around Davis, with every proposed member within 200 miles. Its most common topic is FX Precision Agriculture (16 of 16 members).
  - Membership fingerprint: `fe8719e3735dad01…`

  | Member | Category | Type | Family | Distance to centre |
  |---|---|---|---|---|
  | FX-ag-accelerator | innovation_platform | accelerator | FX-ag-accelerator | 14.59 mi |
  | FX-agricorp | company | private_company | FX-agricorp | 7.98 mi |
  | FX-alpha-dept-1 | university_academic | academic_department | FX-university-alpha | 0.00 mi |
  | FX-alpha-dept-2 | university_academic | academic_department | FX-university-alpha | 0.00 mi |
  | FX-alpha-dept-3 | university_academic | academic_department | FX-university-alpha | 0.00 mi |
  | FX-alpha-plant-sciences | university_academic | academic_department | FX-university-alpha | 0.00 mi |
  | FX-county-ag-department | government | local_municipal | FX-county-ag-department | 7.98 mi |
  | FX-delta-field-station | applied_facility | nonprofit_operated | FX-delta-field-station | 8.84 mi |
  | FX-farm-futures-foundation | foundation_nonprofit | private_foundation | FX-farm-futures-foundation | 14.59 mi |
  | FX-growers-association | association_network | trade_association | FX-growers-association | 46.32 mi |
  | FX-harvest-ventures | investor | venture_capital | FX-harvest-ventures | 26.98 mi |
  | FX-irrigation-systems | company | small_mid_size | FX-irrigation-systems | 21.44 mi |
  | FX-seedgen | startup | university_spinout | FX-seedgen | 0.00 mi |
  | FX-soilsense | startup | independent_startup | FX-soilsense | 14.59 mi |
  | FX-university-alpha | university_academic | university_system | FX-university-alpha | 0.00 mi |
  | FX-valley-crop-institute | research_center | independent_institute | FX-valley-crop-institute | 14.59 mi |

  Family/category matching used for the threshold:
  - `FX-ag-accelerator` → `innovation_platform`
  - `FX-agricorp` → `company`
  - `FX-county-ag-department` → `government`
  - `FX-delta-field-station` → `applied_facility`
  - `FX-farm-futures-foundation` → `foundation_nonprofit`
  - `FX-growers-association` → `association_network`
  - `FX-harvest-ventures` → `investor`
  - `FX-seedgen` → `startup`
  - `FX-university-alpha` → `university_academic`
  - `FX-valley-crop-institute` → `research_center`


### S7b — An ambiguous or cyclic parent graph fails closed

**Input.** The base fixture with a university/department parent cycle.

**Expected.** Both cycled actors reported as unresolved and excluded. Detection does not guess a family, and does not abandon the actors it can resolve.

**Actual.**

- Proposal centre: **Sacramento, CA** (38.567694, -121.468161)
  - Suggested name: Sacramento AGRI Hub
  - Independent families: **11** (threshold 10) · matched categories: **9** (threshold 5)
  - Members: 11
  - Independence statement: 11 independent families from 9 matched categories work in AGRI, concentrated around Sacramento, with every proposed member within 200 miles. Its most common topic is FX Precision Agriculture (11 of 11 members).
  - Membership fingerprint: `c287aa2eccda2d22…`

  | Member | Category | Type | Family | Distance to centre |
  |---|---|---|---|---|
  | FX-ag-accelerator | innovation_platform | accelerator | FX-ag-accelerator | 0.00 mi |
  | FX-agricorp | company | private_company | FX-agricorp | 16.77 mi |
  | FX-county-ag-department | government | local_municipal | FX-county-ag-department | 16.77 mi |
  | FX-delta-field-station | applied_facility | nonprofit_operated | FX-delta-field-station | 20.97 mi |
  | FX-farm-futures-foundation | foundation_nonprofit | private_foundation | FX-farm-futures-foundation | 0.00 mi |
  | FX-growers-association | association_network | trade_association | FX-growers-association | 41.75 mi |
  | FX-harvest-ventures | investor | venture_capital | FX-harvest-ventures | 16.13 mi |
  | FX-irrigation-systems | company | small_mid_size | FX-irrigation-systems | 11.49 mi |
  | FX-seedgen | startup | university_spinout | FX-seedgen | 14.59 mi |
  | FX-soilsense | startup | independent_startup | FX-soilsense | 0.00 mi |
  | FX-valley-crop-institute | research_center | independent_institute | FX-valley-crop-institute | 0.00 mi |

  Family/category matching used for the threshold:
  - `FX-ag-accelerator` → `innovation_platform`
  - `FX-agricorp` → `company`
  - `FX-county-ag-department` → `government`
  - `FX-delta-field-station` → `applied_facility`
  - `FX-farm-futures-foundation` → `foundation_nonprofit`
  - `FX-growers-association` → `association_network`
  - `FX-harvest-ventures` → `investor`
  - `FX-seedgen` → `startup`
  - `FX-valley-crop-institute` → `research_center`

- Unresolved hierarchy (fails closed, never guessed):
  - `FX-alpha-plant-sciences`: cycle
  - `FX-university-alpha`: cycle

### S8 — A previously rejected family set is suppressed by its fingerprint

**Input.** The base fixture, rerun with its own membership fingerprint supplied as a prior rejection.

**Expected.** No proposal; the rejection fingerprint suppresses the unchanged set.

**Actual.**

- Proposals: **none**
- Suppression: **existing_family_fingerprint** at Sacramento (13 actors)
  - Family fingerprint: `fe8719e3735dad01…`

### S9 — An actor beyond the radius is not assigned

**Input.** The base fixture plus FX Boundary Outside in Eureka, CA, 201.22 miles from Davis.

**Expected.** The out-of-radius actor is not a member of any proposal.

**Actual.**

- Proposal centre: **Sacramento, CA** (38.567694, -121.468161)
  - Suggested name: Sacramento AGRI Hub
  - Independent families: **12** (threshold 10) · matched categories: **10** (threshold 5)
  - Members: 13
  - Independence statement: 12 independent families from 10 matched categories work in AGRI, concentrated around Sacramento, with every proposed member within 200 miles. Its most common topic is FX Precision Agriculture (13 of 13 members).
  - Membership fingerprint: `fe8719e3735dad01…`

  | Member | Category | Type | Family | Distance to centre |
  |---|---|---|---|---|
  | FX-ag-accelerator | innovation_platform | accelerator | FX-ag-accelerator | 0.00 mi |
  | FX-agricorp | company | private_company | FX-agricorp | 16.77 mi |
  | FX-alpha-plant-sciences | university_academic | academic_department | FX-university-alpha | 14.59 mi |
  | FX-county-ag-department | government | local_municipal | FX-county-ag-department | 16.77 mi |
  | FX-delta-field-station | applied_facility | nonprofit_operated | FX-delta-field-station | 20.97 mi |
  | FX-farm-futures-foundation | foundation_nonprofit | private_foundation | FX-farm-futures-foundation | 0.00 mi |
  | FX-growers-association | association_network | trade_association | FX-growers-association | 41.75 mi |
  | FX-harvest-ventures | investor | venture_capital | FX-harvest-ventures | 16.13 mi |
  | FX-irrigation-systems | company | small_mid_size | FX-irrigation-systems | 11.49 mi |
  | FX-seedgen | startup | university_spinout | FX-seedgen | 14.59 mi |
  | FX-soilsense | startup | independent_startup | FX-soilsense | 0.00 mi |
  | FX-university-alpha | university_academic | university_system | FX-university-alpha | 14.59 mi |
  | FX-valley-crop-institute | research_center | independent_institute | FX-valley-crop-institute | 0.00 mi |

  Family/category matching used for the threshold:
  - `FX-ag-accelerator` → `innovation_platform`
  - `FX-agricorp` → `company`
  - `FX-county-ag-department` → `government`
  - `FX-delta-field-station` → `applied_facility`
  - `FX-farm-futures-foundation` → `foundation_nonprofit`
  - `FX-growers-association` → `association_network`
  - `FX-harvest-ventures` → `investor`
  - `FX-seedgen` → `startup`
  - `FX-university-alpha` → `university_academic`
  - `FX-valley-crop-institute` → `research_center`


## Determinism

Every scenario above is rerun in
`tests/agent/test_hub_detection_fixtures.py`, which asserts that two runs over the
same fixtures produce identical proposal payloads, identical suppression reasons
and an identical eligible-actor list. This report carries no timestamp for the
same reason: a diff between two runs means the algorithm changed.

## What this report does not do

- It creates no hub. Detection only ever produces a **proposal** for GHUS.
- It writes nothing to any database, local or remote.
- It does not change the family-aware algorithm, the thresholds, or the Phase 6
  assignment logic.

## Open item for GHUS

The Architecture V2 docx text says 3 Verified actors from 2 categories, while the
approved modified spec and the implemented Phase 7 use 10 families / 5 categories
/ 50 miles / 200 miles. These fixtures run the implemented rules. Decision D5 of
the brief keeps them, and Appendix H item 1 asks GHUS to confirm the meeting did
not intend to replace them.

