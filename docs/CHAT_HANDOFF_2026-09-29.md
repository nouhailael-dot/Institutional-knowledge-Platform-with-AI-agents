# UM6P Intelligence — Chat Handoff, 29 September 2026

Paste this into a new chat to pick the project up cold. It is the current state
summary. It does **not** repeat the project's history — that lives elsewhere (§1).

---

## 1. Read in this order

| File | What it is | Trust |
|---|---|---|
| **This file** | Current state, open risks, what to do next | Current |
| **`Architecture V2 Sept.docx`** (user's Downloads) | **THE SPEC OF RECORD.** Categories, regions, two-layer pull, field lists, linking rules | **Authoritative** |
| `docs/ACTOR_PROFILE_V2.md` | Implementation notes for the V2 actor contract | Current |
| `docs/CHAT_HANDOFF_2026-09-21.md` | Previous consolidated handoff; people-search detail | Mostly current |
| `docs/PROJECT_CHANGE_HISTORY.md` | Narrative history, honest about requirement vs prototype vs done | Historical |
| `docs/MAP_COST_TRACKING.md` | Cost/recovery operational detail | Current |

The superseded root handoffs (`HANDOFF.md`, `HANDOFF_CURRENT.md`, `CHAT_HANDOFF.md`,
`BUILD_THE_MAP_HANDOFF.txt`, `BUILD_THE_MAP_STATUS.md`, `PLATFORM_STATUS.md`,
`ARCHITECTURE_PROPOSAL.md`, `Tech_Summary.md`) were deleted on 1 Oct along with the
Streamlit `app.py` the React frontend replaced. They are in git history if ever needed.

When the spec and any meeting note disagree, **Architecture V2 wins** unless the
team says otherwise (see §6 — there are three live contradictions).

---

## 2. What the platform is

Internal research platform for the **UM6P Global Hubs US team**. Local tool,
no authentication, `localhost:8000`. The production database is **read-only from
this repo**; schema and ETL are owned by a colleague (Ismail). The platform does
**not** write actors, people or hubs into that database.

| Feature | Purpose | Paid? |
|---|---|---|
| **Ask** | Question the existing database; SQL + semantic, cited answers | Yes (outside the map ledger) |
| **Browse** | Filter/inspect actors, hubs, events | No |
| **Build a Map** | Research organizations beyond current coverage | Yes — metered, budgeted |

**Run:** `uvicorn backend.app:app --port 8000`. Use **`.venv/bin/python`** (not the
conda env) — it is what the server runs. Tests use `unittest`, not pytest.

---

## 3. Architecture as it stands

Active map path is **controlled research** (`research.py` via
`pipeline.build_map`). Legacy autonomous discovery/enrichment modules were
**deleted** (`discover.py`, `enrich.py`) — do not reference them.

```
src/map_agent/
  research.py          ACTIVE controlled workflow — resumable, bounded, sequential
  actor_profile.py     NEW. V2 contract: 12 categories, 7 regions, normalization
  entity_schemas.py    Extraction schemas (V2 fields patched on after definition)
  search_backend.py    Claude search adapter, bounded page reads, evidence cache
  costs.py             THE paid-call gateway. Nothing else may pay
  run_store.py         Durable jobs/usage/checkpoints in SQLite; recovery
  people_research.py   User-directed people search ($1 separate allowance)
  people_validation.py Conservative affiliation checks
  relationships.py     People ↔ organization merging, multi-affiliation
  rankings.py          Approved ranking publishers + validation
  planner.py           Conversational planning; prompt now frames discovery as light pull
  select.py            Request enforcement/ranking. Never deletes
  verify.py, judge.py  Verification orchestration + model judgment
  export.py            Excel / PowerPoint, includes V2 columns
  client.py            Lazy API client
```

**Money:** every paid call goes through `costs.paid_message`. Integer micro-USD
reservations in SQLite. **$2 default map allowance**, explicit extension to **$3
total**, **$1 separate allowance per deeper people search**. Unknown charges block
further paid work rather than being treated as free. **This is not a provider
billing ceiling** — local estimates have previously diverged from the Claude
dashboard and that reconciliation is still open.

**Known API issue:** Claude's `count_tokens` endpoint rejects the server-side
web-search tool (HTTP 400). The gateway falls back to a conservative local
estimate for those requests.

---

## 4. What landed most recently (28–29 Sept)

Architecture V2 arrived as a written spec and was **substantially implemented**:

**New:** `actor_profile.py`, `docs/ACTOR_PROFILE_V2.md`, `tests/test_actor_profile.py`
(5 tests, passing).

- **Seven regions** replacing the old five-region National Geographic map.
  Verified state-by-state against the spec — all correct, including DC in
  Mid-Atlantic and Washington State in West Coast / Pacific. Frontend updated too.
- **`actor_type` is now an enum of the 12 spec categories**, replacing free text.
  This is the fix for the demo bug where a consortium was labelled a university.
- **New actor fields:** `other_names`, `category_note`, `sector`, `mapped_topic`,
  `match_strength` (strong/moderate enum), `match_explanation`,
  `international_connections`.
- **`actor_relationships`** — typed links (`unit of`, `operated by`, `member of`,
  `portfolio of`, `spinout of`, `funded by`, `collaborates with`), each requiring
  a source URL.
- **`multi_location`** — boolean, set when the collected evidence shows more than
  one physical location.
- **Rankings** widened to approved publishers, plus `ranking_name` and
  **`ranked_entity`** (implements the rule that a department never inherits its
  university's ranking).
- **Removed** `people` from actor extraction (V2: people only on explicit request)
  and `technical_approach`.

**`normalize_actor_profile()` enforces rather than trusts:** it strips
`record_status` / `ghus_notes` / `verification_history` so the model cannot mark
anything Verified, and strips `hub_status` / `um6p_ocp_status` so it cannot
pre-empt workflow fields it has no basis to set. It computes region rather than
extracting it, type-checks `category_details`, and keeps a relationship only when
its `source_url` was actually read.

**Per-fact provenance (`field_evidence`) was tried and removed.** An earlier pass
required the model to restate every fact inside a `field_evidence` array and
dropped any field whose evidence row did not match. That contract is gone: the
field is stripped if the model emits it, and actor sourcing is back to the
entity-level `sources` list. If per-fact provenance returns, note that the
original implementation compared field and evidence with exact string equality —
which silently deleted well-sourced facts whenever the model reworded itself
between the two. Normalize before comparing, and record drops rather than
vanishing them.

### Landed 1–5 October

- **Ask → Build the Map bridge.** One "Research this on the web" action per Ask
  conversation condenses the WHOLE thread into editable rows (topic, must be,
  exclude, prefer, limit) plus a known-actors toggle. The rows generate the request;
  "Edit as text" switches authority to the textbox. Known actors travel separately
  as `ask_context`, injected for the planner like an attached document, so they never
  become the request that selection grades against. Nothing spends until Send.
  Carrying over resets to a fresh map rather than landing on the last saved one.
- **Build the Map is a continuous conversation.** The thread stays open after a map
  is built. The planner sees the found organizations and answers questions about
  them in prose; only a request for new ground produces a plan, whose tasks are
  appended to the saved workflow and merged into existing results. The forced-plan
  guard applies only before a map exists. Once results exist, the stored request is
  kept rather than re-joined from every message, so questions cannot contaminate it.
- **Selection repaired.** Its 1024-token cap was exhausted by thinking on maps of
  ~9+ candidates, so it never answered and filters were silently unapplied on 5 of
  11 maps. Now 8000 tokens at medium effort; every exclusion carries a reason; the
  outcome (applied / no requirements / none matched / failed) is stored and stated
  plainly; results are one list with exclusions marked rather than folded into
  "Also found". Its replay key was a fixed name, so selection could run only once
  per map — follow-up candidates were never judged. It is now keyed on its inputs.
- **Export** no longer fails when selection rejected everything; **extraction**
  ceiling raised 4096 → 16000.
- **Cleanup.** Removed the superseded root docs, the Streamlit `app.py`, the unused
  `src/enrich/`, `.codex_tmp/`, the July data-quality scan, and the unused `groq`,
  `streamlit` and `sse-starlette` dependencies. `outputs/` moved to
  `~/Desktop/um6p-outputs/`. `evals/` kept — the only retrieval quality check.

---

## 5. ⚠ The highest-priority open risk

**V2 extraction has never been run against real model output.** Every test uses
hand-written fixtures and mocked responses, so passing tests demonstrate that the
contract is enforced — not that the model fills it well. Unknown until a live run:
how often `actor_type` lands outside the 12 categories (and so trips
`category_note`), whether `match_strength` / `match_explanation` are grounded or
plausible-sounding, how often `actor_relationships` are dropped for an unread
`source_url`, and whether `multi_location` is set on evidence or on assumption.

**Run one real map and read the output field by field before putting it in front
of reviewers.** Live research is enabled (`MAP_RESEARCH_ENABLED=1` in `.env`), so
this costs real credits against the $2 map allowance.

---

## 6. ⚠ Three unresolved contradictions

The last meeting minutes and Architecture V2 disagree. **The spec's side is what
is now in code**, so the minutes are the outlier. Needs a team decision:

| | Meeting minutes | Architecture V2 (in code) |
|---|---|---|
| ~~Rejected records~~ **SETTLED 5 Oct** | ~~Deleted after 24h~~ | **Spec wins: record stays, reason recorded. See the agreed design at the end of §7** |
| New-hub detection | ≥10 actors, ≥5 categories, incl. major university | **≥3 Verified actors, ≥2 categories, independent** |
| Hub location test | 50 mi centre / 200 mi hub | **Compare to actors already in hub — "no distance calculations"** |

The 3-vs-10 gap is the consequential one — it changes how often the platform
proposes new hubs. **Both remaining rows are being handled by a colleague working
on the updating agent, not here.**

---

## 7. Decisions taken (do not relitigate)

- **Ask and Build a Map STAY SEPARATE.** The earlier "unified workspace" direction
  was **reversed** at the last meeting, to protect verified-data reliability and
  control credit use.
- **When Ask cannot answer, a "Build a Map" button** generates a short prompt
  summarising the conversation and opens Build a Map with it. This is the
  permanent design, not an interim workaround.
- **Claude proposes, GHUS decides.** Only a GHUS person sets Verified or Rejected.
- **Two-layer pull:** light pull on discovery → Parked; deep pull only after GHUS
  verifies. Deep pull is **topic-scoped**, not a general profile — the same actor
  mapped for agriculture and later for AI gets different deep-pull content.
- **Hub definition methodology** was parked, then superseded by Architecture V2 §2.

### Agreed design for the Ask → Build a Map bridge (not yet built)
- Button always present but **promoted** when the answer looks thin (zero hits,
  SQL error, hedged answer). Detection does not gate spending — the user clicks.
- Generate the prompt **on click**, not speculatively on every answer.
- **Carry the constraints, not just the topic.** If the conversation established
  "in California", "universities only", those must survive into the prompt so the
  planner's requirement extraction picks them up.
- **Prefill, never auto-send.** Client-side state transfer only (all pages stay
  mounted) — no backend session plumbing.
- Carry `doc_id` if a document was attached in Ask.
- Do **not** offer it for out-of-scope questions.

### AGREED 5 Oct — Verify, Reject, and the confirm before follow-up research

Decided in discussion, **not yet built**. This supersedes the open questions in the
parked spec below and settles contradiction #1 in §6.

**Verify pushes to the production database, in batches.**
- Verify will eventually push the organization and its fields to the production DB;
  column names get matched to what the map pulls, and most already match.
- The write happens through a **"Push all verified"** button, not per card, so a
  single misclick cannot push anything.
- When user accounts exist, the approver's name is attached to the approval.
- Route every DB write through one module, so a schema change on Ismail's side is
  one file to fix rather than a hunt.

**Reject is added next to Verify — and nothing more.**
- Two explicit states plus "untouched". Do **not** build the full
  Imported / Parked / Verified / Rejected lifecycle; it is ceremony until something
  downstream treats the extra states differently.
- Records a timestamp, an optional one-line reason, and the map it belonged to.
  Nothing is deleted — the map keeps every organization.
- **Rejections never surface in a later map.** No flagging, no filtering, no
  "previously rejected" label. An organization irrelevant to one topic can matter
  for another, and judging two topics "the same" is too fuzzy: a wrong match would
  anchor the reviewer against a good organization before they read a word. Record
  it, do not act on it — the stored reason still answers "why isn't X in here?"
  months later.
- Inside one map it tidies the review list and gives a progress signal:
  *6 verified · 3 rejected · 5 not reviewed*.

**Follow-up research asks once before it runs.**
- When the planner decides to search on a map that **already has results**, show its
  sentence with a **"Start searching"** button instead of starting immediately.
- One extra click, only on follow-ups, never on the first run. **No dollar figures
  in chat** — the usage panel already shows the budget.
- Why: with the thread permanently open most messages are free questions, so an
  ambiguously phrased one ("what about national labs?") could otherwise launch a
  paid multi-minute run with no moment to say "no, I meant the ones already here".

**Out of scope here:** §6 contradictions #2 and #3 (new-hub thresholds, hub location
test) are being handled by a colleague on the updating agent.

### PARKED — Verify as a save action, and checks that run before display

**Status: parked 29 Sept. Designed, not scheduled. Do not start without saying so.**

This records the *original intent* behind the verification layers and the Verify
button, which the current build does not implement. It is written down because
the code reads as though the intent was something else, and a future reader will
otherwise assume the present behaviour was the design.

**The intent was two separate things:**

1. **Checks establish legitimacy _before_ results are shown.** Today they run the
   opposite way — [verify.py](../src/map_agent/verify.py) says they run "ON DEMAND,
   after the user has already seen the fast phase-1 results." The split was driven
   by the ~$4 / ~12-minute cost measured in `6833b3f`, and it quietly traded the
   goal away.
2. **The Verify button is the human's act of accepting a record and storing it** —
   not a quality check. This is §7's "Claude proposes, GHUS decides" expressed as a
   button, and it is the same thing as the Imported / Parked / Verified / Rejected
   lifecycle listed unbuilt in §8.

**Where that leaves the naming.** "Verify" is the correct label *for the intended
behaviour*. The rename to "Check evidence" (since reverted) moved away from the
intent rather than toward it. The label was never the problem — the behaviour is.

**What already runs pre-display, and what does not:**

| Question | Answered pre-display? | By what |
|---|---|---|
| Is this what I asked for? | **Yes**, automatically | `select.apply_request` ([research.py:240](../src/map_agent/research.py:240)), Sonnet |
| Did we actually read this source? | **Yes**, automatically | `_source_filter` ([research.py:67](../src/map_agent/research.py:67)); sourceless entities are dropped and counted |
| Does the `website` URL resolve? | **No** | `urlcheck`, only on click |
| Is this entity plausible? | **No** | `judge`, only on click |

Note `select` never sees a URL — `_render` sends name, type, location, focus and a
description slice, no `website` and no `sources`. And `_source_filter` is a
provenance test ("did this run retrieve this page?"), which is *stronger* than
liveness against invented URLs but says nothing about the `website` field or about
sources recorded as `search_snippet`, where the page fetch failed.

**If this is picked up, the shape it should take:**

- Run `urlcheck` automatically at the end of a map (`verify(..., run_judge=False)`).
  It is free and pure Python, and it closes the `website` gap — the URL a reviewer
  is most likely to click.
- Reconsider `judge` on its merits. `select` already grades relevance against the
  original request, automatically, on a higher model tier. The judge's remaining
  distinction is independence (it did not choose). Measure its real cost with
  `resp.usage` before assuming it is worth a per-entity call; §13 applies.
- If `judge` goes, `floor` goes with it — `_below_floor` reads judge scores. Drive
  weak-match styling off `select`'s `_rank` instead.
- **Verify must not cost money.** A reviewer presses it on every good actor; a
  paid action is the wrong shape for a save.
- **Storage:** the production DB is read-only from this repo and Ismail owns the
  schema (§2), so this means a new verified-records table in the existing SQLite —
  which is also the natural handoff artifact for his ETL, not a workaround.
  `run_store` today has `runs`, `calls`, `budget_approvals`, `work_cache`,
  `people_tasks` and **no actors table**; actors live only inside a run's
  checkpointed result JSON.
- **Key records by actor identity, not by run.** §7's topic-scoped deep pull means
  the same actor is mapped for agriculture and later for AI; one record should
  carry both rather than producing two.
- Whatever is shown must not read as a clearance. A model's opinion cannot
  establish that an organization is real, and a teal ✓ implies it does. Prefer
  "on-topic 0.82" to a checkmark.

---

## 8. Not yet implemented from Architecture V2

- **Hub assignment logic** (§2.2 topic-then-location test). `hub_status` is now
  stripped rather than defaulted, so actors arrive with no hub field at all until
  this exists.
- **New-hub detection** (§2.3 pattern flagging).
- **The Association/Consortium parent-child rule** (§5.1) — the `multi_location`
  boolean now exists, but nothing consumes it to split a statewide network into
  one parent with linked child locations.
- **Status lifecycle** (Imported / Parked / Verified / Rejected) as a working
  workflow, verification history, GHUS notes. See the parked spec at the end of §7
  — this is the same feature as "Verify stores the record", and the intent behind
  the existing button.
- **Duplicate check before creation** (§6 rule 2: name, alt names, especially
  website domain; exact → merge, close → flag, never auto-merge).
- **Deep pull per category** (§5.2 lists).
- **UM6P/OCP sweep** (§5.5) — `um6p_ocp_status` is stripped during normalization;
  neither the field nor the sweep survives a map run.
- **Manual input page**, **weekly scheduled hub agent**, **verifier attribution**
  (needs accounts, which don't exist).

---

## 9. Two design tensions worth raising

**`category_details` reintroduces a naming problem.** The generic `label`/`value`
array cleverly avoids twelve category schemas, but free-text labels will produce
"Funding stage" / "Stage" / "funding_stage" across actors — directly against the
meeting's requirement that field names and capitalisation be identical everywhere.
Spec §5.2 already enumerates per-category items; those could become a controlled
label vocabulary.

**There is no per-field confidence signal any more.** It lived on `field_evidence`,
which was removed, so every extracted field now arrives looking equally certain and
a reviewer cannot tell a firmly sourced value from a thin one. Acceptable while
sourcing is entity-level, but it means review effort cannot be prioritised.

---

## 10. Git state

Everything through 5 October is committed. History contains a `wip(ask)` commit
(`1282331`) holding an abandoned first attempt at the Ask bridge; it reached GitHub
before it was replaced. It was **not** force-removed — it is superseded by a merge
that keeps the rewritten bridge. Ignore it when reading history.

`.claude/launch.json` runs `.venv/bin/python`, the interpreter the project expects (§2).

---

## 11. Test status

`.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`

**101 tests, all passing as of 5 Oct** (selection: 7). Suites use mocked
responses and local stores — **no paid research runs in the test suite**. Passing
tests do not demonstrate live extraction quality (see §5). The two `.mjs` suites
are not covered by that command and run separately under node.

---

## 12. What I would do next, in order

1. **Run one real map and read the extracted fields** (§5). Every bug fixed in the
   first week of October was found from real data, not tests, and the new selection
   format has not yet run against the live API.
2. **Decide the fate of the check layers** once Verify becomes a database push:
   proposal is to delete the relevance judge and the weak-match floor (selection
   already does that job) and run the dead-link check automatically after every map.
3. **Build the agreed Verify / Reject / "Start searching" design** (end of §7).
4. Small: say "can't reach the server" instead of silently disabling Send.
5. Later: check location and category filters in code; fixed label list for
   `category_details`; reconcile the cost ledger against provider billing.

Hub assignment and new-hub detection (§6 #2–3) belong to the updating agent.

---

## 13. Standing cautions

- **Never add a second paid-call path.** Everything must go through
  `costs.paid_message` or the ledger silently becomes wrong.
- **Never treat a failed paid call as free.** Blocking on unknown charges is
  deliberate.
- **One API worker per SQLite store.** More than one corrupts budget accounting.
- **Editing files restarts the dev server and interrupts a running map.**
- **Cost and latency figures that were estimated in this project have been wrong
  by 3–5× every time.** Measure with `resp.usage`; do not estimate.
- Distinguish **agreed requirement / prototype / completed** in all reporting.
  Several things look done but are not: hub integration (suggestions only),
  database writes (none), verification (implemented, never live-acceptance-tested).
