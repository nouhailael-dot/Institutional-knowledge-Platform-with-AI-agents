"""Climate Week deterministic event-card extractor."""

from __future__ import annotations

import html.parser
import logging
from datetime import UTC, datetime
from urllib.parse import urljoin

from agents.discovery.extractors.event import (
    EVENT_FIELDS,
    EVENT_TOOL_SCHEMA,
    VOID_TAGS,
    displayed_event_total,
    hubdb_listing_rows,
)
from agents.discovery.sources.base import FetchedDoc

logger = logging.getLogger(__name__)

PROMPT_VERSION = "climate_week_event_v1"
_CAPTURE_CLASSES = {
    "event-card__title": "title",
    "event-card__address": "location",
    "event-card__meta-item--format": "format",
    "event-card__meta-item--type": "access",
}


class ClimateWeekExtractor:
    entity_type = "event"
    prompt_version = PROMPT_VERSION
    json_schema = EVENT_TOOL_SCHEMA

    def __init__(
        self,
        *,
        theme_to_sector_codes: dict[str, object],
        base_url: str,
        min_row_count: int = 0,
    ) -> None:
        self.theme_to_sector_codes = _normalise_theme_mapping(theme_to_sector_codes)
        self.base_url = base_url
        self.min_row_count = min_row_count
        self.attention_reasons: list[str] = []

    def extract(self, doc: FetchedDoc) -> list[dict[str, object]]:
        rows, found_listing = hubdb_listing_rows(doc.content)
        self._check_listing_completeness(doc, len(rows), found_listing=found_listing)
        if not found_listing:
            logger.warning(
                "hubdb-listing container not found for %s; page_size_bytes=%d",
                doc.url,
                len(doc.content.encode("utf-8")),
            )
            return []
        if not rows:
            logger.warning("hubdb-listing container had zero event-card rows for %s", doc.url)
            return []

        extracted_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        return [self._record_from_row(row, doc, extracted_at) for row in rows]

    def _record_from_row(
        self,
        row: str,
        doc: FetchedDoc,
        extracted_at: str,
    ) -> dict[str, object]:
        card = _ClimateWeekCardParser()
        card.feed(row)
        themes = card.themes
        record = {field: None for field in EVENT_FIELDS}
        record.update(
            {
                "title": card.text("title"),
                "start_date": card.start_date,
                "location": card.text("location"),
                "website": urljoin(self.base_url or doc.url, card.href or "") or None,
                "thematic_focus": ", ".join(themes) or None,
                "event_type": card.text("format"),
                "access_type": card.text("access"),
                "sector_codes": _sector_codes(themes, self.theme_to_sector_codes),
            }
        )
        record["source_url"] = doc.url
        record["extracted_at"] = extracted_at
        record["prompt_version"] = self.prompt_version
        return record

    def _check_listing_completeness(
        self,
        doc: FetchedDoc,
        row_count: int,
        *,
        found_listing: bool,
    ) -> None:
        reasons: list[str] = []
        if not found_listing:
            reasons.append(f"{doc.url} parsed 0 event rows because hubdb-listing was not found")
        if self.min_row_count and row_count < self.min_row_count:
            reasons.append(
                f"{doc.url} parsed {row_count} event rows, "
                f"below configured floor {self.min_row_count}"
            )
        displayed_total = displayed_event_total(doc.content)
        if displayed_total is not None and displayed_total > row_count:
            reasons.append(
                f"{doc.url} displays total={displayed_total} but parser found {row_count} rows"
            )
        for reason in reasons:
            logger.warning(reason)
            if reason not in self.attention_reasons:
                self.attention_reasons.append(reason)


class _ClimateWeekCardParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._captures: list[set[str]] = []
        self._text: dict[str, list[str]] = {
            "title": [],
            "location": [],
            "format": [],
            "access": [],
        }
        self.themes: list[str] = []
        self.href: str | None = None
        self.start_date: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        attributes = {name.lower(): value for name, value in attrs}
        class_values = (attributes.get("class") or "").split()
        classes = set(class_values)
        if tag_lower == "article":
            self.themes = [
                value.removeprefix("theme-")
                for value in class_values
                if value.startswith("theme-")
            ]
        if tag_lower == "a" and "event-card__link" in classes and not self.href:
            self.href = attributes.get("href")
        if tag_lower == "time" and not self.start_date:
            self.start_date = attributes.get("datetime")

        active = set(self._captures[-1]) if self._captures else set()
        for class_name, field in _CAPTURE_CLASSES.items():
            if class_name in classes:
                active.add(field)
        if tag_lower not in VOID_TAGS:
            self._captures.append(active)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() not in VOID_TAGS and self._captures:
            self._captures.pop()

    def handle_data(self, data: str) -> None:
        if not self._captures:
            return
        for field in self._captures[-1]:
            self._text[field].append(data)

    def text(self, field: str) -> str | None:
        value = " ".join(" ".join(self._text[field]).split())
        return value or None


def _normalise_theme_mapping(
    mapping: dict[str, object],
) -> dict[str, tuple[str, ...]]:
    normalised: dict[str, tuple[str, ...]] = {}
    for raw_theme, raw_codes in mapping.items():
        codes = [raw_codes] if isinstance(raw_codes, str) else list(raw_codes or [])
        normalised[str(raw_theme).strip().lower()] = tuple(
            str(code).strip().upper() for code in codes if str(code).strip()
        )
    return normalised


def _sector_codes(
    themes: list[str],
    mapping: dict[str, tuple[str, ...]],
) -> list[str]:
    codes: list[str] = []
    for theme in themes:
        for code in mapping.get(theme, ()):
            if code not in codes:
                codes.append(code)
    return codes
