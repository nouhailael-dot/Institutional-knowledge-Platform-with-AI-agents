"""Routing bridge between staged agent records and canonical entities.

The existing frozen combiner is actor-specific. Event routing therefore uses a
separate deterministic natural-key match: normalized title plus start date. The
score is 1.0 for exact natural-key matches and 0.0 otherwise so the route shape
stays uniform without applying an actor model to events.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import text

from agents.common.config import load_sources_config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Thresholds:
    high: float
    low: float


@dataclass(frozen=True)
class RouteDecision:
    zone: str
    score: float
    target_entity_id: str | None = None
    candidate_ids: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


def load_actor_thresholds(project_root: Path | None = None) -> Thresholds:
    """Load deployed ER thresholds from the existing production config."""
    root = project_root or Path(__file__).resolve().parents[2]
    cfg = json.loads((root / "config" / "er_production.json").read_text(encoding="utf-8"))
    return Thresholds(high=float(cfg["high_threshold"]), low=float(cfg["low_threshold"]))


def load_event_review_threshold(project_root: Path | None = None) -> float:
    root = project_root or Path(__file__).resolve().parents[2]
    cfg = load_sources_config(root)
    try:
        threshold = float(dict(cfg["routing"])["event_fuzzy_review_threshold"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "agents/config/sources.yaml must define routing.event_fuzzy_review_threshold"
        ) from exc
    if threshold <= 0.0 or threshold > 1.0:
        raise RuntimeError("routing.event_fuzzy_review_threshold must be > 0 and <= 1")
    return threshold


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


def route_actor(record: dict[str, object], resolver) -> RouteDecision:
    """Route an actor with the existing frozen actor ER resolver.

    The resolver owns blocking, feature extraction, and combiner scoring. This
    function only maps the best score to the shared route shape so promotion
    stays inside agents/discovery/promote.py.
    """
    name = str(record.get("name") or "").strip()
    if not name:
        raise ValueError("actor record has no name")

    candidates = resolver._candidates(name)
    thresholds = Thresholds(high=float(resolver.HIGH), low=float(resolver.LOW))
    if candidates.empty:
        return RouteDecision(
            zone="create",
            score=0.0,
            candidate_ids=[],
            metadata={"model": getattr(resolver, "model_name", "combiner")},
        )

    scored = resolver._score(record, candidates)
    best = scored.iloc[0]
    score = float(best["score"])
    zone = zone_for_score(score, thresholds)
    candidate_ids = [str(value) for value in scored["actor_id"].tolist()]
    target_entity_id = str(best["actor_id"]) if zone in {"absorb", "review"} else None
    return RouteDecision(
        zone=zone,
        score=score,
        target_entity_id=target_entity_id,
        candidate_ids=candidate_ids,
        metadata={
            "matched_name": str(best.get("name") or ""),
            "model": getattr(resolver, "model_name", "combiner"),
        },
    )


def load_event_candidates(session) -> list[dict[str, object]]:
    rows = (
        session.execute(text("SELECT event_id::text AS event_id, name, next_date FROM event"))
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def load_person_candidates(session) -> list[dict[str, object]]:
    rows = (
        session.execute(
            text(
                "SELECT p.person_id::text AS person_id, p.full_name, p.title, p.linkedin_url, "
                "a.actor_id::text AS actor_id, a.name AS affiliation, ap.role "
                "FROM person p "
                "LEFT JOIN actor_person ap ON ap.person_id = p.person_id "
                "AND ap.is_current IS NOT FALSE "
                "LEFT JOIN actor a ON a.actor_id = ap.actor_id "
                "ORDER BY p.full_name, a.name"
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def route_person(
    record: dict[str, object],
    candidates: Iterable[dict[str, object]],
    *,
    preview_create: bool = False,
) -> RouteDecision:
    """Resolve name plus affiliation deterministically.

    The standing policy still routes new people to review. ``preview_create`` is
    a dry-run-only caller option that exposes the architecture's proposed create
    route without authorizing a canonical write.
    """
    name = str(record.get("name") or "").strip()
    if not name:
        raise ValueError("person record has no name")

    from agents.discovery.normalize import normalize_key_text

    name_key = normalize_key_text(name)
    name_matches = [
        candidate
        for candidate in candidates
        if normalize_key_text(str(candidate.get("full_name") or "")) == name_key
    ]
    affiliation_key = normalize_key_text(str(record.get("affiliation") or ""))
    if not affiliation_key:
        return RouteDecision(
            zone="review",
            score=0.0,
            metadata={"identity_reason": "affiliation is required for deterministic identity"},
        )
    key_matches = [
        candidate
        for candidate in name_matches
        if normalize_key_text(str(candidate.get("affiliation") or "")) == affiliation_key
    ]
    if key_matches:
        candidate = key_matches[0]
        conflicts = _person_detail_conflicts(record, candidate)
        if preview_create and not conflicts:
            return RouteDecision(
                zone="skip",
                score=1.0,
                target_entity_id=_person_candidate_id(candidate),
                candidate_ids=[_person_candidate_id(match) for match in key_matches],
                metadata={
                    "candidate_name": str(candidate.get("full_name") or ""),
                    "identity_reason": "already held with matching name and affiliation",
                },
            )
        return RouteDecision(
            zone="review",
            score=1.0,
            target_entity_id=_person_candidate_id(candidate),
            candidate_ids=[_person_candidate_id(match) for match in key_matches],
            metadata={
                "candidate_name": str(candidate.get("full_name") or ""),
                "identity_reason": (
                    "matching name and affiliation has conflicting details"
                    if conflicts
                    else "standing policy requires person review"
                ),
                "conflicting_fields": conflicts,
            },
        )

    if name_matches:
        candidate = name_matches[0]
        return RouteDecision(
            zone="review",
            score=1.0,
            target_entity_id=_person_candidate_id(candidate),
            candidate_ids=[_person_candidate_id(match) for match in name_matches],
            metadata={
                "candidate_name": str(candidate.get("full_name") or ""),
                "identity_reason": "same normalized name with a different affiliation",
                "candidate_affiliations": sorted(
                    {
                        str(match.get("affiliation") or "").strip()
                        for match in name_matches
                        if str(match.get("affiliation") or "").strip()
                    }
                ),
            },
        )

    return RouteDecision(
        zone="create" if preview_create else "review",
        score=0.0,
        metadata={
            "identity_reason": (
                "normalized name and affiliation are not held"
                if preview_create
                else "standing policy requires person review"
            )
        },
    )


def _person_detail_conflicts(
    record: dict[str, object],
    candidate: dict[str, object],
) -> list[str]:
    conflicts: list[str] = []
    field_pairs = (
        ("role", candidate.get("role") or candidate.get("title")),
        ("public_profile_url", candidate.get("linkedin_url")),
    )
    for record_field, candidate_value in field_pairs:
        incoming = " ".join(str(record.get(record_field) or "").split()).casefold()
        existing = " ".join(str(candidate_value or "").split()).casefold()
        if not incoming or not existing:
            continue
        if incoming != existing and record_field not in conflicts:
            conflicts.append(record_field)
    return conflicts


def route_event(
    record: dict[str, object],
    candidates: Iterable[dict[str, object]],
    *,
    thresholds: Thresholds | None = None,
    event_review_threshold: float | None = None,
    project_root: Path | None = None,
) -> RouteDecision:
    thresholds = thresholds or load_actor_thresholds()
    fuzzy_threshold = (
        event_review_threshold
        if event_review_threshold is not None
        else load_event_review_threshold(project_root)
    )
    blocked = normalized_token_block(record, candidates)
    record_key = str(record.get("natural_key") or "").strip()
    candidate_ids = [_candidate_id(candidate) for candidate in blocked]
    record_title = str(record.get("name") or record.get("title") or "")
    record_date = _date_part(record.get("start_date") or record.get("next_date"))

    for candidate in blocked:
        if record_key and record_key == _candidate_natural_key(candidate):
            score = 1.0
            return RouteDecision(
                zone=zone_for_score(score, thresholds),
                score=score,
                target_entity_id=_candidate_id(candidate),
                candidate_ids=candidate_ids,
            )

    fuzzy_matches: list[tuple[float, dict[str, object]]] = []
    for candidate in blocked:
        candidate_date = _date_part(candidate.get("start_date") or candidate.get("next_date"))
        if not record_date or not candidate_date or record_date != candidate_date:
            continue
        candidate_title = str(candidate.get("name") or candidate.get("title") or "")
        similarity = _title_similarity(record_title, candidate_title)
        if similarity >= fuzzy_threshold:
            logger.info(
                "event fuzzy review match staged_title=%r candidate_title=%r similarity=%.4f threshold=%.4f",
                record_title,
                candidate_title,
                similarity,
                fuzzy_threshold,
            )
            fuzzy_matches.append((similarity, candidate))

    if fuzzy_matches:
        score, candidate = max(fuzzy_matches, key=lambda item: item[0])
        candidate_title = str(candidate.get("name") or candidate.get("title") or "")
        return RouteDecision(
            zone="review",
            score=score,
            target_entity_id=_candidate_id(candidate),
            candidate_ids=candidate_ids,
            metadata={
                "staged_title": record_title,
                "candidate_title": candidate_title,
                "shared_start_date": record_date,
            },
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
        if record_tokens and record_tokens.intersection(
            _tokens(candidate.get("name") or candidate.get("title"))
        ):
            blocked.append(candidate)
    return blocked


def _candidate_id(candidate: dict[str, object]) -> str:
    value = candidate.get("event_id") or candidate.get("entity_id") or candidate.get("id")
    return "" if value is None else str(value)


def _person_candidate_id(candidate: dict[str, object]) -> str:
    value = candidate.get("person_id") or candidate.get("entity_id") or candidate.get("id")
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


def _title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalized_title(left), _normalized_title(right)).ratio()


def _normalized_title(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))
