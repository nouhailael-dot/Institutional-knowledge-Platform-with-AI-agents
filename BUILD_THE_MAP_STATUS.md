# Build the Map — Progress Status

_Last updated: 2026-08-19_

## What we're building

A new feature for the UM6P Intelligence platform called **"Build the Map"** — a
third tab alongside Ask and Browse. The user describes a domain they want mapped
(e.g. "fintech in Boston"), optionally uploads a document, and an AI agent
searches the web to find relevant **organizations, people, and events** — US only —
and returns them as structured results matching the platform's database.

## How it works (plain English)

The agent runs in four stages:

1. **Planner** — reads the user's request and decides what to search for and which
   entity types to look for (organizations / people / events).
2. **Discovery** — searches the web for each topic and collects the entities it finds.
3. **Detail pass** — visits each entity to fill in missing information (optional).
4. **Cleanup** — merges duplicates so the same organization doesn't appear twice.

Results come back grouped into Organizations, People, and Events.

## Where we are now

**The agent itself is built and working.** All the core logic is written:

- ✅ Planner — tested, produces good search plans.
- ✅ Discovery — tested, finds real entities from the web.
- ✅ Detail pass — built.
- ✅ Cleanup/dedup — tested, correctly merges duplicates.
- ✅ Orchestrator that runs all four stages together (with parallel execution for speed).

**Two issues found during testing and fixed:**

1. The output format we first used was too complex for the API and made every
   search fail. Simplified it — now works.
2. The agent was cutting off mid-answer because it tried to do too much in one go.
   Gave it more room and told it to work leaner. Fixed.

The final verification run **passed** — a single search returned 11 real US
organizations (Oishii, Bowery Farming, 80 Acres Farms, Little Leaf Farms, and
more), each with a name, location, and website. Discovery is reliable.

## What's left to do

- [ ] Build the **backend endpoint** so the app can call the agent.
- [ ] Build the **"Build the Map" page** in the app (text box + document upload +
      results displayed as cards).
- [ ] Test the whole thing end to end from the browser.

## Good to know

- **Cost**: roughly **$2–5 per map** depending on how many entities are found and
  whether the detail pass runs. Much pricier than a normal question (which is
  cents), because the agent makes many web searches. Worth keeping in mind before
  opening it to the team.
- **Speed**: a map takes a few minutes to build — the agent does a lot of
  searching. Results show all at once when done (per your choice).
- **Scope**: US only, by design.

## Files added

All under `src/map_agent/` — a self-contained module, separate from the rest of
the code:
- `planner.py`, `discover.py`, `enrich.py`, `dedup.py`, `pipeline.py`

Nothing else in the project was changed yet. The backend and frontend wiring is
the next step.
