"""Structured facts read from a discovery page, each kept only with its evidence.

A person's or an event's page states much more than the canonical record
holds - a department, expertise, named work; an organiser, a registration
link, a format, themes. The rubric call already reads the page; it now also
returns those facts, separately, each with a quote copied from the page. A
fact whose quote is not on the page is dropped - never kept as a guess.

The facts travel with the candidate (search_candidate.record_preview) and the
staged record (staged_record.payload) into Review: the existing staging and
provenance path, not a second fact store. Each kept fact carries its quote,
the page it is on, and when the page was read; the run is the candidate's.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from bs4 import BeautifulSoup

from agents.collection.light_pull_reader import _footer_text, quote_on_page
from agents.discovery.search.actor_scoring import _visible_html_text

_TEXT = {"type": ["string", "null"]}
_LIST = {"type": "array", "items": {"type": "string"}, "maxItems": 6}


def _evidence(fields) -> dict:
    return {"type": "object", "additionalProperties": False,
            "description": "For each fact given, up to 30 words copied exactly from the page "
                           "that state it.",
            "properties": {f: _TEXT for f in fields}}


# Professional facts only (AGENTS rule 11, TARGETING_POLICY section 6): never
# contact details or private information. A short PROFESSIONAL bio, as the
# official page states it, is collected (GHUS decision 2026-10-25: a complete
# profile has a bio or a public LinkedIn) - never family, age, home or contact.
PERSON_FACT_FIELDS = ("bio", "department", "expertise", "relevant_work",
                      "um6p_ocp_connection", "work_location", "other_affiliations")
PERSON_FACT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "description": "Professional facts the page states about THIS person, each with evidence. "
                   "Never contact details or private information.",
    "properties": {
        "bio": {**_TEXT, "description": "The person's professional biography exactly as "
                                        "this page states it: up to three sentences "
                                        "(about 80 words) copied from the page - role, "
                                        "background, research or professional focus, "
                                        "notable work. Never family, age, home, personal "
                                        "life or contact details. Null when the page has "
                                        "no biography of this person."},
        "department": {**_TEXT, "description": "The department, laboratory, school or unit "
                                                "the person works in."},
        "expertise": {**_LIST, "description": "Research areas or professional specialisms, "
                                              "each a short phrase."},
        "relevant_work": {"type": "array", "maxItems": 3, "items": {"type": "string"},
                          "description": "Up to three named projects, programmes, grants or "
                                         "publications, each a short title."},
        "um6p_ocp_connection": {**_TEXT, "description": "Any stated link with UM6P, OCP Group "
                                                        "or Morocco."},
        "work_location": {**_TEXT, "description": "Where the person works - the city and "
                                                  "state of their office or campus - only "
                                                  "as the page states it. Never a home."},
        "other_affiliations": {"type": "array", "maxItems": 4, "items": {"type": "string"},
                               "description": "Other organisations the page says the person "
                                              "is affiliated with (joint appointments, "
                                              "boards, centres), each its name."},
        "evidence": _evidence(("affiliation", "role", *PERSON_FACT_FIELDS)),
    },
}

EVENT_FACT_FIELDS = ("organizer", "registration_url", "registration_deadline", "format",
                     "event_status", "themes", "speakers", "participating_organizations",
                     "um6p_ocp_involvement", "standing_claims")
EVENT_FACT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "description": "Facts the page states about THIS event, each with evidence.",
    "properties": {
        "page_kind": {"type": ["string", "null"],
                      "enum": ["official_event_site", "organizer_page", "listing", "news",
                               "other", None],
                      "description": "What this page is: the event's own site, its "
                                     "organiser's page about it, a listing of many events, a "
                                     "news article, or other."},
        "organizer": {**_TEXT, "description": "The organisation that organises or hosts it."},
        "registration_url": {**_TEXT, "description": "The registration link, as on the page."},
        "registration_deadline": {**_TEXT, "description": "The registration deadline as "
                                                           "written."},
        "format": {"type": ["string", "null"], "enum": ["in_person", "online", "hybrid", None]},
        "event_status": {"type": ["string", "null"],
                         "enum": ["scheduled", "postponed", "cancelled", None]},
        "themes": {**_LIST, "description": "Main themes or agenda tracks, each a short phrase."},
        "speakers": {"type": "array", "maxItems": 12, "items": {"type": "string"},
                     "description": "Confirmed speakers the page names, each 'Name, role or "
                                    "organisation' as written. Professional details only."},
        "participating_organizations": {"type": "array", "maxItems": 12,
                                        "items": {"type": "string"},
                                        "description": "Sponsors, partners, exhibitors or "
                                                       "participating organisations the page "
                                                       "names, each its name."},
        "um6p_ocp_involvement": {**_TEXT, "description": "Any visible UM6P, OCP Group or "
                                                         "INNOVX involvement, as stated."},
        "standing_claims": {"type": "array", "maxItems": 3, "items": {"type": "string"},
                            "description": "Claims the page makes about the event's scale, "
                                           "reputation or standing (e.g. 'the largest water "
                                           "conference in North America'), each copied "
                                           "exactly."},
        "evidence": _evidence(("start_date", "location", *EVENT_FACT_FIELDS)),
    },
}

# Facts judged from the whole page rather than one sentence: no quote needed.
_JUDGED = {"page_kind"}
# Lists are checked item by item: an item stays when it is on the page (for a
# speaker, the name before the first comma), or when every word of it is in a
# quote that is on the page. Items the page does not support are dropped.
_LISTS = {"themes", "speakers", "participating_organizations", "standing_claims",
          "expertise", "relevant_work", "other_affiliations"}
# Text kept only when the text itself is on the page (no paraphrase).
_ON_PAGE = {"bio"}


def _item_supported(item: str, text: str, quote: str | None) -> bool:
    head = item.split(",")[0].strip()
    if quote_on_page(item, text) or (head and quote_on_page(head, text)):
        return True
    words = [w for w in re.findall(r"[a-z0-9]+", item.casefold()) if len(w) > 3]
    said = set(re.findall(r"[a-z0-9]+", str(quote or "").casefold()))
    return bool(words) and all(w in said for w in words)


READING_MAX_CHARS = 16000
_STRUCTURED_TYPES = ("event", "person", "educationevent", "businessevent")
_KEY_LINK = re.compile(r"regist|ticket|rsvp|agenda|program|linkedin\.com/in/", re.I)


def _structured_data(soup) -> list[str]:
    """schema.org Event or Person blocks (JSON-LD), compact: dates, place, organiser, status."""
    blocks: list[str] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (TypeError, ValueError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) \
            if isinstance(data, dict) else []
        for item in items:
            kind = item.get("@type") if isinstance(item, dict) else None
            kinds = kind if isinstance(kind, list) else [kind]
            if any(str(k or "").lower() in _STRUCTURED_TYPES for k in kinds):
                blocks.append(json.dumps(item, ensure_ascii=False)[:2000])
    return blocks[:3]


def _key_links(soup) -> list[str]:
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ", strip=True).split())[:80]
        href = str(a["href"]).strip()
        if href not in seen and (_KEY_LINK.search(text) or _KEY_LINK.search(href)):
            seen.add(href)
            links.append(f"{text or 'link'}: {href}")
    return links[:12]


def page_text(html: str) -> str:
    """What the agent reads of a page: its readable text, not the raw HTML.

    The first 16,000 characters of raw HTML were mostly scripts and styles
    (a median 6% of an event page's text). This is the page's title and
    description, main text, footer, schema.org Event/Person data and its
    registration, agenda and LinkedIn links - the same text quotes are
    checked against.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    structured = _structured_data(soup)
    links = _key_links(soup)
    footer = _footer_text(html or "")
    tail = "".join([
        f"\nStructured data: {' | '.join(structured)}" if structured else "",
        f"\nLinks: {' | '.join(links)}" if links else "",
        f"\nFooter: {footer}" if footer else "",
    ])[:READING_MAX_CHARS // 3]
    body = _visible_html_text(html or "")[:READING_MAX_CHARS - len(tail)]
    return body + tail


def reading_text(content: str, content_type: str | None) -> str:
    """The text given to the model: the readable page for HTML, else the content."""
    if "html" in str(content_type or "").lower() or "<html" in (content or "")[:2000].lower():
        return page_text(content)
    return (content or "")[:READING_MAX_CHARS]


def verify_facts(facts: object, *, html: str, source_url: str, read_at: datetime,
                 fields: tuple[str, ...]) -> dict:
    """Keep each fact only with a quote that is on the page; say what was dropped.

    Returns {field: value, ..., "evidence": {field: {quote, source_url, date_read}},
    "dropped": [field, ...]} - empty fields are left out.
    """
    if not isinstance(facts, dict):
        return {}
    text = page_text(html)
    quotes = facts.get("evidence") if isinstance(facts.get("evidence"), dict) else {}
    kept: dict = {}
    evidence: dict = {}
    dropped: list[str] = []
    for key in (*fields, *[k for k in facts if k in _JUDGED]):
        value = facts.get(key)
        if value in (None, "", [], {}):
            continue
        if key in _JUDGED:
            kept[key] = value
            continue
        quote = str(quotes.get(key) or "").strip()
        if key in _LISTS and isinstance(value, list):
            supported_quote = quote if quote and quote_on_page(quote, text) else None
            items = [str(v).strip() for v in value
                     if str(v).strip() and _item_supported(str(v), text, supported_quote)]
            if not items:
                dropped.append(key)
                continue
            kept[key] = items
            evidence[key] = {"quote": supported_quote, "source_url": source_url,
                             "date_read": read_at.isoformat(),
                             **({"items_dropped": len(value) - len(items)}
                                if len(items) < len(value) else {})}
            continue
        if key in _ON_PAGE:
            bio = " ".join(str(value).split())
            if not quote_on_page(bio, text):
                dropped.append(key)
                continue
            kept[key] = bio
            evidence[key] = {"quote": bio, "source_url": source_url,
                             "date_read": read_at.isoformat()}
            continue
        if key == "registration_url":
            # A link: it must be on the page as a link or as text.
            if str(value) in (html or ""):
                kept[key] = value
                evidence[key] = {"quote": None, "source_url": source_url,
                                 "date_read": read_at.isoformat()}
            else:
                dropped.append(key)
            continue
        if not quote or not quote_on_page(quote, text):
            dropped.append(key)
            continue
        kept[key] = value
        evidence[key] = {"quote": quote, "source_url": source_url,
                         "date_read": read_at.isoformat()}
    # Evidence for record fields (dates, place, role ...) the record itself holds.
    for key, quote in quotes.items():
        if key not in evidence and key not in fields and quote and quote_on_page(str(quote), text):
            evidence[key] = {"quote": str(quote), "source_url": source_url,
                             "date_read": read_at.isoformat()}
    if evidence:
        kept["evidence"] = evidence
    if dropped:
        kept["dropped"] = dropped
    return kept
