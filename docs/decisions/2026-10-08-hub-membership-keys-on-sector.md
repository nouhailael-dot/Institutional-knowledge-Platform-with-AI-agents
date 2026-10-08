# Hub membership keys on sector, with topic as the secondary signal

| | |
|---|---|
| **Date** | 2026-10-08 |
| **Decided by** | GHUS (Ismail Sabbar) |
| **Status** | Implemented in code, behind `HubDetectionConfig.cluster_dimension`. **Schema change is a proposal awaiting the schema owner.** |
| **Supersedes** | *Architecture V2 Sept* §2.1, §2.2 and §2.3, in the specific respect described below |

---

## The decision

> For an actor to be assigned to a hub, "same topic" is replaced by **"same
> sector"**. Topic becomes a secondary signal rather than the thing membership is
> decided on.

## This overrides the architecture document, and that is deliberate

It has to be said plainly, because the next person to read *Architecture V2 Sept*
will find the opposite written there:

| Architecture V2 Sept | Says |
|---|---|
| §2.1 | "Topic — One topic from the controlled topic list. **A hub is always about one topic.**" |
| §2.2 | "**Test 1: Topic.** Does the actor's topic match the hub's topic? If not, stop — don't check location." |
| §2.2 | "An actor can belong to several hubs on **different topics**." |
| §2.3 | "At least 10 Verified actors, **on the same topic**, from at least 5 different categories…" |

The implementation brief's source hierarchy (A4) says Architecture V2 Sept
governs hubs "**unless a later GHUS decision overrides it**". This is that
override, recorded here so the contradiction is visible rather than buried in a
diff.

**Architecture V2 Sept §2.1–2.3 should be amended to match.** Until it is, the
document and the code disagree, and the code is what runs.

## What the architecture document already supports

The change is not arbitrary. The same document already treats **sector** as the
broad, many-to-many dimension an actor connects through, and **topic** as the
narrow thing a particular search was run for:

| Where | What it says |
|---|---|
| §1 | "a real parent when one exists, **or through sector, geography, and hub** when it doesn't" |
| §5.1 | "Sector and topic — **the sector(s) this actor fits**, and the specific topic it was found for" |
| §6 Case 2 | "The actor still connects into the map fully — **through its sector**, its geography, and its hub" |
| §3 | "A research center can work on water, AI, or **five other sectors**" |

So the decision aligns hub membership with the dimension the rest of the document
already uses for connecting actors into the map. What it changes is §2's choice
to gate on the narrower one.

## Why it matters practically

Hub assignment cannot run on topic today. The Phase 12 dry run records:

```
actor_topic_rows      0
actors_with_topic     0
controlled_topic      965 actors blocked
```

No actor carries a sourced controlled topic, by policy: `actor_topic` stays empty
at cutover because hub membership is not topic evidence and a topic claim needs a
source. A topic-gated Test 1 therefore fails for every actor in the database.

Sector tags, by contrast, already exist in the legacy data with sources attached,
and the hubs themselves were given their topics by reading those same legacy
sector tags (`basis: "single legacy primary sector tag"` for 48 of 48 hubs).
Keying on sector uses the evidence that exists instead of waiting for evidence
that does not.

## What changed in the code

**`agents/common/hub_detection.py`**

| | Before | After |
|---|---|---|
| Partition | one per `topic_id` | one per **sector code** |
| An actor in several sectors | n/a (one topic) | takes part in **each** sector's clustering |
| Test 1 | actor topic == hub topic | actor sector == hub sector |
| Already-assigned exclusion | `already_assigned_same_topic` | `already_assigned_same_sector` |
| Covering-hub suppression | `existing_same_topic_hub` | `existing_same_sector_hub` |
| Rejection fingerprint key | topic | sector |
| Topic | the gate | **recorded on the proposal** as `topic_mix` and the dominant topic |

**Unchanged, deliberately:** 10 independent families, 5 matched categories by
maximum bipartite matching, the 50-mile core, the 200-mile cluster, the family
independence rule, the centre-finding method, determinism, and the rule that
detection only ever produces a **proposal**.

**Reversible without a code edit.** `HubDetectionConfig.cluster_dimension` takes
`"sector"` (the new default) or `"topic"` (the earlier behaviour). The original
Phase 7 regression suite — `tests/agent/test_architecture_v2_hub_detection.py`,
49 tests — now runs explicitly in `"topic"` mode, so the old rule stays proven
rather than deleted. If GHUS reverses this decision, the switch is one config
value.

## Topic is kept, not discarded

Every proposal now carries:

- `dimension` / `dimension_key` — what it was clustered on, and which sector;
- `topic_mix` — every topic its members carry, with counts, most common first;
- `topic_id` / `topic_name` — the cluster's **dominant** topic, ties broken
  alphabetically so it stays deterministic.

The independence statement reads, for example:

> *12 independent families from 10 matched categories work in AGRI, concentrated
> around Sacramento, with every proposed member within 200 miles. Its most common
> topic is FX Precision Agriculture (12 of 13 members).*

An actor found for a different topic now **joins** the hub and its topic is
recorded, where before it was excluded and the information was lost.

## What this depends on

**Migration 520** (`agents/sql/520_v2_sector_dimension.sql`), which restores
`sector`, `actor_sector`, `event_sector` and `hub_sector`. Without it there is no
actor-to-sector link in V2 to key on — see the conformance audit, finding F13.

That migration is a **proposal for local `_test` databases only**. It is not
applied, and production DDL needs schema-owner approval, a verified backup, a
tested rollback and a coordinated deployment.

## Open questions for GHUS

1. **Can an actor's sectors be derived from its legacy `actor_sector` rows**, or
   must each be re-sourced? Migration 520 deliberately backfills nothing, because
   each V2 row needs a V2 `source_id` and the legacy sources must be mapped, not
   invented.
2. **Should a hub answer for exactly one primary sector, or several?** 520 allows
   several `hub_sector` rows with at most one `is_primary`. The detection code
   currently keys on the primary.
3. **Should the 10-family / 5-category threshold change?** A sector is broader
   than a topic, so clusters will be larger and proposals more frequent. The
   thresholds are unchanged for now; that is a judgement to revisit once it runs
   against real data.
4. **CROSS and DIASPORA** are seeded inactive and non-thematic, pending Appendix H
   item 3. If they become selectable sectors, they also become hub dimensions.
5. **Does §2.2's overlap rule still read correctly?** It says an actor passing
   both tests for two hubs on the same *topic* goes to the nearest centre. That
   should now say *sector*.
