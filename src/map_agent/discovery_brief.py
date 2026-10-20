"""Turn a finished organization map into a proposed Discovery request.

The Discovery page (Ismail's) reads one free-text brief: a first line naming a
sector and an area, then one short sub-topic per line. Its quality gate keeps an
organization only when every word of four letters or more in a sub-topic appears
on the organization's own page, so long phrases almost never match.

One small Haiku call proposes the brief; every value is then checked here:
- the sector must be one Discovery accepts (or empty: the user picks);
- the area must be a region or state the user actually named;
- each sub-topic must use only words the user wrote, and stay short.
Nothing is invented: a value that fails a check is dropped, not repaired.
"""

import re
from functools import lru_cache

from src.map_agent.actor_profile import REGIONS, STATE_CODES, STATE_NAMES
from src.map_agent.costs import paid_message
from src.map_agent.planner import _get_client

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 512
MAX_TERMS = 5
MAX_TERM_STEMS = 4      # discovery.js MAX_TERM_STEMS: more and the agent rarely matches

# region_definition codes, in the same order as actor_profile.REGIONS.
REGION_CODES = {
    "Northeast": "northeast",
    "Mid-Atlantic": "mid_atlantic",
    "Southeast": "southeast",
    "Midwest / Great Lakes": "midwest_great_lakes",
    "South Central / Texas Gulf": "south_central_texas_gulf",
    "Mountain West / Rocky Mountain": "mountain_west",
    "West Coast / Pacific": "west_coast_pacific",
}
STATES = dict(zip(STATE_NAMES, STATE_CODES))
# Places people write instead of a state's name, and the state each one names.
CITY_STATES = {"NYC": "New York", "New York City": "New York", "D.C.": "District of Columbia",
               "Washington DC": "District of Columbia", "Bay Area": "California",
               "Silicon Valley": "California"}

# Organization types are the kind of result, not the subject: Discovery already
# searches every type, so "universities and labs" as a sub-topic only adds noise.
_ORG_WORDS = re.compile(
    r"\b(research\s+(cent(er|re)s?|labs?|institutes?)|labs|laborator(y|ies)|institutes|universit(y|ies)"
    r"|colleges?|schools?|departments?|institutions?|compan(y|ies)|startups?|firms?"
    r"|organi[sz]ations?|manufacturers?|programs?|programmes?|academic)\b", re.I)
_LEFTOVER = re.compile(r"^(and|or|&|of|for|in)\b\s*|\s*\b(and|or|&|of|for|in)$", re.I)

_SYSTEM = """\
You turn a finished map of US organizations into a request for an agent that keeps
finding more organizations of the same kind over the coming months.

Return, using only what the USER wrote in the conversation:
- sector: the ONE sector from the list that the user's subject belongs to, or ""
  if none clearly fits.
- area: the region or state the user limited the map to, exactly as listed, or ""
  if the user named none (the whole United States).
- sub_topics: 2 to 5 short search terms (1 to 3 words each) for the subject itself,
  built from the user's own words. Not the sector name, not the area, not
  organization types ("universities", "companies"), not requirements such as
  "the 5 best". Prefer the most specific words the user used.
  A city counts as its state (NYC is New York).

Never add a topic, technology or place the user did not write."""


def _stems(text):
    """discovery.js termStems / actor_quality._stems: words of 4+ letters, cut to 4."""
    return {w[:4] for w in re.findall(r"[a-z]{4,}", str(text or "").lower())}


def _named(name, text, prefix=False):
    """`name` as a whole word in `text`; with prefix, also as a word's start
    ("Southeastern" names "Southeast")."""
    end = "" if prefix else "([^a-z0-9]|$)"
    return re.search(rf"(^|[^a-z0-9]){re.escape(name.lower())}{end}", text.lower()) is not None


@lru_cache(maxsize=1)
def sectors():
    """The sectors Discovery accepts, as {name: code}: the active rows of `topic`,
    the same list the Discovery page offers (read once, read-only)."""
    from src.db import get_readonly_connection
    with get_readonly_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT name, code FROM topic WHERE active ORDER BY name")
        return dict(cur.fetchall())


def _tool(sector_names):
    areas = list(REGIONS) + STATE_NAMES
    return {
        "name": "propose_discovery",
        "description": "Propose the Discovery request. Call exactly once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sector": {"type": "string", "enum": [*sector_names, ""]},
                "area": {"type": "string", "enum": [*areas, ""]},
                "sub_topics": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_TERMS},
            },
            "required": ["sector", "area", "sub_topics"],
            "additionalProperties": False,
        },
    }


def clean_proposal(raw, user_text, sector_codes):
    """Keep only what passes the checks; see the module docstring."""
    sector = raw.get("sector") or ""
    if sector not in sector_codes:
        sector = ""
    area = raw.get("area") or ""
    # "Midwest" names "Midwest / Great Lakes": either half of a region's name counts,
    # and so does its adjective ("Southeastern United States").
    region = area in REGIONS
    spoken = [area, *area.split(" / ")] if region else [area]
    spoken += [city for city, state in CITY_STATES.items() if state == area]
    if (area not in REGIONS and area not in STATES
            or not any(_named(n, user_text, prefix=region) for n in spoken)):
        area = ""
    allowed = _stems(user_text)
    sector_words = {name.lower() for name in sector_codes} | {c.lower() for c in sector_codes.values()}
    terms, seen = [], set()
    for term in raw.get("sub_topics") or []:
        term = re.sub(r"\s+", " ", _ORG_WORDS.sub(" ", str(term))).strip(" .,;:-")
        while _LEFTOVER.search(term):
            term = _LEFTOVER.sub("", term).strip(" .,;:-")
        stems = _stems(term)
        key = term.lower()
        if (not term or not stems or len(stems) > MAX_TERM_STEMS
                or not stems <= allowed or key in seen or key in sector_words):
            continue
        seen.add(key)
        terms.append(term)
    return {"sector": sector, "area": area, "sub_topics": terms[:MAX_TERMS]}


def brief_for(proposal, sector_codes):
    """The Discovery brief plus the structured values its form would resolve to."""
    sector, area = proposal["sector"], proposal["area"]
    kind = f"{sector} organizations" if sector else "Organizations"
    where = f"in the {area}" if area in REGIONS else f"in {area}" if area else "in the United States"
    lines = [f"{kind} {where}.", *proposal["sub_topics"]]
    return {
        "brief": "\n".join(lines),
        "sector_code": sector_codes.get(sector) if sector else None,
        "region_code": REGION_CODES.get(area),
        "state_code": STATES.get(area),
        **proposal,
    }


def propose_discovery(messages, description, run, client=None):
    """One paid call on the map's own budget; returns brief_for(...)."""
    user_text = "\n".join([description or ""] + [str(m.get("content", "")) for m in messages or []
                                                if m.get("role") == "user"]).strip()
    if not user_text:
        raise ValueError("This map has no request to build on.")
    sector_codes = sectors()
    conversation = "\n".join(f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
                             for m in messages or []) or f"USER: {description}"
    response = paid_message(
        client or _get_client(), run, "Discovery proposal",
        model=MODEL, max_tokens=MAX_TOKENS, system=_SYSTEM,
        tools=[_tool(list(sector_codes))],
        tool_choice={"type": "tool", "name": "propose_discovery"},
        messages=[{"role": "user", "content": f"SECTORS: {', '.join(sector_codes)}\n\n"
                                              f"CONVERSATION:\n{conversation[:6000]}"}],
    )
    raw = next((b.input for b in response.content
                if getattr(b, "type", "") == "tool_use" and b.name == "propose_discovery"), None)
    if raw is None:
        raise ValueError("The proposal came back empty.")
    return brief_for(clean_proposal(raw, user_text, sector_codes), sector_codes)
