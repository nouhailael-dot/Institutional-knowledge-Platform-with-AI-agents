"""Stage 2 — Discover entities from a single search task.

Given a query and target entity type, the agent searches the web, reads pages,
and extracts every matching entity it can find. Returns a list of partially
filled entity dicts whose keys match the DB schema for that entity type.

One agent call per search task from the planner. The loop runs up to MAX_HOPS
rounds of web_search / web_fetch before the agent must submit its findings.
"""

import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-5"
MAX_TOKENS = 8192
MAX_HOPS = 8

_WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5,
     "max_content_tokens": 4000},
]

# -- Per-entity-type schemas for the submit tool --

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
        "funding_summary":         {"type": "string", "description": "Known funding info (rounds, amounts, investors)."},
        # No estimated_trl: TRL is a judgment call and stays human-written,
        # same rule the enrichment agent follows for relevance/why-valuable.
    },
    "required": ["name"],
    "additionalProperties": False,
}

_PERSON_ITEM = {
    "type": "object",
    "properties": {
        "full_name":    {"type": "string", "description": "Person's full name."},
        "title":        {"type": "string", "description": "Current job title and organization."},
        "bio":          {"type": "string", "description": "Short professional bio (2-3 sentences)."},
        "linkedin_url": {"type": "string", "description": "LinkedIn profile URL if found."},
        "email":        {"type": "string", "description": "Professional email if publicly listed."},
    },
    "required": ["full_name"],
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


def _submit_tool(entity_type: str) -> dict:
    """Build the submit_entities tool with the right item schema."""
    return {
        "name": "submit_entities",
        "description": "Report all entities found from this search. Call exactly once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entities": {
                    "type": "array",
                    "description": f"List of {entity_type}s found.",
                    "items": _ENTITY_SCHEMAS[entity_type],
                },
            },
            "required": ["entities"],
            "additionalProperties": False,
        },
    }


_SYSTEM = """\
You are a research agent mapping US innovation ecosystems. Your job is to \
find {entity_type}s matching a search task.

Instructions:
1. Use web_search to run the query (and variations if needed).
2. Use web_fetch to read promising pages for details.
3. Extract EVERY relevant {entity_type} you find — aim for completeness.
4. Fill in as many fields as you can from credible sources.
5. For each entity, record the 'sources' you used — at minimum the page you
   found it on, plus what each source backs up. This is required for later
   verification, so never leave an entity without at least one source.
6. When done, call submit_entities with your full list.

Rules:
- US scope only. Skip entities outside the United States.
- Only include real, specific entities — no generic categories or placeholder names.
- If a field isn't available, omit it (only 'name' is required).
- Every entity MUST carry at least one source URL. Do not invent URLs — only
  use pages you actually searched or fetched.
- Be efficient: a few searches, read 2-3 key pages, then submit. Don't over-fetch."""
# NB: no "don't write code" rule here. The _20260209 web tools do their dynamic
# filtering via code execution under the hood, so the code_execution blocks seen
# in traces are the tool working as designed — telling the model to avoid them
# fights the feature. (Also why we must NOT declare code_execution separately.)

class SearchToolError(RuntimeError):
    """A task produced no entities AND its web tools were erroring."""

    def __init__(self, query: str, codes: list[str]):
        self.query, self.codes = query, codes
        super().__init__(f"web tools failed for {query!r}: {', '.join(codes)}")


_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        _client = anthropic.Anthropic()
    return _client


def server_tool_errors(content) -> list[str]:
    """Error codes from web_search / web_fetch result blocks in one response.

    Server-tool failures do NOT raise — they come back HTTP 200 with a normal
    *_tool_result block whose `content` is an error OBJECT instead of the usual
    list of results. Without this check a rate-limited or capped run looks
    exactly like "searched fine, found nothing".
    """
    kinds = ("web_search_tool_result", "web_fetch_tool_result")
    out = []
    for block in content:
        if getattr(block, "type", "") not in kinds:
            continue
        c = getattr(block, "content", None)
        if isinstance(c, list):
            continue                      # a list means results — success
        code = getattr(c, "error_code", None)
        if code is None and isinstance(c, dict):
            code = c.get("error_code")
        if code:
            out.append(str(code))
    return out


def discover(query: str, entity_type: str, focus: str = "") -> list[dict]:
    """Search the web for entities matching the query. Returns a list of dicts.

    Each dict has keys matching the DB schema for the given entity_type.
    The 'entity_type' key is added to each result for downstream processing.
    """
    if entity_type not in _ENTITY_SCHEMAS:
        raise ValueError(f"Unknown entity_type {entity_type!r}")

    system = _SYSTEM.format(entity_type=entity_type)
    user_msg = f"SEARCH TASK:\nQuery: {query}\nEntity type: {entity_type}"
    if focus:
        user_msg += f"\nFocus: {focus}"
    user_msg += "\n\nSearch the web and report what you find."

    messages = [{"role": "user", "content": user_msg}]
    tools = _WEB_TOOLS + [_submit_tool(entity_type)]
    client = _get_client()

    tool_errors: list[str] = []

    for _ in range(MAX_HOPS):
        resp = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            system=system, tools=tools, messages=messages,
        )
        tool_errors += server_tool_errors(resp.content)

        for block in resp.content:
            if block.type == "tool_use" and block.name == "submit_entities":
                entities = block.input.get("entities", []) or []
                for e in entities:
                    e["_entity_type"] = entity_type
                return entities

        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue

        # end_turn = finished without submitting; max_tokens = ran out of room
        # mid-response (a truncated tool_use can't be safely echoed back).
        if resp.stop_reason in ("end_turn", "max_tokens"):
            break

        messages.append({"role": "assistant", "content": resp.content})

    # Nothing submitted. If the web tools were erroring, this is a FAILURE, not
    # an empty result — raise so the pipeline logs it instead of silently
    # folding it in as "this search found nothing".
    if tool_errors:
        raise SearchToolError(query, tool_errors)
    return []
