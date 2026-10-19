# How the GHUS agents decide — scoring and update rules, with today's results

Prepared 2026-10-19. The figures in section 4 come from the demo database (`ghus_v2_demo_test`), not production.

---

## 1. Discovery: what "Relevance 0.75 · Engagement priority 0.44" means

Each organisation found by a Discovery request gets **two scores**, both between 0 and 1. A model reads the organisation's page and, for each criterion, answers *present* or *absent* with a quote from the page as evidence. The scores are then computed from those answers by fixed, configurable weights. The model does **not** choose the numbers.

### 1.1 Relevance: "Is this a real, in-scope organisation?" (decides keep / review / reject)

| Criterion | Weight | Credited when |
|---|---|---|
| Own organisational page | 0.15 | The page is the organisation's own (official domain, About-type page) |
| Real operating entity | 0.15 | The page shows it operates: staff, programmes, operations, not a list or an article |
| Sector coverage | 0.15 | The page shows work in one of the request's sectors |
| Research, development or programmes | **0.25** | Named research, development work or programmes |
| Partnerships or tech transfer | 0.15 | Named partnerships, licensing, or a tech-transfer function |
| Identity stated | 0.15 | Half for its own website, half for a stated location |

Worked example, Vistra Corp. (today): own page 0.15 + operating entity 0.15 + sector 0.15 + partnerships 0.15 + identity 0.15 = **0.75**. No research or programmes were shown, so 0 of the 0.25.

Relevance deliberately rewards ecosystem **activity**. An earlier version that also credited engagement signals scored a mineral hobby club, a campaign site and a journalism tour like research labs (replayed on 105 stored candidates).

### 1.2 Engagement priority: "How valuable is it for GHUS to engage?" (orders, never excludes)

| Criterion | Weight | Credited when |
|---|---|---|
| GHUS use cases | **0.30** | The share of GHUS's 8 use cases the page evidences: research collaboration, learning expeditions, executive education, mentorship, student and faculty mobility, open innovation, corporate engagement, opportunity development |
| Distinctiveness | 0.15 | 1 ÷ (1 + organisations already mapped in the same hub and sector). New ground scores higher |
| Open programmes | 0.12 | Open calls, accelerators, open programmes |
| Named route in | 0.12 | A named office or contact path (partnerships office, industry liaison) |
| Partnership precedent | 0.10 | Named past partnerships |
| Partnerships or tech transfer | 0.10 | As in relevance |
| Network membership | 0.06 | Member of consortia or networks |
| Hub match | 0.05 | Location and focus match an existing GHUS hub |

Vistra: distinctiveness 0.15 + partnership precedent 0.10 + partnerships 0.10 + hub match 0.05 = **0.40**. No GHUS use cases were found on its page, which is why the priority is low.

### 1.3 How the scores turn into a decision

1. **Reject gates** (any one rejects, whatever the score):
   - the page names no organisation, or could not be read;
   - it is a list, event, news or careers page;
   - it is outside the requested sector or area;
   - it is a closed or defunct organisation;
   - relevance is **below 0.45**.
2. **Accept gates.** All must hold to accept without a person; any failure sends the organisation to Review with the reason shown:
   - the page is on its own website (not a third-party page about it);
   - at least **5 criteria are evidenced**;
   - it is an operating entity, with concrete work shown;
   - the description is real (not a page title or a tagline);
   - the requested sub-topic is mentioned;
   - relevance is **at least 0.80**.
3. **Verifying without a person** additionally needs engagement priority **at least 0.70**, and the environment switch `GHUS_AGENT_AUTO_VERIFY=confirmed`, which needs GHUS's confirmation before it is turned on in production.

So the five "0.75" organisations today all went to **Review** (0.75 is between 0.45 and 0.80). Their Review reason says exactly that: "Score 0.75 is below the accept threshold 0.80."

All weights and thresholds live in `agents/config/sources.yaml`, so GHUS can change a value without changing code.

---

## 2. The Light Pull: how an organisation's boxes get filled

After discovery, or when an actor is updated, the agent reads **up to three pages of the organisation's own website** (home page, About page, one topic or category page). There is no web search. Then:

- **Every box is answered from those pages only.** A value counts only with a quote that is checked to really appear on the page; otherwise it is "Not found".
- **Recency.** "Recent" items older than two years are refused.
- **Evidence rules per box** apply (for example, a donation button is not a funding signal).
- **Location (fixed today):**
  - each page's footer, where addresses are printed, is now read;
  - a location counts only with a city, a state or coordinates — "Not Provided" is never a value.
- **Cost:** about **$0.03 per organisation** (61 recorded reads: $0.030 on average, never above $0.031), capped per run.

---

## 3. The updating agent: it has no score; it follows rules

An actor update does not score an organisation. It decides, box by box, **what to read, what changed, and what may be written**.

### 3.1 Which boxes to read (free preview)

| Scope | Reads |
|---|---|
| General profile | Every box of the actor's category |
| Specific topic | Every box, for one sector, with words that steer which page is read |
| Missing information | Only empty boxes; a "not found" box is re-checked after **90 days** |
| Outdated information | Only values older than **365 days** (**180** for fast-changing boxes: recent activity, funding, projects, pilots, rankings) |
| Specific changes | Only the boxes chosen |

Boxes outside the actor's category are never read, so an inapplicable box is never reported as missing. "Change categories" (funding, partnerships, and so on) only reorder the boxes and steer which page is read.

### 3.2 What each box's result means (the before/after report)

| Result | Rule | Written as |
|---|---|---|
| **New** | Nothing (or only "not found") recorded; the page states it | A new sourced fact |
| **Changed** | A different value, from evidence at least as confident and newer | Replaces the current value; the old one stays in history |
| **Confirmed** | The same fact: the same numbers and at least 70% of the wording; or the page says less than what is recorded | A corroboration of the current value; nothing is replaced |
| **Conflict** | A different value from weaker or older evidence | The current value is kept; the difference goes to **Review** |
| **GHUS value kept** | The current value was set by GHUS | Never overwritten; a pending change goes to **Review** |
| **No change** | The page is silent; a value is recorded | Nothing is written ("not on today's page" is not evidence) |
| **Not found** | The page is silent; nothing is recorded | Recorded as not found |

Confidence ranks high > medium > low. Every fact keeps its actor, sector, box, value, source page, date read, confidence and run. Nothing is ever deleted.

### 3.3 Guards

- **Deep Pull** (deeper boxes) only when GHUS has verified the actor for that exact sector. Otherwise it is refused, with the reason and an offer of the Light refresh.
- **Spend:**
  - **$0.15** at most per actor;
  - each saved request also has a ceiling per run (default $1.50), and the run stops, saying who it did not reach, when the ceiling is reached.
- **Group requests:** at most **10 actors** per run, those with the most gaps first. An actor with nothing to read is not read and costs $0.
- **Related organisations named on its pages** are listed only if their names appear word for word in a checked value:
  - **On the map:** a link proposal goes to Review, with its source.
  - **Not on the map:** offered to Discovery.
- **Hubs:** a membership that no longer fits is reported, never removed. An unassigned actor that a hub now fits gets a proposal in Review. No hub is ever created.
- **Location (new today):** a location found on the actor's own pages fills its empty city, state, region and coordinates. The place must exist in the US Census gazetteer, and a recorded value is never overwritten.
- **Derivations from the record** (new today), only when unique:
  - the state of a city that exists in only one US state;
  - coordinates of a city in the record's own state ("Urbana-Champaign" → Urbana, IL);
  - the region from the state;
  - the state from the name ("University of Texas at Austin" → Austin, TX; never "Washington" alone).

---

## 4. Today's results (demo database)

### Discovery requests

| Request | Pages found | Accepted | To Review | Rejected | Cost |
|---|---|---|---|---|---|
| Water reuse and desalination organizations in California | 91 | 1 | 2 | 2 | $0.64 |
| Grid-scale battery storage organizations in Texas | 90 | 0 | 6 | 1 | $0.81 |

| Organisation | Relevance | Priority | Decision | Boxes filled (Review) |
|---|---|---|---|---|
| California Water Environment Association | 1.00 | 0.73 | Accepted | — |
| WateReuse California | 0.75 | 0.78 | Review | 16 / 18 |
| San Diego County Water Authority | 0.75 | 0.44 | Review | 13 / 15 |
| Vistra Corp. | 0.75 | 0.40 | Review | 12 / 15 |
| Mortenson | 0.75 | 0.44 | Review | 11 / 15 |
| Entergy Texas | 0.60 | 0.44 | Review (4 criteria) | 11 / 15 |
| Texas Utility Management | 0.60 | 0.40 | Review (4 criteria) | 11 / 15 |
| Base Power | 0.60 | 0.32 | Review (3 criteria) | 13 / 15 |
| EticaAG | 0.45 | 0.28 | Review (2 criteria) | 12 / 15 |

### Actor updates

| Actor | Result | Location | Cost |
|---|---|---|---|
| Clean Energy Group | 5 changed, 3 confirmed, 2 not found | Montpelier, VT, Northeast (from its homepage footer) | $0.05 |
| CPower Energy | 4 changed, 2 confirmed, 2 not found | Baltimore, MD, Mid-Atlantic | $0.04 |
| Stanford Woods Institute (California water group request) | 8 new boxes; 1 link proposed to Review | Stanford, CA | $0.05 |
| California Dept. of Water Resources, Stanford Water in the West | Not read: site refuses the agent (403); broken site certificate | — | $0.00 |
| WEAT | Location found | Austin, TX | $0.01 |

**Location repair.** 22 verified actors gained coordinates and region from their own records. Verified actors without coordinates went from 120 to 98; most of the rest are outside the US, where the gazetteer cannot place them.

---

## 5. Limits worth knowing

- **Some sites refuse the agent or render only by script:** national labs, state agencies, MIT. Those are reported as "could not be read", and nothing is written.
- **A newer, weaker reading can replace a stronger recorded one in the same box,** under the Phase 11 rule "newer and at least as confident". A finer rule needs GHUS to define "stronger evidence".
- **Data quality found on the map:**
  - placeholder groups recorded as verified actors ("Research Institutes", "Regional Commissions");
  - a duplicate (UWM School of Freshwater Sciences, under two names);
  - verified actors with no sector link, which cannot be updated until a sector is chosen.
- **One reject reason reads oddly:** the California Department of Water Resources' grants page was rejected because it was judged an event page. The priority sentence was joined onto the same reason, so it reads as if the priority caused it.
- **Production has not been migrated:** migration 570 (saved update requests) is applied only to local test databases.
