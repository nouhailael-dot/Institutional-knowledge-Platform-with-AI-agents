## Table: hub

The hub is your primary first-class entity. Each row represents one geographic ecosystem.
Required fields: hub_id (UUID primary key), name (varchar, unique), slug (lowercase URL-safe ID like uc-davis-sacramento).
Location fields: primary_city, state, country (default 'USA'), region (e.g., "Sacramento Valley"). Coordinates as latitude and longitude if available.
Narrative fields (long text, nullable, from your data): description, upstream_inputs, downstream_outputs, integrated_flow_description, constraints_summary, funding_summary, cross_hub_themes.
Structural fields: primary_sectors (array of sector codes; a hub can be multi-sector), secondary_sectors (array).
Provenance fields on every row: created_at, updated_at, source_id (foreign key to source table), verification_status (enum: phase_1, ai_inferred, human_verified), confidence (real 0-1).

## Table: actor

Organizations operating within hubs. This is where your NutriCrops sheet's 144 rows mostly land.
Required: actor_id, name, slug.
Typed: actor_type (enum: university, university_lab, national_research_lab, company, startup, accelerator, government_agency, nonprofit, consortium, other).
Descriptive: description (text), website (varchar), location_city, state, country.
Technical (from NutriCrops): primary_technical_focus, technical_approach, current_activities, technology_ip_notes, key_constraints.
Lifecycle: estimated_trl (smallint 1-9, nullable), primary_lifecycle_role (enum: discovery, validation, demonstration, deployment, scaling).
Provenance: same five provenance fields as hub.

## Table: person

Empty for now in your data, but the schema needs to support it because the Phase 2 brief asks for "key researchers" queries.
Required: person_id, full_name. Optional: title, email, orcid, bio, linkedin_url. Provenance fields.

## Table: sector

The controlled vocabulary. About 15 rows total — populate it once.
Required: sector_id, code (e.g., 'AGRI'), name (e.g., 'Agriculture'), description. Hierarchy: parent_sector_id (nullable, for sub-sectors like 'Precision Agriculture' under 'Agriculture').

## Table: event

The Events Name sheet maps here directly.
Required: event_id, name, event_type, location, website. Optional: recurring_pattern (annual, biennial, etc.), next_date, sponsoring_orgs.

## Table: strategic_document

The uploaded OCP, UM6P, GHUS strategy documents.
Required: document_id, title, source_organization (enum: OCP, UM6P, GHUS, other), document_type (strategy, brief, capability, etc.), upload_date, full_text (very long text or pointer to storage), extracted_themes (array of theme strings).
Vector field for RAG: embedding (vector(1536) using pgvector). This is what lets the platform answer the brief's capability C — connecting ecosystem intelligence to UM6P/OCP priorities.

## Table: challenge

The "specific OCP/UM6P priority being matched against." NutriCrops is the first row.
Required: challenge_id, name ('NutriCrops Phosphogypsum'), sponsoring_org, description, target_sectors (array), target_technologies (array), created_date.
Optional link: source_document_id (foreign key to strategic_document — the doc that defined the challenge).

## Table: actor_relevance (junction)

This is the heart of the NutriCrops-style sheets. Crucially, this table can have many rows per actor — one per challenge the actor has been evaluated against.
Required: actor_id, challenge_id, relevance_score (real 0-1 or 1-5), maturity_risk, collaboration_orientation, why_relevant (text), current_evidence (text), additional_validation_needed (text).
This table lets the platform answer "show me actors relevant to phosphogypsum" without confusing them with actors in the general ecosystem mapping.

## Table: hub_actor (junction)

Hub-to-actor membership. Many-to-many because actors can serve multiple hubs.
Required: hub_id, actor_id, relationship_type (anchor, member, partner, peripheral), is_primary (boolean — is this the actor's primary hub).

## Table: actor_sector (junction)

Tags actors with the sectors they work in.
Required: actor_id, sector_id, confidence (real), source_id.

## Table: hub_sector_strength (computed table)

This is the precomputed answer to "which hubs are strongest for X." You compute this nightly from your other data.
Required: hub_id, sector_id, strength_score (real 0-100), actor_count, top_actor_ids (array of top 5), narrative_summary (text), last_computed.

## Table: source

Provenance for every fact.
Required: source_id, source_type (enum: phase_1_mapping, uploaded_document, external_api, ai_inference, human_entry, web_scrape), url (nullable), retrieved_at, description, trust_tier (enum: verified, candidate, unverified).

## Table: funding_source

Reference table.
Required: funding_source_id, name (e.g., 'USDA'), category (enum: federal, state, private_industry, philanthropic, venture, commodity_board).

## Table: hub_funding (junction)

Required: hub_id, funding_source_id, narrative (text — the funding details from your data).
