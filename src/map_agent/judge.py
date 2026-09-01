"""Layer 3 — Independent judge. Runs on demand (phase 2).

A SEPARATE model call, per entity, that did NOT produce the entity. It receives
the entity, its recorded sources, and the user's ORIGINAL request, and grades
how relevant and plausible the entity is. Because it is independent of the
discovery agent, it grades honestly rather than defending its own work
(LLM-as-a-judge, not self-evaluation).

Judgment only — no web tools, no fetching. It reasons over what discovery
already gathered. One cheap Haiku call per entity, run concurrently.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-4-5-20251001"   # cheap; the judge is a light filter
MAX_TOKENS = 512
MAX_WORKERS = 6

_SUBMIT_JUDGMENT = {
    "name": "submit_judgment",
    "description": "Grade this entity against the request. Call exactly once.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "relevance_score": {
                "type": "number",
                "description": "0.0-1.0: how well this entity matches what the user "
                               "asked for. 1.0 = squarely on-target, 0.0 = off-topic.",
            },
            "is_relevant": {
                "type": "boolean",
                "description": "True if this entity clearly belongs in the requested map.",
            },
            "reason": {
                "type": "string",
                "description": "One short sentence: why this score, and any concern "
                               "(wrong entity, thin sourcing, off-topic, not US).",
            },
        },
        "required": ["relevance_score", "is_relevant", "reason"],
        "additionalProperties": False,
    },
}

_SYSTEM = """\
You are an independent reviewer for a US innovation-ecosystem mapping tool. You
did NOT gather this entity — your job is to judge it honestly.

Given the user's original request and one entity (with the sources used to find
it), decide how well it matches the request. Consider:
- Relevance: does it actually fit the domain/criteria the user asked for?
- Identity: does it look like a real, specific entity (not a category label)?
- Sourcing: are there credible sources, or is the evidence thin?
- Scope: is it US-based, as required?

Be skeptical but fair. A thinly-sourced or off-topic entity should score low.
Call submit_judgment exactly once."""

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        _client = anthropic.Anthropic()
    return _client


def _render_entity(entity: dict) -> str:
    """Render the entity's fields + sources for the judge (skip internal keys)."""
    lines = []
    for k, v in entity.items():
        if k.startswith("_") or k == "sources" or not v:
            continue
        lines.append(f"{k}: {v}")
    srcs = entity.get("sources") or []
    if srcs:
        lines.append("sources:")
        for s in srcs:
            lines.append(f"  - {s.get('url','?')} ({s.get('supports','')})")
    else:
        lines.append("sources: (none provided)")

    # If the link check (Layer 2) already ran, let the judge see its verdict —
    # a dead website is evidence about the entity, not just a broken link.
    if "_links_ok" in entity:
        lc = entity.get("_link_check") or {}
        web = lc.get("website")
        if web:
            lines.append(f"link check — website: {web.get('note')} "
                         f"(status {web.get('status')})")
        bad = [r for r in lc.get("sources", []) if not r.get("ok")]
        if bad:
            lines.append(f"link check — {len(bad)} source URL(s) did not resolve")
        if not entity["_links_ok"]:
            lines.append("link check — NO working URL for this entity")

    return "\n".join(lines)


def judge_entity(entity: dict, request: str) -> dict:
    """Grade one entity against the original request. Returns the judgment dict."""
    user_msg = (f"USER'S ORIGINAL REQUEST:\n{request}\n\n"
                f"ENTITY TO JUDGE ({entity.get('_entity_type','?')}):\n"
                f"{_render_entity(entity)}\n\n"
                f"Judge this entity and call submit_judgment.")
    try:
        resp = _get_client().messages.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            system=_SYSTEM, tools=[_SUBMIT_JUDGMENT],
            messages=[{"role": "user", "content": user_msg}],
        )
        for block in resp.content:
            if block.type == "tool_use" and block.name == "submit_judgment":
                return dict(block.input)
    except Exception as e:
        return {"relevance_score": None, "is_relevant": None,
                "reason": f"judge error: {e}"}

    return {"relevance_score": None, "is_relevant": None,
            "reason": "judge did not return a verdict"}


def judge_entities(entities: list[dict], request: str) -> list[dict]:
    """Judge every entity concurrently. Annotates each with '_judge' (mutates)."""
    if not entities:
        return entities
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        verdicts = pool.map(lambda e: judge_entity(e, request), entities)
        for entity, verdict in zip(entities, verdicts):
            entity["_judge"] = verdict
    return entities
