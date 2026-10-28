"""Structured output schemas shared by controlled map extraction."""

_RESULT_LIMITS = {"actor": 10, "person": 8, "map_person": 8, "event": 8}

# Architecture V2 §5.5: what counts as a UM6P/OCP entity, and the states recorded.
_UM6P_OCP = ("A documented connection to a UM6P/OCP entity: OCP Group or its units, UM6P "
             "or its units (including UM6P United States), or INNOVX and its funds and "
             "ventures. A name with only 'UM6' (not 'UM6P') does not count. Check only "
             "the supplied sources.")
_UM6P_OCP_FIELDS = {
    "um6p_ocp_status": {"type": "string", "enum": ["found", "not found in what's been read"],
                        "description": _UM6P_OCP},
    "um6p_ocp_detail": {"type": "string",
                        "description": "When found: which UM6P/OCP entity and the kind of connection."},
    "um6p_ocp_source": {"type": "string",
                        "description": "When found: the supplied source URL showing it."},
}

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

# A person found by a people map: Architecture V2 §5.3 light pull, plus the
# organization's location so regional requests can be judged. The person record
# above stays as it is for the "Find relevant people" search on organization cards.
_MAP_PERSON_ITEM = {
    "type": "object",
    "properties": {
        "full_name":         {"type": "string", "description": "Given name and surname, spelled out as the "
                              "sources give them. Leave the person out if the sources do not give both."},
        "title":             {"type": "string", "description": "Current role."},
        "organization_name": {"type": "string", "description": "Current organization, at the most "
                              "specific level documented (the department rather than the university "
                              "when the sources name it)."},
        "organization_location": {"type": "string", "description": "City, State of that organization, "
                                  "if the sources show it."},
        "affiliation_evidence_year": {"type": "string", "description": "Year (YYYY) of the newest supplied "
                                      "source showing them at this organization. Use the current year when "
                                      "it is the organization's own current staff or profile page. Leave "
                                      "empty if the source is undated."},
        "expertise":         {"type": "string", "description": "Their expertise relevant to the request, "
                              "in a few words."},
        "profile_url":       {"type": "string", "description": "A page about this person — a staff, faculty or "
                              "academic profile, preferring the official organization page. Leave empty "
                              "if none is among the sources; a publication or news story is not a profile."},
        "work_evidence":     {"type": "string", "description": "Brief evidence of relevant work (a project, "
                              "publication, grant or role), supported by the cited sources."},
        **_UM6P_OCP_FIELDS,
        "email":             {"type": "string", "description": "Official public email, ONLY if the request "
                              "explicitly asks for contact details."},
    },
    "required": ["full_name", "organization_name"],
    "additionalProperties": False,
}

# Architecture V2 §5.4 light pull, plus the event details GHUS asked for on 20 Oct 2026.
# Field names follow the production `event` table where one exists
# (recurring_pattern, expected_attendance), so a verified event maps 1:1.
FREQUENCIES = ["One-time", "Annual", "Every two years", "Twice a year", "Quarterly",
               "Monthly", "Irregular", "Not found"]
EVENT_FORMATS = ["In-person", "Virtual", "Hybrid", "Not found"]

_EVENT_ITEM = {
    "type": "object",
    "properties": {
        "name":                {"type": "string", "description": "Event name."},
        "event_type":          {"type": "string", "description": "e.g. conference, summit, workshop, demo day, hackathon."},
        "description":         {"type": "string", "description": "What the event is about, in two to four "
                                "sentences: its themes, notable sessions or presentations relevant to the "
                                "request, and any publicly stated claim about its scale or standing (e.g. "
                                "'the leading AI conference'), quoted and backed by a cited source."},
        "sector":              {"type": "string", "description": "The ONE listed sector the event belongs to, "
                                "or 'Not found' if none fits. The specific subject goes in thematic_focus."},
        "thematic_focus":      {"type": "string", "description": "The specific topic or themes, e.g. "
                                "'critical minerals, national security'."},
        "location":            {"type": "string", "description": "City, State or venue."},
        "website":             {"type": "string", "description": "Event website URL."},
        "next_date":           {"type": "string", "description": "First day of the edition found: YYYY-MM-DD, "
                                "or YYYY-MM / YYYY when the source gives only the month or year."},
        "end_date":            {"type": "string", "description": "Last day of the same edition (YYYY-MM-DD). "
                                "Empty for a one-day event or when no source gives it."},
        "date_status":         {"type": "string", "enum": ["upcoming", "past", "date unconfirmed"],
                                "description": "Whether that edition is upcoming, past, or its date is unconfirmed. "
                                "The platform recomputes this from the dates."},
        "recurring_pattern":   {"type": "string", "enum": FREQUENCIES,
                                "description": "How often the event takes place: one-time, annual, every two "
                                "years, twice a year, quarterly, monthly, irregular, or Not found."},
        "event_format":        {"type": "string", "enum": EVENT_FORMATS,
                                "description": "In-person, virtual, hybrid, or Not found."},
        "expected_attendance": {"type": "string", "description": "Typical attendance with the edition and the "
                                "source, e.g. '≈870 delegates at the November 2025 edition (per organiser)'. "
                                "A past edition is fine. Leave empty if no source gives a number."},
        "audience":            {"type": "string", "description": "Who usually attends, as stated by a source, "
                                "e.g. 'students, founders, investors, industry professionals, government'."},
        "organizer":           {"type": "string", "description": "Organization that runs or hosts the event."},
        "match_explanation":   {"type": "string", "description": "Why it matches the request, in one short "
                                "sentence. Put details about the event in the description, not here."},
        **_UM6P_OCP_FIELDS,
        "um6p_ocp_detail":     {"type": "string", "description": "When found: which UM6P/OCP entity and its "
                                "role at the event: sponsor, speaker, partner, organizer or attendee."},
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
    "map_person": _MAP_PERSON_ITEM,
    "event": _EVENT_ITEM,
}

# Add the sources field to every entity schema (DRY — one definition).
for _schema in _ENTITY_SCHEMAS.values():
    _schema["properties"]["sources"] = _SOURCES_FIELD


def submit_entities_tool(entity_type: str, sectors: list[str] | None = None) -> dict:
    """Build the submit_entities tool with the right item schema.

    `sectors` (events only) restricts the sector to that list - the database's
    active sectors - so events group consistently; without it the field stays free."""
    item = _ENTITY_SCHEMAS[entity_type]
    if entity_type == "event" and sectors:
        item = {**item, "properties": {**item["properties"], "sector": {
            **item["properties"]["sector"], "enum": [*sectors, "Not found"]}}}
    return {
        "name": "submit_entities",
        "description": "Report all entities found from this search. Call exactly once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entities": {
                    "type": "array",
                    "description": f"Best matching "
                                   f"{'people' if entity_type == 'map_person' else entity_type + 's'} found, up to "
                                   f"{_RESULT_LIMITS[entity_type]} results.",
                    "items": item,
                    "maxItems": _RESULT_LIMITS[entity_type],
                },
            },
            "required": ["entities"],
            "additionalProperties": False,
        },
    }

# V2 adds light-pull fields without changing production database columns.
from src.map_agent.actor_profile import ALL_CATEGORY_TYPES, CATEGORIES, CATEGORY_TYPES
_ACTOR_ITEM['properties']['actor_type'] = {'type': 'string', 'enum': CATEGORIES}
# One flat list, because the schema cannot tie a list to the chosen category;
# normalize_actor_profile rejects a type from the wrong category.
_ACTOR_ITEM['properties']['category_type'] = {
    'type': 'string', 'enum': ALL_CATEGORY_TYPES,
    'description': 'Sub-type within the chosen actor_type. Use only that category\'s list: '
                   + ' | '.join(f'{c}: {", ".join(t)}' for c, t in CATEGORY_TYPES.items())}
_ACTOR_ITEM['required'] = _ACTOR_ITEM['required'] + ['category_type']
_ACTOR_ITEM['properties']['country']['description'] = 'Evidence-supported country; do not assume US for an international actor.'
for key, description in {
    'other_names': 'Former names and abbreviations, separated by semicolons.',
    'category_note': 'One-line uncertainty note, only when category is uncertain.',
    'sector': 'Evidence-supported sectors, separated by semicolons.',
    'mapped_topic': 'Specific topic this actor was found for.',
    'match_explanation': '1–2 sentences explaining the evidence-based match to the topic, not hypothetical GHUS use.',
    'international_connections': 'Documented Africa/Morocco programs or partnerships visible in these sources.',
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
