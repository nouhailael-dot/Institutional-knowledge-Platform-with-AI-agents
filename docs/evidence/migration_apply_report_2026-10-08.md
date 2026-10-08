# Migration apply report — 2026-10-08

**Database:** `ghus_v2_review_redesign_test` on local PostgreSQL 17 at
`127.0.0.1:55432`, created with `TEMPLATE ghus_v2_phase12_full_test` — the
restored full production copy, 965 actors.

**Production Supabase was not contacted.** No connection, no DDL, no write.
Authentication was `trust` on loopback (the instance's own `pg_hba.conf`); no
password was used or stored, and the role name came from the committed schema
manifest.

**The reference copies were not modified.** `ghus_v2_phase12_full_test` was used
only as a `CREATE DATABASE` template and had zero active connections.

---

## Applied, in order

| Migration | Result |
|---|---|
| `agents/sql/510_v2_intern_guide_taxonomy.sql` | applied, assertions passed |
| `agents/sql/520_v2_sector_dimension.sql` | applied, assertions passed |
| `agents/sql/530_v2_conformance_fixes.sql` | applied, assertions passed |
| `migrations/proposed/deferred/545_v2_canonical_conformance.sql` | applied, assertions passed |

Each migration asserts its own outcome inside its transaction and aborts the
whole thing on failure. None needed to.

## Verified state afterwards

| Check | Expected | Found |
|---|---|---|
| Selectable category types | 69 | **69** |
| Retired types kept, not deleted | > 0 | **37** |
| Categories with a selectable Not Applicable | 12 | **12** |
| Actor rows with a pair that has no definition | 0 | **0** |
| Sectors seeded | 10 | **10** |
| Selectable thematic sectors | 8 | **8** |
| Hubs with a primary sector row | 48 | **48** |
| `collection_run.trigger_type` | present | **present** |
| `strategic_entity` | present | **present** |
| `person_verification_event` | present | **present** |
| `hub_actor.is_current` | present | **present** |
| Actors | 965, unchanged | **965** |

---

## Three things the real data changed about the plan

Applying against real rows settled questions that reading the schema could not.

### 1. The legacy sector tables survived. Migration 520 was rewritten to adopt them.

`sector` (10 rows), `actor_sector` and `event_sector` (87 rows) are all present
in the production copy. The first draft of 520 tried to `CREATE` them and failed
on the existing `sector` table. It now **adopts** what is there: it adds the V2
evidence columns, gives `sector.sector_id` the default V1 never had (V1 generated
ids in Python), and seeds `hub_sector` from `hub.primary_sectors`.

### 2. `actor_sector` is empty, so sector is not ready on day one either

This corrects a claim in the first draft of the decision record.

| | Rows |
|---|---|
| `actor_topic` | **0** |
| `actor_sector` | **0** |
| `hub.primary_sectors` | 48 of 48 hubs |
| `staged_record.sector_codes` | 6,407 of 7,286 |

Sector's real advantage over topic is narrower than claimed, and still decisive:
the **hub side** of Test 1 is answerable today (every hub has a sector; no hub
has a usable topic), and **new** actors get a sector through the normal promote
path from the 6,407 staged records that carry one.

For the existing 965: 574 sit in at least one hub, and 540 of those resolve to
exactly one sector through that membership. **That is a derivation, not
evidence**, so 520 applies none of it. The remaining 391 have no derivable
sector at all.

### 3. No existing actor has a category type, so there is nothing to re-map

| | Count |
|---|---|
| Actors | 965 |
| With `actor_category` | **809** |
| With `category_type` | **0** |
| Flagged `category_needs_review` | 214 |

The mapping report's `record_count` is now a measured **0 on every one of the 65
pairs**, and that is the right answer rather than a missing one: the migration
has no stored pair to move.

**What this means for Monday.** The taxonomy work on the existing 965 is not a
migration problem, it is a **classification** problem. 510 relabels the
categories the 809 already hold, and all 965 keep `category_type = NULL`, which
the Review screen shows as "Pending Classification" exactly as decision D4
requires. The 2 mappings that would change an actor's category affect no row
today; they matter for what gets classified next.

| Category | Actors |
|---|---|
| `research_center` | 274 |
| *(none)* | 156 |
| `company` | 146 |
| `university_academic` | 130 |
| `association_network` | 73 |
| `government` | 64 |
| `national_laboratory` | 49 |
| `startup` | 40 |
| `innovation_platform` | 16 |
| `foundation_nonprofit` | 8 |
| `investor` | 7 |
| `hospital_clinical` | 2 |

> `national_laboratory` holding 49 actors is worth a look. The Intern Guide
> requires a formal FFRDC or charter designation, and the United States has
> roughly 40 FFRDCs in total. Some of these are likely Category 2
> Government-Affiliated under the Guide. That is a review question, not
> something to change automatically.

---

## Not done

- **No backfill of any kind.** `actor_sector` stays empty, no category type was
  written, and no membership changed.
- **No `VALIDATE`** on the `NOT VALID` constraints. Each scans a whole table and
  may fail on legacy rows, so each belongs to its own reviewed step.
- **Production is untouched**, and these migrations remain proposals for the
  schema owner.

## Reproducing this

```bash
# the instance, if it is not running
pg_ctl -D C:/Users/Ismail/GHUS-data/postgres/ghus-pg-v2 -o "-p 55432" start

export PGHOST=127.0.0.1 PGPORT=55432 PGUSER=ghus_test PGDATABASE=ghus_v2_review_redesign_test
psql -c "CREATE DATABASE ghus_v2_review_redesign_test TEMPLATE ghus_v2_phase12_full_test" postgres
for f in agents/sql/510_*.sql agents/sql/520_*.sql agents/sql/530_*.sql \
         migrations/proposed/deferred/545_*.sql; do
  psql -v ON_ERROR_STOP=1 -f "$f"
done
python -m scripts.taxonomy_intern_guide_mapping
```
