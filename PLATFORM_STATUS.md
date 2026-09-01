# UM6P Intelligence — Platform Status

_Last updated: 2026-09-01_

---

## ⚠️ Attention first

**Nothing from the Build the Map work is committed.** The last commit is `9816f3d`,
from before the feature existed. Uncommitted:

- ~623 lines changed across three tracked files (`backend/app.py`,
  `frontend/index.html`, `CHAT_HANDOFF.md`)
- The entire `src/map_agent/` module — 11 files — **untracked**
- `BUILD_THE_MAP_HANDOFF.txt`, `BUILD_THE_MAP_STATUS.md` — untracked

A lost working directory loses all of it.

**The server is not running** — nothing listening on port 8000. Start it with:

```bash
uvicorn backend.app:app --port 8000
```

---

## What the platform is

An internal RAG platform for the **UM6P Global Hubs US team (~4 users)**. It makes a
research database of US innovation ecosystems searchable in plain English, with cited
answers.

This repo is the **application layer only**. The Postgres schema and the ETL that
populates it are owned separately, and **all DB access here is read-only**.

- Working directory: `/Users/ghus/Desktop/um6p-rag`
- Active UI: React + FastAPI (`backend/app.py` + `frontend/index.html`)
- Frozen reference: `app.py` (Streamlit) — not maintained, do not edit
- Python 3.11, conda env at `~/.conda/envs/um6p`

---

## Features

### 1. Ask — working
Multi-turn cited chatbot over the database. Routes between exact SQL lookups and
semantic search (hybrid pgvector + keyword, fused with RRF).

Verified this session: the question *"Which U.S. hubs are most relevant to Morocco's
drought and food systems challenges?"* produced a strong cited answer naming the
California Water Hub, Arizona Water Innovation Hub, and Colorado Sustainability Hub.
It appeared to fail at the time only because file edits restarted the server
mid-stream — the feature itself is fine.

### 2. Browse — working
Filterable Actors / Hubs (49) / Events (231).

### 3. Build the Map — NEW, working
Chat-based web scouting for US research organizations.

---

## Build the Map — how it works

**Conversation → automatic pipeline → cards → on-demand verification.**

**Conversation** (`planner.py`, Haiku, cents)
You describe the map you want. The agent asks only when genuinely ambiguous, then
**decides on its own and starts** — no approval step. It never shows search keywords;
it describes what it will look for in plain language. Hard cap of 2 question rounds
before it must commit (prompting alone did not reliably stop it).

**Automatic pipeline**
1. **Discover** (`discover.py`, Sonnet + web search/fetch, parallel) — one agent per
   search; records a source URL for every entity.
2. **Dedup** (`dedup.py`, rapidfuzz, free).
3. **Enforce the request** (`select.py`, one Sonnet call) — applies what you actually
   asked for: *"only in California"*, *"not thermal"*, *"the 4–5 best"*. Ranks and
   annotates; **never deletes**.

**Results** — cards with DB-schema fields and clickable sources. Matches first;
non-matches collapsed under "Also found".

**On-demand verification** (`verify.py`)
- Link check (`urlcheck.py`, free) — dead and hallucinated URLs
- Independent judge (`judge.py`, Haiku) — separate call, scores relevance + says why
- Relevance floor (`floor.py`) — weak matches separated, never hidden
- The link verdict is fed into the judge, so a dead site counts against an entity

### Defaults
- US only
- ~80/20 weighted toward universities and national labs
- **Organizations only**, unless you ask otherwise
- **Events only when explicitly requested**
- **No TRL** — judgment field, stays human-written (matches the enrichment agent's rule)
- Deep enrichment **off** (cost more than it added)

---

## Measured facts (not estimates)

| | |
|---|---|
| Cost per map | **~$4** (down from ~$12–14) |
| Time per map | **~12 minutes** |
| Test-day total | **$22** — 8,450,538 tokens in · 293,095 out · 242 web searches |
| Input:output ratio | **29:1** — this is an *input* cost problem |

> Every cost and latency figure that was **estimated** during development turned out
> wrong by 3–5×. The numbers above come from the Anthropic Console and a real timed
> run. Measure; do not estimate.

**Why input dominates:** every hop re-sends the whole accumulated conversation,
including fetched page text. The highest-leverage dial is `max_content_tokens` on
`web_fetch` (currently 4000) — cutting it saves those tokens on *every* remaining hop.

**Speed note:** all search tasks run in parallel (10 workers), so total time equals the
**slowest single task**. Reducing the *number* of searches cuts cost but not time.
Only `MAX_HOPS`, tool `max_uses`, and `max_content_tokens` affect the 12 minutes.

---

## Verified by real runs

- **58 entities** (27 organizations, 25 people, 6 events) with correct cities, real
  founders and accurate titles, real conference venues.
- **38 entities**, academic-focused run — *every one* a university lab, national lab,
  research center, or venture studio; **all with sources**; including named PI-level
  labs (Hatton Lab at MIT, Amanchukwu Lab at UChicago).

---

## Open risks

**No persistence.** Map results live in memory and die on server restart. Two runs were
lost this way, one costing ~$12. This is the storage decision still open in the handoff
and the first thing worth closing.

**No auth**, on endpoints that cost ~$4 per call. Do not expose beyond localhost.

**Handoff docs are stale** — `BUILD_THE_MAP_HANDOFF.txt` and `CHAT_HANDOFF.md` are
several changes behind the code.

**Not re-measured** since the most recent changes: cost and time after removing the
"don't write code" prompt rule, and the new server-tool error handling — which is
defensive code verified only against synthetic inputs, never seen fire for real.

**Enrichment** has its sources-destroying bug fixed (it now merges instead of replacing)
but is off by default and has not been exercised since the fix.

---

## Discussed, not built

**A UM6P context file.** A standing half-page — priority domains, the
Morocco-transferability lens, what makes a partner valuable — applied at the
**selection stage only**, so discovery stays broad and unbiased.

The design principle agreed: strategy context **ranks and explains, it never filters**.
Since the selection stage already never deletes, the worst case of a wrong or stale
strategy is a suboptimal ordering on a page that still contains everything found.

Blocked on: your actual priorities, in your own words.

---

## Notable corrections made during development

Three claims that turned out wrong, now fixed in code and documented so they are not
repeated:

1. **Cost and latency estimates** were 3–5× off. Now measured.
2. **`code_execution` calls in traces were not misbehavior** — the `_20260209` web
   tools run code execution internally for dynamic filtering. A prompt rule telling the
   model to avoid it was fighting the feature; the rule has been removed.
3. **Sonnet 5 pricing** is $2/$10 per MTok, not the $3/$15 used in an earlier
   calculation. That single error explained the whole gap between a $32 prediction and
   the $22 actual bill.

Two real bugs found by running the thing for real, both fixed:

- **Enrichment silently destroyed every entity's sources** by replacing records with
  the model's tool output instead of merging. This gutted the whole verification layer.
  *Lesson: any stage returning a model-shaped dict must merge, not replace.*
- **The planner replied in prose and the code discarded it**, producing a silent empty
  map. Prose is now a first-class response (it is how the agent asks questions).

---

## Repo structure — map agent

```
src/map_agent/
  planner.py    Chat + plan. Parses the request into a SPEC (hard_filters,
                preferences, result_limit), not just a topic.
  discover.py   Per-task web-search agent. Records sources. Detects server-tool errors.
  enrich.py     Optional per-entity detail pass. OFF by default.
  dedup.py      rapidfuzz merge. No LLM.
  select.py     Enforces the request against the full candidate set. Never deletes.
  verify.py     Phase-2 chain: urlcheck → judge → floor.
  urlcheck.py   URL liveness. Pure Python.
  judge.py      Independent relevance judge. Separate Haiku call.
  floor.py      Relevance threshold. Flags, does not delete.
  pipeline.py   Orchestrator.
```

**No agent framework** (LangChain/LangGraph deliberately avoided — the flow is a linear
chain of plain functions at this scale). **No scraping library** — Anthropic's servers
fetch and extract page text.

---

## Suggested next steps

1. **Commit the work** — it is all uncommitted.
2. **Add result persistence** — a $4, 12-minute run should not die on a restart.
3. **Write the UM6P context file** — needs your priorities.
4. **Refresh the handoff docs** to match the code.
5. Later: auth, before this is shared anywhere.
