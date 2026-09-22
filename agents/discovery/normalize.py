"""Deterministic normalization for discovery records."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, date, datetime
from urllib.parse import urlparse

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

AFFILIATION_ORGANISATION_MARKERS = (
    "academy",
    "bureau",
    "college",
    "company",
    "corporation",
    "foundation",
    "institute",
    "lab",
    "laboratory",
    "organisation",
    "organization",
    "university",
)
AFFILIATION_UNIT_MARKERS = (
    "battery research group",
    "center for",
    "centre for",
    "chemical and biological engineering",
    "department of",
    "faculty of",
    "laboratory of",
    "materials science & engineering",
    "materials science and engineering",
    "mechanical engineering",
    "research group",
    "school of",
)
AFFILIATION_ROLE_PREFIX_RE = re.compile(
    r"^(?:assistant|associate|adjunct|full|visiting)?\s*"
    r"(?:professor|researcher|scientist|director|dean|chair|fellow|engineer)\b",
    flags=re.IGNORECASE,
)


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


def normalize_actor_record(record: dict[str, object]) -> dict[str, object]:
    out = {key: normalize_whitespace(value) for key, value in record.items()}
    out["name"] = out.get("name")
    out["country"] = canonical_country(out.get("country"))
    out["sector_codes"] = normalize_sector_codes(out.get("sector_codes"))
    out["estimated_trl"] = parse_optional_int(out.get("estimated_trl"))
    out["natural_key"] = actor_natural_key(str(out.get("name") or ""), out.get("website"))
    out["entity_type"] = "actor"
    return out


def normalize_person_record(record: dict[str, object]) -> dict[str, object]:
    out = {key: normalize_whitespace(value) for key, value in record.items()}
    out["name"] = out.get("name")
    raw_affiliation = out.get("affiliation_raw") or out.get("affiliation")
    out["affiliation_raw"] = raw_affiliation
    out["affiliation"] = normalize_affiliation_institution(raw_affiliation)
    out["sector_codes"] = []
    out["natural_key"] = person_natural_key(
        str(out.get("name") or ""),
        out.get("affiliation"),
    )
    out["entity_type"] = "person"
    return out


def normalize_affiliation_institution(value: object) -> str | None:
    """Reduce a public affiliation string to the employing institution."""
    cleaned = normalize_whitespace(value)
    if cleaned is None:
        return None
    text = str(cleaned)
    text = re.sub(
        r"\s*\(([^)]*)\)",
        lambda match: "" if _contains_unit_marker(match.group(1)) else match.group(0),
        text,
    ).strip(" ,;-")
    text = re.split(r"\s+[\u2013\u2014]\s+", text, maxsplit=1)[0].strip()

    segments = [segment.strip() for segment in text.split(",") if segment.strip()]
    institution_index = next(
        (
            index
            for index, segment in enumerate(segments)
            if _contains_organisation_marker(segment)
            and not _is_organisation_unit(segment)
        ),
        None,
    )
    if institution_index is None:
        return None

    institution = segments[institution_index]
    if AFFILIATION_ROLE_PREFIX_RE.search(institution):
        marker_positions = [
            institution.casefold().find(marker)
            for marker in AFFILIATION_ORGANISATION_MARKERS
            if institution.casefold().find(marker) >= 0
        ]
        if marker_positions:
            institution = institution[min(marker_positions) :].strip()

    # Preserve geographic suffixes that are part of an institution's public name,
    # such as "University of Nevada, Reno", but never append an academic unit.
    if institution_index + 1 < len(segments):
        suffix = segments[institution_index + 1]
        if (
            institution.casefold().startswith("university of ")
            and len(suffix.split()) <= 3
            and not _is_organisation_unit(suffix)
            and not AFFILIATION_ROLE_PREFIX_RE.search(suffix)
        ):
            institution = f"{institution}, {suffix}"

    institution = str(normalize_whitespace(institution) or "")
    if not institution or _is_organisation_unit(institution):
        return None
    return institution


def is_institution_affiliation(value: object) -> bool:
    cleaned = normalize_whitespace(value)
    return bool(
        cleaned
        and _contains_organisation_marker(str(cleaned))
        and not _is_organisation_unit(str(cleaned))
        and not AFFILIATION_ROLE_PREFIX_RE.search(str(cleaned))
    )


def _contains_organisation_marker(value: str) -> bool:
    lowered = value.casefold()
    return any(re.search(rf"\b{re.escape(marker)}\b", lowered) for marker in AFFILIATION_ORGANISATION_MARKERS)


def _contains_unit_marker(value: str) -> bool:
    lowered = value.casefold()
    return any(marker in lowered for marker in AFFILIATION_UNIT_MARKERS)


def _is_organisation_unit(value: str) -> bool:
    lowered = value.casefold().strip()
    return _contains_unit_marker(lowered) or lowered.startswith(
        ("department ", "school ", "centre ", "center ", "faculty ", "division ")
    )


def normalize_whitespace(value: object) -> object:
    if value is None or isinstance(value, list):
        return value
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    if text.lower() in MISSING_TOKENS:
        return None
    return text or None


def parse_date_to_iso(value: object) -> str | None:
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
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)

    range_match = re.match(r"^([A-Za-z]+)\s+(\d{1,2})\s*-\s*\d{1,2},?\s+(\d{4})$", text)
    if range_match:
        text = f"{range_match.group(1)} {range_match.group(2)}, {range_match.group(3)}"
    range_match = re.match(r"^(\d{1,2})\s*-\s*\d{1,2}\s+([A-Za-z]+)\s+(\d{4})$", text)
    if range_match:
        text = f"{range_match.group(1)} {range_match.group(2)} {range_match.group(3)}"

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError as exc:
        raise ValueError(f"could not parse date {value!r}") from exc


def canonical_country(value: object) -> str | None:
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


def parse_optional_int(value: object) -> int | None:
    cleaned = normalize_whitespace(value)
    if cleaned is None:
        return None
    try:
        return int(str(cleaned).strip())
    except ValueError as exc:
        raise ValueError(f"could not parse integer {value!r}") from exc


def actor_natural_key(name: str, website: object = None) -> str:
    name_key = normalize_key_text(name)
    website_key = _website_key(website)
    if website_key:
        return f"{name_key}|{website_key}"
    return name_key


def person_natural_key(
    name: str,
    affiliation: object = None,
) -> str:
    name_key = normalize_key_text(name)
    affiliation_key = normalize_key_text(str(affiliation or ""))
    return "|".join(part for part in [name_key, affiliation_key] if part)


def _website_key(value: object) -> str:
    cleaned = normalize_whitespace(value)
    if cleaned is None:
        return ""
    parsed = urlparse(str(cleaned) if "://" in str(cleaned) else f"https://{cleaned}")
    host = (parsed.netloc or parsed.path).lower().removeprefix("www.")
    path = parsed.path.strip("/") if parsed.netloc else ""
    return "/".join(part for part in [host, path] if part)


def normalize_key_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return text
