# UM6P Intelligence — Data Architecture and Map Information Design

_Working proposal for discussion with mentors. This does not change the shared database._

## 1. Design principles

1. The user-facing hierarchy is **country → ecosystem hub → actor → person**.
2. The database must not implement that hierarchy as a strict tree:
   - an actor can participate in multiple ecosystem hubs;
   - a person can hold roles at multiple actors;
   - an actor can have a parent organization, subsidiaries, labs, or programs;
   - evidence and verification belong to individual claims, not only to a whole record.
3. Agents propose records and changes. Humans approve what enters the database.
4. Discovery data, verified data, and approved database data must remain distinguishable.
5. “Relevant to the request” is contextual. It must not become a permanent claim that an
   actor is universally important or “best.”

## 2. Core layers and fields

### Country

Country is a reference layer used for navigation, normalization, and geography rules.

Required:

- `country_id`
- `name`
- `iso2_code`
- `iso3_code`
- `region`

Useful later:

- `subregion`
- `default_currency`
- `notes`

Country should not store strategic rankings. Those belong in a contextual evaluation.

### Ecosystem hub

An ecosystem hub is a geographic or thematic concentration of connected institutions. It is
not merely a city and not an individual organization.

Required identity and geography:

- `hub_id`
- `name`
- `hub_type` — geographic, thematic, hybrid
- `description`
- `primary_city`
- `state_or_region`
- `country_id`
- `official_websites`

Required mapping fields:

- `primary_topics`
- `secondary_topics`
- `core_strengths`
- `anchor_actors`
- `actor_count`
- `research_infrastructure`
- `industry_integration`
- `talent_and_workforce`
- `programs_and_labs`
- `international_engagement`
- `funding_environment`
- `constraints`

Contextual, not permanent identity fields:

- `rank`
- `why_relevant`
- `strategic_value_summary`
- `evaluation_context`

These contextual fields should live in a hub evaluation or map-result table so the same hub
can be ranked differently for different questions.

### Actor/entity

An actor is a specific organization or organizational unit: university, lab, company,
startup, government body, nonprofit, funder, accelerator, institute, or similar entity.

Required identity:

- `actor_id`
- `canonical_name`
- `aliases`
- `actor_type`
- `description`
- `website`
- `parent_actor_id` when applicable
- `operating_status` — active, inactive, acquired, merged, unknown

Required geography and classification:

- `headquarters_location_id`
- `topics`
- `primary_technical_focus`
- `primary_lifecycle_role`

Useful research fields:

- `technical_approach`
- `current_activities`
- `technology_or_ip_notes`
- `key_constraints`
- `funding_summary`
- `estimated_trl` when human-assessed

System and governance fields:

- `verification_status`
- `confidence`
- `last_verified_at`
- `merged_into_actor_id`
- `created_at`
- `updated_at`

Request-specific fields such as `rank`, `why_relevant`, and `criteria_match` belong to a map
result or evaluation, not the actor's permanent identity record.

### Person

A person is stored once and connected to organizations through dated role records.

Required identity:

- `person_id`
- `full_name`
- `profile_url` or another disambiguating identifier when available

Useful profile fields:

- `bio`
- `email`
- `phone`
- `orcid`
- `linkedin_url`
- `areas_of_expertise`
- `country_id`

System fields:

- `verification_status`
- `confidence`
- `last_verified_at`
- `created_at`
- `updated_at`

Do not store one permanent `title` as the person's organizational relationship. Titles and
affiliations change and belong in `person_actor_role`.

## 3. Required relationships

### `hub_actor`

- `hub_id`
- `actor_id`
- `relationship_type` — anchor, member, partner, funder, service provider, other
- `is_primary`
- `start_date`
- `end_date`
- provenance and verification fields

This remains many-to-many.

### `person_actor_role`

- `person_id`
- `actor_id`
- `title`
- `role_type`
- `department_or_unit`
- `is_current`
- `start_date`
- `end_date`
- `professional_email`
- provenance and verification fields

This replaces the assumption that one person belongs to only one organization. Updating a
job should close the prior role and create or update the new role rather than overwrite the
person.

### `organization_hierarchy`

- `parent_actor_id`
- `child_actor_id`
- `relationship_type` — university-lab, parent-subsidiary, department, program, acquired-by
- `start_date`
- `end_date`
- provenance and verification fields

### Topic relationships

Use a controlled `topic` table plus `actor_topic` and `hub_topic` junctions. Each link should
carry `strength`, `is_primary`, evidence, confidence, and verification status. This is needed
for the maintenance agent to know which existing topics to monitor; the current
`actor_sector` table is empty and cannot support that workflow.

## 4. Evidence, verification, and approval

The architecture should distinguish:

- **Source:** a webpage, document, feed, or dataset and when it was retrieved.
- **Evidence/claim:** a specific value or claim supported by a source.
- **Verification run:** what checks were performed, when, and with what outcome.
- **Candidate:** a discovered entity not yet approved as a database entity.
- **Proposal:** a proposed field or relationship addition/change.
- **Review decision:** who approved or rejected it, when, and why.

The existing `source`, `proposal`, verification, confidence, merge-log, and review-queue
structures should be extended rather than duplicated. A new actor proposal should not be
forced into many unrelated field proposals without a parent candidate or review bundle.

## 5. Build the Map result structure

The map should return organizations with their people attached:

```text
Map
└── ecosystem hubs
    └── actors
        └── person roles
```

The payload still needs normalized entity collections and relationship IDs internally so an
actor or person can appear in more than one place without being duplicated.

Each result should also carry:

- discovery status;
- selection state for verification/export;
- match explanation against the current request;
- sources and supported claims;
- duplicate or already-in-database status;
- verification state and last verification time;
- unresolved questions or missing required fields.

## 6. What to display in Build the Map

### Recommended default: summary card with expand

Showing the full record for every discovery makes a large map difficult to scan and presents
unverified details with too much visual authority. The default card should show:

- selection checkbox;
- actor or hub name;
- entity type;
- location;
- parent organization or primary hub, when applicable;
- one-sentence description;
- “Why it matches your request”;
- attached people count and the two most relevant names;
- source count;
- status: unverified, verifying, verified, needs review, or failed;
- “Already in database,” “Possible duplicate,” or “New” indicator.

The user can expand the card to see:

- full description;
- technical focus and approach;
- current activities;
- funding information;
- all attached people and their roles;
- hub memberships and organizational hierarchy;
- field-level or claim-level sources;
- missing information and uncertainties;
- verification details.

### Before verification

- Label all records **Unverified discovery**.
- Show summaries and sources, but visually distinguish discovered claims from verified facts.
- Let users select which records enter Verify All; select likely matches by default.
- Do not describe the record as database-ready.

### After verification

Show separate outcomes rather than one unexplained score:

- identity confirmed;
- official source reachable;
- request relevance confirmed or disputed;
- important claims supported or unsupported;
- duplicate risk;
- data completeness;
- last checked timestamp;
- concise discrepancies and reviewer action needed.

The final action should be **Propose for database**, not “Add,” until human review is wired to
the proposal workflow.

## 7. Decisions needed from mentors

1. What precisely qualifies as an ecosystem hub: geographic concentration, formal network,
   thematic cluster, or any of these?
2. Which hub fields from the original PowerPoint are mandatory, and which are contextual
   evaluation fields?
3. What are the minimum fields required before an actor or person may be proposed?
4. Should public professional email addresses be stored, or only displayed as sourced leads?
5. What counts as sufficiently recent evidence for actors, roles, funding, and events?
6. Should users see every failed verification detail, or a summary with an audit view?

## 8. Implementation sequence

1. Agree on entity definitions and mandatory fields.
2. Finalize topic taxonomy and many-to-many relationship tables.
3. Finalize candidate/proposal/review bundles and provenance rules.
4. Change discovery to return actors with linked person-role relationships.
5. Add hub discovery and hub-actor relationships.
6. Implement summary cards, expand views, selection checkboxes, and database-status badges.
7. Implement functional selective verification and post-verification results.
8. Connect approved proposals to the colleague-owned database pipeline.

