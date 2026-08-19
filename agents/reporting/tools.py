"""Curated reporting tools exposed to the Claude loop."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import text

from agents.reporting.artifacts import ArtifactBuilder
from agents.reporting.rag import RagSearchAdapter

LIMIT_CAP = 100
DEFAULT_LIMIT = 25


@dataclass(frozen=True)
class DraftEmail:
    draft_id: str
    to: list[str]
    subject: str
    body: str
    created_at: str
    status: str = "draft"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any]


class ReportingTools:
    def __init__(
        self,
        session,
        *,
        rag_adapter: Optional[RagSearchAdapter] = None,
        artifact_builder: Optional[ArtifactBuilder] = None,
        output_dir: Optional[Path] = None,
    ):
        root = Path(__file__).resolve().parents[2]
        self.session = session
        self.rag_adapter = rag_adapter or RagSearchAdapter()
        self.artifact_builder = artifact_builder or ArtifactBuilder(
            template_dir=root / "agents" / "reporting" / "templates",
            output_dir=output_dir or root / "agents" / "runs" / "reporting",
        )
        self.called_tools: list[tuple[str, dict[str, Any]]] = []

    def registry(self) -> dict[str, ToolSpec]:
        return {
            "list_sectors": ToolSpec(
                "list_sectors",
                "List available GHUS sectors.",
                {"type": "object", "properties": {}, "additionalProperties": False},
                self.list_sectors,
            ),
            "query_actors": ToolSpec(
                "query_actors",
                "Query actors by sector, country, actor_type, with a capped limit.",
                _schema(
                    sector={"type": "string"},
                    country={"type": "string"},
                    actor_type={"type": "string"},
                    limit={"type": "integer", "minimum": 1},
                ),
                self.query_actors,
            ),
            "query_events": ToolSpec(
                "query_events",
                "Query events by sector, date range, host, with a capped limit.",
                _schema(
                    sector={"type": "string"},
                    date_from={"type": "string"},
                    date_to={"type": "string"},
                    host={"type": "string"},
                    limit={"type": "integer", "minimum": 1},
                ),
                self.query_events,
            ),
            "query_hubs": ToolSpec(
                "query_hubs",
                "Query hubs by sector and minimum actor TRL, with a capped limit.",
                _schema(
                    sector={"type": "string"},
                    trl={"type": "integer", "minimum": 0},
                    limit={"type": "integer", "minimum": 1},
                ),
                self.query_hubs,
            ),
            "get_entity": ToolSpec(
                "get_entity",
                "Get one canonical entity row plus its source provenance row.",
                _schema(
                    entity_type={"type": "string", "enum": ["actor", "event", "hub", "person"]},
                    entity_id={"type": "string"},
                ),
                self.get_entity,
                ),
            "count": ToolSpec(
                "count",
                "Count canonical entities by an allow-listed group_by field and filters.",
                _schema(
                    entity_type={"type": "string", "enum": ["actor", "event", "hub", "person"]},
                    group_by={"type": "string"},
                    filters={"type": "object"},
                ),
                self.count,
            ),
            "rag_search": ToolSpec(
                "rag_search",
                "Delegate semantic/keyword retrieval to the sibling um6p-rag retriever.",
                _schema(question={"type": "string"}, top_k={"type": "integer", "minimum": 1}),
                self.rag_search,
            ),
            "build_pptx": ToolSpec(
                "build_pptx",
                "Build a PPTX artifact from a reporting template; spec must cite entity ids.",
                _schema(spec={"type": "object"}),
                self.build_pptx,
            ),
            "build_docx": ToolSpec(
                "build_docx",
                "Build a DOCX artifact from a reporting template; spec must cite entity ids.",
                _schema(spec={"type": "object"}),
                self.build_docx,
            ),
            "build_xlsx": ToolSpec(
                "build_xlsx",
                "Build an XLSX artifact from a reporting template; spec must cite entity ids.",
                _schema(spec={"type": "object"}),
                self.build_xlsx,
            ),
            "build_pdf": ToolSpec(
                "build_pdf",
                "Build a PDF artifact from a reporting template; spec must cite entity ids.",
                _schema(spec={"type": "object"}),
                self.build_pdf,
            ),
            "draft_email": ToolSpec(
                "draft_email",
                "Return an email draft object. This tool never sends email.",
                _schema(
                    to={"type": "array", "items": {"type": "string"}},
                    subject={"type": "string"},
                    body={"type": "string"},
                ),
                self.draft_email,
            ),
        }

    def call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        registry = self.registry()
        if tool_name not in registry:
            raise ValueError(f"unknown reporting tool: {tool_name}")
        self.called_tools.append((tool_name, dict(arguments)))
        return registry[tool_name].handler(**arguments)

    def list_sectors(self) -> list[dict[str, Any]]:
        rows = self.session.execute(
            text(
                "SELECT sector_id::text AS sector_id, code, name, description, "
                "parent_sector_id::text AS parent_sector_id "
                "FROM sector ORDER BY code"
            )
        ).mappings().all()
        return [dict(row) for row in rows]

    def query_actors(
        self,
        sector: Optional[str] = None,
        country: Optional[str] = None,
        actor_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        clauses = ["a.merged_into_actor_id IS NULL"]
        params: dict[str, Any] = {"limit": _cap_limit(limit)}
        if sector:
            clauses.append("(LOWER(s.code) = LOWER(:sector) OR LOWER(s.name) = LOWER(:sector))")
            params["sector"] = sector
        if country:
            clauses.append("LOWER(a.country) = LOWER(:country)")
            params["country"] = country
        if actor_type:
            clauses.append("LOWER(a.actor_type) = LOWER(:actor_type)")
            params["actor_type"] = actor_type
        rows = self.session.execute(
            text(
                "SELECT a.actor_id::text AS entity_id, a.name, a.actor_type, a.country, "
                "a.website, a.description, a.primary_technical_focus, a.estimated_trl, "
                "array_remove(array_agg(DISTINCT s.code), NULL) AS sectors "
                "FROM actor a "
                "LEFT JOIN actor_sector ac ON ac.actor_id = a.actor_id "
                "LEFT JOIN sector s ON s.sector_id = ac.sector_id "
                f"WHERE {' AND '.join(clauses)} "
                "GROUP BY a.actor_id, a.name, a.actor_type, a.country, a.website, "
                "a.description, a.primary_technical_focus, a.estimated_trl "
                "ORDER BY a.name LIMIT :limit"
            ),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def query_events(
        self,
        sector: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        host: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        clauses = ["1 = 1"]
        params: dict[str, Any] = {"limit": _cap_limit(limit)}
        if sector:
            clauses.append("(LOWER(s.code) = LOWER(:sector) OR LOWER(s.name) = LOWER(:sector))")
            params["sector"] = sector
        if date_from:
            clauses.append("e.next_date >= CAST(:date_from AS date)")
            params["date_from"] = date_from
        if date_to:
            clauses.append("e.next_date <= CAST(:date_to AS date)")
            params["date_to"] = date_to
        if host:
            clauses.append("(host.actor_id::text = :host OR host.name ILIKE :host_like)")
            params["host"] = host
            params["host_like"] = f"%{host}%"
        rows = self.session.execute(
            text(
                "SELECT e.event_id::text AS entity_id, e.name, e.event_type, e.next_date, "
                "e.location, e.website, e.thematic_focus, host.name AS host_name, "
                "array_remove(array_agg(DISTINCT s.code), NULL) AS sectors "
                "FROM event e "
                "LEFT JOIN actor host ON host.actor_id = e.host_actor_id "
                "LEFT JOIN event_sector es ON es.event_id = e.event_id "
                "LEFT JOIN sector s ON s.sector_id = es.sector_id "
                f"WHERE {' AND '.join(clauses)} "
                "GROUP BY e.event_id, e.name, e.event_type, e.next_date, e.location, "
                "e.website, e.thematic_focus, host.name "
                "ORDER BY e.next_date NULLS LAST, e.name LIMIT :limit"
            ),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def query_hubs(
        self,
        sector: Optional[str] = None,
        trl: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        clauses = ["1 = 1"]
        params: dict[str, Any] = {"limit": _cap_limit(limit)}
        if sector:
            clauses.append("(LOWER(s.code) = LOWER(:sector) OR LOWER(s.name) = LOWER(:sector))")
            params["sector"] = sector
        if trl is not None:
            clauses.append("a.estimated_trl >= :trl")
            params["trl"] = int(trl)
        rows = self.session.execute(
            text(
                "SELECT h.hub_id::text AS entity_id, h.name, h.primary_city, h.state, h.country, "
                "h.description, h.official_websites, "
                "array_remove(array_agg(DISTINCT s.code), NULL) AS sectors, "
                "MAX(hss.strength_score) AS max_sector_strength, "
                "MAX(a.estimated_trl) AS max_actor_trl "
                "FROM hub h "
                "LEFT JOIN hub_sector_strength hss ON hss.hub_id = h.hub_id "
                "LEFT JOIN sector s ON s.sector_id = hss.sector_id "
                "LEFT JOIN hub_actor ha ON ha.hub_id = h.hub_id "
                "LEFT JOIN actor a ON a.actor_id = ha.actor_id "
                f"WHERE {' AND '.join(clauses)} "
                "GROUP BY h.hub_id, h.name, h.primary_city, h.state, h.country, "
                "h.description, h.official_websites "
                "ORDER BY h.name LIMIT :limit"
            ),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def get_entity(self, entity_type: str, entity_id: str) -> dict[str, Any]:
        config = _entity_config(entity_type)
        row = self.session.execute(
            text(
                f"SELECT {config['columns']} "
                f"FROM {config['table']} "
                f"WHERE {config['id_column']} = CAST(:entity_id AS uuid)"
            ),
            {"entity_id": entity_id},
        ).mappings().first()
        if row is None:
            return {"entity_type": entity_type, "entity_id": entity_id, "row": None, "provenance": []}
        row_dict = dict(row)
        source_id = row_dict.get("source_id")
        provenance = []
        if source_id:
            provenance = [
                dict(item)
                for item in self.session.execute(
                    text(
                        "SELECT source_id::text AS source_id, source_type, url, retrieved_at, "
                        "description, trust_tier, created_at "
                        "FROM source WHERE source_id = CAST(:source_id AS uuid)"
                    ),
                    {"source_id": str(source_id)},
                ).mappings().all()
            ]
        return {"entity_type": entity_type, "entity_id": entity_id, "row": row_dict, "provenance": provenance}

    def count(self, entity_type: str, group_by: str, filters: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        config = _count_config(entity_type, group_by)
        clauses, params = _count_filters(entity_type, filters or {})
        rows = self.session.execute(
            text(
                f"SELECT {config['group_expr']} AS group_value, COUNT(DISTINCT {config['id_expr']}) AS count "
                f"FROM {config['from_clause']} "
                f"WHERE {' AND '.join(clauses)} "
                f"GROUP BY {config['group_expr']} "
                "ORDER BY count DESC, group_value NULLS LAST LIMIT :limit"
            ),
            {**params, "limit": LIMIT_CAP},
        ).mappings().all()
        return [dict(row) for row in rows]

    def rag_search(self, question: str, top_k: int = 10) -> list[dict[str, Any]]:
        return self.rag_adapter.search(question, top_k=_cap_limit(top_k, default=10))

    def build_pptx(self, spec: dict[str, Any]) -> dict[str, Any]:
        return asdict(self.artifact_builder.build_pptx(spec))

    def build_docx(self, spec: dict[str, Any]) -> dict[str, Any]:
        return asdict(self.artifact_builder.build_docx(spec))

    def build_xlsx(self, spec: dict[str, Any]) -> dict[str, Any]:
        return asdict(self.artifact_builder.build_xlsx(spec))

    def build_pdf(self, spec: dict[str, Any]) -> dict[str, Any]:
        return asdict(self.artifact_builder.build_pdf(spec))

    def draft_email(self, to: list[str], subject: str, body: str) -> dict[str, Any]:
        draft = DraftEmail(
            draft_id=str(uuid.uuid4()),
            to=[str(item) for item in to],
            subject=str(subject),
            body=str(body),
            created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
        return asdict(draft)


def tool_schemas(registry: dict[str, ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.input_schema,
        }
        for spec in registry.values()
    ]


def _schema(**properties) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "additionalProperties": False}


def _cap_limit(limit: Optional[int], *, default: int = DEFAULT_LIMIT) -> int:
    if limit is None:
        return default
    return min(max(1, int(limit)), LIMIT_CAP)


def _entity_config(entity_type: str) -> dict[str, str]:
    configs = {
        "actor": {
            "table": "actor",
            "id_column": "actor_id",
            "columns": (
                "actor_id::text AS entity_id, name, actor_type, description, website, "
                "location_city, state, country, primary_technical_focus, technical_approach, "
                "current_activities, technology_ip_notes, key_constraints, funding_summary, "
                "estimated_trl, primary_lifecycle_role, source_id::text AS source_id, "
                "verification_status, confidence, created_at, updated_at"
            ),
        },
        "event": {
            "table": "event",
            "id_column": "event_id",
            "columns": (
                "event_id::text AS entity_id, name, event_type, description, location, website, "
                "thematic_focus, expected_attendance, access_type, recurring_pattern, next_date, "
                "sponsoring_orgs, host_actor_id::text AS host_actor_id, source_id::text AS source_id, created_at"
            ),
        },
        "hub": {
            "table": "hub",
            "id_column": "hub_id",
            "columns": (
                "hub_id::text AS entity_id, name, primary_city, state, country, region, description, "
                "official_websites, strategic_value_summary, core_topic_strengths, funding_summary, "
                "source_id::text AS source_id, verification_status, confidence, created_at, updated_at"
            ),
        },
        "person": {
            "table": "person",
            "id_column": "person_id",
            "columns": (
                "person_id::text AS entity_id, full_name, title, email, orcid, bio, tel_num, "
                "country_code, linkedin_url, source_id::text AS source_id, verification_status, "
                "confidence, created_at, updated_at"
            ),
        },
    }
    if entity_type not in configs:
        raise ValueError(f"unsupported entity_type: {entity_type}")
    return configs[entity_type]


def _count_config(entity_type: str, group_by: str) -> dict[str, str]:
    configs = {
        "actor": {
            "from_clause": (
                "actor a LEFT JOIN actor_sector ac ON ac.actor_id = a.actor_id "
                "LEFT JOIN sector s ON s.sector_id = ac.sector_id"
            ),
            "id_expr": "a.actor_id",
            "groups": {
                "country": "a.country",
                "actor_type": "a.actor_type",
                "sector": "s.code",
                "verification_status": "a.verification_status",
            },
        },
        "event": {
            "from_clause": (
                "event e LEFT JOIN actor host ON host.actor_id = e.host_actor_id "
                "LEFT JOIN event_sector es ON es.event_id = e.event_id "
                "LEFT JOIN sector s ON s.sector_id = es.sector_id"
            ),
            "id_expr": "e.event_id",
            "groups": {
                "event_type": "e.event_type",
                "sector": "s.code",
                "host": "host.name",
                "year": "EXTRACT(YEAR FROM e.next_date)::int",
            },
        },
        "hub": {
            "from_clause": (
                "hub h LEFT JOIN hub_sector_strength hss ON hss.hub_id = h.hub_id "
                "LEFT JOIN sector s ON s.sector_id = hss.sector_id "
                "LEFT JOIN hub_actor ha ON ha.hub_id = h.hub_id "
                "LEFT JOIN actor a ON a.actor_id = ha.actor_id"
            ),
            "id_expr": "h.hub_id",
            "groups": {
                "country": "h.country",
                "state": "h.state",
                "sector": "s.code",
            },
        },
        "person": {
            "from_clause": "person p",
            "id_expr": "p.person_id",
            "groups": {
                "country_code": "p.country_code",
                "title": "p.title",
            },
        },
    }
    if entity_type not in configs:
        raise ValueError(f"unsupported entity_type: {entity_type}")
    groups = configs[entity_type]["groups"]
    if group_by not in groups:
        valid = ", ".join(sorted(groups))
        raise ValueError(f"unsupported group_by for {entity_type}: {group_by}; valid: {valid}")
    return {
        "from_clause": configs[entity_type]["from_clause"],
        "id_expr": configs[entity_type]["id_expr"],
        "group_expr": groups[group_by],
    }


def _count_filters(entity_type: str, filters: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    clauses = ["1 = 1"]
    params: dict[str, Any] = {}
    allowed = {
        "actor": {"country": "a.country", "actor_type": "a.actor_type", "sector": "s.code"},
        "event": {"sector": "s.code", "host": "host.name"},
        "hub": {"country": "h.country", "state": "h.state", "sector": "s.code"},
        "person": {"country_code": "p.country_code"},
    }
    for key, value in filters.items():
        if value is None or value == "":
            continue
        if key == "date_from" and entity_type == "event":
            clauses.append("e.next_date >= CAST(:date_from AS date)")
            params["date_from"] = value
        elif key == "date_to" and entity_type == "event":
            clauses.append("e.next_date <= CAST(:date_to AS date)")
            params["date_to"] = value
        elif key == "trl" and entity_type == "hub":
            clauses.append("a.estimated_trl >= :trl")
            params["trl"] = int(value)
        elif key in allowed.get(entity_type, {}):
            column = allowed[entity_type][key]
            clauses.append(f"LOWER({column}) = LOWER(:{key})")
            params[key] = str(value)
        else:
            raise ValueError(f"unsupported filter for {entity_type}: {key}")
    return clauses, params
