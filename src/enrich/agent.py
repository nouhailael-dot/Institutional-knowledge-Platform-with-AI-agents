"""Stage 2 — enrich ONE (actor, field) from the web, with a citation.

Claude is given the actor's known context + the target field, the web_search
and web_fetch server tools, and a single strict `submit_proposal` tool it must
call exactly once. It searches, verifies against a source, and returns a
structured proposal. If it can't find the value with a credible source, it
returns found=False rather than guessing — every accepted proposal carries an
evidence_url + evidence_snippet (the guardrail the `proposal` table enforces).

The LLM is isolated to this file (mirrors src/generate.py). MODEL is a cheap,
web-capable model per the project's enrichment cost decision; bump to Opus for
quality, or swap to Haiku 4.5 + Batch for the full run (see note below).
"""

import json
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-5"       # pilot model; project decision = cheap+web-capable
MAX_TOKENS = 2048
MAX_HOPS = 6                    # cap server-tool round-trips (pause_turn resumes)

# web_search/web_fetch tool versions with dynamic filtering. These require
# Sonnet 5 / Opus 4.6+. For a Haiku 4.5 full run, switch to the basic variants
# "web_search_20250305" / "web_fetch_20250910".
_WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5,
     "max_content_tokens": 4000},   # cap fetched content -> cost control
]

_SUBMIT_TOOL = {
    "name": "submit_proposal",
    "description": "Report the enrichment result for this one field. Call exactly once.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "found": {"type": "boolean",
                      "description": "True only if a credible source gives the value."},
            "new_value": {"type": "string",
                          "description": "The proposed value, or '' if not found. "
                                         "For country use the plain English name (e.g. 'United States')."},
            "evidence_url": {"type": "string",
                             "description": "URL of the source that supports the value, or '' if not found."},
            "evidence_snippet": {"type": "string",
                                 "description": "Short verbatim quote from the source, or '' if not found."},
            "confidence": {"type": "number",
                           "description": "0.0-1.0 confidence the value is correct for THIS entity."},
        },
        "required": ["found", "new_value", "evidence_url", "evidence_snippet", "confidence"],
        "additionalProperties": False,
    },
}

_FIELD_HINT = {
    "website": "the organization's official primary website (homepage URL). "
               "Prefer the org's own domain over directories, LinkedIn, or news.",
    "country": "the country where the organization is headquartered, as a plain "
               "English name (e.g. 'United States', 'Canada').",
}

_SYSTEM = """You verify a single factual field about a US-innovation-ecosystem \
organization by searching the web. You are filling gaps in a curated research map.

Rules:
1. Identify the SPECIFIC organization from the context given — name plus city/ \
state/type/hubs. Do not confuse it with a similarly named entity.
2. Find the value from a CREDIBLE source (the org's own site first; then \
reputable directories, .gov/.edu, or established press).
3. Call submit_proposal exactly once. Set found=true ONLY if a source actually \
supports the value; include the source URL and a short verbatim snippet from it.
4. If you cannot confirm it, set found=false with empty strings — never guess. A \
wrong value is worse than no value.
Be efficient: a few targeted searches, then submit."""

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to .env.")
        _client = anthropic.Anthropic()
    return _client


def _context_block(actor: dict) -> str:
    """Render the actor's known fields as identification context for the prompt."""
    parts = [f"name: {actor.get('name')}"]
    for k in ("actor_type", "location_city", "state", "country", "website"):
        v = actor.get(k)
        if v and str(v).strip():
            parts.append(f"{k}: {v}")
    if actor.get("hubs"):
        parts.append(f"appears in hubs: {actor['hubs']}")
    return "\n".join(parts)


def enrich(actor: dict, field: str) -> dict:
    """Search the web for `field` on `actor`; return a proposal dict.

    Result keys: found, new_value, evidence_url, evidence_snippet, confidence,
    plus old_value and (on failure) error. Never raises for a "not found" — only
    for hard API/transport errors the caller may want to retry.
    """
    if field not in _FIELD_HINT:
        raise ValueError(f"no prompt hint for field {field!r}")

    user = (f"ORGANIZATION CONTEXT:\n{_context_block(actor)}\n\n"
            f"TARGET FIELD: {field} — {_FIELD_HINT[field]}\n\n"
            f"Find and verify this field, then call submit_proposal.")
    messages = [{"role": "user", "content": user}]
    tools = _WEB_TOOLS + [_SUBMIT_TOOL]
    client = _get_client()

    for _ in range(MAX_HOPS):
        resp = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            system=_SYSTEM, tools=tools, messages=messages,
        )
        # Did it submit? (client-side tool -> we capture and stop)
        for block in resp.content:
            if block.type == "tool_use" and block.name == "submit_proposal":
                p = dict(block.input)
                p["old_value"] = actor.get(field)
                return p
        if resp.stop_reason == "pause_turn":
            # server tool hit its per-turn cap; resume by echoing the turn back
            messages.append({"role": "assistant", "content": resp.content})
            continue
        if resp.stop_reason == "end_turn":
            # finished without submitting — treat as not found
            return {"found": False, "new_value": "", "evidence_url": "",
                    "evidence_snippet": "", "confidence": 0.0,
                    "old_value": actor.get(field),
                    "error": "model ended without calling submit_proposal"}
        # any other stop reason with tool activity: echo and continue
        messages.append({"role": "assistant", "content": resp.content})

    return {"found": False, "new_value": "", "evidence_url": "",
            "evidence_snippet": "", "confidence": 0.0,
            "old_value": actor.get(field), "error": f"exceeded {MAX_HOPS} hops"}
