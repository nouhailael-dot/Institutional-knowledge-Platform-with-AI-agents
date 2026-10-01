"""Structured output schemas shared by controlled map extraction."""

_RESULT_LIMITS = {"actor": 10, "person": 8, "event": 8}

# -- Per-entity-type schemas for the submit tool --

_PERSON_ITEM = {
    "type": "object",
    "properties": {
        "full_name":    {"type": "string", "description": "Person's full name."},
        "organization_name": {"type": "string", "description": "Current organization this person belongs to."},
        "title":        {"type": "string", "description": "Current role at this organization."},
        "bio":          {"type": "string", "description": "Short professional bio (2-3 sentences)."},
        "criteria_assessment": {"type": "array", "description": "Assess requested people criteria using supplied evidence, or mark not established.",
            "items": {"type": "object", "properties": {
                "criterion": {"type": "string"},
                "status": {"type": "string", "enum": ["supported", "not established"]},
                "explanation": {"type": "string"},
                "source_url": {"type": "string", "description": "Supplied evidence URL for a supported criterion."},
                "evidence_quote": {"type": "string", "description": "Verbatim passage supporting this specific criterion; no inferred project participation from conference attendance."}},
                "required": ["criterion", "status", "explanation"], "additionalProperties": False}},
        "linkedin_url": {"type": "string", "description": "LinkedIn profile URL if found."},
        "email":        {"type": "string", "description": "Professional email if publicly listed."},
        "sources": {
            "type": "array",
            "description": "Official profile or other sources supporting this person's role.",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "supports": {"type": "string"},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["full_name", "organization_name"],
    "additionalProperties": False,
}

_ACTOR_ITEM = {
    "type": "object",
    "properties": {
        "name":                    {"type": "string", "description": "Organization name."},
        "actor_type":              {"type": "string", "description": "e.g. startup, lab, accelerator, institute, company, nonprofit."},
        "description":             {"type": "string", "description": "One-paragraph description of the organization."},
        "website":                 {"type": "string", "description": "Homepage URL."},
        "location_city":           {"type": "string", "description": "City name."},
        "state":                   {"type": "string", "description": "US state (full name or abbreviation)."},
        "country":                 {"type": "string", "description": "Always 'United States'."},
        "primary_technical_focus": {"type": "string", "description": "Main technical domain."},
        "technical_approach":      {"type": "string", "description": "How they approach the problem."},
        "current_activities":      {"type": "string", "description": "What they are currently doing."},
        "funding_summary":         {"type": "string", "description":
            "Concise funding summary using only supplied evidence. Include disclosed amounts "
            "and currency, plus funder, purpose and year when available. Preserve qualifiers "
            "such as approximate or up to. Distinguish a total consortium award from this "
            "organization's share; never attribute the total to one member without evidence. "
            "For documented funding with no disclosed amount, say amount not disclosed. "
            "Do not estimate, convert currencies, add unrelated awards together, or treat "
            "an open funding opportunity as an awarded grant. Omit if no funding is supported."},
        "people": {
            "type": "array",
            "description": "Named founders, researchers, directors, or other key people who currently belong to this organization.",
            "items": _PERSON_ITEM,
        },
        "rankings": {
            "type": "array", "description": "Universities only. QS or Times Higher Education world rankings explicitly supported by supplied sources. Never assign a university rank to a lab, department or center. Omit when unsupported.",
            "items": {"type": "object", "properties": {
                "system": {"type": "string", "enum": ["QS World University Rankings", "Times Higher Education World University Rankings"]},
                "rank": {"type": "string", "description": "Exact published position, tie or band, e.g. =25, 201–250 or 1001+."},
                "year": {"type": "integer", "description": "Ranking edition year, not the webpage publication year."},
                "scope": {"type": "string", "enum": ["overall", "subject"]},
                "subject": {"type": "string", "description": "Exact ranked subject, or empty for overall."},
                "source_url": {"type": "string", "description": "Supplied source explicitly reporting this ranking."}},
                "required": ["system", "rank", "year", "scope", "subject", "source_url"], "additionalProperties": False}},
        # No estimated_trl: TRL is a judgment call and stays human-written,
        # same rule the enrichment agent follows for relevance/why-valuable.
    },
    "required": ["name"],
    "additionalProperties": False,
}

_EVENT_ITEM = {
    "type": "object",
    "properties": {
        "name":                {"type": "string", "description": "Event name."},
        "event_type":          {"type": "string", "description": "e.g. conference, summit, workshop, demo day, hackathon."},
        "description":         {"type": "string", "description": "What the event is about."},
        "location":            {"type": "string", "description": "City, State or venue."},
        "website":             {"type": "string", "description": "Event website URL."},
        "next_date":           {"type": "string", "description": "Next occurrence date (YYYY-MM-DD if known)."},
        "recurring_pattern":   {"type": "string", "description": "e.g. annual, quarterly, one-time."},
        "sponsoring_orgs":     {"type": "string", "description": "Organizations behind the event."},
        "thematic_focus":      {"type": "string", "description": "Key themes or topics."},
        "expected_attendance": {"type": "string", "description": "Estimated number of attendees."},
        "access_type":         {"type": "string", "description": "e.g. open, invite-only, paid."},
    },
    "required": ["name"],
    "additionalProperties": False,
}

# Evidence field, shared by every entity type. Entity-level (not per-field) to
# keep the schema small — per-field sourcing blew past the schema-complexity
# limit earlier. Each source is a URL plus what it backs up.
_SOURCES_FIELD = {
    "type": "array",
    "description": "Web sources backing this entity's data. Include at least the "
                   "primary source (the page the entity was found on). Prefer the "
                   "entity's own site and credible directories/press.",
    "items": {
        "type": "object",
        "properties": {
            "url":      {"type": "string", "description": "Source page URL."},
            "supports": {"type": "string", "description": "Which facts this source "
                         "backs up, e.g. 'website + location' or 'funding'."},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
}

_ENTITY_SCHEMAS = {
    "actor": _ACTOR_ITEM,
    "person": _PERSON_ITEM,
    "event": _EVENT_ITEM,
}

# Add the sources field to every entity schema (DRY — one definition).
for _schema in _ENTITY_SCHEMAS.values():
    _schema["properties"]["sources"] = _SOURCES_FIELD


def submit_entities_tool(entity_type: str) -> dict:
    """Build the submit_entities tool with the right item schema."""
    return {
        "name": "submit_entities",
        "description": "Report all entities found from this search. Call exactly once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entities": {
                    "type": "array",
                    "description": f"Best matching {entity_type}s found, up to "
                                   f"{_RESULT_LIMITS[entity_type]} results.",
                    "items": _ENTITY_SCHEMAS[entity_type],
                    "maxItems": _RESULT_LIMITS[entity_type],
                },
            },
            "required": ["entities"],
            "additionalProperties": False,
        },
    }

# V2 adds light-pull fields without changing production database columns.
from src.map_agent.actor_profile import CATEGORIES
_ACTOR_ITEM['properties']['actor_type'] = {'type': 'string', 'enum': CATEGORIES}
_ACTOR_ITEM['properties']['country']['description'] = 'Evidence-supported country; do not assume US for an international actor.'
for key, description in {
    'other_names': 'Former names and abbreviations, separated by semicolons.',
    'category_note': 'One-line uncertainty note, only when category is uncertain.',
    'sector': 'Evidence-supported sectors, separated by semicolons.',
    'mapped_topic': 'Specific topic this actor was found for.',
    'match_explanation': '1–2 sentences explaining the evidence-based match to the topic, not hypothetical GHUS use.',
    'international_connections': 'Documented international/Africa/Morocco programs or partnerships visible in these sources.',
}.items():
    _ACTOR_ITEM['properties'][key] = {'type':'string', 'description':description}
_ACTOR_ITEM['properties']['match_strength'] = {'type':'string', 'enum':['strong','moderate']}
_ACTOR_ITEM['properties']['category_details'] = {'type':'array', 'maxItems':8, 'items':{
    'type':'object','properties':{'label':{'type':'string'}, 'value':{'type':'string'}},
    'required':['label','value'],'additionalProperties':False}}
_ACTOR_ITEM['properties']['actor_relationships'] = {'type':'array','maxItems':8,'items':{
    'type':'object','properties':{'organization_name':{'type':'string'},
    'relationship':{'type':'string','enum':['unit of','operated by','member of','portfolio of','spinout of','funded by','collaborates with']},
    'source_url':{'type':'string'}},'required':['organization_name','relationship','source_url'],'additionalProperties':False}}

_ACTOR_ITEM['properties']['multi_location'] = {'type':'boolean', 'description':'Whether the collected evidence identifies multiple physical locations.'}
