"""Deterministic normalization for discovery records."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Optional

MISSING_TOKENS = {"", "n/a", "na", "none", "null", "unknown", "tbd", "-", "--"}

COUNTRY_ALIASES = {
    "u.s.": "USA",
    "u.s.a.": "USA",
    "us": "USA",
    "usa": "USA",
    "united states": "USA",
    "united states of america": "USA",
    "morocco": "Morocco",
    "kingdom of morocco": "Morocco",
    "canada": "Canada",
    "france": "France",
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
}

DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%b %d %Y",
    "%d %B %Y",
    "%d %b %Y",
]


def normalize_event_record(record: dict[str, object]) -> dict[str, object]:
    out = {key: normalize_whitespace(value) for key, value in record.items()}
    title = out.get("title") or out.get("name")
    start_date = parse_date_to_iso(out.get("start_date") or out.get("next_date"))
    end_date = parse_date_to_iso(out.get("end_date"))

    out["title"] = title
    out["name"] = title
    out["start_date"] = start_date
    out["next_date"] = start_date
    out["end_date"] = end_date
    out["country"] = canonical_country(out.get("country"))
    out["sector_codes"] = normalize_sector_codes(out.get("sector_codes"))
    out["natural_key"] = event_natural_key(str(title or ""), str(start_date or ""))
    out["entity_type"] = "event"
    return out


def normalize_whitespace(value: object) -> object:
    if value is None or isinstance(value, list):
        return value
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    if text.lower() in MISSING_TOKENS:
        return None
    return text or None


def parse_date_to_iso(value: object) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = normalize_whitespace(value)
    if raw is None:
        return None
    text = str(raw)
    text = text.replace("Sept.", "Sep").replace("Sept ", "Sep ")
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)
    text = text.replace("–", "-").replace("—", "-")

    range_match = re.match(r"^([A-Za-z]+)\s+(\d{1,2})\s*-\s*\d{1,2},?\s+(\d{4})$", text)
    if range_match:
        text = f"{range_match.group(1)} {range_match.group(2)}, {range_match.group(3)}"
    range_match = re.match(r"^(\d{1,2})\s*-\s*\d{1,2}\s+([A-Za-z]+)\s+(\d{4})$", text)
    if range_match:
        text = f"{range_match.group(1)} {range_match.group(2)} {range_match.group(3)}"

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError as exc:
        raise ValueError(f"could not parse date {value!r}") from exc


def canonical_country(value: object) -> Optional[str]:
    cleaned = normalize_whitespace(value)
    if cleaned is None:
        return None
    lowered = str(cleaned).lower()
    return COUNTRY_ALIASES.get(lowered, str(cleaned).title())


def normalize_sector_codes(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_values = re.split(r"[,;/|]", value)
    elif isinstance(value, list):
        raw_values = value
    else:
        raw_values = [value]
    codes: list[str] = []
    for raw in raw_values:
        cleaned = normalize_whitespace(raw)
        if cleaned is None:
            continue
        code = str(cleaned).upper().strip()
        if code and code not in codes:
            codes.append(code)
    return codes


def event_natural_key(title: str, start_date: str) -> str:
    return f"{normalize_key_text(title)}|{start_date.strip()}"


def normalize_key_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return text
