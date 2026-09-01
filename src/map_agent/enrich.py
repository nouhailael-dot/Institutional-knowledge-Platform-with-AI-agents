"""Stage 3 — Enrich a single entity found during discovery.

Takes one partially-filled entity dict, searches the web for more details,
and returns a more complete version. Same loop pattern as discover.py but
focused on ONE entity — visit its website, search for specifics, fill gaps.
"""

import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-5"
MAX_TOKENS = 4096
MAX_HOPS = 6

_WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 3},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 3,
     "max_content_tokens": 4000},
]

_ACTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "name":                    {"type": "string"},
        "actor_type":              {"type": "string"},
        "description":             {"type": "string"},
        "website":                 {"type": "string"},
        "location_city":           {"type": "string"},
        "state":                   {"type": "string"},
        "country":                 {"type": "string"},
        "primary_technical_focus": {"type": "string"},
        "technical_approach":      {"type": "string"},
        "current_activities":      {"type": "string"},
        "funding_summary":         {"type": "string"},
        # No estimated_trl — judgment field, stays human-written (see discover.py).
    },
    "required": ["name"],
    "additionalProperties": False,
}

_PERSON_SCHEMA = {
    "type": "object",
    "properties": {
        "full_name":    {"type": "string"},
        "title":        {"type": "string"},
        "bio":          {"type": "string"},
        "linkedin_url": {"type": "string"},
        "email":        {"type": "string"},
    },
    "required": ["full_name"],
    "additionalProperties": False,
}

_EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "name":                {"type": "string"},
        "event_type":          {"type": "string"},
        "description":         {"type": "string"},
        "location":            {"type": "string"},
        "website":             {"type": "string"},
        "next_date":           {"type": "string"},
        "recurring_pattern":   {"type": "string"},
        "sponsoring_orgs":     {"type": "string"},
        "thematic_focus":      {"type": "string"},
        "expected_attendance": {"type": "string"},
        "access_type":         {"type": "string"},
    },
    "required": ["name"],
    "additionalProperties": False,
}

_SCHEMAS = {
    "actor": _ACTOR_SCHEMA,
    "person": _PERSON_SCHEMA,
    "event": _EVENT_SCHEMA,
}

# Enrichment must be able to CONTRIBUTE sources for the fields it adds — and the
# merge in enrich_entity() keeps the ones discovery already found. Without this
# the verification layers have nothing to check.
_SOURCES_FIELD = {
    "type": "array",
    "description": "Sources for the fields you filled in. Add to what is already "
                   "there; do not invent URLs.",
    "items": {
        "type": "object",
        "properties": {
            "url":      {"type": "string", "description": "Source page URL."},
            "supports": {"type": "string", "description": "Which facts it backs up."},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
}

for _schema in _SCHEMAS.values():
    _schema["properties"]["sources"] = _SOURCES_FIELD


def _submit_tool(entity_type: str) -> dict:
    return {
        "name": "submit_enriched",
        "description": "Submit the enriched entity with all fields filled. Call exactly once.",
        "input_schema": _SCHEMAS[entity_type],
    }


_SYSTEM = """\
You are enriching a single {entity_type} for a US innovation-ecosystem map.

You are given an entity with some fields already filled. Your job:
1. Visit the entity's website (if known) to gather details.
2. Search the web for additional information about this specific entity.
3. Fill in as many missing fields as you can from credible sources.
4. Call submit_enriched with the complete entity.

Rules:
- Keep existing values unless you find a clear correction.
- Only fill fields you can verify — leave them empty rather than guess.
- Be efficient: fetch the website, maybe one search, then submit."""
# No "don't write code" rule — see the note in discover.py: the _20260209 web
# tools run code execution internally for dynamic filtering.

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        _client = anthropic.Anthropic()
    return _client


def _merge_sources(old: list | None, new: list | None) -> list:
    """Union of two source lists, de-duplicated by URL, originals first."""
    out, seen = [], set()
    for group in (old or [], new or []):
        for s in group:
            url = (s or {}).get("url")
            if url and url not in seen:
                seen.add(url)
                out.append(s)
    return out


def _format_known(entity: dict, entity_type: str) -> str:
    """Render what we already know about the entity."""
    lines = []
    for k, v in entity.items():
        if k.startswith("_") or not v:
            continue
        lines.append(f"{k}: {v}")
    return "\n".join(lines) if lines else "(only the name is known)"


def enrich_entity(entity: dict) -> dict:
    """Take a partial entity, search for details, return a more complete version.

    The input must have '_entity_type' set by the discovery stage.
    """
    entity_type = entity.get("_entity_type")
    if entity_type not in _SCHEMAS:
        raise ValueError(f"Unknown entity_type: {entity_type!r}")

    system = _SYSTEM.format(entity_type=entity_type)
    known = _format_known(entity, entity_type)
    name_field = "full_name" if entity_type == "person" else "name"
    name = entity.get(name_field, "unknown")

    user_msg = (f"ENTITY TO ENRICH ({entity_type}):\n{known}\n\n"
                f"Search for more details about {name} and call submit_enriched.")

    messages = [{"role": "user", "content": user_msg}]
    tools = _WEB_TOOLS + [_submit_tool(entity_type)]
    client = _get_client()

    for _ in range(MAX_HOPS):
        resp = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            system=system, tools=tools, messages=messages,
        )

        for block in resp.content:
            if block.type == "tool_use" and block.name == "submit_enriched":
                # MERGE onto the original — never replace it. The model only
                # returns the schema's fields, so a wholesale swap would drop
                # everything discovery gathered (notably `sources`, which the
                # whole verification layer depends on).
                result = {**entity, **{k: v for k, v in block.input.items() if v}}
                result["sources"] = _merge_sources(entity.get("sources"),
                                                   block.input.get("sources"))
                result["_entity_type"] = entity_type
                return result

        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue

        # end_turn = done without submitting; max_tokens = truncated mid-response.
        # Either way, fall back to the entity we already have.
        if resp.stop_reason in ("end_turn", "max_tokens"):
            return entity

        messages.append({"role": "assistant", "content": resp.content})

    return entity
