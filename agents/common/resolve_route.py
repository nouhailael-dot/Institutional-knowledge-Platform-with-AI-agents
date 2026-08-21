"""Routing bridge between staged agent records and canonical entities.

The existing frozen combiner is actor-specific. Event routing therefore uses a
separate deterministic natural-key match: normalized title plus start date. The
score is 1.0 for exact natural-key matches and 0.0 otherwise so the route shape
stays uniform without applying an actor model to events.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import text


@dataclass(frozen=True)
class Thresholds:
    high: float
    low: float


@dataclass(frozen=True)
class RouteDecision:
    zone: str
    score: float
    target_entity_id: Optional[str] = None
    candidate_ids: list[str] = field(default_factory=list)


def load_actor_thresholds(project_root: Optional[Path] = None) -> Thresholds:
    """Load deployed ER thresholds from the existing production config."""
    root = project_root or Path(__file__).resolve().parents[2]
    cfg = json.loads((root / "config" / "er_production.json").read_text(encoding="utf-8"))
    return Thresholds(high=float(cfg["high_threshold"]), low=float(cfg["low_threshold"]))


def load_actor_resolver_class():
    """Return the existing actor resolver class without reimplementing actor ER."""
    from src.ML.entity_resolution.resolve_or_create import EntityResolver

    return EntityResolver


def zone_for_score(score: float, thresholds: Thresholds) -> str:
    if score >= thresholds.high:
        return "absorb"
    if score >= thresholds.low:
        return "review"
    return "create"


def load_event_candidates(session) -> list[dict[str, object]]:
    rows = session.execute(
        text("SELECT event_id::text AS event_id, name, next_date FROM event")
    ).mappings().all()
    return [dict(row) for row in rows]


def route_event(
    record: dict[str, object],
    candidates: Iterable[dict[str, object]],
    *,
    thresholds: Optional[Thresholds] = None,
) -> RouteDecision:
    thresholds = thresholds or load_actor_thresholds()
    blocked = normalized_token_block(record, candidates)
    record_key = str(record.get("natural_key") or "").strip()
    candidate_ids = [_candidate_id(candidate) for candidate in blocked]

    for candidate in blocked:
        if record_key and record_key == _candidate_natural_key(candidate):
            score = 1.0
            return RouteDecision(
                zone=zone_for_score(score, thresholds),
                score=score,
                target_entity_id=_candidate_id(candidate),
                candidate_ids=candidate_ids,
            )

    score = 0.0
    return RouteDecision(
        zone=zone_for_score(score, thresholds),
        score=score,
        target_entity_id=None,
        candidate_ids=candidate_ids,
    )


def normalized_token_block(
    record: dict[str, object],
    candidates: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    """Cheap event blocking before deterministic natural-key scoring."""
    record_tokens = _tokens(record.get("name") or record.get("title") or record.get("natural_key"))
    record_date = _date_part(record.get("start_date") or record.get("next_date"))
    blocked: list[dict[str, object]] = []
    for candidate in candidates:
        candidate_date = _date_part(candidate.get("start_date") or candidate.get("next_date"))
        if record_date and candidate_date and record_date == candidate_date:
            blocked.append(candidate)
            continue
        if record_tokens and record_tokens.intersection(_tokens(candidate.get("name") or candidate.get("title"))):
            blocked.append(candidate)
    return blocked


def _candidate_id(candidate: dict[str, object]) -> str:
    value = candidate.get("event_id") or candidate.get("entity_id") or candidate.get("id")
    return "" if value is None else str(value)


def _candidate_natural_key(candidate: dict[str, object]) -> str:
    if candidate.get("natural_key"):
        return str(candidate["natural_key"])
    from agents.discovery.normalize import event_natural_key

    title = candidate.get("name") or candidate.get("title") or ""
    start_date = candidate.get("start_date") or candidate.get("next_date") or ""
    return event_natural_key(str(title), str(start_date))


def _date_part(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().split("T", 1)[0]


def _tokens(value: object) -> set[str]:
    if value is None:
        return set()
    return {token for token in re.findall(r"[a-z0-9]+", str(value).lower()) if len(token) > 2}
