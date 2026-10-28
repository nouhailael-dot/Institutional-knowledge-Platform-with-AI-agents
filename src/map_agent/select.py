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
from datetime import date

import anthropic
from dotenv import load_dotenv
from src.map_agent.costs import paid_message
from src.map_agent.run_store import MapStopped
from src.map_agent.search_backend import operation_key

load_dotenv()

MODEL = "claude-sonnet-5"     # judgment against nuanced intent — worth the tier
# Thinking shares this budget. At 1024 the model spent all of it reasoning over
# ~14+ candidates and never answered, so the filters silently went unapplied.
MAX_TOKENS = 8000
EFFORT = "medium"             # a fairly mechanical comparison; less thinking, faster answer

# How the selection stage ended, so the page can say so plainly.
APPLIED, NO_REQUIREMENTS, NONE_MATCHED, FAILED = "applied", "no_requirements", "none_matched", "failed"

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
            "excluded": {
                "type": "array",
                "description": "EVERY candidate not selected, each with a short reason "
                               "naming the requirement it fails.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer",
                               "description": "The candidate's number from the list."},
                        "reason": {"type": "string",
                                   "description": "A few words: 'company, not an "
                                                  "accelerator', 'in Dallas, outside "
                                                  "the region'."},
                        "fits": {"type": "boolean",
                                 "description": "True when it meets every hard filter "
                                                "and was left out only by the result "
                                                "limit."},
                    },
                    "required": ["id", "reason"],
                },
            },
        },
        "required": ["selected", "excluded"],
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
6. An event whose date status is "date unconfirmed" does not meet a requirement \
about when it takes place (for example "in the next 12 months"); exclude it \
with that reason. An event's date status was computed from its dates against \
today's date: trust it, and never exclude an event for its year alone.
7. A person whose affiliation is marked "unconfirmed" is not established as \
working there now, so a requirement about their current organization or \
location is not met; exclude them with that reason.

Be decisive. Every candidate goes in exactly one list: `selected` or \
`excluded`. Give each excluded one a short reason naming the requirement it \
fails — the user sees it next to the organization. If a result limit is the \
only reason a candidate was left out, still list it in `excluded` with \
fits: true. Call submit_selection exactly once."""

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
    for k in ("actor_type", "category_type", "location_city", "state", "location", "title",
              "organization_name", "organization_location", "affiliation_note", "expertise",
              "primary_technical_focus", "event_type", "next_date", "end_date", "date_status"):
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


def _mark(entity, selected, rank=None, why=None, why_not=None, beyond_limit=False):
    entity["_selected"], entity["_rank"] = selected, rank
    entity["_why"], entity["_why_not"] = why, why_not
    entity["_beyond_limit"] = beyond_limit


def apply_request(entities: list[dict], request: str, requirements: dict,
                  doc_text: str | None = None, run=None) -> dict:
    """Rank/filter `entities` against the request. Annotates in place.

    Adds to each entity: _selected, _rank, _why (selected) and _why_not (excluded).
    Returns {"selected": [...best first...], "rest": [...], "note": str,
             "outcome": APPLIED | NO_REQUIREMENTS | NONE_MATCHED | FAILED}.

    No-ops (everything selected, original order) when the user stated no
    requirements — a bare topic means "show me the map", not "pick some".
    """
    if not entities:
        return {"selected": [], "rest": [], "note": "", "outcome": NO_REQUIREMENTS}

    if not _has_request(requirements):
        for e in entities:
            _mark(e, True)
        return {"selected": entities, "rest": [], "note": "", "outcome": NO_REQUIREMENTS}

    reqs = requirements or {}
    listing = "\n".join(_render(e, i) for i, e in enumerate(entities, 1))
    parts = [f"TODAY'S DATE: {date.today().isoformat()}",
             f"USER'S ORIGINAL REQUEST (verbatim — authoritative):\n{request}"]
    if doc_text:
        parts.append(f"\nATTACHED DOCUMENT (excerpt):\n{doc_text[:4000]}")
    parts.append(
        "\nPARSED REQUIREMENTS:"
        f"\n  hard filters: {reqs.get('hard_filters') or '(none)'}"
        f"\n  preferences:  {reqs.get('preferences') or '(none)'}"
        f"\n  result limit: {reqs.get('result_limit') or '(none given)'}")
    parts.append(f"\nCANDIDATES ({len(entities)}):\n{listing}")
    parts.append("\nDecide which satisfy the request, then call submit_selection.")

    # Keyed on the inputs, not a fixed name: a resumed run replays its own answer,
    # but a follow-up that added candidates or changed the request is judged again
    # rather than handed the first answer's now-misaligned candidate numbers.
    key = operation_key("select-v2", {"request": request, "requirements": reqs,
                                      "candidates": listing})
    try:
        resp = paid_message(_get_client(), run, "Selection",
            operation_key=key,
            model=MODEL, max_tokens=MAX_TOKENS, system=_SYSTEM,
            output_config={"effort": EFFORT},
            tools=[_SUBMIT], messages=[{"role": "user", "content": "\n".join(parts)}],
        )
        picked = excluded = None
        for block in resp.content:
            if block.type == "tool_use" and block.name == "submit_selection":
                picked = block.input.get("selected") or []
                excluded = block.input.get("excluded") or []
                break
        if picked is None:
            raise RuntimeError("the output limit was reached before it answered"
                               if resp.stop_reason == "max_tokens" else "no selection returned")
    except MapStopped:
        raise
    except Exception as e:
        # Fail OPEN: a selection failure must not hide results the user paid for.
        for ent in entities:
            _mark(ent, True)
        return {"selected": entities, "rest": [], "outcome": FAILED,
                "note": f"Your filters could not be applied ({e}). These results are unfiltered."}

    for e in entities:
        _mark(e, False)

    reasons, fits = {}, set()
    for item in excluded:
        i = (item.get("id") or 0) - 1
        if not 0 <= i < len(entities):
            continue
        # The tool schema is not strictly enforced; in live use the model has
        # written the reason under "why", the key it uses for selected items.
        reason = item.get("reason") or item.get("why")
        if reason:
            reasons[i] = str(reason).strip()
        if item.get("fits") is True:
            fits.add(i)

    selected = []
    for rank, item in enumerate(picked, 1):
        i = (item.get("id") or 0) - 1
        if 0 <= i < len(entities) and not entities[i]["_selected"]:
            _mark(entities[i], True, rank=len(selected) + 1, why=item.get("why"))
            selected.append(entities[i])

    rest = [e for e in entities if not e["_selected"]]
    # A result-limit cut is not a mismatch. When the limit was reached, anything
    # the model left unlisted gets the one label true either way: it is not among
    # the top N, whether or not it would otherwise have fitted.
    limit = reqs.get("result_limit") or 0
    limit_reached = limit > 0 and len(selected) >= limit
    for i, e in enumerate(entities):
        if e["_selected"]:
            continue
        if limit > 0 and (i in fits or (limit_reached and i not in reasons)):
            e["_beyond_limit"] = True
            e["_why_not"] = f"Not among the top {limit} you asked for."
        else:
            e["_why_not"] = reasons.get(i) or "No reason given."

    kinds = {e.get("_entity_type") for e in entities}
    noun = {"person": "people", "event": "events"}.get(kinds.pop(), "organizations") \
        if len(kinds) == 1 else "results"
    if not selected:
        return {"selected": [], "rest": rest, "outcome": NONE_MATCHED,
                "note": f"None of the {len(entities)} {noun} matched your filters. "
                        "Each is shown with the reason it was left out."}
    return {"selected": selected, "rest": rest, "outcome": APPLIED,
            "note": f"{len(selected)} of {len(entities)} match your request."}
