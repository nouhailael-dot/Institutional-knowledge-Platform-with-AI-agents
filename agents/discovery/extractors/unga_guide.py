"""UNGA Guide deterministic event extractor."""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from agents.discovery.extractors.event import EVENT_FIELDS, EVENT_TOOL_SCHEMA
from agents.discovery.sources.base import FetchedDoc
from agents.discovery.sources.unga_guide import _is_coming_soon

logger = logging.getLogger(__name__)

PROMPT_VERSION = "unga_guide_event_v1"
MAX_ACTOR_NAME_LENGTH = 255
CATEGORY_TO_SECTOR_CODES = {
    "ai": ["AI"],
    "data-tech": ["AI"],
    "health": ["HEALTH"],
    "food": ["AGRI"],
    "climate-environment": ["SUSTAIN"],
    "sustainable-development": ["SUSTAIN"],
    "global-development": ["SUSTAIN"],
}
ORGANIZER_CONNECTOR_SPLIT_RE = re.compile(
    r"\s*(?:;|,|\b(?:in collaboration with|in partnership with|in cooperation with|"
    r"in association with|co-hosted by|hosted by|supported by|with support from)\b)\s*",
    flags=re.IGNORECASE,
)
ORGANIZER_AND_SPLIT_RE = re.compile(r"\s+\band\s+", flags=re.IGNORECASE)
ORG_LIST_MARKERS = {
    "academy",
    "agency",
    "alliance",
    "association",
    "bank",
    "center",
    "centre",
    "coalition",
    "commission",
    "committee",
    "compact",
    "council",
    "department",
    "foundation",
    "fund",
    "group",
    "institute",
    "initiative",
    "lab",
    "labs",
    "ministry",
    "network",
    "nations",
    "organization",
    "organisation",
    "programme",
    "program",
    "project",
    "university",
    "union",
}


class UngaGuideExtractor:
    entity_type = "event"
    prompt_version = PROMPT_VERSION
    json_schema = EVENT_TOOL_SCHEMA

    def __init__(
        self,
        llm_client,
        *,
        max_tokens: int = 2048,
        coming_soon_markers: list[str] | None = None,
        people_enabled: bool = False,
    ):
        self.llm_client = llm_client
        self.max_tokens = max_tokens
        self.coming_soon_markers = coming_soon_markers or ["coming soon", "launching soon", "check back soon"]
        self.people_enabled = people_enabled

    def extract(self, doc: FetchedDoc) -> list[dict]:
        if _is_coming_soon(doc.content, self.coming_soon_markers):
            logger.warning("UNGA Guide page is coming soon; no extraction attempted for %s", doc.url)
            return []
        article_metadata = _article_metadata_by_title(doc.content)
        records = [
            _record_from_jsonld(
                event,
                doc,
                article_metadata,
                people_enabled=self.people_enabled,
            )
            for event in _jsonld_events(doc.content)
        ]
        if records:
            return records
        return [
            _record_from_article(article, doc, people_enabled=self.people_enabled)
            for article in _article_blocks(doc.content)
        ]


def _jsonld_events(content: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw in re.findall(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        try:
            payload = json.loads(raw.strip())
        except json.JSONDecodeError:
            logger.warning("could not parse UNGA Guide JSON-LD block")
            continue
        events.extend(item for item in _flatten_jsonld(payload) if _jsonld_type(item) == "event")
    return events


def _flatten_jsonld(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        flattened: list[dict[str, Any]] = []
        for item in value:
            flattened.extend(_flatten_jsonld(item))
        return flattened
    if isinstance(value, dict):
        graph = value.get("@graph")
        if isinstance(graph, list):
            return _flatten_jsonld(graph)
        return [value]
    return []


def _jsonld_type(item: dict[str, Any]) -> str:
    value = item.get("@type")
    if isinstance(value, list):
        return "event" if any(str(part).lower() == "event" for part in value) else ""
    return str(value or "").lower()


def _record_from_jsonld(
    event: dict[str, Any],
    doc: FetchedDoc,
    article_metadata: dict[str, dict[str, object]],
    *,
    people_enabled: bool,
) -> dict[str, object]:
    title = _clean_text(event.get("name"))
    metadata = article_metadata.get(_key(title), {})
    location = _location_text(event.get("location"))
    organizers = _event_organizer_names(event, metadata)
    category_slugs = list(metadata.get("category_slugs", []) or [])
    sector_codes = _sector_codes(category_slugs)
    record = {field: None for field in EVENT_FIELDS}
    record.update(
        {
            "title": title,
            "start_date": event.get("startDate"),
            "end_date": event.get("endDate"),
            "description": _clean_text(event.get("description")),
            "location": location,
            "country": _address_country(event.get("location")),
            "website": _clean_text(event.get("url")) or metadata.get("href"),
            "thematic_focus": _category_label_text(category_slugs),
            "event_type": None,
            "expected_attendance": None,
            "access_type": None,
            "recurring_pattern": None,
            "sponsoring_orgs": ", ".join(organizers) if organizers else metadata.get("organizer"),
            "sector_codes": sector_codes,
            "participant_actors": [
                {
                    "name": name,
                    "participant_role": "organizer",
                    "actor_type": None,
                    "website": None,
                }
                for name in organizers
            ],
            "participant_people": (
                _speaker_people(event.get("description")) if people_enabled else []
            ),
        }
    )
    record["source_url"] = doc.url
    record["extracted_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    record["prompt_version"] = PROMPT_VERSION
    return record


def _record_from_article(
    article: str,
    doc: FetchedDoc,
    *,
    people_enabled: bool,
) -> dict[str, object]:
    title_match = re.search(
        r'<h2[^>]*class=["\'][^"\']*\bunga-event__title\b[^"\']*["\'][^>]*>\s*<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        article,
        flags=re.IGNORECASE | re.DOTALL,
    )
    title = _clean_text(title_match.group(2) if title_match else "")
    href = html.unescape(title_match.group(1)) if title_match else None
    time_match = re.search(r"<time[^>]+datetime=[\"']([^\"']+)[\"']", article, flags=re.IGNORECASE)
    organizer_match = re.search(
        r'<p[^>]*class=["\'][^"\']*\bunga-event__organizer\b[^"\']*["\'][^>]*>(.*?)</p>',
        article,
        flags=re.IGNORECASE | re.DOTALL,
    )
    category_slugs = _category_slugs_from_class(_article_class(article))
    organizers = _split_organizer_name(
        _clean_text(organizer_match.group(1) if organizer_match else "") or ""
    )
    record = {field: None for field in EVENT_FIELDS}
    record.update(
        {
            "title": title,
            "start_date": time_match.group(1) if time_match else None,
            "website": href,
            "thematic_focus": _category_label_text(category_slugs),
            "sponsoring_orgs": ", ".join(organizers) or None,
            "sector_codes": _sector_codes(category_slugs),
            "participant_actors": [
                {
                    "name": name,
                    "participant_role": "organizer",
                    "actor_type": None,
                    "website": None,
                }
                for name in organizers
            ],
            "participant_people": _speaker_people(article) if people_enabled else [],
        }
    )
    record["source_url"] = doc.url
    record["extracted_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    record["prompt_version"] = PROMPT_VERSION
    return record


def _article_metadata_by_title(content: str) -> dict[str, dict[str, object]]:
    metadata: dict[str, dict[str, object]] = {}
    for article in _article_blocks(content):
        title_match = re.search(
            r'<h2[^>]*class=["\'][^"\']*\bunga-event__title\b[^"\']*["\'][^>]*>\s*<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            article,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not title_match:
            continue
        organizer_match = re.search(
            r'<p[^>]*class=["\'][^"\']*\bunga-event__organizer\b[^"\']*["\'][^>]*>(.*?)</p>',
            article,
            flags=re.IGNORECASE | re.DOTALL,
        )
        category_slugs = _category_slugs_from_class(_article_class(article))
        title = _clean_text(title_match.group(2))
        metadata[_key(title)] = {
            "href": html.unescape(title_match.group(1)),
            "organizer": _clean_text(organizer_match.group(1) if organizer_match else ""),
            "category_slugs": category_slugs,
        }
    return metadata


def _article_blocks(content: str) -> list[str]:
    return re.findall(
        r'<article\s+class=["\'][^"\']*\bunga_event\b[^"\']*["\'][^>]*>.*?</article>',
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _article_class(article: str) -> str:
    match = re.search(r'<article\s+class=["\']([^"\']+)["\']', article, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _category_slugs_from_class(class_value: str) -> list[str]:
    return [part.removeprefix("unga_event_category-") for part in class_value.split() if part.startswith("unga_event_category-")]


def _sector_codes(category_slugs: list[str]) -> list[str]:
    codes: list[str] = []
    for slug in category_slugs:
        for code in CATEGORY_TO_SECTOR_CODES.get(slug, []):
            if code not in codes:
                codes.append(code)
    if len(codes) >= 2 and "CROSS" not in codes:
        codes.append("CROSS")
    return codes


def _category_label_text(category_slugs: list[str]) -> str | None:
    if not category_slugs:
        return None
    return ", ".join(slug.replace("-", " ").title() for slug in category_slugs)


def _location_text(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    parts: list[str] = []
    if value.get("name"):
        parts.append(_clean_text(value["name"]))
    address = value.get("address")
    if isinstance(address, dict):
        for key in ("streetAddress", "addressLocality", "addressRegion", "postalCode"):
            if address.get(key):
                parts.append(_clean_text(address[key]))
    return ", ".join(part for part in parts if part) or None


def _address_country(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    address = value.get("address")
    if isinstance(address, dict) and address.get("addressCountry"):
        return _clean_text(address["addressCountry"])
    return None


def _organizer_names(value: Any) -> list[str]:
    raw_items = value if isinstance(value, list) else [value]
    names: list[str] = []
    for item in raw_items:
        if isinstance(item, dict) and item.get("name"):
            names.append(_clean_text(item["name"]))
        elif isinstance(item, str):
            names.append(_clean_text(item))
    return [name for name in names if name]


def _event_organizer_names(
    event: dict[str, Any],
    metadata: dict[str, object],
) -> list[str]:
    names = _organizer_names(event.get("organizers") or event.get("organizer"))
    if not names:
        names = _organizer_names(metadata.get("organizer"))
    deduped: list[str] = []
    for name in names:
        for part in _split_organizer_name(name):
            if part not in deduped:
                deduped.append(part)
    return deduped


def _split_organizer_name(value: str) -> list[str]:
    cleaned = _clean_text(value)
    if not cleaned:
        return []
    names: list[str] = []
    for piece in ORGANIZER_CONNECTOR_SPLIT_RE.split(cleaned):
        clean_piece = _clean_text(piece)
        if not clean_piece:
            continue
        names.extend(_split_and_organizer_piece(clean_piece))
    return [
        name
        for name in names
        if len(name) <= MAX_ACTOR_NAME_LENGTH and not _non_org_connector(name)
    ]


def _split_and_organizer_piece(value: str) -> list[str]:
    pieces = [_clean_text(piece) for piece in ORGANIZER_AND_SPLIT_RE.split(value)]
    names = [str(piece) for piece in pieces if piece]
    if len(names) <= 1:
        return [value]
    if all(_looks_like_standalone_org_piece(piece) for piece in names):
        return names
    return [value]


def _looks_like_standalone_org_piece(value: str) -> bool:
    stripped = value.strip()
    if re.fullmatch(r"[A-Z0-9][A-Z0-9&./-]+(?:\s+[A-Z0-9][A-Z0-9&./-]+)*", stripped):
        return True
    tokens = re.findall(r"[A-Za-z][A-Za-z&.'-]*", stripped)
    if {token.lower().strip(".") for token in tokens}.intersection(ORG_LIST_MARKERS):
        return True
    title_tokens = [token for token in tokens if token[:1].isupper()]
    return len(tokens) >= 2 and len(title_tokens) >= 2


def _non_org_connector(value: str) -> bool:
    return value.lower().strip() in {
        "and",
        "&",
        "in collaboration with",
        "in partnership with",
        "in cooperation with",
        "in association with",
        "co-hosted by",
        "hosted by",
        "supported by",
        "with support from",
    }


def _speaker_people(value: object) -> list[dict[str, object]]:
    content = html.unescape(str(value or ""))
    sections = re.findall(
        r"<h[1-6][^>]*>\s*speakers?\s*</h[1-6]>(.*?)(?=<h[1-6][^>]*>|$)",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    people: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for section in sections:
        for item in re.findall(r"<li[^>]*>(.*?)</li>", section, flags=re.IGNORECASE | re.DOTALL):
            profile_match = re.search(r'<a[^>]+href=["\']([^"\']+)["\']', item, re.IGNORECASE)
            text = _clean_text(item) or ""
            parts = re.split(r"\s+[\u2013\u2014-]\s+", text, maxsplit=1)
            name = parts[0].strip()
            details = parts[1].strip() if len(parts) > 1 else ""
            detail_parts = [part.strip() for part in details.split(",") if part.strip()]
            affiliation = detail_parts[-1] if len(detail_parts) >= 2 else None
            role = ", ".join(detail_parts[:-1]) if len(detail_parts) >= 2 else details or None
            key = (_key(name), _key(affiliation))
            if not name or not key[0] or key in seen:
                continue
            seen.add(key)
            people.append(
                {
                    "name": name,
                    "affiliation": affiliation,
                    "role": role,
                    "public_profile_url": (
                        html.unescape(profile_match.group(1)) if profile_match else None
                    ),
                }
            )
    return people


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
