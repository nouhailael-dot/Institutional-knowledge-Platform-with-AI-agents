"""Query generation for open-web discovery."""

from __future__ import annotations

import ast
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text

from agents.common.config import load_sources_config

logger = logging.getLogger(__name__)
STREET_MARKERS = re.compile(
    r"\b(street|st\.?|avenue|ave\.?|road|rd\.?|boulevard|blvd\.?|"
    r"floor|suite|ste\.?|room|building|bldg\.?)\b",
    re.IGNORECASE,
)
POSTCODE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
STATE_ABBREVIATIONS = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DC",
    "DE",
    "FL",
    "GA",
    "HI",
    "IA",
    "ID",
    "IL",
    "IN",
    "KS",
    "KY",
    "LA",
    "MA",
    "MD",
    "ME",
    "MI",
    "MN",
    "MO",
    "MS",
    "MT",
    "NC",
    "ND",
    "NE",
    "NH",
    "NJ",
    "NM",
    "NV",
    "NY",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VA",
    "VT",
    "WA",
    "WI",
    "WV",
    "WY",
}
NYC_METRO_PARTS = {"manhattan", "brooklyn", "queens", "bronx", "staten island", "nyc"}
TERM_STOPWORDS = {
    "about",
    "agenda",
    "annual",
    "conference",
    "congress",
    "event",
    "events",
    "forum",
    "global",
    "high",
    "international",
    "level",
    "meeting",
    "meetings",
    "new",
    "programme",
    "session",
    "summit",
    "the",
    "week",
    "world",
    "york",
}


@dataclass(frozen=True)
class QueryBundle:
    entity_type: str
    queries: list[str]
    deterministic_queries: list[str]
    llm_queries: list[str]
    reference_count: int


class QueryGenerator:
    def __init__(self, llm_client, config: dict[str, object], *, today: date | None = None):
        self.llm_client = llm_client
        self.config = config
        self.today = today or datetime.now(UTC).date()

    def generate(self, entity_type: str, *, session=None, project_root: Path | None = None) -> QueryBundle:
        if entity_type == "person" and not bool(self.config.get("people_enabled", False)):
            raise RuntimeError(
                "open-web people discovery is disabled pending TARGETING_POLICY.md section 6 approval"
            )
        if entity_type not in {"event", "actor", "person"}:
            raise ValueError("entity_type must be one of event, actor, person")

        root = project_root or Path(__file__).resolve().parents[3]
        sectors = load_seeded_sectors(root)
        excluded = {
            str(code).upper()
            for code in (self.config.get("query_excluded_sectors") or [])
        }
        if excluded:
            logger.info(
                "excluding sectors from open-web query generation: %s", sorted(excluded)
            )
            sectors = [s for s in sectors if str(s["code"]).upper() not in excluded]
        if entity_type == "event":
            references = load_event_reference_examples(session)
            geographies = load_event_geographies(session)
            sector_terms = load_sector_event_terms(session)
            search_sectors = _sectors_with_representative_terms(sectors, sector_terms)
            deterministic = _event_seed_queries(
                search_sectors,
                geographies,
                self.today,
                self.config,
            )
            prompt_context = {
                "entity_type": "event",
                "sectors": search_sectors,
                "geographies": geographies,
                "forward_window": _forward_window(self.today, self.config),
                "reference_events": references,
                "configured_reference_sources": _configured_event_sources(root),
                "query_quality_rule": (
                    "Use sector names and representative title terms. Do not use sector codes. "
                    "Use city, state, region, or metro geography only; never use a venue street "
                    "address, postcode, room, suite, or floor."
                ),
            }
        elif entity_type == "actor":
            references = load_actor_reference_set(session)
            if not references:
                raise RuntimeError(
                    "actor query generation requires a non-empty non-aggregate database reference set"
                )
            deterministic = _actor_seed_queries(references)
            prompt_context = {
                "entity_type": "actor",
                "sectors": sectors,
                "reference_actors": references,
                "quality_rule": (
                    "Return queries for real operating organisations with evidence of "
                    "activity, not grouping pages, consortium listings, or categories."
                ),
            }
        else:
            references = []
            deterministic = []
            prompt_context = {"entity_type": "person", "sectors": sectors}

        llm_queries = self._llm_queries(prompt_context)
        queries = _distinct_queries([*deterministic, *llm_queries])
        if not queries:
            raise RuntimeError(f"query generation returned zero queries for {entity_type}")
        return QueryBundle(
            entity_type=entity_type,
            queries=queries,
            deterministic_queries=deterministic,
            llm_queries=llm_queries,
            reference_count=len(references),
        )

    def _llm_queries(self, context: dict[str, object]) -> list[str]:
        payload = self.llm_client.extract_with_tool(
            system=(
                "Generate concise web search queries for the GHUS ecosystem. "
                "Return only tool-schema fields. Do not include secrets."
            ),
            user=(
                "Create distinct high-signal search queries from this JSON context. "
                "Avoid configured source domains and social networks.\n\n"
                f"{json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)}"
            ),
            tool_name="generate_open_web_queries",
            tool_description="Return search queries for open-web candidate discovery.",
            input_schema={
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 25,
                    }
                },
                "required": ["queries"],
                "additionalProperties": False,
            },
            max_tokens=int(self.config.get("query_max_tokens", 1024)),
        )
        queries = payload.get("queries", [])
        if not isinstance(queries, list):
            raise TypeError("query generator returned non-list queries")
        clean = _distinct_queries(str(item) for item in queries)
        if not clean:
            logger.warning("LLM query generation returned zero queries")
        return clean


def load_seeded_sectors(project_root: Path) -> list[dict[str, str]]:
    seed_path = project_root / "scripts" / "seed_sectors.py"
    tree = ast.parse(seed_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "SECTORS" in names:
                return [
                    {"code": str(code).upper(), "name": str(name)}
                    for code, name in ast.literal_eval(node.value)
                ]
    raise RuntimeError(f"could not find SECTORS in {seed_path}")


def load_event_geographies(session, *, limit: int = 20) -> list[str]:
    if session is None:
        return []
    rows = (
        session.execute(
            text(
                "SELECT DISTINCT location FROM event "
                "WHERE location IS NOT NULL AND btrim(location) <> '' "
                "ORDER BY location LIMIT :limit"
            ),
            {"limit": limit},
        )
        .mappings()
        .all()
    )
    geographies: list[str] = []
    for row in rows:
        geography = normalize_event_geography(row.get("location"))
        if geography:
            geographies.append(geography)
    return _distinct_queries(geographies)


def load_event_reference_examples(session, *, limit: int = 20) -> list[dict[str, object]]:
    if session is None:
        return []
    rows = (
        session.execute(
            text(
                "SELECT event_id::text AS event_id, name, event_type, description, "
                "location, next_date, thematic_focus "
                "FROM event ORDER BY next_date DESC NULLS LAST, name LIMIT :limit"
            ),
            {"limit": limit},
        )
        .mappings()
        .all()
    )
    return [_compact_event_reference(dict(row)) for row in rows]


def load_sector_event_terms(session, *, limit_per_sector: int = 25) -> dict[str, list[str]]:
    if session is None:
        return {}
    rows = (
        session.execute(
            text(
                "SELECT code, name FROM ("
                "SELECT s.code, e.name, "
                "row_number() OVER (PARTITION BY s.code ORDER BY e.next_date DESC NULLS LAST, e.name) AS rn "
                "FROM event e "
                "JOIN event_sector es ON es.event_id = e.event_id "
                "JOIN sector s ON s.sector_id = es.sector_id "
                "WHERE e.name IS NOT NULL AND btrim(e.name) <> ''"
                ") ranked WHERE rn <= :limit"
            ),
            {"limit": limit_per_sector},
        )
        .mappings()
        .all()
    )
    titles_by_code: dict[str, list[str]] = {}
    for row in rows:
        code = str(row.get("code") or "").strip().upper()
        title = str(row.get("name") or "").strip()
        if code and title:
            titles_by_code.setdefault(code, []).append(title)
    return {
        code: _representative_terms_from_titles(titles)
        for code, titles in titles_by_code.items()
    }


def load_actor_reference_set(session, *, limit: int = 20) -> list[dict[str, object]]:
    if session is None:
        return []
    rows = (
        session.execute(
            text(
                "SELECT actor_id::text AS actor_id, name, actor_type, "
                "merged_into_actor_id::text AS merged_into_actor_id, description, "
                "website, country, primary_technical_focus, current_activities "
                "FROM actor "
                "WHERE merged_into_actor_id IS NULL "
                "AND (actor_type IS NULL OR lower(actor_type) <> 'aggregate') "
                "ORDER BY updated_at DESC NULLS LAST, name LIMIT :limit"
            ),
            {"limit": limit},
        )
        .mappings()
        .all()
    )
    return [
        _compact_row(dict(row))
        for row in rows
        if _is_reference_actor(dict(row))
    ][:limit]


def _is_reference_actor(row: dict[str, object]) -> bool:
    actor_type = str(row.get("actor_type") or "").strip().lower()
    if actor_type == "aggregate":
        return False
    if row.get("merged_into_actor_id"):
        return False
    return bool(str(row.get("name") or "").strip())


def _event_seed_queries(
    sectors: list[dict[str, str]],
    geographies: list[str],
    today: date,
    config: dict[str, object],
) -> list[str]:
    start, end = _forward_window(today, config)
    year_terms = _year_terms(start, end)
    geo_terms = [geo for geo in geographies[:5] if geo]
    if not geo_terms:
        geo_terms = ["New York", "United States", "global"]

    queries: list[str] = []
    for sector in sectors:
        phrase = _sector_search_phrase(sector)
        queries.append(f"{phrase} summit conference event {year_terms}")
        queries.append(f"{phrase} innovation forum {geo_terms[0]} {year_terms}")
    queries.append(f'"UM6P" global hubs ecosystem event {year_terms}')
    return _distinct_queries(queries)


def _actor_seed_queries(references: list[dict[str, object]]) -> list[str]:
    queries: list[str] = []
    for row in references[:10]:
        actor_type = str(row.get("actor_type") or "organisation").strip()
        country = str(row.get("country") or "").strip()
        focus = str(row.get("primary_technical_focus") or row.get("description") or "").strip()
        focus_terms = " ".join(focus.split()[:8]) if focus else "research innovation"
        queries.append(f'"{actor_type}" "{focus_terms}" organisation {country}'.strip())
    return _distinct_queries(queries)


def _configured_event_sources(project_root: Path) -> list[dict[str, object]]:
    config = load_sources_config(project_root)
    refs: list[dict[str, object]] = []
    for source_name, source in dict(config.get("sources", {})).items():
        if not isinstance(source, dict):
            continue
        if "event" not in [str(value) for value in source.get("entity_types", []) or []]:
            continue
        urls = []
        for key in ("listing_url", "meeting_url"):
            if source.get(key):
                urls.append(str(source[key]))
        urls.extend(str(url) for url in source.get("seed_urls", []) or [])
        refs.append({"source_name": str(source_name), "urls": sorted(set(urls))})
    return refs


def _forward_window(today: date, config: dict[str, object]) -> tuple[date, date]:
    days = int(config.get("forward_window_days", 365))
    if days <= 0:
        raise RuntimeError("open_web_discovery.forward_window_days must be positive")
    return today, today + timedelta(days=days)


def _year_terms(start: date, end: date) -> str:
    years = sorted({start.year, end.year})
    return " ".join(str(year) for year in years)


def _compact_row(row: dict[str, Any]) -> dict[str, object]:
    compact: dict[str, object] = {}
    for key, value in row.items():
        if value is None:
            continue
        text_value = str(value).strip()
        if text_value:
            compact[key] = text_value[:500]
    return compact


def _compact_event_reference(row: dict[str, Any]) -> dict[str, object]:
    geography = normalize_event_geography(row.get("location"))
    compact = _compact_row(row)
    if geography:
        compact["location"] = geography
    else:
        compact.pop("location", None)
    return compact


def normalize_event_geography(value: object) -> str:
    text_value = " ".join(str(value or "").replace("\n", " ").split()).strip(" ,")
    if not text_value:
        return ""
    parts = [part.strip(" ,") for part in text_value.split(",") if part.strip(" ,")]
    candidates = parts if parts else [text_value]
    for part in candidates:
        normalized = _normalize_geography_part(part)
        if normalized:
            return normalized
    if STREET_MARKERS.search(text_value) or POSTCODE.search(text_value):
        return ""
    return _normalize_geography_part(text_value)


def _normalize_geography_part(value: str) -> str:
    text_value = " ".join(value.split()).strip(" ,")
    if not text_value:
        return ""
    if text_value.upper() in STATE_ABBREVIATIONS:
        return ""
    if POSTCODE.fullmatch(text_value):
        return ""
    if STREET_MARKERS.search(text_value) or any(char.isdigit() for char in text_value):
        return ""
    if text_value.lower() in NYC_METRO_PARTS:
        return "New York"
    if len(text_value) < 3:
        return ""
    return text_value


def _sectors_with_representative_terms(
    sectors: list[dict[str, str]],
    sector_terms: dict[str, list[str]],
) -> list[dict[str, str]]:
    enriched: list[dict[str, str]] = []
    for sector in sectors:
        code = str(sector["code"]).upper()
        enriched.append(
            {
                "code": code,
                "name": str(sector["name"]),
                "representative_terms": " ".join(sector_terms.get(code, [])),
            }
        )
    return enriched


def _sector_search_phrase(sector: dict[str, str]) -> str:
    name = str(sector["name"]).strip()
    terms = str(sector.get("representative_terms") or "").strip()
    if terms:
        return f'"{name}" {terms}'
    return f'"{name}"'


def _representative_terms_from_titles(titles: list[str], *, max_terms: int = 4) -> list[str]:
    counts: Counter[str] = Counter()
    for title in titles:
        for token in re.findall(r"[A-Za-z][A-Za-z-]{2,}", title.lower()):
            token = token.strip("-")
            if token in TERM_STOPWORDS or token.isdigit():
                continue
            if token.startswith("unga"):
                continue
            counts[token] += 1
    return [token for token, _count in counts.most_common(max_terms)]


def _distinct_queries(queries) -> list[str]:
    seen: set[str] = set()
    distinct: list[str] = []
    for raw in queries:
        query = " ".join(str(raw or "").split())
        if _query_has_street_address_or_postcode(query):
            logger.warning("dropping open-web query with street address or postcode: %s", query)
            continue
        key = query.lower()
        if not query or key in seen:
            continue
        seen.add(key)
        distinct.append(query)
    return distinct


def _query_has_street_address_or_postcode(query: str) -> bool:
    return bool(POSTCODE.search(query) or (STREET_MARKERS.search(query) and re.search(r"\d", query)))