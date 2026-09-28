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
from urllib.parse import urlparse

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


def route_actor(
    record: dict[str, object],
    resolver,
    mapped_candidates: Iterable[dict[str, object]] | None = None,
) -> RouteDecision:
    """Apply the V2 mapped-first actor routing rule.

    Exact website-domain, canonical-name, or alternate-name matches append to
    the held record. The frozen resolver remains useful for identifying close
    candidates, but its score can never authorize an automatic merge.
    """
    name = str(record.get("name") or "").strip()
    if not name:
        raise ValueError("actor record has no name")

    exact = _exact_actor_matches(record, mapped_candidates or [])
    if len(exact) == 1:
        candidate = exact[0]
        actor_id = _actor_candidate_id(candidate)
        return RouteDecision(
            zone="absorb",
            score=1.0,
            target_entity_id=actor_id,
            candidate_ids=[actor_id],
            metadata={
                "match_rule": str(candidate["_match_rule"]),
                "matched_name": str(candidate.get("name") or ""),
                "matched_record_status": candidate.get("record_status"),
                "route_policy": "v2_exact_only",
            },
        )
    if len(exact) > 1:
        candidate_ids = sorted({_actor_candidate_id(candidate) for candidate in exact})
        return RouteDecision(
            zone="review",
            score=1.0,
            target_entity_id=candidate_ids[0],
            candidate_ids=candidate_ids,
            metadata={
                "review_kind": "possible_duplicate",
                "match_rule": "conflicting_exact_identity",
                "route_policy": "v2_exact_only",
            },
        )

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
    # V2 prohibits score-authorized merging. Every non-exact plausible match
    # is a possible-duplicate review item, including scores above the old HIGH.
    zone = "review" if score >= thresholds.low else "create"
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
            "review_kind": "possible_duplicate" if zone == "review" else None,
            "route_policy": "v2_exact_only",
        },
    )


def load_actor_candidates(session) -> list[dict[str, object]]:
    """Load mapped identities without depending on the pending column rename.

    ``to_jsonb`` lets this query run on both the current schema and the isolated
    V2 schema. Aggregate records remain excluded throughout the transition.
    """
    rows = (
        session.execute(
            text(
                "SELECT a.actor_id::text AS actor_id, a.name, a.website, "
                "COALESCE(to_jsonb(a)->'alternate_names','[]'::jsonb) AS alternate_names, "
                "COALESCE(to_jsonb(a)->>'website_domain','') AS website_domain, "
                "COALESCE(to_jsonb(a)->>'record_status', "
                "to_jsonb(a)->>'verification_status') AS record_status "
                "FROM actor a WHERE a.merged_into_actor_id IS NULL "
                "AND COALESCE(to_jsonb(a)->>'actor_category', "
                "to_jsonb(a)->>'actor_type','') <> 'aggregate' ORDER BY a.name"
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def _exact_actor_matches(
    record: dict[str, object], candidates: Iterable[dict[str, object]]
) -> list[dict[str, object]]:
    record_names = _actor_identity_names(record)
    record_domain = _actor_domain(record)
    matches: list[dict[str, object]] = []
    for candidate in candidates:
        rule = ""
        candidate_domain = _actor_domain(candidate)
        if record_domain and candidate_domain and record_domain == candidate_domain:
            rule = "website_domain"
        elif record_names.intersection(_actor_identity_names(candidate)):
            rule = "name_or_alternate_name"
        if rule:
            matches.append({**candidate, "_match_rule": rule})
    return matches


def _actor_identity_names(record: dict[str, object]) -> set[str]:
    from agents.discovery.normalize import normalize_key_text

    raw_names: list[object] = [record.get("name")]
    alternates = record.get("alternate_names") or record.get("alt_names") or []
    if isinstance(alternates, str):
        try:
            parsed = json.loads(alternates)
            alternates = parsed if isinstance(parsed, list) else [alternates]
        except json.JSONDecodeError:
            alternates = [alternates]
    if isinstance(alternates, Iterable):
        raw_names.extend(alternates)
    return {
        normalize_key_text(str(value))
        for value in raw_names
        if value is not None and str(value).strip()
    }


def _actor_domain(record: dict[str, object]) -> str:
    value = str(record.get("website_domain") or record.get("website") or "").strip()
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.hostname or "").casefold().strip(".").removeprefix("www.")


def _actor_candidate_id(candidate: dict[str, object]) -> str:
    actor_id = str(candidate.get("actor_id") or "").strip()
    if not actor_id:
        raise ValueError("mapped actor candidate has no actor_id")
    return actor_id


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


def load_person_affiliation_candidates(session) -> list[dict[str, object]]:
    rows = (
        session.execute(
            text(
                "SELECT actor_id::text AS actor_id, name AS affiliation "
                "FROM actor WHERE merged_into_actor_id IS NULL "
                "AND (actor_type IS NULL OR lower(actor_type) <> 'aggregate') "
                "ORDER BY name"
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
    allow_create: bool = False,
    affiliation_candidates: Iterable[dict[str, object]] | None = None,
    actor_resolver=None,
) -> RouteDecision:
    """Resolve name plus affiliation deterministically.

    Creation is available only to a caller that has already established an
    ``auto_high`` relevance band. Promotion independently verifies that
    authorization metadata before any canonical write.
    """
    name = str(record.get("name") or "").strip()
    if not name:
        raise ValueError("person record has no name")
    if len(name) > 255:
        return RouteDecision(
            zone="review",
            score=0.0,
            metadata={
                "identity_outcome": "invalid_name_length",
                "clean_identity_key": False,
                "identity_reason": "name exceeds the canonical 255-character limit",
            },
        )

    from agents.discovery.normalize import normalize_key_text

    name_key = normalize_key_text(name)
    name_matches = [
        candidate
        for candidate in candidates
        if normalize_key_text(str(candidate.get("full_name") or "")) == name_key
    ]
    affiliation_key = normalize_key_text(str(record.get("affiliation") or ""))
    if not affiliation_key:
        candidate_ids = sorted({_person_candidate_id(candidate) for candidate in name_matches})
        return RouteDecision(
            zone="review",
            score=1.0 if name_matches else 0.0,
            target_entity_id=candidate_ids[0] if len(candidate_ids) == 1 else None,
            candidate_ids=candidate_ids,
            metadata={
                "candidate_name": (
                    str(name_matches[0].get("full_name") or "")
                    if len(candidate_ids) == 1 else None
                ),
                "identity_outcome": "missing_affiliation",
                "clean_identity_key": False,
                "identity_reason": (
                    "name matches a held person but affiliation is missing"
                    if name_matches
                    else "affiliation is required for deterministic identity"
                ),
            },
        )
    key_matches = [
        candidate
        for candidate in name_matches
        if normalize_key_text(str(candidate.get("affiliation") or "")) == affiliation_key
    ]
    if key_matches:
        matched_person_ids = {
            _person_candidate_id(candidate) for candidate in key_matches
        }
        if len(matched_person_ids) != 1:
            return RouteDecision(
                zone="review",
                score=1.0,
                candidate_ids=sorted(matched_person_ids),
                metadata={
                    "identity_outcome": "ambiguous_identity",
                    "clean_identity_key": False,
                    "identity_reason": (
                        "normalized name and affiliation match multiple held people"
                    ),
                },
            )
        candidate = key_matches[0]
        conflicts = _person_detail_conflicts(record, candidate)
        if not conflicts:
            return RouteDecision(
                zone="skip",
                score=1.0,
                target_entity_id=_person_candidate_id(candidate),
                candidate_ids=[_person_candidate_id(match) for match in key_matches],
                metadata={
                    "candidate_name": str(candidate.get("full_name") or ""),
                    "identity_outcome": "already_held",
                    "clean_identity_key": True,
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
                "identity_outcome": "conflicting_details",
                "clean_identity_key": False,
                "identity_reason": "matching name and affiliation has conflicting details",
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
                "identity_outcome": "different_affiliation",
                "clean_identity_key": False,
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

    create_authorized = allow_create or preview_create
    if not create_authorized:
        return RouteDecision(
            zone="review",
            score=0.0,
            metadata={
                "identity_outcome": "create_not_authorized",
                "clean_identity_key": False,
                "identity_reason": "person creation requires an auto_high relevance band",
            },
        )

    from agents.discovery.normalize import is_institution_affiliation

    affiliation = str(record.get("affiliation") or "").strip()
    if not is_institution_affiliation(affiliation):
        return RouteDecision(
            zone="review",
            score=0.0,
            metadata={
                "identity_outcome": "invalid_affiliation",
                "clean_identity_key": False,
                "identity_reason": (
                    "affiliation did not normalize to an institution; departments and role text "
                    "cannot become actors"
                ),
            },
        )

    if actor_resolver is not None:
        actor_route = route_actor({"name": affiliation}, actor_resolver)
        if actor_route.zone == "review":
            return RouteDecision(
                zone="review",
                score=actor_route.score,
                target_entity_id=actor_route.target_entity_id,
                candidate_ids=actor_route.candidate_ids,
                metadata={
                    **dict(actor_route.metadata or {}),
                    "identity_outcome": "ambiguous_affiliation",
                    "clean_identity_key": False,
                    "identity_reason": (
                        "normalized institution is inside the frozen actor resolver review band"
                    ),
                },
            )
        if actor_route.zone == "absorb":
            actor_ids = {str(actor_route.target_entity_id or "").strip()}
            actor_ids.discard("")
        else:
            actor_ids = set()
    else:
        actor_pool = list(
            affiliation_candidates if affiliation_candidates is not None else candidates
        )
        actor_matches = [
            candidate
            for candidate in actor_pool
            if normalize_key_text(
                str(candidate.get("affiliation") or candidate.get("name") or "")
            )
            == affiliation_key
            and str(candidate.get("actor_id") or "").strip()
        ]
        actor_ids = {
            str(candidate.get("actor_id") or "").strip() for candidate in actor_matches
        }
    if len(actor_ids) > 1:
        return RouteDecision(
            zone="review",
            score=0.0,
            candidate_ids=sorted(actor_ids),
            metadata={
                "identity_outcome": "ambiguous_affiliation",
                "clean_identity_key": False,
                "identity_reason": "affiliation matches more than one held actor",
            },
        )
    role = str(record.get("role") or "").strip()
    if not role:
        return RouteDecision(
            zone="review",
            score=0.0,
            metadata={
                "identity_outcome": "missing_role",
                "clean_identity_key": False,
                "identity_reason": "role is required to create the actor-person affiliation",
            },
        )
    if len(role) > 120:
        return RouteDecision(
            zone="review",
            score=0.0,
            metadata={
                "identity_outcome": "invalid_role_length",
                "clean_identity_key": False,
                "identity_reason": (
                    "role exceeds the actor_person 120-character limit"
                ),
            },
        )
    if not actor_ids:
        return RouteDecision(
            zone="create",
            score=0.0,
            metadata={
                "identity_outcome": "create",
                "clean_identity_key": True,
                "create_affiliation_stub": True,
                "affiliation_stub_name": affiliation,
                "identity_reason": (
                    "frozen actor resolution found no match; create a needs-review actor stub"
                ),
            },
        )

    actor_id = next(iter(actor_ids))
    return RouteDecision(
        zone="create",
        score=0.0,
        metadata={
            "identity_outcome": "create",
            "clean_identity_key": True,
            "affiliation_actor_id": actor_id,
            "identity_reason": "normalized name and affiliation are not held",
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
