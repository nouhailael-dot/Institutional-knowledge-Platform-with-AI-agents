# Migration 820: topic becomes sector, and nine more tables go

Platform owner's decision of 27 Nov 2026 (after the 25 Nov meeting). Written for the
database after 810.

Status: **ready, not applied.**

## Topic and sector were the same list

`topic` held the eight thematic sectors again: the same codes (AGRI, AI, CHEM, ENERGY,
HEALTH, MINING, SUSTAIN, WATER) and the same names. Twelve tables pointed to it: the facts
(674), the current-value pointers, verification history, requests (59), Review items (98),
hub evidence (138) and more, and every hub carries one.

Most of those are append-only records. Instead of rewriting them, **each of the eight
sectors takes the id its topic had**. Their links follow: 779 organization links, 88 event
links and 48 hub links get the new ids. Then every stored `topic_id` simply names a sector,
and the twelve links point to `sector`. The column keeps its name `topic_id` until the
actor → organization rename; it now holds a sector id.

The organization-sector links (`actor_sector`) are append-only: the migration switches that
guard off for the one statement that moves their ids and on again in the same transaction.
Verify checks it is on.

## Removed

| Table | Rows (27 Nov) | Why / where it went |
|---|---|---|
| `topic` | 8 | The same list as `sector` |
| `actor_topic` | 15 | Organization ↔ topic links; `actor_sector` holds the same (779) |
| `event_topic` | 2 | Event ↔ topic links; `event_sector` holds the same (88) |
| `actor_location` | 818 | One row per organization, identical to its own city, state and coordinates (the migration refuses otherwise) |
| `actor_relevance`, `challenge` | 130, 1 | The June NutriCrops assessment; archived |
| `person_discovery_profile` | 0 | Merged into `person`: new columns `research_area`, `public_profile_url` |
| `event_claim` | 1 | Archived; standing claims are kept as event facts from now on |
| `architecture_v2_cutover_attestation`, `architecture_v2_cutover_baseline` | 1, 4 | Records of the 6 Oct move; archived |

Nouhaila's `actor_template` view (730) is recreated without its Topic column, with its
other 20 column titles; the Data Feed templates have no Topic column any more either.

## Code changed in the same commit (works before and after 820)

- The topic list is read through `topic_rows()` (`agents/common/topics.py`, `src/topics.py`):
  the `topic` table while it exists, the thematic sectors afterwards. The ids are the same
  either way, so nothing changes for a person.
- Discovery no longer writes `actor_topic`, `event_topic` or `actor_location` (the sector
  links and the organization's own columns already hold the same); standing event claims
  become event facts; a person's research area and profile page go to `person` once the
  columns exist.
- Review's "Keep both" on a location keeps the second location as an accepted fact and marks
  the organization as having several locations (there is no location table to add it to).
- Hub detection reads an organization's thematic sectors instead of `actor_topic`.
- Ask's index and SQL router no longer read `actor_relevance` / `challenge` (the "Why
  relevant" and "Current evidence" text of 130 organizations leaves Ask's index).
- The Data Feed templates, validation and preview have no Topic column: the topic is the
  record's first sector, as it already was when the column was left empty. A file from an
  older template with a Topic column is still read.

## Archive (outside the repository)

- `C:\Users\Ismail\GHUS-data\backups\archive-820-removed-tables-20261127.sql`: structure and
  rows of the 10 tables.
- `C:\Users\Ismail\GHUS-data\backups\archive-820-sector-links-20261127.sql`: `sector` and its
  three link tables with their ids before 820.
- Full backup: `supabase-before-820-20261127T113158Z-without-raw-document-rows.dump`.

## Rehearsal (27 Nov 2026)

On `ghus_820_rehearsal_test`, restored from that backup (without Ask's search index, which
needs pgvector):

- the new code before 820: the Directory (744 organizations, 48 hubs all with their sector,
  361 events, 7 people), Ask's index (744), the request form, Data Feed and map planner
  sector lists (8), Review, hub detection and the deletion policy all work;
- preflight 9 of 9; apply; ledger; verify 9 of 9; a second apply refuses; nothing lost:
  779 / 88 / 48 links and 674 facts with a sector before and after;
- the same checks with 820 applied: all work, every id the same;
- rollback: the schema is identical to before 820 (0 lines differ), the eight sectors have
  their own ids again, `topic` and its 12 links are back, and the archive's COPY sections
  bring back every row; 820 applies again afterwards (verify 9 of 9).

## Apply sequence (Supabase SQL editor; one script per run; a quiet window)

0. **Deploy the commit that carries 820 first.** The code deployed before it reads `topic`,
   `actor_location` and the profile table directly.
1. No Discovery, Update or Data Feed run in progress; tell Nouhaila (her `actor_template`
   view changes). Fresh backup with `pg_dump` if the one above is no longer the latest.
2. `preflight.sql`: every row `ok = true`. Stop otherwise (the migration would refuse anyway).
3. `../deferred/820_topic_into_sector_and_cleanup.sql`: one transaction.
4. `ledger.sql`.
5. `verify.sql`: every row `ok = true`.

## Rollback

1. `../deferred/rollback/820_topic_into_sector_and_cleanup.sql` (puts back `topic` with its
   eight rows, the sectors' own ids, every link and the original template view).
2. `DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '820';`
3. Rows, if needed: the archive's `COPY` sections (`challenge` before `actor_relevance`;
   skip `topic`, already filled).
4. Deploy the code from before 820.
