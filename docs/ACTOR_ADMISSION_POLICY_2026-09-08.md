# Continuous Maintenance Agent — Admission Policy

**Status:** proposed implementation policy  
**Scope:** candidates found by the continuous maintenance agent, not results from Ask, Browse, or Build the Map  
**Default geography:** United States  
**Core rule:** the agent may propose records; only a human may admit them to the institutional database.

## 1. Purpose and boundary

The maintenance agent searches for actors and people active in topics the database already covers. Its job is to maintain and deepen the current map, not decide which actors are strategically “best” and not expand the map into a new domain or geography.

Route discoveries as follows:

| Discovery | Route |
|---|---|
| In an already-covered topic and authorized geography | Apply this admission policy |
| Plausibly relevant, but topic coverage is ambiguous | `REVIEW` for scope determination |
| Primarily in a new topic or unauthorized geography | Send to Build the Map or a scope owner; do not admit through maintenance |
| Update to an existing entity | Create an update proposal, not a new-entity proposal |
| Possible alternate name, unit, subsidiary, or duplicate | Entity-resolution review before any new record |

This policy standardizes relevance, evidence quality, current activity, record usability, and non-duplication. It deliberately does **not** standardize strategic importance. Reviewers may judge importance differently for research, partnerships, introductions, funding, commercialization, or ecosystem analysis.

## 2. Decision outputs

The agent must return exactly one disposition:

- **`ADD CANDIDATE`** — passes every mandatory gate and meets the quality threshold. This means “ready for human admission review,” never “insert automatically.”
- **`REVIEW`** — plausible candidate, but an ambiguity, missing fact, evidence conflict, identity risk, or policy exception requires judgment.
- **`REJECT`** — clearly out of scope, ineligible, inactive under this policy, not a real/specific entity, unsupported after a reasonable search, or already represented without meaningful reason for a separate record.

`REJECT` is a discovery disposition, not a permanent blacklist. A later run may reconsider the entity if new evidence or a new scope authorization appears.

## 3. Mandatory gates

Gates are evaluated in order. Scores cannot compensate for a failed gate.

### G0 — Scope authorization

Pass only when:

1. at least one normalized topic is already covered by the database or explicitly included in the maintenance run; and
2. the candidate is within the authorized geography.

“US-first” means the actor has a material US presence or activity relevant to the covered topic—not merely a page accessible in the US. A foreign-headquartered actor may pass if a distinct US operation, facility, program, or sustained US activity is evidenced. Otherwise it requires explicit non-US authorization.

- Clear pass: continue.
- Ambiguous topic boundary or geography exception: `REVIEW`.
- Clear new-domain/new-geography discovery: `REJECT` from maintenance and optionally route to Build the Map.

### G1 — Real, eligible, addressable entity

The candidate must be a specific organization, organizational unit, public body, or person with a stable identity that can be represented and revisited.

Eligible organizational classes include universities, formally named research centers or labs, companies and startups, government agencies and programs, nonprofits, funders, accelerators, consortia, and umbrella organizations when the separate-record rules in section 8 are met.

Reject generic categories, market segments, unnamed programs, search-result groupings, lists, technologies, buildings without an operating organization, and labels such as “similar startups” or “environmental remediation firms.”

For a person, require a publicly evidenced current professional identity and a qualifying relationship to a covered topic. Do not collect a private individual merely because they mention the topic socially.

### G2 — Substantive topical activity

The agent must identify at least one **qualifying activity** tied to a covered topic. Name similarity, mission-language overlap, tags, SEO copy, membership in a broad directory, or a keyword appearing on a page is insufficient.

Qualifying activity includes a topic-specific project, program, product deployment, research output, grant, investment, facility, partnership, procurement, regulatory responsibility, service, or recurring event. The evidence must say what the actor does, not only that the actor is “interested in,” “supports,” or “is committed to” the topic.

### G3 — Current or operationally relevant activity

Require evidence that the actor or the qualifying activity remains operationally relevant.

Default freshness rules:

| Evidence | Normally current when |
|---|---|
| Project, program, partnership, funding, product, event, leadership role | dated within 24 months |
| Peer-reviewed research or technical publication | dated within 36 months |
| Facility, statutory mandate, standing government program, endowment, or durable infrastructure | official source shows it still exists; undated evidence may be accepted with a second current signal |
| Startup/company status | current official site plus a signal within 18 months; absence of news alone is not proof of inactivity |
| Person’s role | verified within 12 months |

Use the publication/event date, not the page’s generic “updated” timestamp. If no dated signal is discoverable but the official source appears live, return `REVIEW`; do not infer closure. If reliable evidence shows dissolution, closure, acquisition, retirement, or role departure, treat it as an update to an existing entity when applicable, otherwise `REJECT` as a new active candidate.

### G4 — Evidence sufficiency

At least one primary source must support identity, and primary-source evidence should support topical activity and current status. Examples are the actor’s official site, government record, university directory, official grant database, regulator filing, or funder award page.

An `ADD CANDIDATE` normally requires:

- one official/authoritative identity source; and
- one dated source for qualifying activity; and
- corroboration from a second independent source for claims that are material, disputed, or not available from a primary source.

One source may satisfy the first two requirements if it is an authoritative, dated page containing both facts. Secondary discovery sources may lead to a candidate but should not be the sole support when a primary source is reasonably available. Search snippets, AI summaries, scraped profile farms, user-edited aggregators, and unsourced listicles are leads, not admission evidence.

Every material populated claim must map to a URL, an evidence excerpt or precise locator, source type, retrieval date, and confidence. If sources conflict, preserve the conflict and return `REVIEW` unless an authoritative source clearly resolves it.

### G5 — Minimum useful record

An organization candidate must contain:

- canonical name;
- normalized actor type;
- official website or authoritative registry/profile URL;
- country and, for US actors, state when reasonably discoverable;
- concise identity description;
- at least one covered topic;
- at least one specific qualifying activity;
- activity date or an explicit durable-activity rationale;
- evidence records supporting identity and activity.

A person candidate must contain:

- full name;
- current title or role;
- current affiliated actor, or an explicit independent status;
- qualifying topic contribution/activity;
- country or work location when reasonably discoverable;
- an authoritative profile URL; and
- evidence supporting role and activity.

Optional fields such as email, phone, funding amount, ORCID, LinkedIn, TRL, or detailed technical notes never block admission unless a downstream workflow explicitly requires them. Never infer or synthesize contact details. Do not collect personal phone numbers or personal email addresses; use only clearly public professional contact information when needed.

### G6 — Entity resolution and incremental value

Search live actors (`merged_into_actor_id IS NULL`), people, aliases, websites/domains, and organization hierarchy before proposing a new record. Compare normalized names, acronyms, former names, domains, locations, parent entities, and topic/activity descriptions.

Classify duplicate risk:

- **Low:** no plausible match after exact and fuzzy checks.
- **Medium:** a similar name, shared domain, parent/child relationship, or possible rebrand exists but evidence supports distinct identity.
- **High:** same domain, acronym expansion, former/current name, substantially identical identity, or uncertain unit-versus-parent boundary.

Outcomes:

- Exact existing entity: propose an update; `REJECT` the new record as duplicate.
- Likely duplicate or unresolved hierarchy: `REVIEW`.
- Distinct entity that adds a separately queryable capability, role, location, or relationship: pass, recording the relationship to the existing entity.
- Separate record with no meaningful retrieval or analysis benefit over the parent: `REJECT` as separately redundant; propose aliases/relationships or parent updates instead.

### G7 — Human control

No disposition may directly create or modify a canonical actor/person record. `ADD CANDIDATE` creates a pending, immutable review bundle. Approval must record reviewer, timestamp, decision, and any edits. Rejection and merge decisions should remain auditable.

## 4. Quality score (after gates)

Score only candidates that have not already failed a gate. The score prioritizes research readiness, not prestige or strategic desirability.

| Dimension | Points | Operational test |
|---|---:|---|
| Topical relevance | 0–25 | specificity and strength of evidenced activity in an existing topic |
| Evidence quality | 0–20 | authority, directness, corroboration, and claim-level traceability |
| Current activity | 0–20 | recency and strength of operational signal, using class-appropriate rules |
| Record completeness | 0–15 | required identity, location, activity, and relationship fields |
| Entity resolution | 0–15 | confidence that identity is distinct and correctly modeled |
| Institutional usability | 0–5 | record supports a concrete use such as research, relationship mapping, introductions, funding analysis, or ecosystem mapping |

“Institutional usability” measures whether the record can support a use, not whether the actor is important or desirable. The agent may attach neutral `potential_use_cases[]`; it must not rank prestige, partnership priority, or “best actor.”

Decision mapping:

- `ADD CANDIDATE`: all gates pass, total score **≥ 75**, topical relevance **≥ 18**, evidence quality **≥ 14**, current activity **≥ 12**, and duplicate risk is Low or resolved Medium.
- `REVIEW`: total **55–74**, any unresolved-but-plausible gate, permitted policy exception, evidence conflict, or Medium/High duplicate risk.
- `REJECT`: total **< 55** or any clear gate failure.

The agent must output the component scores. It must not use the total score as the explanation.

## 5. Evidence and confidence model

### Source tiers

1. **Tier 1 — authoritative primary:** official actor page, government database, statute/regulation, university directory, regulator filing, official grant/award record.
2. **Tier 2 — strong independent:** reputable journalism, peer-reviewed publication, established industry database with editorial controls.
3. **Tier 3 — discovery-only or weak:** directories, event listings, investor portfolios, press-release syndication, self-authored social profiles. Some may be primary for a narrow claim (for example, an investor portfolio for that investor’s participation) but not for the candidate’s whole identity.
4. **Tier 4 — unacceptable as evidence:** search snippets alone, AI-generated answers, content farms, anonymous claims, or inaccessible citations whose relevant content cannot be verified.

### Criterion confidence

Report confidence per criterion, not only globally:

- **High:** directly supported by current Tier 1 evidence, with no material conflict.
- **Medium:** supported but indirect, older, single-source, or dependent on a modest inference explicitly labeled as such.
- **Low:** ambiguous, weakly sourced, conflicting, or identity linkage uncertain.

Overall confidence is the minimum confidence among identity, topical relevance, current activity, and non-duplication—not an average. `ADD CANDIDATE` requires no Low value in those four criteria.

## 6. Required output contract

Each run emits a machine-readable candidate bundle and a short human-readable explanation. A recommended logical shape is:

```json
{
  "decision": "ADD CANDIDATE | REVIEW | REJECT",
  "candidate_entity_type": "actor | person",
  "canonical_name": "string",
  "normalized_actor_type": "string or null",
  "scope": {
    "matched_topics": ["controlled topic id"],
    "geography": "string",
    "authorized": true,
    "scope_notes": "string"
  },
  "criteria": [
    {
      "criterion": "identity | topical_relevance | current_activity | evidence | completeness | non_duplication | usability",
      "status": "PASS | UNCERTAIN | FAIL | NOT_APPLICABLE",
      "score": 0,
      "confidence": "HIGH | MEDIUM | LOW",
      "facts": ["concise factual finding"],
      "evidence_ids": ["source reference"],
      "missing_information": ["specific missing fact"]
    }
  ],
  "duplicate_assessment": {
    "risk": "LOW | MEDIUM | HIGH",
    "possible_matches": [
      {"entity_id": "uuid", "name": "string", "relationship": "duplicate | alias | former_name | parent | child | affiliated | unknown", "reason": "string"}
    ],
    "recommended_action": "new_record | update_existing | add_alias | add_relationship | merge_review"
  },
  "evidence": [
    {"id": "string", "url": "string", "source_tier": 1, "publisher": "string", "published_at": "date or null", "retrieved_at": "date", "excerpt_or_locator": "string", "supports": ["claim ids"]}
  ],
  "missing_information": ["string"],
  "potential_use_cases": ["research | partnership_analysis | introductions | funding_analysis | ecosystem_mapping"],
  "strategic_importance": "NOT_SCORED_HUMAN_JUDGMENT",
  "score_total": 0,
  "overall_confidence": "HIGH | MEDIUM | LOW",
  "concise_justification": "2–4 sentences",
  "policy_version": "actor-admission-v1.0"
}
```

Persist raw evidence separately from the proposed canonical values. Because the current `proposal` table is field-oriented, implementations should add a candidate/batch identifier (or a candidate table) so reviewers approve the record as a coherent bundle rather than accidentally approving only some required fields.

## 7. Search and decision procedure

1. Normalize the discovery name, domain, actor type, geography, and candidate topics.
2. Check whether the topic and geography are authorized for maintenance.
3. Establish the legal/organizational identity from a primary source.
4. Find a specific qualifying activity and determine its date/status.
5. Collect only the facts needed for a useful minimum record; attach claim-level evidence.
6. Resolve against live entities, merged entities, aliases, domains, acronyms, and hierarchy.
7. Apply entity-type rules in section 8.
8. Evaluate gates, then calculate the quality score.
9. Emit one disposition and the complete audit bundle.
10. For `ADD CANDIDATE` or `REVIEW`, place the bundle in the human queue. Never write the canonical record directly.

The search budget should be finite and recorded. “Not found within budget” is not equivalent to “does not exist.” If the candidate is plausible but evidence is unavailable because of access failure, emit `REVIEW` with the failure. If several normal searches yield only weak/irrelevant material, `REJECT` as insufficiently demonstrated.

## 8. Entity-specific treatment

### Umbrella organizations, consortia, and networks

Create a separate record only when the umbrella has its own name, mandate, governance or operating mechanism, and activity. A member list alone does not justify treating the umbrella as the same entity as its members. Record member/parent relationships rather than copying all member capabilities to the umbrella. Do not infer that every member participates in every umbrella activity.

An informal label or geographic grouping without governance is not an actor; it may belong as a hub, tag, or narrative. Unclear formal status goes to `REVIEW`.

### Universities

Default to one university-level actor. Create separate records for a school, center, institute, technology-transfer office, or program only if it has a stable public identity and at least two of: distinct leadership, dedicated site, durable program/facility, separate external partnerships/funding, or a materially distinct topic role. Always link the unit to the university. Do not attribute a professor’s work to the entire university without qualification.

### Labs and research centers

Admit a named lab/center separately when it operates as a durable, externally addressable unit with distinct capabilities, facilities, programs, or leadership. A temporary research project or an individual investigator’s group normally remains activity attached to the university/organization or person. Federally funded/national labs should record operator, owner/sponsor, and site relationships where known; shared branding does not make the lab identical to its operator.

### Startups and companies

Require a real operating company or legally/organizationally identifiable venture plus specific topic activity. A landing page or stealth announcement alone normally yields `REVIEW`. Check former names, acquisitions, parent/subsidiary status, and shared domains. Brands and product lines are aliases/offerings unless independently organized and analytically useful. Acquired companies may remain separate if their brand, team, product, or facility continues to operate; otherwise update/relate the surviving parent rather than adding a new active actor.

Funding announcements support activity and maturity but do not by themselves prove technical claims. Never infer TRL from funding stage.

### Government bodies and public programs

Statutory mandate, official responsibility, facility operation, awards, procurement, or active programs qualify as activity. Durable mandates may use longer freshness windows, but verify that the office/program still exists. Model an agency, subordinate office, laboratory, and program separately only when each has a distinct mandate and future queries benefit from the distinction. Record hierarchy. Elected officials are not organizational actors; consider them as people only under the person rules.

### Nonprofits, associations, and foundations

Require evidence of actual programs, grants, research, convening, standards, services, or implementation—not mission language alone. Chapters receive separate records only when locally autonomous or independently active enough to be queried. Fiscal sponsors and sponsored projects must not be conflated; record the relationship.

### Funders and investors

Admit when they have an evidenced active funding mandate, instrument, portfolio, award, or call in a covered topic. General access to capital is not topical activity. Distinguish a fund, fund manager, foundation, corporate venture arm, and government funding program when they make separate decisions or provide different instruments; otherwise prefer relationship/sub-entity fields over duplicate records. A portfolio page is primary evidence for the investor’s claimed investment, not necessarily for the investee’s technical performance.

### People

People are a separate entity class, never an `actor_type`. A person qualifies through a current, material role in a covered topic—for example research leadership, program ownership, technical founding, funding authority, regulatory responsibility, or documented subject-matter contribution. Fame, seniority, or generic executive status is insufficient.

Require current affiliation/role evidence and a specific contribution. Link the person to the institutional actor through `actor_person`; do not duplicate the organization’s full record in the biography. Create one person record across multiple roles and preserve role dates. Role uncertainty, name collision, or affiliation conflict requires `REVIEW`.

Collect the minimum professional information necessary. Public professional email is optional; personal contact information, protected characteristics, and unrelated personal details are out of scope.

## 9. Edge-case decision table

| Case | Default outcome | Reason/action |
|---|---|---|
| Keyword appears only in generic mission copy | `REJECT` | No substantive activity |
| Strong activity, but only secondary evidence is available | `REVIEW` | Seek primary confirmation |
| Old seminal work, no current signal | `REVIEW` | Potential historical value; human decides whether active scope includes it |
| Entity is clearly closed or person has left role | `REJECT` as new active candidate | Propose status/role update if already represented |
| Foreign headquarters with an evidenced active US facility/program | Continue gates | Record both headquarters and US presence accurately |
| Foreign actor with only US customers or web reach | `REVIEW` or `REJECT` | Not automatically a material US presence |
| Same official domain as an existing record | `REVIEW` | High identity/hierarchy risk unless relationship is already clear |
| Acronym collides with another entity | `REVIEW` | Canonical name and context must resolve collision |
| University lab has a distinct site but no durable activity | `REVIEW` | Site alone does not prove separate-record value |
| Company product/brand has distinct marketing but no separate organization | `REJECT` as actor | Add offering/alias to company if useful |
| Consortium has projects but no legal incorporation | May pass | Legal personality is not required if governance and durable activity are evidenced |
| Person has many publications but no current affiliation found | `REVIEW` | Identity/current-role uncertainty |
| Candidate duplicates a merged loser record | Treat winner as existing | Propose update against merge winner; do not resurrect loser |
| Source pages disagree on location or status | `REVIEW` | Preserve both claims and identify authority/date |
| Official page is undated | Continue only with current corroboration or durable-activity rule | A live page is a weak freshness signal by itself |
| High score but mandatory gate fails | `REJECT` or `REVIEW` per gate | No compensating scores |

## 10. Human review

The review interface should show, in this order:

1. proposed identity and normalized type;
2. exact covered-topic match and qualifying activity;
3. current-activity evidence and dates;
4. possible duplicates and hierarchy diagram/list;
5. proposed field values beside supporting evidence;
6. missing information and conflicts;
7. component scores and agent confidence;
8. neutral potential use cases; and
9. reviewer controls: approve, approve with edits, reject, merge/update existing, or defer/request research.

The reviewer supplies any strategic-priority judgment separately from admission quality. A strategically unimportant actor may still be a valid database record; a strategically attractive actor must not bypass evidence, scope, identity, or duplication requirements.

## 11. Governance and calibration

- Version the policy, thresholds, topic taxonomy, geography authorization, source rules, and actor-type vocabulary.
- Log searches, evidence, model/tool versions, gate results, scores, disposition, reviewer decision, and reviewer edits.
- Maintain a labeled calibration set covering all actor classes and edge cases.
- Measure precision of `ADD CANDIDATE`, reviewer overturn rate by criterion, duplicate escape rate, false-reject samples, evidence-link decay, and time-to-review.
- Tune thresholds from reviewer outcomes, but do not weaken mandatory gates to raise volume.
- Sample `REJECT` decisions periodically to detect systematic undercoverage, especially for small organizations, new ventures, non-English sources, and actors whose work is poorly indexed.
- Never use protected traits, prestige proxies, university/company rankings, or inferred political alignment in admission scoring.

## 12. Short decision rule

An actor is worth proposing when it is a real and eligible entity, within the maintenance scope, demonstrably and currently active in a covered topic, supported by traceable evidence, complete enough to be useful, and distinct enough to improve the map. The agent judges those properties; a human judges whether to admit the record and how strategically important it is.
