# UM6P — Data-Quality Scan (read-only)

_Generated 2026-07-28 · 872 live actors (merged duplicates excluded) · nothing in the DB was changed._

> Every item below is a **candidate for human review**, not an auto-fix. This mirrors the `review_queue` "score → human decides" pattern already in the database. Fixes belong in the source spreadsheets / ETL, not applied blindly.


## 1. `country` field hygiene

**1a. United States is stored under 2 different spellings (392 actors total).** Pick one canonical value and map the rest. This directly breaks Browse-by-region and the SQL router's exact substring filters.

| stored value | actors |
|---|---|
| USA | 214 |
| United States | 178 |


**1b. US state stored in the `country` column (6 actors).** Should be `country = United States` with the state moved to `state`.

| actor | country value (a US state) |
|---|---|
| Brookhaven National Laboratory | New York |
| Lawrence Livermore National Laboratory (LLNL) | California |
| National Renewable Energy Laboratory (NREL) | D.C. |
| Purdue University-Agricultural Engineering, Precision Nutrients & Deployment Systems | Indiana |
| Sandia National Laboratories | California |
| University of California, Irvine | California |


**1c. Free-text / descriptions leaked into `country` (19 actors).** These look like ETL spillover from a wider cell. Each needs the real country extracted.

| actor | country value (truncated) |
|---|---|
| Battelle Memorial Institute | DC area Operational Footprint: Nationwide + international project deli… |
| Carbon Solutions LLC | especially in states active in carbon sequestration permitting. |
| DOE Natioanl Laboratories (US Department of Energy labs) | Illinois DOE National Laboratory system spans the entire United States… |
| Dow- Advanced Materials & Sustainability R&D | Texas Additional global innovation hubs |
| Electric Power Research Institute | Washington DC area Operational Footprint: Nationwide + international m… |
| EPA Radionuclide Programs | USA Regional Offices: 10 EPA regions nationwide (regulatory implementa… |
| Evoqua Water Technologies (Xylem) | and deployment sites Global Reach: Industrial deployments worldwide |
| Fermi National Accelerator Laboratory (Fermilab) | USA Part of the U.S. DOE National Laboratory System. |
| Florida Phosphate & Phosphogypsum Hub (Central Florida – Tampa Bay Corridor) | Mulberry Primary corridor: Tampa Bay ↔ Polk County |
| IREL (India) Limited | India; major operations in Odisha and Kerala |
| Mosaic Fertilizantes Brasil | Brazil (plus wider Brazil footprint) |
| ReElement Technologies | USA Deployment Model: Modular facilities deployable across multiple U.… |
| Similar Electrochemical separation startups | but still potential collaborators depending on IP/export constraints). |
| SLAC National Accelerator Laboratory | USA Operated by Stanford University for the U.S. Department of Energy. |
| Thomas Jefferson National Accelerator Facility (Jefferson Lab) | USA Operated by Jefferson Science Associates for the U.S. Department o… |
| U.S. Nuclear Regulatory Commission (NRC) | USA Regional Offices: Region I – Pennsylvania Region II – Georgia Regi… |
| University of Alabama- Center for Materials for Information Technology | USA Embedded within the University of Alabama’s College of Engineering… |
| Veolia North America- Innovation & Technology | USA Major Operations: Nationwide (municipal + industrial sites across … |
| Veolia Nuclear Solutions | and international nuclear cleanup sites. |


## 2. Suspected near-duplicate actor names

**8 name pairs are ≥88% similar** and may be the same organization not yet merged. Higher score = more likely a true duplicate. (Exact-name collisions are already 0 — the merge workflow handles those; these are the fuzzy ones it misses.)

⚠️ Similarity is on *spelling*, so a few pairs share a template but are genuinely different organizations (e.g. Arizona vs California Dept of Water Resources) — do **not** merge those. The colleague judges each pair.

| similarity | name A | name B |
|---|---|---|
| 94% | Department of Agricultural & Biological Engineering (UIUC) | Department of Biological & Agricultural Engineering |
| 91% | NOAA Earth System Research | NOAA Earth System Research Labs |
| 91% | Department of Biological & Agricultural Engineering | Texas A&M Department of Biological & Agricultural Engineering |
| 90% | Environmental Reclamation Firms | Environmental Remediation Firms |
| 90% | College of Agricultural & Environmental Sciences (CAES) | College of Agricultural, Consumer & Environmental Sciences (ACES) |
| 89% | Hydrogen Research Programs | Hydropower Research Programs |
| 88% | College of Agriculture & Life Sciences (CALS) | College of Agriculture & Life Sciences (Texas A&M) |
| 88% | Arizona Department of Water Resources | California Department of Water Resources |


## How this was produced

- Source: live `actor` rows (`merged_into_actor_id IS NULL`), read over a **read-only** Postgres session.
- Near-dup metric: `rapidfuzz.token_sort_ratio` (word-order/punctuation tolerant), threshold 88.
- Re-run anytime: `PYTHONPATH=~/Desktop/um6p-rag ~/.conda/envs/um6p/bin/python -m data_quality_scan`
