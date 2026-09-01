"""Final stage — enforce the user's request against the candidate set.

Everything upstream is built for RECALL: the planner turns the request into
keyword queries, and each discovery agent sees only its own query. By the time
results arrive, nothing has checked them against what was actually asked.

This is the one point where the whole candidate set and the original request
exist together, so it is the only place "the 4-5 best", "only in California",
or "membrane approaches, not thermal" can be evaluated.

Two deliberate choices:
  * The RAW request text is passed through verbatim alongside the parsed
    requirements. Extraction is lossy; the model should see what the user
    actually wrote so nuance the parser missed is still actionable.
  * Nothing is deleted. Entities are annotated (_selected / _rank / _why) and
    the caller decides what to show. The user paid to discover all of them, and
    a judgment call should be overridable.
"""

import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-5"     # judgment against nuanced intent — worth the tier
MAX_TOKENS = 4096

_SUBMIT = {
    "name": "submit_selection",
    "description": "Report which candidates satisfy the request. Call exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "selected": {
                "type": "array",
                "description": "The candidates that satisfy the request, BEST FIRST.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer",
                               "description": "The candidate's number from the list."},
                        "why": {"type": "string",
                                "description": "One sentence: why this one satisfies "
                                               "the request. Be specific."},
                    },
                    "required": ["id", "why"],
                },
            },
            "excluded_note": {
                "type": "string",
                "description": "One line on why the rest were left out (e.g. 'outside "
                               "California' or 'thermal rather than membrane'). Empty "
                               "if nothing was excluded.",
            },
        },
        "required": ["selected"],
    },
}

_SYSTEM = """\
You decide which research entities actually satisfy a user's request.

You are given: the user's ORIGINAL request (verbatim), the requirements parsed \
from it, and a numbered list of candidates found by web search.

How to decide:
1. HARD FILTERS are pass/fail. A candidate that violates one is excluded, no \
matter how good it otherwise looks.
2. PREFERENCES rank what survives — best first.
3. If a result limit is given, return exactly that many (fewer only if too few \
candidates qualify). If no limit is given, return every candidate that satisfies \
the request, still ordered best first.
4. Read the ORIGINAL REQUEST yourself. The parsed requirements may have missed \
something the user asked for — the raw text is authoritative.
5. Judge only on the evidence shown. Do not assume facts not present in a \
candidate's fields.

Be decisive: if a candidate does not fit, leave it out and say why in \
excluded_note. Call submit_selection exactly once."""

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        _client = anthropic.Anthropic()
    return _client


def _render(entity: dict, idx: int) -> str:
    """One compact line per candidate — enough to judge, cheap to send."""
    name = entity.get("full_name") or entity.get("name") or "?"
    bits = [f"{idx}. {name}"]
    for k in ("actor_type", "location_city", "state", "location", "title",
              "primary_technical_focus", "event_type", "next_date"):
        v = entity.get(k)
        if v:
            bits.append(str(v))
    desc = entity.get("description") or entity.get("bio") or ""
    line = " | ".join(bits)
    if desc:
        line += f"\n     {desc[:220]}"
    return line


def _has_request(requirements: dict) -> bool:
    """Is there anything to enforce beyond 'find things about this topic'?"""
    r = requirements or {}
    return bool(r.get("hard_filters") or r.get("preferences")
                or (r.get("result_limit") or 0) > 0)


def apply_request(entities: list[dict], request: str, requirements: dict,
                  doc_text: str | None = None) -> dict:
    """Rank/filter `entities` against the request. Annotates in place.

    Adds to each entity:  _selected (bool), _rank (int|None), _why (str|None)
    Returns {"selected": [...best first...], "rest": [...], "note": str}.

    No-ops (everything selected, original order) when the user stated no
    requirements — a bare topic means "show me the map", not "pick some".
    """
    if not entities:
        return {"selected": [], "rest": [], "note": ""}

    if not _has_request(requirements):
        for e in entities:
            e["_selected"], e["_rank"], e["_why"] = True, None, None
        return {"selected": entities, "rest": [], "note": ""}

    reqs = requirements or {}
    listing = "\n".join(_render(e, i) for i, e in enumerate(entities, 1))
    parts = [f"USER'S ORIGINAL REQUEST (verbatim — authoritative):\n{request}"]
    if doc_text:
        parts.append(f"\nATTACHED DOCUMENT (excerpt):\n{doc_text[:4000]}")
    parts.append(
        "\nPARSED REQUIREMENTS:"
        f"\n  hard filters: {reqs.get('hard_filters') or '(none)'}"
        f"\n  preferences:  {reqs.get('preferences') or '(none)'}"
        f"\n  result limit: {reqs.get('result_limit') or '(none given)'}")
    parts.append(f"\nCANDIDATES ({len(entities)}):\n{listing}")
    parts.append("\nDecide which satisfy the request, then call submit_selection.")

    try:
        resp = _get_client().messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=_SYSTEM,
            tools=[_SUBMIT], messages=[{"role": "user", "content": "\n".join(parts)}],
        )
        picked, note = None, ""
        for block in resp.content:
            if block.type == "tool_use" and block.name == "submit_selection":
                picked = block.input.get("selected") or []
                note = block.input.get("excluded_note") or ""
                break
        if picked is None:
            raise RuntimeError("no selection returned")
    except Exception as e:
        # Fail OPEN: a selection failure must not hide results the user paid for.
        for ent in entities:
            ent["_selected"], ent["_rank"], ent["_why"] = True, None, None
        return {"selected": entities, "rest": [],
                "note": f"(selection unavailable: {e})"}

    for e in entities:
        e["_selected"], e["_rank"], e["_why"] = False, None, None

    selected = []
    for rank, item in enumerate(picked, 1):
        i = (item.get("id") or 0) - 1
        if 0 <= i < len(entities):
            e = entities[i]
            e["_selected"], e["_rank"], e["_why"] = True, rank, item.get("why")
            selected.append(e)

    rest = [e for e in entities if not e["_selected"]]
    return {"selected": selected, "rest": rest, "note": note}
