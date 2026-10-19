# The complete workflow, run for real — 2026-10-15

Discovery → Entity Resolution → Classification → Light Pull → Hub Assignment →
Review / Verification, run end to end on the **isolated** demonstration
database (`ghus_v2_demo_test`, 127.0.0.1:55432, migrations 550 and 560
applied). Nothing was run against the shared Supabase database. A backup copy
was taken first: `ghus_v2_demo_backup_20261015_test`.

Decisions were made through the platform's own HTTP API, exactly as the Review
page makes them, and the results were then read back from the database.

## What the run proved

| Step | Result |
|---|---|
| **Light Pull on real pages** | 9 organisations read, 3 pages each, **$0.344 total** (≈ $0.038 each). Every box answered. |
| **Admission → actor created** | Clean Energy Group and CPower Energy created as **Parked**, with 19 and 18 Layer 1 facts (16 and 15 found). |
| **Classification** | foundation_nonprofit / operating_nonprofit and company / private_company, from the pages' own self-description. |
| **Hub assignment** | Deterministic: an assignment plan was written for each; a reviewer's **proposed hub** ("Vermont Clean Energy Hub") was recorded as `pending` for the hub owner, not created. |
| **Verification** | Both verified through Review: `decision_origin = ghus_review`, scoped to the ENERGY topic. Status moved Parked → Verified by the trigger, never written directly. |
| **Deep Pull gate** | `actor_is_verified_for_topic` → **True** for the reviewed topic, **False** for another topic of the same actor. |
| **Duplicate prevention** | 3 of 5 candidates were refused as duplicates — correctly (below). |
| **Existing-actor update** | Re-reading two existing actors added **no** actor and **no** duplicate fact: unchanged values were recorded as corroboration. |
| **Hub-less actors** | Both new actors remain in the detection snapshot, excluded only with the stated reason `missing_deterministic_geography`. |

## Duplicate prevention, in detail

| Candidate | "New actor" | Outcome |
|---|---|---|
| North Dakota Water Users Association | refused | exact **website domain** match with an existing actor — the message now names it |
| Energy & Environmental Research Center | refused | close model match → possible duplicate; a person must choose |
| Department of Water Resources (DWR) | refused | exact domain match with the verified *California Department of Water Resources* |
| → then "same existing" | accepted | **one immutable fact appended** (`discovery_sighting`) to the existing actor: facts 13 → 14, actors on that domain unchanged at 3 |

## What each Light Pull read produced

| Organisation | Pages | Boxes found / asked | Cost |
|---|---|---|---|
| Clean Energy Group | 3 | 7 / 10 | $0.049 |
| CPower Energy | 3 | 7 / 9 | $0.045 |
| NEW Water (Green Bay MSD) | 3 | 6 / 9 | $0.035 |
| North Dakota Water Users Association | 2 | 6 / 12 | $0.034 |
| Indiana Water Resources Research Center | 3 | 5 / 11 | $0.034 |
| Energy & Environmental Research Center | 3 | 4 / 11 | $0.034 |
| North Dakota Rural Water Systems Association | 3 | 4 / 9 | $0.027 |
| California Water Efficiency Partnership | 3 | 6 / 10 | $0.041 |
| KGAN CBS 2 (a rejected example) | 3 | 4 / 9 | $0.047 |

Every remaining box reads **"Not Stated on the N Pages Read"**, with those
pages linked in Review. No box reads "Not Yet Collected" after a read.

## What is NOT filled, and why

You asked for nothing to be left as not found. Two honest limits:

1. **A page that does not say it.** Where the organisation's own three pages
   say nothing about, say, a Morocco connection, the box says exactly that,
   and names the pages checked. Filling it would be inventing data
   (Architecture V2 rule 7). Reading more pages per actor is possible — the
   3-page bound is Architecture V2's, and raising it is your decision.
2. **Sites this machine cannot reach.** 11 reads failed with connection
   timeouts (thewatercouncil.com, ndwater.org, cleanegroup-adjacent energy
   sites, nsf-engine, ctgreenbank, suncommon…). `curl` fails on them too, so
   it is this network, not the code. Nothing is saved for them and they are
   read again on the next run.

Two boxes are worth noting: **Location** was not stated on the pages for Clean
Energy Group and CPower Energy, and location is what hub detection needs. A
reviewer can type the city and state in Review; geocoding then runs at
promotion.

## Defects found by running it, all fixed

1. **No reviewed actor could be created at all.** Admission rejected the Review
   screen's own fields — `actor_category`, `category_type`, `category_note`,
   `primary_sector`, `region` — as "unsupported edited fields".
2. **Promotion collected almost no Layer 1 facts.** A reviewed candidate had
   no topic, and the whole Light Pull is topic-scoped: the first actor created
   got **1 fact**; after the fix, 19.
3. **The admission bridge ran the wrong interpreter** (`python` from PATH), so
   every decision failed with "exited with code 1"; its 120 s timeout was also
   too short for the entity-resolution model to load.
4. **A Parked actor could not be verified from Review** — the screen had no
   path to the `verify_actor` decision.
5. **An over-long field blocked two candidates** with an error naming no field.
6. **Admission did not apply the exact domain/name rule** that discovery
   applies, so a renamed organisation on a known domain could be created twice.

## Reproducing it

```bash
# 1. Light Pull for a request's kept candidates (dry-run without --live)
cd C:/Users/Ismail/Projects/GHUS-Platform
DATABASE_URL="postgresql+psycopg://ghus_test@127.0.0.1:55432/ghus_v2_demo_test" \
  python -m agents.collection.light_pull_candidates --request-id <REQUEST_ID> --live --max-usd 0.45
```

```bash
# 2. The same, for existing actors (writes immutable facts, creates nothing)
cd C:/Users/Ismail/Projects/GHUS-Platform
DATABASE_URL="postgresql+psycopg://ghus_test@127.0.0.1:55432/ghus_v2_demo_test" \
  python -m agents.collection.light_pull_candidates --actors --live --max-usd 0.15
```

```bash
# 3. The platform, against the same isolated database
cd C:/Users/Ismail/Projects/Institutional-knowledge-Platform/.claude/worktrees/frosty-gates-7e6f7a
.venv/Scripts/python.exe -m scripts.run_demo_server --port 8030
```
