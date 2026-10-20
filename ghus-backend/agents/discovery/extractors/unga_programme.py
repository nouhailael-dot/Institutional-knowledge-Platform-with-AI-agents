"""Deterministic extractor for the official UNGA high-level meetings page."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from urllib.parse import urljoin

from agents.discovery.extractors.event import EVENT_FIELDS, EVENT_TOOL_SCHEMA
from agents.discovery.sources.base import FetchedDoc

PROMPT_VERSION = "unga_programme_event_v1"
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


class UngaProgrammeExtractor:
    entity_type = "event"
    prompt_version = PROMPT_VERSION
    json_schema = EVENT_TOOL_SCHEMA

    def __init__(self, llm_client=None, *, max_tokens: int = 2048):
        self.llm_client = llm_client
        self.max_tokens = max_tokens

    def extract(self, doc: FetchedDoc) -> list[dict]:
        records: list[dict] = []
        for item in _provisional_schedule_items(doc.content):
            record = _record_from_item(item, doc)
            if record.get("title"):
                records.append(record)
        return records


def _provisional_schedule_items(content: str) -> list[str]:
    match = re.search(
        r"<h3>\s*Provisional Schedule\s*</h3>\s*<ul>(.*?)</ul>",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []
    return re.findall(r"<li>(.*?)</li>", match.group(1), flags=re.IGNORECASE | re.DOTALL)


def _record_from_item(item: str, doc: FetchedDoc) -> dict[str, object]:
    title_match = re.search(r"<strong>(.*?)</strong>", item, flags=re.IGNORECASE | re.DOTALL)
    title = _clean_text(title_match.group(1) if title_match else item.split(":", 1)[0])
    start_date, end_date = _date_range(_clean_text(item) or "")
    record = {field: None for field in EVENT_FIELDS}
    record.update(
        {
            "title": title,
            "start_date": start_date,
            "end_date": end_date,
            "description": _clean_text(item),
            "location": None,
            "country": None,
            "website": _first_href(item, doc.url) or doc.url,
            "thematic_focus": _focus_from_title(title),
            "event_type": "UN General Assembly high-level meeting",
            "expected_attendance": None,
            "access_type": None,
            "recurring_pattern": None,
            "sponsoring_orgs": "United Nations General Assembly",
            "sector_codes": _sector_codes_from_title(title),
            "participant_actors": [
                {
                    "name": "United Nations General Assembly",
                    "participant_role": "convener",
                    "actor_type": "intergovernmental_organization",
                    "website": "https://www.un.org/en/ga/",
                }
            ],
            "participant_people": [],
        }
    )
    record["source_url"] = doc.url
    record["extracted_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    record["prompt_version"] = PROMPT_VERSION
    return record


def _date_range(text: str) -> tuple[str | None, str | None]:
    year_match = re.search(r"\b(20\d{2})\b", text)
    year = year_match.group(1) if year_match else ""
    month_names = "|".join(MONTHS)
    dated = re.findall(rf"\b(\d{{1,2}}\s+(?:{month_names})(?:\s+20\d{{2}})?)\b", text)
    normalized = [_ensure_year(value, year) for value in dated]
    return (normalized[0] if normalized else None, normalized[-1] if normalized else None)


def _ensure_year(value: str, year: str) -> str:
    return value if re.search(r"\b20\d{2}\b", value) or not year else f"{value} {year}"


def _first_href(item: str, base_url: str) -> str | None:
    match = re.search(r"<a[^>]+href=[\"']([^\"']+)[\"']", item, flags=re.IGNORECASE)
    return urljoin(base_url, html.unescape(match.group(1))) if match else None


def _focus_from_title(title: object) -> str | None:
    text = str(title or "").lower()
    if "climate" in text or "sea level" in text:
        return "Climate and environment"
    if "pandemic" in text or "health" in text:
        return "Health"
    if "sustainable development" in text or "sdg" in text:
        return "Sustainable development"
    if "right to development" in text or "durban" in text:
        return "Human rights and development"
    if "nuclear weapons" in text:
        return "Peace and security"
    return "UN General Assembly"


def _sector_codes_from_title(title: object) -> list[str]:
    text = str(title or "").lower()
    codes: list[str] = []
    if "climate" in text or "sea level" in text:
        codes.append("SUSTAIN")
    if "pandemic" in text or "health" in text:
        codes.append("HEALTH")
    if "sustainable development" in text or "sdg" in text:
        codes.append("SUSTAIN")
    return codes


def _clean_text(value: object) -> str | None:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None
