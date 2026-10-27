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
    "and",
    "annual",
    "america",
    "american",
    "calendar",
    "conference",
    "congress",
    "dates",
    "event",
    "events",
    "exhibition",
    "exhibitions",
    "expo",
    "exposition",
    "forum",
    "global",
    "high",
    "international",
    "innovation",
    "level",
    "meeting",
    "meetings",
    "new",
    "program",
    "programme",
    "schedule",
    "session",
    "show",
    "shows",
    "summit",
    "the",
    "trade",
    "university",
    "usa",
    "week",
    "world",
    "york",
}
REPRESENTATIVE_TERM_WHITELIST = {"arpa-e"}
REPRESENTATIVE_TOKEN = re.compile(r"[A-Za-z][A-Za-z-]{1,}")
ACTOR_TYPE_ROTATION_GROUPS = (
    (
        "company / industrial operator",
        ("company", "corporate R&D lab", "industrial partner", "project developer"),
    ),
    (
        "research organization",
        (
            "federal research system",
            "national research center",
            "national research lab",
            "research organization",
            "university",
            "university lab",
        ),
    ),
    (
        "public agency",
        ("federal agency", "government agency", "state agency"),
    ),
    (
        "ecosystem convenor",
        ("consortium", "industry association", "nonprofit"),
    ),
    (
        "startup ecosystem",
        ("accelerator", "startup", "venture capital"),
    ),
)
HUB_QUERY_EXCLUDED_ACTOR_TYPES = {
    "intergovernmental organization",
    "multilateral development bank",
    "un agency",
    "un committee",
    "un programme",
    "un secretariat",
}
PERSON_RESEARCH_TOPICS = {
    "AGRI": ("crop science", "soil science", "agricultural biotechnology"),
    "WATER": ("membrane desalination", "water reuse", "water resources"),
    "AI": ("applied artificial intelligence", "machine learning systems", "responsible AI"),
    "ENERGY": ("green hydrogen", "battery storage", "renewable energy systems"),
    "MINING": ("critical minerals", "mineral processing", "mining technology"),
    "CHEM": ("specialty chemicals", "catalysis", "materials chemistry"),
    "HEALTH": ("biomedical research", "public health innovation", "medical technology"),
    "SUSTAIN": ("climate resilience", "circular economy", "decarbonization"),
}
PERSON_EXPERTISE_ROLES = (
    "university researcher",
    "research institute scientist",
    "national laboratory researcher",
    "principal investigator",
    "research programme director",
)
HUB_THEME_SECTOR_CODES = {
    "agriculture": "AGRI",
    "water": "WATER",
    "AI": "AI",
    "energy": "ENERGY",
    "critical minerals": "MINING",
    "specialty chemicals": "CHEM",
    "health": "HEALTH",
    "sustainability": "SUSTAIN",
}


# Query templates that point at specific GHUS use cases. The hub grid finds
# research labs; it never finds an executive education office, which is why
# those use cases fired 0-2 times across 200 candidates in run 5268566e.
ACTOR_USE_CASE_QUERY_TEMPLATES: dict[str, tuple[str, ...]] = {
    "executive_education": ("executive education program {theme} {geo}",),
    "learning_expeditions": (
        "site visit program {theme} {geo}",
        "industry tour {theme} {geo}",
    ),
    "mentorship": (
        "mentorship program {theme} {geo}",
        "fellowship program {theme} {geo}",
    ),
    "student_and_faculty_mobility": (
        "visiting researcher program {theme} {geo}",
        "exchange program {theme} {geo}",
    ),
    "open_innovation": (
        "open innovation challenge {theme} {geo}",
        "innovation hub {theme} {geo}",
    ),
    "corporate_engagement": ("industry partnership program {theme} {geo}",),
}

@dataclass(frozen=True)
class QueryBundle:
    entity_type: str
    queries: list[str]
    deterministic_queries: list[str]
    llm_queries: list[str]
    reference_count: int
    metadata: dict[str, object] | None = None


class QueryGenerator:
    def __init__(self, llm_client, config: dict[str, object], *, today: date | None = None):
        self.llm_client = llm_client
        self.config = config
        self.today = today or datetime.now(UTC).date()

    def generate(
        self,
        entity_type: str,
        *,
        session=None,
        project_root: Path | None = None,
        request=None,
    ) -> QueryBundle:
        """Queries for one run.

        ``request`` is a ``DiscoveryRequest``. For actors it replaces the hub
        grid entirely: a requested run searches only what was asked for.
        """
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
        if request is not None and entity_type in {"event", "person"}:
            # An on-request event or people run searches only what was asked
            # for; the automatic runs below are untouched.
            from agents.discovery.search.discovery_request import (
                request_event_queries,
                request_person_queries,
            )

            limit = int(self.config.get("request_query_limit") or 24)
            if entity_type == "event":
                queries, metadata = request_event_queries(
                    request, sectors, today=self.today, max_queries=limit)
            else:
                queries, metadata = self._person_request_queries(
                    request, sectors, session=session, limit=limit)
            queries = _distinct_queries(queries)
            if not queries:
                raise RuntimeError("query generation returned zero queries for the request")
            return QueryBundle(
                entity_type=entity_type,
                queries=queries,
                deterministic_queries=list(queries),
                llm_queries=[],
                reference_count=0,
                metadata=metadata,
            )
        if entity_type == "event":
            from agents.discovery.search.us_scope import us_places

            # United States only (agents/discovery/search/us_scope.py): the
            # map's own events abroad never steer a search.
            references = [r for r in load_event_reference_examples(session)
                          if us_places([str(r.get("location") or "")])]
            geographies = us_places(load_event_geographies(session))
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
                    "address, postcode, room, suite, or floor. Every query is for events "
                    "taking place in the United States (or online): never name another "
                    "country, a foreign city or a world region."
                ),
            }
        elif entity_type == "actor" and request is not None:
            from agents.discovery.search.discovery_request import request_actor_queries

            queries, metadata = request_actor_queries(
                request,
                sectors,
                max_queries=int(
                    self.config.get("request_query_limit")
                    or self.config.get("actor_query_limit")
                    or 24
                ),
                rotation_seed=_actor_type_rotation_seed(self.today, self.config),
            )
            # The page-scoring stage classifies against the database's own
            # actor types; the readable phrases above are for searching only.
            if session is not None:
                metadata["actor_type_enum"] = list(load_actor_types(session))
            deterministic = _interleave_queries(
                queries, list(metadata.get("use_case_queries") or [])
            )
            queries = _distinct_queries(deterministic)
            if not queries:
                raise RuntimeError("query generation returned zero queries for the request")
            return QueryBundle(
                entity_type=entity_type,
                queries=queries,
                deterministic_queries=deterministic,
                llm_queries=[],
                reference_count=0,
                metadata=metadata,
            )
        elif entity_type == "actor":
            actor_types = load_actor_types(session)
            hubs = load_actor_query_hubs(session)
            max_queries = int(self.config.get("actor_query_limit") or self.config.get("max_searches", 40))
            types_per_hub = int(self.config.get("actor_type_queries_per_hub", 3))
            deterministic, metadata = _actor_grid_queries(
                actor_types,
                hubs,
                max_queries=max_queries,
                rotation_seed=_actor_type_rotation_seed(self.today, self.config),
                types_per_hub=types_per_hub,
            )
            deterministic = _interleave_queries(
                deterministic,
                list(metadata.get("use_case_queries") or []),
            )
            references = []
            llm_queries = []
            queries = _distinct_queries(deterministic)
            if not queries:
                raise RuntimeError(f"query generation returned zero queries for {entity_type}")
            return QueryBundle(
                entity_type=entity_type,
                queries=queries,
                deterministic_queries=deterministic,
                llm_queries=llm_queries,
                reference_count=0,
                metadata=metadata,
            )
        else:
            references = []
            hubs = load_actor_query_hubs(session)
            max_queries = int(
                self.config.get("person_query_limit")
                or self.config.get("max_searches", 40)
            )
            deterministic, metadata = _person_expertise_queries(
                sectors,
                hubs,
                max_queries=max_queries,
                rotation_seed=_person_query_rotation_seed(self.today, self.config),
            )
            queries = _distinct_queries(deterministic)
            if not queries:
                raise RuntimeError("query generation returned zero queries for person")
            return QueryBundle(
                entity_type=entity_type,
                queries=queries,
                deterministic_queries=deterministic,
                llm_queries=[],
                reference_count=0,
                metadata=metadata,
            )

        llm_queries = self._llm_queries(prompt_context)
        if entity_type == "event":
            from agents.discovery.search.us_scope import us_queries

            # A search naming a foreign place is not run, whoever wrote it.
            deterministic, dropped_seed = us_queries(deterministic)
            llm_queries, dropped_llm = us_queries(llm_queries)
            if dropped_seed or dropped_llm:
                logger.info("not searched (outside the United States): %s",
                            [*dropped_seed, *dropped_llm])
        queries = _distinct_queries([*deterministic, *llm_queries])
        if not queries:
            raise RuntimeError(f"query generation returned zero queries for {entity_type}")
        return QueryBundle(
            entity_type=entity_type,
            queries=queries,
            deterministic_queries=deterministic,
            llm_queries=llm_queries,
            reference_count=len(references),
            metadata=None,
        )

    def _person_request_queries(self, request, sectors, *, session, limit: int):
        """Profile searches on the official sites of the institutions that employ them.

        agents/discovery/search/people_targets.py. Without a map to read (no
        database) or with no institution held in the area, the open search
        built from the request is used instead.
        """
        from agents.discovery.search.discovery_request import request_person_queries
        from agents.discovery.search.people_targets import (
            academic_role,
            institution_domains,
            profile_queries,
            themes_for,
        )

        themes = themes_for(request, sectors)
        names = {str(s.get("code") or "").upper(): str(s.get("name") or "") for s in sectors}
        targets = institution_domains(
            session, states=request.states, sector_codes=request.sector_codes,
            institution=request.institution,
            keywords=[*themes, *(names.get(c, c) for c in request.sector_codes)],
            academic_only=academic_role(request.role),
            limit=int(self.config.get("person_target_domains", 8)),
        ) if session is not None else []
        if not targets:
            return request_person_queries(request, sectors, max_queries=limit)
        queries, where = profile_queries(
            themes, [t["domain"] for t in targets], role=request.role,
            max_queries=min(limit, int(self.config.get("person_request_searches", 6))))
        return queries, {
            "discovery_request": request.describe(),
            "query_domains": where,
            "target_institutions": [{"domain": t["domain"],
                                     "institutions": t["institutions"][:4]} for t in targets],
            "sector_codes_covered": list(request.sector_codes),
        }

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


def load_active_sectors(session, project_root: Path) -> list[dict[str, str]]:
    """The sectors in the database, so one a reviewer adds in Review is used by
    the next discovery run. Falls back to the seed file without a database."""
    if session is not None:
        try:
            rows = session.execute(text(
                "SELECT code, name FROM sector WHERE active ORDER BY code"
            )).mappings().all()
        except Exception:  # noqa: BLE001 - a missing table falls back to the seed
            rows = []
        if rows:
            return [{"code": str(r["code"]).upper(), "name": str(r["name"])} for r in rows]
    return load_seeded_sectors(project_root)


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
                "SELECT code, sector_name, event_name FROM ("
                "SELECT s.code, s.name AS sector_name, e.name AS event_name, "
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
    sector_names_by_code: dict[str, str] = {}
    for row in rows:
        code = str(row.get("code") or "").strip().upper()
        sector_name = str(row.get("sector_name") or "").strip()
        title = str(row.get("event_name") or row.get("name") or "").strip()
        if code and sector_name:
            sector_names_by_code[code] = sector_name
        if code and title:
            titles_by_code.setdefault(code, []).append(title)
    return {
        code: _representative_terms_from_titles(
            titles,
            sector_name=sector_names_by_code.get(code, ""),
        )
        for code, titles in titles_by_code.items()
    }


def load_actor_reference_set(session, *, limit: int = 20) -> list[dict[str, object]]:
    if session is None:
        return []
    rows = (
        session.execute(
            text(
                "SELECT actor_id::text AS actor_id, name, "
                "COALESCE(to_jsonb(actor)->>'actor_category',to_jsonb(actor)->>'actor_type') "
                "AS actor_type, "
                "merged_into_actor_id::text AS merged_into_actor_id, description, "
                "website, country, "
                # Narrative fields move to imported baseline facts at the V2 cutover.
                "COALESCE(to_jsonb(actor)->>'primary_technical_focus',(SELECT f.fact_value#>>'{}' "
                "FROM actor_fact f WHERE f.actor_id=actor.actor_id "
                "AND f.fact_type='legacy_baseline' AND f.fact_key='primary_technical_focus' "
                "LIMIT 1)) AS primary_technical_focus, "
                "COALESCE(to_jsonb(actor)->>'current_activities',(SELECT f.fact_value#>>'{}' "
                "FROM actor_fact f WHERE f.actor_id=actor.actor_id "
                "AND f.fact_type='legacy_baseline' AND f.fact_key='current_activities' "
                "LIMIT 1)) AS current_activities "
                "FROM actor "
                "WHERE merged_into_actor_id IS NULL "
                "AND lower(COALESCE(to_jsonb(actor)->>'actor_category',to_jsonb(actor)->>'actor_type','')) <> 'aggregate' "
                "AND COALESCE(to_jsonb(actor)->>'status','') <> 'rejected' "
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


def load_actor_types(session) -> list[str]:
    if session is None:
        return []
    rows = (
        session.execute(
            text(
                "SELECT category_code AS actor_category "
                "FROM actor_category_definition WHERE active ORDER BY sort_order"
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        # Transitional fallback for databases that do not yet have V2 reference
        # data. This is removed with the physical actor_type cutover.
        rows = (
            session.execute(
                text(
                    "SELECT DISTINCT actor_type FROM ("
                    "SELECT to_jsonb(actor)->>'actor_type' AS actor_type FROM actor) legacy "
                    "WHERE actor_type IS NOT NULL "
                    "AND btrim(actor_type) <> '' "
                    "AND lower(actor_type) NOT IN ('aggregate', 'other') "
                    "ORDER BY actor_type"
                )
            )
            .mappings()
            .all()
        )
    return [
        actor_category
        for actor_category in _distinct_queries(
            str(row.get("actor_category") or row.get("actor_type") or "").strip()
            for row in rows
        )
        if actor_category.lower() not in {"aggregate", "other"}
    ]


def load_actor_query_hubs(session) -> list[dict[str, object]]:
    if session is None:
        return []
    rows = (
        session.execute(
            text(
                "SELECT h.hub_id::text AS hub_id, h.name, h.primary_city, h.state, h.country, h.region, "
                "count(a.actor_id) AS actor_count "
                "FROM hub h "
                "LEFT JOIN hub_actor ha ON ha.hub_id = h.hub_id "
                "LEFT JOIN actor a ON a.actor_id = ha.actor_id "
                "AND a.merged_into_actor_id IS NULL "
                "AND lower(COALESCE(to_jsonb(a)->>'actor_category',to_jsonb(a)->>'actor_type','')) <> 'aggregate' "
                "AND COALESCE(to_jsonb(a)->>'status','') <> 'rejected' "
                "WHERE h.name <> 'Mining Hubs' "
                "GROUP BY h.hub_id, h.name, h.primary_city, h.state, h.country, h.region "
                "ORDER BY count(a.actor_id) ASC, h.name"
            )
        )
        .mappings()
        .all()
    )
    hubs: list[dict[str, object]] = []
    for row in rows:
        hub = dict(row)
        name = str(hub.get("name") or "").strip()
        if not name or name == "Mining Hubs":
            continue
        theme = _hub_theme(name)
        geographies = _hub_geographies(name, row=hub)
        if not theme or not geographies:
            continue
        actor_count = hub.get("actor_count")
        try:
            count = int(actor_count or 0)
        except (TypeError, ValueError):
            count = 0
        hubs.append(
            {
                "hub_id": str(hub.get("hub_id") or ""),
                "name": name,
                "actor_count": count,
                "theme": theme,
                "geographies": geographies,
            }
        )
    return hubs


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
        geo_terms = ["United States", "New York"]

    queries: list[str] = []
    for sector in sectors:
        phrase = _sector_search_phrase(sector)
        queries.append(f"{phrase} summit conference event {year_terms}")
        queries.append(f"{phrase} innovation forum {geo_terms[0]} {year_terms}")
    queries.append(f'"UM6P" United States event {year_terms}')
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


def _person_expertise_queries(
    sectors: list[dict[str, str]],
    hubs: list[dict[str, object]],
    *,
    max_queries: int,
    rotation_seed: int = 0,
) -> tuple[list[str], dict[str, object]]:
    if max_queries <= 0:
        raise RuntimeError("open_web_discovery person query limit must be positive")

    sector_by_code = {
        str(sector.get("code") or "").strip().upper(): sector
        for sector in sectors
        if str(sector.get("code") or "").strip()
    }
    plans: list[dict[str, object]] = []
    for hub in sorted(
        hubs,
        key=lambda item: (int(item.get("actor_count") or 0), str(item.get("name") or "")),
    ):
        theme = str(hub.get("theme") or "").strip()
        code = HUB_THEME_SECTOR_CODES.get(theme)
        geographies = [
            str(value).strip()
            for value in hub.get("geographies", []) or []
            if str(value).strip()
        ]
        if not code or code not in sector_by_code or not geographies:
            continue
        plans.append(
            {
                "hub_name": str(hub.get("name") or "").strip(),
                "actor_count": int(hub.get("actor_count") or 0),
                "sector_code": code,
                "sector_name": str(sector_by_code[code]["name"]),
                "topics": list(PERSON_RESEARCH_TOPICS.get(code, (theme,))),
                "geographies": geographies,
            }
        )

    for code, sector in sector_by_code.items():
        plans.append(
            {
                "hub_name": "",
                "actor_count": None,
                "sector_code": code,
                "sector_name": str(sector["name"]),
                "topics": list(
                    PERSON_RESEARCH_TOPICS.get(code, (str(sector["name"]),))
                ),
                "geographies": ["United States"],
            }
        )

    if not plans:
        raise RuntimeError("person query generation requires a searchable seeded sector")

    queries: list[str] = []
    query_plan: list[dict[str, object]] = []
    seen: set[str] = set()
    pass_index = 0
    max_passes = max(len(PERSON_EXPERTISE_ROLES), 1) * 3
    while len(queries) < max_queries and pass_index < max_passes:
        added = False
        for plan_index, plan in enumerate(plans):
            if len(queries) >= max_queries:
                break
            topics = [str(value) for value in plan["topics"]]
            geographies = [str(value) for value in plan["geographies"]]
            topic = topics[(rotation_seed + pass_index + plan_index) % len(topics)]
            role = PERSON_EXPERTISE_ROLES[
                (rotation_seed + pass_index) % len(PERSON_EXPERTISE_ROLES)
            ]
            geography = geographies[
                ((rotation_seed + pass_index) // len(topics)) % len(geographies)
            ]
            query = f'"{topic}" {role} {geography}'
            key = query.casefold()
            if key in seen:
                continue
            seen.add(key)
            queries.append(query)
            query_plan.append(
                {
                    "query": query,
                    "hub_name": plan["hub_name"],
                    "actor_count": plan["actor_count"],
                    "sector_code": plan["sector_code"],
                    "sector_name": plan["sector_name"],
                    "topic": topic,
                    "geography": geography,
                    "pass_index": pass_index,
                }
            )
            added = True
        if not added:
            break
        pass_index += 1

    return queries, {
        "query_mode": "expertise",
        "rotation_seed": rotation_seed,
        "query_plan": query_plan,
        "distinct_hubs_covered": len(
            {str(item["hub_name"]) for item in query_plan if item["hub_name"]}
        ),
        "sector_codes_covered": sorted(
            {str(item["sector_code"]) for item in query_plan}
        ),
    }


def _person_query_rotation_seed(today: date, config: dict[str, object]) -> int:
    configured = config.get("person_query_rotation_seed")
    if configured is not None:
        return int(configured)
    iso_year, iso_week, _weekday = today.isocalendar()
    return (iso_year * 53) + iso_week


def _actor_use_case_queries(
    plans: list[dict[str, object]],
    *,
    max_queries: int,
    rotation_seed: int,
    seen_queries: set[str],
) -> tuple[list[str], list[dict[str, object]]]:
    """Queries aimed at specific use cases, cycling hubs and use cases together."""
    if max_queries <= 0 or not plans:
        return [], []

    use_cases = sorted(ACTOR_USE_CASE_QUERY_TEMPLATES)
    queries: list[str] = []
    plan_items: list[dict[str, object]] = []
    attempt = 0
    max_attempts = len(plans) * len(use_cases) * 4

    while len(queries) < max_queries and attempt < max_attempts:
        plan = plans[(rotation_seed + attempt) % len(plans)]
        use_case = use_cases[(rotation_seed + attempt) % len(use_cases)]
        attempt += 1

        geographies = list(plan.get("geographies") or [])
        theme = str(plan.get("theme") or "").strip() or _hub_theme(
            str(plan.get("hub_name") or plan.get("name") or ""))
        if not geographies or not theme:
            continue

        templates = ACTOR_USE_CASE_QUERY_TEMPLATES[use_case]
        template = templates[attempt % len(templates)]
        geo = str(geographies[attempt % len(geographies)]).strip()
        if not geo:
            continue

        query = " ".join(template.format(theme=theme, geo=geo).split())
        if query.lower() in seen_queries:
            continue

        seen_queries.add(query.lower())
        queries.append(query)
        plan_items.append(
            {
                "query": query,
                "hub_id": plan.get("hub_id"),
                "hub_name": plan.get("name"),
                "actor_count": plan.get("actor_count"),
                "theme": theme,
                "geography": geo,
                "use_case": use_case,
                "query_type": "use_case",
            }
        )

    return queries, plan_items


def _interleave_queries(primary: list[str], secondary: list[str]) -> list[str]:
    """Distribute secondary queries so a cap cannot silently remove the whole class."""
    if not secondary:
        return list(primary)
    if not primary:
        return list(secondary)
    interval = max(1, (len(primary) + len(secondary) - 1) // len(secondary))
    combined: list[str] = []
    secondary_index = 0
    for index, query in enumerate(primary, start=1):
        combined.append(query)
        if index % interval == 0 and secondary_index < len(secondary):
            combined.append(secondary[secondary_index])
            secondary_index += 1
    combined.extend(secondary[secondary_index:])
    return combined


def _actor_grid_queries(
    actor_types: list[str],
    hubs: list[dict[str, object]],
    *,
    max_queries: int,
    rotation_seed: int = 0,
    types_per_hub: int = 3,
    use_case_queries_count: int = 12,
) -> tuple[list[str], dict[str, object]]:
    if not actor_types:
        raise RuntimeError("actor query generation requires at least one searchable actor_type")
    if not hubs:
        raise RuntimeError("actor query generation requires at least one non-category hub")
    if max_queries <= 0:
        raise RuntimeError("open_web_discovery actor query limit must be positive")
    if types_per_hub <= 0:
        raise RuntimeError("open_web_discovery.actor_type_queries_per_hub must be positive")

    readable_types = [_actor_type_query_phrase(actor_type) for actor_type in actor_types]
    readable_types = [
        phrase
        for phrase in _distinct_queries(readable_types)
        if phrase not in {"aggregate", "other"}
        and phrase.casefold() not in HUB_QUERY_EXCLUDED_ACTOR_TYPES
    ]
    if not readable_types:
        raise RuntimeError("actor query generation found no searchable hub actor types")

    sorted_hubs = sorted(
        hubs,
        key=lambda item: (int(item.get("actor_count") or 0), str(item.get("name") or "")),
    )
    type_buckets = _actor_type_rotation_buckets(readable_types)
    plans = [
        _actor_hub_query_plan(
            hub,
            type_buckets,
            hub_index=index,
            rotation_seed=rotation_seed,
            types_per_hub=types_per_hub,
        )
        for index, hub in enumerate(sorted_hubs)
    ]
    plans = [plan for plan in plans if plan["geographies"] and plan["actor_types"]]

    queries: list[str] = []
    query_plan: list[dict[str, object]] = []
    seen_queries: set[str] = set()
    pass_index = 0
    while len(queries) < max_queries:
        added_this_pass = False
        for plan in plans:
            if len(queries) >= max_queries:
                break
            query_item = _query_for_plan_pass(plan, pass_index, seen_queries)
            if query_item is None:
                continue
            queries.append(str(query_item["query"]))
            query_plan.append(query_item)
            seen_queries.add(str(query_item["query"]).lower())
            added_this_pass = True
        if not added_this_pass:
            break
        pass_index += 1

    use_case_queries, use_case_plan = _actor_use_case_queries(
        plans,
        max_queries=use_case_queries_count,
        rotation_seed=rotation_seed,
        seen_queries=seen_queries,
    )

    selected_hubs = _selected_hub_metadata(plans, query_plan)
    grid_size = sum(
        len(plan["actor_types"]) * len(plan["geographies"])
        for plan in plans
    )
    full_grid_size = sum(
        len(readable_types) * len(plan["geographies"])
        for plan in plans
    )
    return queries, {
        "actor_types": readable_types,
        "actor_type_enum": list(actor_types),
        "actor_type_rotation_groups": _actor_type_rotation_group_metadata(type_buckets),
        "actor_type_rotation_seed": rotation_seed,
        "actor_types_per_hub": min(types_per_hub, len(type_buckets)),
        "full_query_grid_size": full_grid_size,
        "query_grid_size": grid_size,
        "selected_hubs": selected_hubs,
        "distinct_hubs_covered": len(selected_hubs),
        "query_plan": query_plan,
        "use_case_queries": use_case_queries,
        "use_case_query_plan": use_case_plan,
        "use_case_query_count": len(use_case_queries),
    }


def _actor_type_rotation_seed(today: date, config: dict[str, object]) -> int:
    configured = config.get("actor_query_rotation_seed")
    if configured is not None:
        return int(configured)
    iso_year, iso_week, _weekday = today.isocalendar()
    return (iso_year * 53) + iso_week


def _actor_type_rotation_buckets(readable_types: list[str]) -> list[dict[str, object]]:
    by_key = {actor_type.lower(): actor_type for actor_type in readable_types}
    used: set[str] = set()
    buckets: list[dict[str, object]] = []
    for label, members in ACTOR_TYPE_ROTATION_GROUPS:
        present = [
            by_key[member.lower()]
            for member in members
            if member.lower() in by_key
        ]
        if not present:
            continue
        used.update(member.lower() for member in present)
        buckets.append({"label": label, "members": present})
    for actor_type in readable_types:
        if actor_type.lower() in used:
            continue
        buckets.append({"label": actor_type, "members": [actor_type]})
    return buckets


def _actor_hub_query_plan(
    hub: dict[str, object],
    type_buckets: list[dict[str, object]],
    *,
    hub_index: int,
    rotation_seed: int,
    types_per_hub: int,
) -> dict[str, object]:
    bucket_count = min(types_per_hub, len(type_buckets))
    bucket_start = (rotation_seed + hub_index) % len(type_buckets)
    actor_types: list[str] = []
    bucket_labels: list[str] = []
    for offset in range(bucket_count):
        bucket = type_buckets[(bucket_start + offset) % len(type_buckets)]
        members = [str(member) for member in bucket["members"]]
        if not members:
            continue
        member_index = (rotation_seed + hub_index + offset) % len(members)
        actor_types.append(members[member_index])
        bucket_labels.append(str(bucket["label"]))
    return {
        "hub_id": str(hub.get("hub_id") or hub.get("name") or ""),
        "name": str(hub.get("name") or ""),
        "actor_count": int(hub.get("actor_count") or 0),
        "theme": str(hub.get("theme") or "").strip(),
        "geographies": [
            str(geo).strip()
            for geo in hub.get("geographies", []) or []
            if str(geo).strip()
        ],
        "actor_types": actor_types,
        "actor_type_groups": bucket_labels,
    }


def _query_for_plan_pass(
    plan: dict[str, object],
    pass_index: int,
    seen_queries: set[str],
) -> dict[str, object] | None:
    actor_types = [str(value) for value in plan["actor_types"]]
    geographies = [str(value) for value in plan["geographies"]]
    theme = str(plan["theme"])
    combinations = len(actor_types) * len(geographies)
    for attempt in range(combinations):
        actor_type = actor_types[(pass_index + attempt) % len(actor_types)]
        geography = geographies[((pass_index + attempt) // len(actor_types)) % len(geographies)]
        query = f"{actor_type} {theme} {geography}"
        if query.lower() in seen_queries:
            continue
        return {
            "query": query,
            "hub_id": str(plan["hub_id"]),
            "hub_name": str(plan["name"]),
            "actor_count": int(plan["actor_count"]),
            "theme": theme,
            "geography": geography,
            "actor_type": actor_type,
            "pass_index": pass_index,
        }
    return None


def _selected_hub_metadata(
    plans: list[dict[str, object]],
    query_plan: list[dict[str, object]],
) -> list[dict[str, object]]:
    planned_by_hub = {str(plan["hub_id"]): plan for plan in plans}
    selected: dict[str, dict[str, object]] = {}
    for item in query_plan:
        hub_id = str(item["hub_id"])
        plan = planned_by_hub[hub_id]
        entry = selected.setdefault(
            hub_id,
            {
                "name": str(plan["name"]),
                "actor_count": int(plan["actor_count"]),
                "theme": str(plan["theme"]),
                "geographies": [],
                "actor_types": list(plan["actor_types"]),
                "actor_type_groups": list(plan["actor_type_groups"]),
                "query_count": 0,
            },
        )
        entry["query_count"] = int(entry["query_count"]) + 1
        geography = str(item["geography"])
        if geography not in entry["geographies"]:
            entry["geographies"].append(geography)
    return list(selected.values())


def _actor_type_rotation_group_metadata(
    type_buckets: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "label": str(bucket["label"]),
            "members": [str(member) for member in bucket["members"]],
        }
        for bucket in type_buckets
    ]


def _actor_type_query_phrase(actor_type: str) -> str:
    parts = [part for part in re.split(r"[_\s]+", actor_type.strip().lower()) if part]
    readable: list[str] = []
    for part in parts:
        if part == "rd":
            readable.append("R&D")
        elif part == "vc":
            readable.append("venture capital")
        else:
            readable.append(part)
    return " ".join(readable).strip()


def _hub_theme(name: str) -> str:
    text = name.lower()
    if re.search(r"\b(ai|artificial intelligence)\b", text):
        return "AI"
    if re.search(r"\b(critical minerals?|mining|mine|mineral)\b", text):
        return "critical minerals"
    if re.search(r"\b(specialty chemicals?|chemicals?|chemistry|catalysis)\b", text):
        return "specialty chemicals"
    if re.search(r"\b(water|aquifer|desalination|irrigation)\b", text):
        return "water"
    if re.search(
        r"\b(agriculture|agricultural|agtech|ag|ag-biotech|food|plant science|soil|crop|crops)\b",
        text,
    ):
        return "agriculture"
    if re.search(r"\b(health|biomedical|biohealth|medicine|medical|clinical|nic)\b", text):
        return "health"
    if re.search(r"\b(energy|hydrogen|battery|batteries|solar|grid)\b", text):
        return "energy"
    if re.search(r"\b(sustainability|sustainable|climate|cleantech|clean tech)\b", text):
        return "sustainability"
    return ""


def _hub_geographies(
    name: str,
    *,
    row: dict[str, object] | None = None,
) -> list[str]:
    parenthetical = re.search(r"\(([^)]*)\)", name)
    if parenthetical:
        terms = _clean_geography_terms(
            parenthetical.group(1),
            qualifier=_state_qualifier(_leading_place_words(name)),
        )
        if terms:
            return terms
        column_terms = _hub_geographies_from_columns(row or {})
        if column_terms:
            return column_terms
    leading_terms = _clean_geography_terms(_leading_place_words(name))
    if leading_terms:
        return leading_terms[:1]
    return _hub_geographies_from_columns(row or {})


def _hub_geographies_from_columns(row: dict[str, object]) -> list[str]:
    city = _clean_geography_term(str(row.get("primary_city") or ""))
    state = _clean_geography_term(str(row.get("state") or ""))
    if city:
        return [" ".join(part for part in (city, state) if part)]
    for key in ("region", "state", "country"):
        value = _clean_geography_term(str(row.get(key) or ""))
        if value and value.casefold() not in {"usa", "united states"}:
            return [value]
    return []


def _leading_place_words(name: str) -> str:
    outside_parenthetical = re.sub(r"\([^)]*\)", "", name)
    theme_match = re.search(
        r"\b(water|ai|artificial intelligence|critical minerals?|mining|mine|mineral|"
        r"advanced materials?|"
        r"specialty chemicals?|chemicals?|chemistry|catalysis|agriculture|agricultural|"
        r"agtech|food|soil|crop|crops|health|biomedical|biohealth|medicine|medical|"
        r"energy|hydrogen|battery|batteries|solar|grid|sustainability|sustainable|"
        r"climate|cleantech|clean tech|hub)\b",
        outside_parenthetical,
        flags=re.IGNORECASE,
    )
    candidate = outside_parenthetical[: theme_match.start()] if theme_match else outside_parenthetical
    candidate = re.sub(
        r"\b(clean|academic)\b.*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\bhub(s)?\b", "", candidate, flags=re.IGNORECASE)
    return " ".join(candidate.replace("-", " ").split()).strip(" ,")


def _clean_geography_terms(value: str, *, qualifier: str = "") -> list[str]:
    raw_terms = re.split(r"\s*(?:,|;|/|\||\band\b| - |-|–|—)\s*", value)
    terms: list[str] = []
    clean_qualifier = " ".join(qualifier.split()).strip()
    for raw in raw_terms:
        term = _clean_geography_term(str(raw or ""))
        if not term:
            continue
        if clean_qualifier and clean_qualifier.lower() not in term.lower():
            term = f"{term} {clean_qualifier}"
        terms.append(term)
    return _distinct_queries(terms)


def _clean_geography_term(value: str) -> str:
    term = " ".join(value.split()).strip(" ,")
    term = re.sub(r"\([^)]*\)", " ", term)
    term = re.sub(r"[()\[\]]", " ", term)
    term = " ".join(term.split()).strip(" ,-")
    if not term:
        return ""
    lowered = term.casefold()
    if lowered in {
        "hub",
        "hubs",
        "usa",
        "united states",
        "berkeley",
        "stanford",
        "ucla",
        "lbnl",
        "ucsf",
        "nyu",
        "cornell",
        "cornell tech",
        "mit",
        "harvard",
        "mount sinai",
        "usc",
        "caltech",
        "big tech ai",
        "columbia",
    }:
        return ""
    if re.search(
        r"\b(university|college|institute|school|academy|laboratory|lab|ecosystem)\b",
        lowered,
    ):
        return ""
    if re.match(r"^(uc|u\.c\.)\s+", lowered):
        return ""
    if lowered.startswith("state of "):
        term = term[9:].strip()
    if term.casefold() in {"nyc", "greater nyc"}:
        return "New York City"
    return term


def _state_qualifier(value: str) -> str:
    normalized = " ".join(value.replace("–", "-").replace("—", "-").split()).strip()
    if normalized.casefold() in {
        "arizona",
        "california",
        "colorado",
        "massachusetts",
        "missouri",
        "nevada",
        "pennsylvania",
        "texas",
        "utah",
    }:
        return normalized
    return ""


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
        name = str(sector["name"])
        clean_terms = _sanitize_representative_terms(
            sector_terms.get(code, []),
            sector_name=name,
        )
        enriched.append(
            {
                "code": code,
                "name": name,
                "representative_terms": " ".join(clean_terms),
            }
        )
    return enriched


def _sector_search_phrase(sector: dict[str, str]) -> str:
    name = str(sector["name"]).strip()
    terms = _sanitize_representative_terms(
        str(sector.get("representative_terms") or "").split(),
        sector_name=name,
    )
    if terms:
        return f'"{name}" {" ".join(terms)}'
    return f'"{name}"'


def _representative_terms_from_titles(
    titles: list[str],
    *,
    sector_name: str = "",
    max_terms: int = 2,
) -> list[str]:
    counts: Counter[str] = Counter()
    sector_tokens = _sector_tokens(sector_name)
    for title in titles:
        for token in REPRESENTATIVE_TOKEN.findall(title.lower()):
            token = token.strip("-")
            if not _is_clean_representative_token(token, sector_tokens):
                continue
            counts[token] += 1
    return [token for token, _count in counts.most_common(max_terms)]


def _sanitize_representative_terms(
    terms: object,
    *,
    sector_name: str,
    max_terms: int = 2,
) -> list[str]:
    if isinstance(terms, str):
        raw_terms = terms.split()
    else:
        raw_terms = list(terms or [])
    sector_tokens = _sector_tokens(sector_name)
    clean: list[str] = []
    seen: set[str] = set()
    for raw in raw_terms:
        token = str(raw or "").strip().strip(".,;:()[]{}\"'").lower()
        if not token or token in seen:
            continue
        if not _is_clean_representative_token(token, sector_tokens):
            continue
        clean.append(token)
        seen.add(token)
        if len(clean) >= max_terms:
            break
    return clean


def _is_clean_representative_token(token: str, sector_tokens: set[str]) -> bool:
    if not token:
        return False
    if token in TERM_STOPWORDS:
        return False
    if token.startswith("unga"):
        return False
    letters = re.sub(r"[^a-z]", "", token)
    if not letters:
        return False
    if len(letters) < 5 and token not in REPRESENTATIVE_TERM_WHITELIST:
        return False
    return not _is_sector_name_repeat(token, sector_tokens)


def _sector_tokens(sector_name: str) -> set[str]:
    return {
        token.strip("-").lower()
        for token in REPRESENTATIVE_TOKEN.findall(sector_name)
        if token.strip("-")
    }


def _is_sector_name_repeat(token: str, sector_tokens: set[str]) -> bool:
    token_compact = token.replace("-", "")
    token_stem = token_compact.rstrip("s")
    for sector_token in sector_tokens:
        sector_compact = sector_token.replace("-", "")
        sector_stem = sector_compact.rstrip("s")
        if token_stem == sector_stem:
            return True
        if (
            len(token_stem) >= 5
            and len(sector_stem) >= 5
            and (token_stem.startswith(sector_stem) or sector_stem.startswith(token_stem))
        ):
            return True
    return False


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
