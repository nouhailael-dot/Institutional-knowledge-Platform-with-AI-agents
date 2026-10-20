**Ecosystem Hub Intelligence Platform: Architecture Overview**

# **1. How the platform works**

**The platform has two jobs:**

- **Map, and**** keep the map current.** Find actors, collect facts about them, and update the map over time. Do not guess how an actor might be used.

- **Turn the map into action, when asked.** When GHUS gives a spec — an audience, a topic, criteria — reason over the mapped data and produce a recommendation. This job is covered in the companion document.

These two jobs stay separate. Job 2 only works if Job 1 is done honestly. An actor's fit for a learning expedition or an executive education program is judged against a real spec, never guessed at while mapping.

**Four rules that apply everywhere in this document:**

- **Check what's mapped before searching anything new.** This applies to every kind of request.

- **Two-layer pull.** A light pull for every actor Claude finds while mapping. A deeper pull only after GHUS verifies the actor. (Section 4)

- **Everything connects the right way** — a real parent when one exists, or through sector, geography, and hub when it doesn't (Section 6).

- **Claude proposes. GHUS decides.** Only GHUS verifies a record or approves a hub.

**When Claude finds a new actor**, these steps happen in this order: assign an actor category, then its category type (Section 3) → check for a real parent, or connect it through sector, geography, and hub if it has none (Section 6) → check whether it fits an existing hub (Section 2) → run the light pull (Section 4, Section 5.1) → the actor is now Parked. Later, once GHUS verifies it, the deep pull runs (Section 4, Section 5.2).

**Sources never mix.** Imported, Parked/Verified, and uploaded GHUS/UM6P/OCP documents are always labeled by where they came from.

# **2. Regions and hubs**

**Regions** are seven fixed U.S. groupings GHUS uses to organize searches and to browse. Every state belongs to exactly one region. The platform sets the region automatically, based on the state — nobody enters it by hand.

| **Region** | **States and district** |
| --- | --- |
| Northeast | Connecticut, Maine, Massachusetts, New Hampshire, New York, Rhode Island, Vermont |
| Mid-Atlantic | Delaware, Maryland, New Jersey, Pennsylvania, Virginia, West Virginia, Washington DC |
| Southeast | Alabama, Florida, Georgia, Kentucky, Mississippi, North Carolina, South Carolina, Tennessee |
| Midwest / Great Lakes | Illinois, Indiana, Iowa, Kansas, Michigan, Minnesota, Missouri, Nebraska, North Dakota, Ohio, South Dakota, Wisconsin |
| South Central / Texas Gulf | Arkansas, Louisiana, Oklahoma, Texas |
| Mountain West / Rocky Mountain | Arizona, Colorado, Idaho, Montana, Nevada, New Mexico, Utah, Wyoming |
| West Coast / Pacific | Alaska, California, Hawaii, Oregon, Washington |

Washington **DC** is Mid-Atlantic. Washington **State** is West Coast.

Every actor gets a region, state, and city the moment it's mapped (Section 5.1) — automatically, whether or not it belongs to a hub. An actor is never “homeless”: it's immediately browsable by region, state, and city alone, hub or no hub.

A **hub** is a separate, additional layer — the approved Phase 1 hubs, kept exactly as GHUS named and defined them, plus any new hubs GHUS creates going forward. A hub's value comes from the combination of actors in it, not from one institution. Example: the “UC Davis / Sacramento Valley Agriculture Ecosystem” is a hub. “UC Davis” by itself is not.

## **2.1 What a hub is made of**

Every hub has four parts:

| **Part** | **What it is** |
| --- | --- |
| Topic | One topic from the controlled topic list. A hub is always about one topic. |
| Center | The point where the hub's actors are most concentrated (how it's found: Section 2.3). Stored as coordinates plus the name of the city it sits in. |
| Radius | The hub's reach around its center. **Default: 200 miles.** GHUS can set a smaller radius for a specific hub. |
| Members | The actors assigned to the hub (Section 2.2). |

Distances are straight-line distances between an actor's city and the hub center, computed by the platform from a fixed U.S. city coordinate list. Nobody measures by hand, and Claude doesn't estimate distances.

**Phase 1 hubs** keep their names and definitions exactly as GHUS wrote them. The platform computes a center for each one from its current members (same method as Section 2.3) and gives it the default 200-mile radius, unless GHUS sets another. A Phase 1 hub that doesn't meet the new-hub criteria below is **not** removed — it's listed for GHUS as information only.

**A hub's center is fixed once GHUS approves it.** It only moves when GHUS asks for it to be recalculated. If new members shift the densest point significantly, the platform flags it for GHUS rather than moving the hub by itself.

## **2.2 Deciding whether an actor belongs to an existing hub**

**Test 1: Topic.** Does the actor's topic match the hub's topic? If not, stop — don't check location.

**Test 2: Location.** Is the actor's city within the hub's radius (default 200 miles) of the hub's center?

| **Result** | **Outcome** |
| --- | --- |
| Both pass | Assigned to that hub |
| Topic passes, location doesn't | Unassigned, needs review |
| Topic fails | Unassigned, needs review — don't check location |

An actor can belong to several hubs on **different** topics. If it passes both tests for two hubs on the **same** topic (their circles overlap), it's assigned to the hub whose center is closest, and the overlap is flagged for GHUS.

## **2.3 Spotting a possible new hub**

A new hub on a topic exists when a real, diverse cluster of actors on that topic sits in one area. The criterion:

**At least 10 Verified actors, on the same topic, from at least 5 different categories, all within 200 miles of the cluster's center.**

Claude flags it and suggests a name. GHUS decides.

**Finding the center.** The center is the place where the most actors are close to each other:

1. Take every Verified actor on the topic that isn't already a member of a hub on that same topic.
2. For each of those actors' cities, count how many of the other actors sit within a **core radius of 50 miles** of it.
3. The city with the highest count is the center. If two cities tie, pick the one with the smallest average distance to all actors within 200 miles of it.
4. The candidate hub is every one of those actors within **200 miles** of that center.
5. Check the criterion (10 actors, 5 categories, independence) on that set. If it passes, flag it. Then remove those actors and repeat from step 2 to find any further cluster.

*The 50-mile core radius finds the real concentration point. Without it, a 200-mile search can put the center in empty ground between two cities.*

**Independence.** The 10 actors must be genuinely separate organizations. Actors that share a parent — a university, its department, its research center, its accelerator — form one **family**, and a family counts **once**: once toward the 10 actors and once toward the 5 categories. *A university with nine of its own units is one organization, not a hub.*

**No overlap with a hub on the same topic.** If the candidate center falls inside the radius of an existing hub on the same topic, it isn't a new hub. Its actors are checked against that existing hub instead (Section 2.2).

*Example: “These 12 actors — [names] — from 6 categories are on [topic], concentrated around [city], all within 200 miles of it, and independent of one another. No hub on [topic] covers this area. Suggested name: '[Area] [Topic] Hub.' Want to create it?”*

**GHUS decides:** approve (as named), rename, or reject. GHUS can also set a smaller radius when approving. Only Verified actors count toward the criterion — Parked and Imported actors don't trigger the flag, though they can still be added once a hub exists. A rejected cluster isn't proposed again unless its membership changes.

# **3. Actor category and category type**

Every actor is classified on two levels, in this order:

- **Actor category** — what the organization **is**, from the 12 categories below.
- **Category type** — which kind of that category it is, from the fixed list of types that belong to that category.

A category describes what an organization is — never how GHUS might use it, and never its sector. A research center can work on water, AI, or five other sectors and it's still a research center. Every actor gets exactly one category and exactly one category type, and the type must belong to the chosen category.

| **#** | **Actor category** | **What it is** | **Category types** | **Examples** |
| --- | --- | --- | --- | --- |
| 1 | University / Academic Institution | A degree-granting school, or a formal academic unit of one: college, school, department, campus | University or university system · College / school within a university (including medical, law, business, engineering schools) · Academic department or program · Branch campus · Community or technical college | UC Davis; its Department of Plant Sciences |
| 2 | Research Center / Institute / Laboratory | An organization whose main job is research — independent, or attached to a university. Not a formally designated national lab | Independent research institute · University-affiliated research center or institute · Research laboratory or research group | MIT Energy Initiative; Donald Danforth Plant Science Center |
| 3 | National Laboratory | A formally designated national laboratory, or a federal research facility with a national mission. Kept separate because access rules differ. Federal funding alone does not qualify an organization for this category | DOE national laboratory · Other federally funded R&D center (FFRDC) · Federal agency research facility | Argonne; Oak Ridge |
| 4 | Applied Research Facility / Testbed / Field Site | A physical site where something gets tested or demonstrated under real conditions | Experimental farm or research station · Pilot or demonstration plant · Testbed · Field site or living lab | Experimental farm; pilot plant; water testbed |
| 5 | Hospital / Clinical System / Medical Center | An organization providing clinical care, medical research, or clinical education. A medical school is category 1, not this one | Academic medical center · Health system · Hospital · Specialty clinic or center | Cleveland Clinic; Mayo Clinic |
| 6 | Company / Corporate Actor | An established commercial or industrial company, including a business unit of one | Large or multinational corporation · Small or mid-size company · Business unit or subsidiary · Corporate R&D or innovation center | Bayer; BASF; Freeport-McMoRan |
| 7 | Startup / Emerging Technology Company | A company building or commercializing a new technology or business model, including university spinouts. Judge this by development stage, not age | University spinout · Corporate spinout · Independent startup | Any early- or pilot-stage venture |
| 8 | Innovation Platform / Incubator / Accelerator / Venture Studio | An organization whose main job is supporting startups or innovation | Incubator · Accelerator · Venture studio · Innovation center or shared lab space · Technology-transfer or commercialization office | Greentown Labs; Berkeley SkyDeck |
| 9 | Investor / VC / Funding Platform | An organization that manages investment capital | Venture capital firm · Corporate venture arm · Angel group · Impact or climate fund · Private equity or growth fund · Public or quasi-public investment fund | Breakthrough Energy Ventures |
| 10 | Government Agency / Public Authority | A public-sector body with a government mandate, including public utilities | Federal agency · State agency · Local or municipal government · Regional or special-purpose authority · Public utility | USDA; DOE; EPA |
| 11 | Foundation / Nonprofit | A nonprofit pursuing a mission, including one that gives grants | Private foundation · Corporate foundation · Community foundation · Operating nonprofit · Think tank or policy institute | Gates Foundation; Rockefeller Foundation |
| 12 | Industry Association / Consortium / Network | A formal group connecting several organizations around a shared industry or agenda — including a statewide or multi-location network, which is recorded as one parent record with each of its physical locations mapped as its own linked actor (Section 6) | Trade or industry association · Research consortium · Professional society · Standards body · Alliance or coalition · Statewide or multi-location network | Trade associations; research consortia; a statewide extension network |

**People and events are not on this list.** They are separate record types with their own rules. A person is a person record, linked to an organization (Section 5.3). An event is an event record (Section 5.4).

**How to pick a category and a type, step by step:**

- Is it a person? Make a person record instead. Stop here.

- Is it a time-bound event? Make an event record instead. Stop here.

- What is this organization's **main job**? Decide the **category** from what it says about itself. Do not decide by who funds it, its sector, or how well-known it is.

- Does the organization have several distinct parts? For example, a university with a research center, an accelerator, and a hospital. If so, create one record per part, each with its own category and type, all linked to the university as parent. Never give one record two categories or two types.

- Now pick the **category type**, only from the types listed for that category.

- Still unsure about the category or the type? Pick the closest one, write a one-line note explaining the doubt, and send it to GHUS for review. If no listed type fits, use "Other", with a one-line note — GHUS decides whether a new type should be added to the list.

# **4. The two-layer pull**

The light and deep pulls happen while mapping — the light pull as soon as Claude finds a candidate, the deep pull only once GHUS verifies it. The UM6P/OCP connection check (Section 5.5) runs at both layers, using whatever Claude is already reading at each stage.

**Layer 1 — the light ****pull****.** Runs for every actor Claude finds. Collects just enough to identify the actor, place it, and explain why it matched (Section 5.1).

Once the light pull is done, the actor's status is **Parked.** It stays Parked until GHUS reviews it.

**Layer 2 — the deep pull.** Runs only after GHUS verifies the actor. Collects selected, topic-relevant detail on what the actor actually does on the topic — not an exhaustive record (Section 5.2). Verifying an actor authorizes focused enrichment, not exhaustive research.

**Layer 3 — specific ask from GHUS.** Full catalogs, complete grant histories, full portfolios, and other exhaustive or narrow requests are pulled only when GHUS specifically asks for them.

# **5. What gets pulled**

## **5.1 Fields collected for every actor**

| **Field** | **What it records** | **When it's collected** |
| --- | --- | --- |
| Name, other names | Official name, plus any former names or abbreviations | Light |
| Actor category and category type | One category from Section 3, then one category type belonging to that category, plus a note if either is uncertain | Light |
| Parent or connection | The organization this actor belongs to, if one exists — or, if not, how it connects through sector, geography, and hub instead (Section 6) | Light |
| Website | The actor's official site | Light |
| Description | 1–3 plain, factual sentences: what it is, what it does | Light |
| Location | Country, state, city; region and city coordinates (both set automatically); flagged if multi-location | Light |
| Hub | Which hub or hubs, if any, and each hub's distance from the actor (Section 2) | Light |
| Sector and topic | The sector(s) this actor fits, and the specific topic it was found for | Light |
| Why it matched | Strong or moderate match, with 1–2 sentences explaining why | Light |
| Recent activity | One dated, documented project, program, or development on this topic, if easy to find | Light if easy to find, deep pull otherwise |
| Funding signal | One clear, documented grant, award, or investment on this topic | Light if visible, deep pull otherwise |
| International / Africa / Morocco connection | Documented programs or partnership | Light if visible, deep pull otherwise |
| UM6P/OCP connection | A documented connection to an entity on the UM6P/OCP list, found in whatever Claude is already reading (Section 5.5) | Light and deep |
| Sources and confidence | For every fact: the link, where it came from (already mapped / newly found / uploaded document), the date read, and a confidence level (high / medium / low) | Both |
| Status | Imported, Parked, Verified, or Rejected — see below | Both |
| Verification record | Verified By, Verification Date, Verification Notes — kept as a running history, never overwritten | Set only by GHUS |
| GHUS notes | Free text, written only by GHUS | Manual |

**Status values, plain and simple:**

| **Status** | **What it means** |
| --- | --- |
| Imported | Came from the Phase 1 mapping. Not yet reviewed under this platform — never treated as GHUS-verified until a GHUS person actually reviews it here |
| Parked | Claude found it. Nobody has reviewed it yet. Default for every actor Claude finds |
| Verified | A GHUS person reviewed it and confirmed it's accurate |
| Rejected | A GHUS person reviewed it and said no. The record stays — it's not deleted — with the reason recorded |

Claude can never set an actor to Verified or Rejected. Only a GHUS person can, and every verification decision records who made it, when, and any notes — kept as history, not overwritten by the next review.

## **5.2 What's collected by actor type**

These fields come in addition to Section 5.1, and everything below is pulled **specifically for the topic being asked about — not a general profile of the actor.** If GHUS is mapping agriculture, Claude pulls agriculture-specific programs, funding, and activity; if GHUS later maps the same actor for AI, Claude pulls AI-specific programs, funding, and activity — even though it's the same actor.

**The deep pull is selected and topic-relevant, not exhaustive.** Verifying an actor authorizes Claude to characterize what it does on the topic — not to compile everything about it. Complete grant histories, full program catalogs, and full portfolios belong to Layer 3, on a specific ask.

**The lists below are a starting point, not a blank check.** No fixed list can anticipate everything a given sector might surface — a university's agriculture extension program matters for agriculture but not for AI at the same university. Claude may pull an item not named below, but only when it materially contributes to answering the mapped topic — not simply because more information exists.

| **Category** | **Light pull** | **Deep pull (after Verified)** | **Specific ask from GHUS** |
| --- | --- | --- | --- |
| University / Academic | The relevant school, department, or research lab tied to the topic (linked to its parent university), and what it does on this topic; public or private; land-grant or other designation, where relevant; university and subject rankings — see Ranking attribution below; names of the main relevant centers and programs; one current activity on the topic; a recent or current funding signal for the relevant school, department, or lab on this topic, if publicly visible, with its source | Research centers and labs on the topic, each as its own linked record; selected, topic-relevant degree and executive/professional education programs (format, length, audience); applied facilities like farms or testbeds; selected, topic-relevant funded projects; selected industry and international collaborations; tech-transfer or accelerator units; exchange programs; recurring events; extension, outreach, or other topic-specific programs (for example, an agriculture extension program, when the topic is agriculture) | Full program catalogs, faculty directories, publication lists, admissions details, complete grant history |
| Research Center / Lab | Its parent and type; its research focus on the topic; 1–2 active or recent projects; main funders, and a recent or current funding signal on this topic, if publicly visible, with its source. No ranking is collected for this category, at any layer. | Research themes; selected, topic-relevant recent projects and outputs; applied or validation facilities; selected, topic-relevant funded initiatives; collaborations; fellowships; spinouts; scale; events | Equipment inventories, full publication histories, researcher lists, complete grant history |
| National Laboratory | Sponsoring agency; confirmation it's formally designated; relevant program area; current activity on the topic | Programs and flagship projects; user facilities; selected funded initiatives; collaborations; workforce and training programs; technology transfer; international programs | Access rules, visitor conditions, restrictions on international collaboration |
| Applied Facility | Facility type; operator; location; what it tests or demonstrates; a current project | What's tested and how; scale; deployments and partners; monitoring capabilities; public events it hosts; funding | Detailed specifications, access conditions, site-visit feasibility |
| Hospital / Health System | Clinical or research focus on the topic; parent or academic link; type and scale; a current initiative | Clinical and research programs; digital health or AI units; medical education programs; partnerships; selected funded initiatives; global health programs | Trial capacity, simulation infrastructure, regulatory arrangements |
| Company | Public or private, and size; relevant business segment or product; where it operates in the mapped geography; current activity on the topic | Relevant products (not the whole portfolio); R&D and innovation initiatives; industrial sites; collaborations; topic-related funding; public sustainability commitments; corporate training programs | Leadership, strategy, financials, detailed capacity |
| Startup | Its technology and the problem it addresses; founding year and location; stage or TRL, only if published; funding stage; pilot or customer evidence, if easy to find | Technical approach and maturity evidence; pilots and deployments; funding rounds and investors; partnerships; public IP, only when needed | Detailed IP analysis, team lists, financials |
| Innovation Platform | Type and operator; sector focus; what it offers (lab space, prototyping, co-working); a scale indicator | Programs and cohorts; startups it supports, each linked; corporate and investor connections; facilities offered; funding; events | Mentor lists, complete portfolios |
| Investor / Funder | Type and headquarters; sector and stage focus; geographic focus; fund size, if published; investment thesis on the topic | Selected investments, each linked; relationships with universities and accelerators; programs it runs | Complete portfolios or investment histories |
| Government Agency | Jurisdiction and parent agency; relevant mandate or program; funding programs, if visible | Programs and funding opportunities; public initiatives; facilities it operates; relevant policy context | Full grant catalogs, regulatory frameworks, staff lists |
| Foundation / Nonprofit | Mission and sector focus; geographic focus; a relevant program; programs and grant themes | Selected grants; supported organizations on the topic; international activity | Full grant histories, grantee directories, board lists |
| Association / Consortium | Type; sector focus and geographic scope; member types; a current initiative or working group, if visible; members, each linked; if the organization is a statewide or multi-location network, its overall scope (for example, "statewide"), with each individual location recorded as its own actor, linked to this record as parent (Section 6) | Working groups and standards on the topic; recurring events; key reports | Exhaustive membership lists |

**Ranking sources.** For universities only:

- **University-wide:** QS World University Rankings, Times Higher Education (THE) World University Rankings, U.S. News & World Report Best Colleges, or the Academic Ranking of World Universities (ARWU).

- **Subject-specific:** QS World University Rankings by Subject, THE World University Rankings by Subject, or U.S. News Best Graduate Schools by specialty.

Capture only what's actually published — publisher and year required.

**Ranking attribution.** Record each ranking exactly as published: publisher, ranking name, year, the subject or specialty (if any), the institution or program actually ranked, and the position. A university-wide subject ranking may be shown alongside a relevant department or lab as context, but stays labeled as the university's ranking in that subject — never presented as the department's or lab's own ranking. Link a ranking to a specific department or lab only when that unit is verifiably the university's program in that subject, not on a loose name or keyword match.

*Example: “UC Davis — Agriculture & Forestry subject ranking (QS, 2026)” shown on the Department of Plant Sciences page, not “UC Davis Department of Plant Sciences ranking.”*

**RULE: nothing on this table is ever invented.** Every fact in the light pull or deep pull comes from a real, checkable source — recorded alongside it. If the evidence isn't there, the field says “not found.” Never a guess. Two places this matters most:

- A department never inherits its university's overall ranking — it only gets a ranking if one of the named subject-specific publishers has actually published one for it, attributed the way described above.

- A startup never gets an assumed TRL — if there isn't enough technical evidence, the field says “not found,” not an estimate.

## **5.3 People**

People are their own records, always linked to their organization. They are **not** collected automatically for every organization Claude maps — that's expensive and produces shallow lists.

Claude only collects people when:

- GHUS asks for experts on a topic, or

- GHUS asks for people at an actor that's already Verified, or

- Answering a specific question needs a person (see the companion document).

| **When** | **What's collected** |
| --- | --- |
| Light pull | Name, title, organization; their relevant expertise; a public profile; brief evidence of relevant work; any UM6P/OCP connection stated in their profile |
| Deep pull (after Verified) | Selected publications, projects, or grants on the topic; relevant teaching or applied experience; international/Africa activity; details of any UM6P/OCP connection |

Only public, professional information — never private details. Contact info is only collected if explicitly requested, and only if it's an official, public contact. Each person gets their own verification, separate from their organization's.

## **5.4 Events**

Events are time-bound records — not actors. Claude only looks for events in response to a specific need, never as a blanket sweep of a sector.

| **When** | **What's collected** |
| --- | --- |
| Light pull | Name and type; sector and topic; date and location; organizer; website; whether it's annual, recurring, or one-time; why it matched; whether it's upcoming, past, or the date is unconfirmed; any visible UM6P/OCP involvement; a short description of the event, including any notable claims about its scale, reputation, or standing that are publicly stated — for example, if a source calls it “the leading AI conference in the world,” that claim is captured, with its source |
| Deep pull (after verification) | Themes or sessions; links to existing actors; later editions of the event |
| Specific ask from GHUS | Speakers, participating organizations, agendas, sponsors |

Past events are kept — they're historical evidence, not “out of date.”

**GHUS event notes.** Every event record has an open area reserved for GHUS — not a required field Claude fills in or asks about, just a blank space that's flagged when empty. GHUS adds to it whenever there's something worth recording:

- Did anyone from GHUS attend?

- Who attended?

- Did GHUS speak or present at it?

- Do we recommend attending again?

- Any other relationship notes or follow-up actions.

Claude never writes to this area. It exists so this knowledge has a home once GHUS has it — it doesn't need to be filled in right away, and it isn't something Claude prompts GHUS to complete.

## **5.5 UM6P/OCP connection check**

A separate spreadsheet lists every UM6P/OCP entity that counts: OCP Group and its units, UM6P and its units (including UM6P United States), and INNOVX with its funds and ventures. A name with only “UM6” — not “UM6P” — does not count.

**The sweep uses only what Claude is already reading — never a dedicated search.** During the light pull, Claude checks whatever sources it's already reading for that actor (its own site, the pages already pulled) for a documented connection to the list. During the deep pull, the same check runs again against whatever additional sources get read at that stage — a connection that wasn't visible on an actor's homepage might show up on a program page or partnerships page pulled later.

Claude records one of three states, not just found/not found:

- **Found** — a specific entity, the kind of connection, and the source.

- **Not found in what's been read so far** — nothing turned up in the sources read at this stage. This is not a claim that no connection exists, only that none was visible yet; it can still change at the deep-pull stage.

- **Not yet checked** — the sweep hasn't run at this actor's current stage yet.

A connection is never a reason to map an actor that wouldn't otherwise be mapped, and it never changes an actor's ranking or priority. It's a fact on the record, nothing more. A dedicated, targeted UM6P/OCP search — beyond what Claude is already reading — only happens on a specific ask from GHUS (Layer 3).

# **6. The web: connecting records the right way**

Records connect to each other wherever a real, evidence-supported relationship exists. Not every actor has a parent, and the platform should never invent one to force a connection.

**Two cases, and Claude checks them in this order:**

**Case 1 — a real parent relationship exists.** A department within a university, a business unit within a company, a facility operated by an organization, a company that spun out of a lab. Link it, using the relationship types below.

**Case 2 — no parent relationship exists.** An independent company, a standalone research institute, a freestanding actor with no larger organization above it. **Do not invent a parent.** The actor still connects into the map fully — through its sector, its geography, and its hub if it belongs to one (Section 2) — it simply has no organization above it, and that's a normal, complete state for a record, not a gap to fill.

**Two examples side by side:**

UC Davis                          (University — no parent)
├── Dept. of Plant Sciences      (unit — parent: UC Davis)
│     └── Professor X            (affiliated with: the dept.)
├── A research center            (parent: UC Davis)
└── A university accelerator     (parent: UC Davis)
      └── Startup Y               (portfolio of: accelerator,
                                not a child)

Freeport-McMoRan                  (Company — no parent.
                                    Independent. Connects via
                                    its sector, its Arizona
                                    location, and the Arizona
                                    Mining hub — nothing more
                                    is needed above it.)

**Six rules:**

- **Check for a real parent first; if there isn't one, don't invent one.** Case 1 or Case 2, as above. A standalone actor is a complete record on its own.

- **Check before creating anything new.** Compare every new record against what's already there: name, alternate names, and especially the website domain. If it's an exact match, add the new information to the existing record instead of creating a duplicate. If it's a close match but not exact, flag it for GHUS to review — never merge automatically.

- **People and events link too.** A person links to their organization, at the department level when that's known. An event links to whoever organized it, and to any related actors.

- **A parent record shows everything beneath it.** At any depth, and it updates automatically as new records get added. A statewide or multi-location network (Section 3) is recorded as one parent with each physical location as its own linked child actor — the network's overall reach doesn't get pasted onto every location, and no single location gets credited with the whole network's scope.

- **Every link has a type and a source.** The types are: unit of, operated by, affiliated with (for people), member of, portfolio of (a startup in an accelerator — this is not ownership), spinout of, funded by, collaborates with, organizes (for events), participates in (for events), and connected to a UM6P/OCP entity. Pick the right one — they mean different things. Every link needs a source.

- **Never overwrite, never delete.** New information gets added alongside the old. If two facts conflict, flag it for GHUS to review. If old information came from a person, don't replace it automatically — mark the new version as a pending update instead.