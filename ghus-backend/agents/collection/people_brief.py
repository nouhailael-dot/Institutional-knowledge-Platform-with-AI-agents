"""A People request's description, read into what the search uses.

Monitor and Update -> New request -> People asks one question, "Who would you
like to find?", answered in a paragraph: expertise, roles, affiliations,
experience, preferences and exclusions (GHUS, 2026-10-29). People searches are
built from a few short themes, a role and, when named, an institution
(agents/discovery/search/people_targets.py), so the paragraph is read once,
when the request is previewed or created, into exactly those:

    themes       up to three short search phrases ("water reuse", ...)
    role         the professional role, when the description names one
    institution  one institution, only when the description restricts to it
    title        a short name for the request

Everything comes from the person's own words: nothing is added. The whole
description is kept on the request (discovery_options.brief), so the criteria
the reading leaves out - experience, preferences, exclusions - stay with it.
One small Claude call; no web search.
"""

from __future__ import annotations

import re

MODEL = "claude-haiku-4-5"
PRICING = {"input_usd_per_million": 1.0, "output_usd_per_million": 5.0}
MAX_BRIEF = 2000
MAX_THEMES = 3

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string",
                  "description": "A short name for the request, at most 80 characters, "
                                 "e.g. 'Water reuse researchers in the Southwest'."},
        "themes": {"type": "array", "minItems": 1, "maxItems": MAX_THEMES,
                   "items": {"type": "string"},
                   "description": "The expertise to search for: short phrases of two to four "
                                  "words, each stated in the description. One or two is fine; "
                                  "never pad the list with broader or related topics."},
        "role": {"type": ["string", "null"],
                 "description": "The professional role, if the description names one "
                                "(e.g. 'professor', 'program director'); else null."},
        "institution": {"type": ["string", "null"],
                        "description": "One institution, only if the description restricts the "
                                       "search to it; else null."},
    },
    "required": ["title", "themes", "role", "institution"],
}

_SYSTEM = (
    "You turn a request for people into search terms for GHUS, the UM6P Global Hubs team "
    "in the United States. Use only what the description says; never add a topic, role, "
    "place or institution it does not state. Themes are areas of expertise or research "
    "topics only - short phrases a search engine can match on a faculty or staff profile "
    "page. Preferences, experience, requirements and exclusions ('with field projects', "
    "'not pure modelling') are not themes, and neither are places. Return only the forced "
    "tool call."
)


class BriefError(ValueError):
    """The description cannot be read into a search."""


def _clean(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def read_brief(brief: str, *, client=None) -> dict:
    """{title, themes, role, institution} from a People description."""

    text = _clean(brief, MAX_BRIEF)
    if len(text) < 10:
        raise BriefError("Describe who you would like to find in a sentence or two.")
    if client is None:
        from agents.common.llm import ClaudeToolClient

        client = ClaudeToolClient(MODEL, **PRICING)
    try:
        answer = client.extract_with_tool(
            system=_SYSTEM,
            user=f"<description>\n{text}\n</description>",
            tool_name="people_search_terms",
            tool_description="Return the search terms for this request.",
            input_schema=_SCHEMA,
            max_tokens=400,
        )
    except RuntimeError as exc:
        raise BriefError(f"The description could not be read just now: {exc}") from exc
    themes = []
    for theme in answer.get("themes") or []:
        cleaned = _clean(theme, 60)
        if cleaned and cleaned.casefold() not in {t.casefold() for t in themes}:
            themes.append(cleaned)
    if not themes:
        raise BriefError("Name the expertise you are looking for in the description.")
    title = _clean(answer.get("title"), 80) or _clean(text, 80)
    return {
        "title": re.sub(r"[.\s]+$", "", title),
        "themes": themes[:MAX_THEMES],
        "role": _clean(answer.get("role"), 120) or None,
        "institution": _clean(answer.get("institution"), 120) or None,
    }


def apply_brief(fields: dict, *, client=None) -> dict:
    """A People draft whose description is read into its themes, role and name.

    Only a People draft with a description and no themes of its own is read;
    anything the person set explicitly (a name, a role, an institution) wins.
    """

    options = dict(fields.get("discovery_options") or {})
    brief = str(options.get("brief") or "").strip()
    if fields.get("discovery_entity") != "person" or not brief or fields.get("focus_terms"):
        return fields
    read = read_brief(brief, client=client)
    options["brief"] = _clean(brief, MAX_BRIEF)
    for key in ("role", "institution"):
        if read[key] and not options.get(key):
            options[key] = read[key]
    return {**fields, "title": fields.get("title") or read["title"],
            "focus_terms": read["themes"], "discovery_options": options}
