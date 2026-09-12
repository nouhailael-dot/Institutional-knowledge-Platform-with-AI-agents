"""Candidate triage for open-web discovery."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, replace
from urllib.parse import urlparse

from sqlalchemy import text

from agents.discovery.search.models import SearchResult, TriageDecision

logger = logging.getLogger(__name__)
TRIAGE_INCOMPLETE_REASON_PREFIX = "triage incomplete:"
ENGAGEMENT_ROUTE_SIGNAL_NAMES = (
    "partnerships_and_research",
    "memberships",
    "leadership_networks",
    "ecosystem_platforms",
    "hosted_visits",
    "executive_programmes",
    "event_participation",
    "introductions",
)
ACTOR_USE_CASES = (
    ("research_collaboration", "research collaboration"),
    ("learning_expeditions", "learning expeditions"),
    ("executive_education", "executive education"),
    ("mentorship", "mentorship"),
    ("student_and_faculty_mobility", "student and faculty mobility"),
    ("open_innovation", "open innovation"),
    ("corporate_engagement", "corporate engagement"),
    ("opportunity_development", "opportunity development"),
)
ACTOR_USE_CASE_NAMES = tuple(name for name, _label in ACTOR_USE_CASES)
ACTOR_REJECTION_CONDITION_NAMES = (
    "sector_relevance",
    "engagement_route",
    "strategic_ecosystem_value",
)
PERSON_RELEVANCE_SIGNAL_NAMES = (
    "sector_intersection",
    "hub_or_held_affiliation",
    "actionable_role",
    "topic_evidence",
)
DEFAULT_ACTOR_REJECTION_THRESHOLDS = {
    "sector_relevance": 0.35,
    "engagement_route": 0.20,
    "strategic_ecosystem_value": 0.35,
}
DEFAULT_ACTOR_FIT_WEIGHTS = {
    "sector_relevance": 0.30,
    "engagement_route": 0.35,
    "strategic_ecosystem_value": 0.25,
    "distinctiveness": 0.10,
}
ACTOR_TRIAGE_SYSTEM_PROMPT = (
    "Evaluate actor candidates for GHUS open-web discovery across eight use cases: "
    "research collaboration, learning expeditions, executive education, mentorship, "
    "student and faculty mobility, open innovation, corporate engagement, and opportunity "
    "development. Use only the search-result title, snippet, URL, seeded sectors, public "
    "actor reference examples, and supplied deterministic coverage context. Do not infer "
    "facts from pages that have not been fetched. Evidence must come from a result published "
    "on the organisation's own site."
)
PERSON_TRIAGE_SYSTEM_PROMPT = (
    "Evaluate the professional relevance of person-page search candidates for GHUS. "
    "Use only the search-result title, snippet, URL, seeded sectors, and supplied hub "
    "context. Return a short evidence string or null for every relevance signal. "
    "Judge relevance only. Never decide whether two people are the same person, never "
    "return an identity key or route, and never collect contact or personal details."
)
ACTOR_NEWS_AND_DIRECTORY_BLOCKLIST = (
    "geekwire.com",
    "siliconangle.com",
    "axios.com",
    "hpcwire.com",
    "marktechpost.com",
    "techcrunch.com",
    "crunchbase.com",
    "businesswire.com",
    "prnewswire.com",
    "globenewswire.com",
)
PERSON_DIRECTORY_AND_PROFILE_BLOCKLIST = (
    "academia.edu",
    "crunchbase.com",
    "google.com",
    "linkedin.com",
    "researchgate.net",
    "rocketreach.co",
    "zoominfo.com",
)
DEFAULT_PERSON_INSTITUTIONAL_SUFFIXES = (
    ".edu",
    ".gov",
    ".mil",
    ".int",
    ".org",
    ".ac.uk",
    ".ac.ma",
)

DEFAULT_NON_CONTENT_PATHS = (
    "/login",
    "/cart",
    "/privacy",
    "/privacy-policy",
    "/terms",
    "/tag/",
)


@dataclass(frozen=True)
class DeterministicReject:
    reason: str
    domain: str


class RawDocumentLookup:
    def has_seen_raw_url(self, url: str) -> bool:
        raise NotImplementedError


class TriageResponseError(RuntimeError):
    """Raised when Claude returns a malformed triage tool payload."""


class SearchTriageClient:
    def __init__(self, llm_client, config: dict[str, object]):
        self.llm_client = llm_client
        self.config = config
        self._logged_raw_payload = False

    def triage(
        self,
        candidates: list[SearchResult],
        *,
        entity_type: str,
        sectors: list[dict[str, str]],
        references: list[dict[str, object]],
        actor_context: dict[str, object] | None = None,
    ) -> dict[str, TriageDecision]:
        if not candidates:
            return {}
        if entity_type == "person" and not bool(self.config.get("people_enabled", False)):
            raise RuntimeError(
                "person relevance triage is disabled pending TARGETING_POLICY.md section 6 approval"
            )
        candidate_payloads = [candidate.__dict__ for candidate in candidates]
        user_payload = _triage_user_payload(
            entity_type=entity_type,
            sectors=sectors,
            references=references,
            candidates=candidate_payloads,
            actor_context=actor_context,
            config=self.config,
        )
        payload = self.llm_client.extract_with_tool(
            system=(
                ACTOR_TRIAGE_SYSTEM_PROMPT
                if entity_type == "actor"
                else PERSON_TRIAGE_SYSTEM_PROMPT
                if entity_type == "person"
                else (
                    "Triage search results for GHUS open-web discovery. "
                    "Use only the title, snippet, URL, sectors, and reference examples. "
                    "Do not infer facts from pages you have not fetched."
                )
            ),
            user=json.dumps(user_payload, ensure_ascii=False, sort_keys=True),
            tool_name="triage_open_web_candidates",
            tool_description=(
                "Return actor identity, per-use-case fit, engagement evidence, and evidence "
                "for each actor rejection condition. The application computes engagement "
                "route, fit, and verdict."
                if entity_type == "actor"
                else (
                    "Return professional-page status, relevance evidence, sector/hub matches, "
                    "a relevance score, and reasoning. Do not return identity decisions."
                    if entity_type == "person"
                    else "Return deterministic-search survivors with fit scores and reasons."
                )
            ),
            input_schema=_triage_input_schema(entity_type),
            max_tokens=int(self.config.get("triage_max_tokens", 2048)),
        )
        returned = _candidate_items_from_payload(payload)
        if returned is None:
            self._log_raw_payload_once(payload, "non-list candidates")
            raise TriageResponseError("LLM triage returned non-list candidates")

        decisions: dict[str, TriageDecision] = {}
        for item in returned:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            if entity_type == "actor":
                decisions[url] = _actor_decision_from_item(
                    item,
                    url=url,
                    actor_context=actor_context,
                    config=self.config,
                )
            elif entity_type == "person":
                decisions[url] = _person_decision_from_item(item, url=url)
            else:
                decisions[url] = TriageDecision(
                    url=url,
                    is_entity_type=bool(item.get("is_entity_type")),
                    plausible_sector=bool(item.get("plausible_sector")),
                    fit_score=_coerce_score(item.get("fit_score")),
                    reason=_clean_decision_reason(item.get("reason")),
                )

        input_urls = {candidate.url for candidate in candidates}
        extra_urls = sorted(set(decisions) - input_urls)
        for url in extra_urls:
            decisions.pop(url, None)
        if extra_urls:
            logger.warning("LLM triage returned %d URL(s) not present in the batch", len(extra_urls))
            self._log_raw_payload_once(payload, "extra candidate urls")

        missing = [candidate for candidate in candidates if candidate.url not in decisions]
        if missing:
            logger.warning("LLM triage omitted %d candidate(s)", len(missing))
            self._log_raw_payload_once(payload, "omitted candidates")
        return decisions

    def _log_raw_payload_once(self, payload: object, reason: str) -> None:
        if self._logged_raw_payload:
            return
        self._logged_raw_payload = True
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        logger.warning("LLM triage raw response anomaly (%s): %s", reason, raw[:4000])


def _triage_user_payload(
    *,
    entity_type: str,
    sectors: list[dict[str, str]],
    references: list[dict[str, object]],
    candidates: list[dict[str, object]],
    actor_context: dict[str, object] | None,
    config: dict[str, object],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "entity_type": entity_type,
        "sectors": sectors,
        "reference_examples": (
            _public_actor_reference_examples(references)
            if entity_type == "actor"
            else references
        ),
        "candidates": candidates,
        "decision_rule": (
            "Return exactly one decision object for every candidate URL provided. "
            "If a candidate is hard to judge, reject it and explain the uncertainty."
        ),
    }
    if entity_type != "actor":
        if entity_type == "person":
            payload.update(
                {
                    "candidate_hub_context": _candidate_hubs(actor_context),
                    "person_relevance_rule": (
                        "For each signal return a short quote or paraphrase from the result, or "
                        "null when the result does not establish it. The signals are: "
                        "sector_intersection (research intersects a seeded sector); "
                        "hub_or_held_affiliation (affiliation is in a hub or is an organisation "
                        "already held); actionable_role (lab head, programme director, "
                        "partnerships lead, principal investigator, or comparable senior role); "
                        "topic_evidence (evidence of actual work on the topic, not a passing "
                        "mention). Reject confidently and accept provisionally."
                    ),
                    "identity_boundary": (
                        "Do not return a natural key, duplicate judgment, identity match, or "
                        "routing decision. Identity is computed later by deterministic code."
                    ),
                    "relevance_floor": float(
                        dict(config.get("accept_floor", {}) or {}).get("person", 0.75)
                    ),
                }
            )
        return payload

    weights = actor_fit_weights(config)
    thresholds = actor_rejection_thresholds(config)
    payload["candidates"] = _actor_candidates_with_context(
        candidates,
        sectors=sectors,
        actor_context=actor_context,
    )
    payload.update(
        {
            "actor_quality_rule": (
                "Reject any candidate that is not published by the organisation itself or is "
                "not a real operating organisation. Press coverage, conference speaker bios, "
                "directory listings, third-party funding announcements, aggregator profiles, "
                "grouping pages, consortium listings, category pages, and bare projects must be "
                "rejected. Use reason 'not the organisation's own page' when the publisher test "
                "fails."
            ),
            "actor_use_cases": [label for _name, label in ACTOR_USE_CASES],
            "use_case_fit_rule": (
                "For every actor use case, return a short quote or paraphrase from the supplied "
                "result when the candidate plausibly serves it, or null. Never return a boolean. "
                "Do not award research_collaboration merely because the candidate is a large "
                "company: a corporate visitor programme supports learning_expeditions and "
                "corporate_engagement unless research collaboration is separately evidenced. "
                "A university lab with collaboration and visiting-student evidence supports "
                "research_collaboration and student_and_faculty_mobility."
            ),
            "engagement_route_rule": (
                "Identify practical routes into the organisation. A partnerships page is not "
                "required. For each named route signal, return a short quote or paraphrase from "
                "the result, or null; never return a boolean. Count partnerships and research "
                "programmes, memberships, leadership networks, ecosystem platforms, hosted "
                "visits, executive programmes, event participation, and introductions. The "
                "application derives engagement_route as the share of eight use cases with "
                "evidence. Do not return engagement_route. A missing route lowers fit but never "
                "rejects alone."
            ),
            "three_condition_rejection_rule": (
                "Score sector_relevance and strategic_ecosystem_value, and explain all three "
                "conditions separately. sector_relevance measures relevance to the seeded "
                "sectors. The application derives engagement_route from use_case_fit. "
                "strategic_ecosystem_value measures whether the organisation could add strategic "
                "ecosystem value across the eight use cases based only on supplied evidence. "
                "Return a concise evidence string for every condition, including an explicit "
                "no-evidence statement when evidence is absent. Do not return engagement_route or "
                "a verdict. The application rejects only when all three scores are below their "
                "configured thresholds."
            ),
            "distinctiveness_rule": (
                "Each candidate's coverage_context contains only hub/sector labels and aggregate "
                "counts. Reference existing_actor_count in the reasoning when useful. The "
                "application computes distinctiveness as 1 / (1 + existing_actor_count). Do not "
                "return or infer distinctiveness from prominence. "
                "Distinctiveness changes ranking only and must never cause rejection."
            ),
            "fit_score_rule": (
                "The application computes fit_score from sector_relevance, engagement_route, "
                "strategic_ecosystem_value, and deterministic distinctiveness using the supplied "
                "weights. Do not return fit_score."
            ),
            "actor_fit_weights": weights,
            "actor_rejection_thresholds": thresholds,
        }
    )
    return payload


def _triage_input_schema(entity_type: str) -> dict[str, object]:
    if entity_type == "actor":
        item_schema = _actor_triage_item_schema()
    elif entity_type == "person":
        item_schema = _person_triage_item_schema()
    else:
        item_schema = {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "is_entity_type": {"type": "boolean"},
                "plausible_sector": {"type": "boolean"},
                "fit_score": {
                    "type": ["number", "null"],
                    "minimum": 0,
                    "maximum": 1,
                },
                "reason": {"type": "string"},
            },
            "required": [
                "url",
                "is_entity_type",
                "plausible_sector",
                "fit_score",
                "reason",
            ],
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": {"candidates": {"type": "array", "items": item_schema}},
        "required": ["candidates"],
        "additionalProperties": False,
    }


def _actor_triage_item_schema() -> dict[str, object]:
    evidence_value = {"type": ["string", "null"], "minLength": 1, "maxLength": 240}
    condition_evidence_value = {"type": "string", "minLength": 1, "maxLength": 240}
    properties: dict[str, object] = {
        "url": {"type": "string"},
        "is_own_page": {"type": "boolean"},
        "is_operating_org": {"type": "boolean"},
        "actor_type_guess": {"type": ["string", "null"]},
        "hub_matches": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "sector_codes": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "engagement_signals": {
            "type": "object",
            "properties": {
                name: evidence_value for name in ENGAGEMENT_ROUTE_SIGNAL_NAMES
            },
            "required": list(ENGAGEMENT_ROUTE_SIGNAL_NAMES),
            "additionalProperties": False,
        },
        "use_case_fit": {
            "type": "object",
            "properties": {name: evidence_value for name in ACTOR_USE_CASE_NAMES},
            "required": list(ACTOR_USE_CASE_NAMES),
            "additionalProperties": False,
        },
        "condition_evidence": {
            "type": "object",
            "properties": {
                name: condition_evidence_value
                for name in ACTOR_REJECTION_CONDITION_NAMES
            },
            "required": list(ACTOR_REJECTION_CONDITION_NAMES),
            "additionalProperties": False,
        },
        "sector_relevance": {"type": "number", "minimum": 0, "maximum": 1},
        "strategic_ecosystem_value": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string", "minLength": 1, "maxLength": 300},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _person_triage_item_schema() -> dict[str, object]:
    evidence_value = {"type": ["string", "null"], "minLength": 1, "maxLength": 240}
    properties: dict[str, object] = {
        "url": {"type": "string"},
        "is_professional_person_page": {"type": "boolean"},
        "sector_codes": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "hub_matches": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "relevance_signals": {
            "type": "object",
            "properties": {
                name: evidence_value for name in PERSON_RELEVANCE_SIGNAL_NAMES
            },
            "required": list(PERSON_RELEVANCE_SIGNAL_NAMES),
            "additionalProperties": False,
        },
        "relevance_score": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string", "minLength": 1, "maxLength": 300},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _actor_decision_from_item(
    item: dict[str, object],
    *,
    url: str,
    actor_context: dict[str, object] | None,
    config: dict[str, object],
) -> TriageDecision:
    signals = _clean_evidence_signals(
        item.get("engagement_signals"),
        names=ENGAGEMENT_ROUTE_SIGNAL_NAMES,
    )
    use_case_fit = _clean_evidence_signals(
        item.get("use_case_fit"),
        names=ACTOR_USE_CASE_NAMES,
    )
    condition_evidence = _clean_condition_evidence(item.get("condition_evidence"))
    sector_relevance = _coerce_score(item.get("sector_relevance"))
    engagement_route = actor_engagement_route_score(use_case_fit)
    strategic_ecosystem_value = _coerce_score(item.get("strategic_ecosystem_value"))

    hub_matches = _clean_string_tuple(item.get("hub_matches"))
    sector_codes = tuple(value.upper() for value in _clean_string_tuple(item.get("sector_codes")))
    existing_actor_count = _existing_actor_count_for_candidate(
        url=url,
        hub_matches=hub_matches,
        sector_codes=sector_codes,
        actor_context=actor_context,
    )
    distinctiveness = actor_distinctiveness_score(existing_actor_count)
    fit_score = None
    if all(
        score is not None
        for score in (sector_relevance, engagement_route, strategic_ecosystem_value)
    ):
        fit_score = actor_fit_score(
            sector_relevance,
            engagement_route,
            strategic_ecosystem_value,
            distinctiveness,
            config=config,
        )

    legacy_entity_type = item.get("is_entity_type")
    is_operating_org = _coerce_optional_bool(
        item.get("is_operating_org"),
        fallback=legacy_entity_type,
    )
    is_own_page = _coerce_optional_bool(
        item.get("is_own_page"),
        fallback=legacy_entity_type,
    )
    plausible_sector = sector_relevance is not None
    decision = TriageDecision(
        url=url,
        is_entity_type=bool(
            legacy_entity_type if legacy_entity_type is not None else is_operating_org
        ),
        plausible_sector=plausible_sector,
        fit_score=fit_score,
        reason=_clean_decision_reason(item.get("reason")),
        is_own_page=is_own_page,
        is_operating_org=is_operating_org,
        actor_type_guess=_clean_optional_string(item.get("actor_type_guess")),
        hub_matches=hub_matches,
        sector_codes=sector_codes,
        engagement_signals=signals,
        use_case_fit=use_case_fit,
        condition_evidence=condition_evidence,
        sector_relevance=sector_relevance,
        engagement_route=engagement_route,
        strategic_ecosystem_value=strategic_ecosystem_value,
        distinctiveness=distinctiveness,
        existing_actor_count=existing_actor_count,
    )
    verdict = triage_verdict(
        decision,
        floor=0.0,
        entity_type="actor",
        actor_thresholds=actor_rejection_thresholds(config),
    )
    reason = decision.reason
    if (
        verdict == "rejected"
        and decision.is_own_page is not False
        and decision.is_operating_org is not False
        and fails_all_actor_conditions(
            decision,
            thresholds=actor_rejection_thresholds(config),
        )
    ):
        reason = "low sector relevance; no engagement route; no strategic ecosystem value"
    return replace(decision, verdict=verdict, reason=reason)


def _person_decision_from_item(item: dict[str, object], *, url: str) -> TriageDecision:
    professional_page = bool(item.get("is_professional_person_page"))
    sector_codes = tuple(value.upper() for value in _clean_string_tuple(item.get("sector_codes")))
    signals = _clean_evidence_signals(
        item.get("relevance_signals"),
        names=PERSON_RELEVANCE_SIGNAL_NAMES,
    )
    return TriageDecision(
        url=url,
        is_entity_type=professional_page,
        plausible_sector=bool(sector_codes),
        fit_score=_coerce_score(item.get("relevance_score")),
        reason=_clean_decision_reason(item.get("reason")),
        is_professional_person_page=professional_page,
        hub_matches=_clean_string_tuple(item.get("hub_matches")),
        sector_codes=sector_codes,
        relevance_signals=signals,
    )


def _clean_condition_evidence(value: object) -> dict[str, str]:
    evidence = _clean_evidence_signals(value, names=ACTOR_REJECTION_CONDITION_NAMES)
    return {
        name: detail or "No evidence found in the supplied search result."
        for name, detail in evidence.items()
    }


def _clean_evidence_signals(
    value: object,
    *,
    names: Iterable[str],
) -> dict[str, str | None]:
    mapping = value if isinstance(value, dict) else {}
    signals: dict[str, str | None] = {}
    for name in names:
        evidence = mapping.get(name)
        if isinstance(evidence, bool) or evidence is None:
            signals[name] = None
            continue
        cleaned = str(evidence).strip()
        signals[name] = cleaned or None
    return signals


def _clean_string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    cleaned: list[str] = []
    for item in value:
        text_value = str(item or "").strip()
        if text_value and text_value not in cleaned:
            cleaned.append(text_value)
    return tuple(cleaned)


def _clean_optional_string(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _coerce_optional_bool(value: object, *, fallback: object = None) -> bool:
    selected = fallback if value is None else value
    return bool(selected)


def load_actor_triage_reference_examples(
    session,
    *,
    limit: int = 20,
) -> list[dict[str, object]]:
    if session is None:
        return []
    rows = (
        session.execute(
            text(
                "SELECT actor.name, actor.actor_type, "
                "array_remove(array_agg(DISTINCT upper(sector.code)), NULL) AS sectors "
                "FROM actor "
                "LEFT JOIN actor_sector ON actor_sector.actor_id = actor.actor_id "
                "LEFT JOIN sector ON sector.sector_id = actor_sector.sector_id "
                "WHERE actor.merged_into_actor_id IS NULL "
                "AND (actor.actor_type IS NULL OR lower(actor.actor_type) <> 'aggregate') "
                "GROUP BY actor.actor_id, actor.name, actor.actor_type, actor.updated_at "
                "ORDER BY actor.updated_at DESC NULLS LAST, actor.name "
                "LIMIT :limit"
            ),
            {"limit": limit},
        )
        .mappings()
        .all()
    )
    return _public_actor_reference_examples([dict(row) for row in rows])[:limit]


def _public_actor_reference_examples(
    references: list[dict[str, object]],
) -> list[dict[str, object]]:
    public: list[dict[str, object]] = []
    for reference in references[:20]:
        name = str(reference.get("name") or "").strip()
        if not name:
            continue
        raw_sectors = reference.get("sectors") or reference.get("sector_codes") or []
        if isinstance(raw_sectors, str):
            raw_sectors = [raw_sectors]
        public.append(
            {
                "name": name,
                "actor_type": str(reference.get("actor_type") or "").strip(),
                "sectors": [value.upper() for value in _clean_string_tuple(raw_sectors)],
            }
        )
    return public


def load_actor_hub_sector_counts(session) -> dict[tuple[str, str], int]:
    if session is None:
        return {}
    rows = (
        session.execute(
            text(
                "SELECT h.name AS hub_name, upper(s.code) AS sector_code, "
                "count(DISTINCT CASE WHEN actor_sector.actor_id IS NOT NULL "
                "THEN actor.actor_id END) AS actor_count "
                "FROM hub h CROSS JOIN sector s "
                "LEFT JOIN hub_actor ON hub_actor.hub_id = h.hub_id "
                "LEFT JOIN actor ON actor.actor_id "
                "= hub_actor.actor_id "
                "AND actor.merged_into_actor_id IS NULL "
                "AND (actor.actor_type IS NULL OR lower(actor.actor_type) <> 'aggregate') "
                "LEFT JOIN actor_sector ON actor_sector.actor_id = actor.actor_id "
                "AND actor_sector.sector_id = s.sector_id "
                "WHERE h.name <> 'Mining Hubs' "
                "GROUP BY h.name, s.code"
            )
        )
        .mappings()
        .all()
    )
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        hub_name = str(row.get("hub_name") or "").strip()
        sector_code = str(row.get("sector_code") or "").strip().upper()
        if not hub_name or not sector_code:
            continue
        try:
            actor_count = max(0, int(row.get("actor_count") or 0))
        except (TypeError, ValueError):
            actor_count = 0
        counts[(hub_name, sector_code)] = actor_count
    return counts


def actor_rejection_thresholds(config: dict[str, object]) -> dict[str, float]:
    return {
        name: _bounded_config_score(
            config.get(
                f"actor_{name}_floor",
                DEFAULT_ACTOR_REJECTION_THRESHOLDS[name],
            ),
            key=f"actor_{name}_floor",
        )
        for name in ACTOR_REJECTION_CONDITION_NAMES
    }


def actor_fit_weights(config: dict[str, object]) -> dict[str, float]:
    configured = dict(config.get("actor_fit_weights", {}) or {})
    try:
        weights = {
            name: float(configured.get(name, DEFAULT_ACTOR_FIT_WEIGHTS[name]))
            for name in (*ACTOR_REJECTION_CONDITION_NAMES, "distinctiveness")
        }
    except (TypeError, ValueError) as exc:
        raise RuntimeError("open_web_discovery.actor_fit_weights must be numeric") from exc
    if any(weight < 0 for weight in weights.values()):
        raise RuntimeError("open_web_discovery.actor_fit_weights must be non-negative")
    total = sum(weights.values())
    if total <= 0:
        raise RuntimeError("open_web_discovery.actor_fit_weights must have a positive total")
    return {name: weight / total for name, weight in weights.items()}


def actor_distinctiveness_score(existing_actor_count: int | None) -> float:
    if existing_actor_count is None:
        return 0.0
    return 1.0 / (1.0 + max(0, int(existing_actor_count)))


def actor_engagement_route_score(use_case_fit: dict[str, str | None]) -> float:
    evidenced = sum(bool(use_case_fit.get(name)) for name in ACTOR_USE_CASE_NAMES)
    return evidenced / len(ACTOR_USE_CASE_NAMES)


def actor_fit_score(
    sector_relevance: float,
    engagement_route: float,
    strategic_ecosystem_value: float,
    distinctiveness: float,
    *,
    config: dict[str, object],
) -> float:
    weights = actor_fit_weights(config)
    return max(
        0.0,
        min(
            1.0,
            sector_relevance * weights["sector_relevance"]
            + engagement_route * weights["engagement_route"]
            + strategic_ecosystem_value * weights["strategic_ecosystem_value"]
            + distinctiveness * weights["distinctiveness"],
        ),
    )


def _bounded_config_score(value: object, *, key: str) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"open_web_discovery.{key} must be numeric") from exc
    if not 0.0 <= score <= 1.0:
        raise RuntimeError(f"open_web_discovery.{key} must be between 0 and 1")
    return score


def _actor_candidates_with_context(
    candidates: list[dict[str, object]],
    *,
    sectors: list[dict[str, str]],
    actor_context: dict[str, object] | None,
) -> list[dict[str, object]]:
    coverage = _actor_coverage_counts(actor_context)
    candidate_hubs = _candidate_hubs(actor_context)
    sector_codes = [
        str(sector.get("code") or "").strip().upper()
        for sector in sectors
        if str(sector.get("code") or "").strip()
    ]
    contextualized: list[dict[str, object]] = []
    for candidate in candidates:
        hubs = candidate_hubs.get(str(candidate.get("url") or ""), ())
        hub_context = []
        for hub_name in hubs:
            sector_counts = []
            for sector_code in sector_codes:
                count = coverage.get((_normal_key(hub_name), sector_code))
                if count is None:
                    continue
                sector_counts.append(
                    {
                        "sector_code": sector_code,
                        "existing_actor_count": count,
                    }
                )
            hub_context.append(
                {
                    "hub_name": hub_name,
                    "sector_counts": sector_counts,
                }
            )
        candidate_payload = dict(candidate)
        candidate_payload["coverage_context"] = {"likely_hubs": hub_context}
        contextualized.append(candidate_payload)
    return contextualized


def _existing_actor_count_for_candidate(
    *,
    url: str,
    hub_matches: tuple[str, ...],
    sector_codes: tuple[str, ...],
    actor_context: dict[str, object] | None,
) -> int | None:
    coverage = _actor_coverage_counts(actor_context)
    hubs = hub_matches or _candidate_hubs(actor_context).get(url, ())
    counts = [
        coverage[(_normal_key(hub_name), sector_code.upper())]
        for hub_name in hubs
        for sector_code in sector_codes
        if (_normal_key(hub_name), sector_code.upper()) in coverage
    ]
    return min(counts) if counts else None


def _actor_coverage_counts(
    actor_context: dict[str, object] | None,
) -> dict[tuple[str, str], int]:
    if not isinstance(actor_context, dict):
        return {}
    raw = actor_context.get("coverage_counts")
    if not isinstance(raw, dict):
        return {}
    counts: dict[tuple[str, str], int] = {}
    for key, value in raw.items():
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        try:
            count = max(0, int(value))
        except (TypeError, ValueError):
            continue
        counts[(_normal_key(key[0]), str(key[1]).strip().upper())] = count
    return counts


def _candidate_hubs(
    actor_context: dict[str, object] | None,
) -> dict[str, tuple[str, ...]]:
    if not isinstance(actor_context, dict):
        return {}
    raw = actor_context.get("candidate_hubs")
    if not isinstance(raw, dict):
        return {}
    return {str(url): _clean_string_tuple(hubs) for url, hubs in raw.items()}


def _normal_key(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def has_engagement_route(decision: TriageDecision, *, floor: float) -> bool:
    score = decision.engagement_route
    return score is not None and score >= floor


def fails_all_actor_conditions(
    decision: TriageDecision,
    *,
    thresholds: dict[str, float],
) -> bool:
    scores = {
        "sector_relevance": decision.sector_relevance,
        "engagement_route": decision.engagement_route,
        "strategic_ecosystem_value": decision.strategic_ecosystem_value,
    }
    return all(
        score is not None and score < thresholds[name]
        for name, score in scores.items()
    )


def has_person_topic_evidence(decision: TriageDecision) -> bool:
    signals = decision.relevance_signals or {}
    return bool(signals.get("sector_intersection") and signals.get("topic_evidence"))


def deterministic_rejection(
    result: SearchResult,
    *,
    raw_lookup: RawDocumentLookup,
    blocklist_domains: Iterable[str],
    known_source_domains: Iterable[str],
    existing_actor_domains: Iterable[str] = (),
    non_content_paths: Iterable[str] = DEFAULT_NON_CONTENT_PATHS,
    reject_seen_raw_urls: bool = True,
) -> DeterministicReject | None:
    parsed = urlparse(result.url or "")
    if parsed.scheme not in ("http", "https") or "." not in parsed.netloc:
        return DeterministicReject("invalid URL", domain="")
    domain = normalized_domain(result.url)
    if not domain:
        return DeterministicReject("invalid URL", domain="")
    for existing in _normalized_domains(existing_actor_domains):
        if _domain_matches(domain, existing):
            return DeterministicReject("actor already in database", domain=domain)
    if reject_seen_raw_urls and raw_lookup.has_seen_raw_url(result.url):
        return DeterministicReject(
            "already in raw_document; Phase 1 does not fetch pages to recompute content hash",
            domain=domain,
        )
    for blocked in _normalized_domains(blocklist_domains):
        if _domain_matches(domain, blocked):
            return DeterministicReject(f"blocked domain: {blocked}", domain=domain)
    for known in _normalized_domains(known_source_domains):
        if _domain_matches(domain, known):
            return DeterministicReject(f"domain already covered by configured source: {known}", domain=domain)

    path = urlparse(result.url).path.lower()
    for fragment in non_content_paths:
        if str(fragment).lower() in path:
            return DeterministicReject(f"obvious non-content URL pattern: {fragment}", domain=domain)
    return None


def blocklist_domains_for_entity(entity_type: str, config: dict[str, object]) -> list[str]:
    domains = list(config.get("blocklist_domains", []) or [])
    if entity_type == "actor":
        domains.extend(ACTOR_NEWS_AND_DIRECTORY_BLOCKLIST)
        domains.extend(config.get("actor_blocklist_domains", []) or [])
    elif entity_type == "person":
        domains.extend(ACTOR_NEWS_AND_DIRECTORY_BLOCKLIST)
        domains.extend(PERSON_DIRECTORY_AND_PROFILE_BLOCKLIST)
        domains.extend(config.get("actor_blocklist_domains", []) or [])
        domains.extend(config.get("person_blocklist_domains", []) or [])
    return sorted(set(_normalized_domains(domains)))


def person_scope_rejection(
    result: SearchResult,
    *,
    held_actor_domains: Iterable[str],
    config: dict[str, object],
) -> DeterministicReject | None:
    """Admit only institution-owned or explicitly approved self-published pages."""
    domain = normalized_domain(result.url)
    allowed_domains = _normalized_domains(
        [
            *held_actor_domains,
            *(config.get("person_allowed_domains", []) or []),
        ]
    )
    if any(_domain_matches(domain, allowed) for allowed in allowed_domains):
        return None

    suffixes = tuple(
        str(value).strip().lower()
        for value in (
            config.get("person_institutional_domain_suffixes")
            or DEFAULT_PERSON_INSTITUTIONAL_SUFFIXES
        )
        if str(value).strip()
    )
    if any(domain.endswith(suffix) for suffix in suffixes):
        return None
    labels = domain.split(".")
    if len(labels) >= 3 and labels[-2] in {"ac", "edu"} and len(labels[-1]) == 2:
        return None
    return DeterministicReject(
        "not an institutional or approved self-published professional page",
        domain=domain,
    )


def load_existing_actor_domains(session) -> list[str]:
    if session is None:
        return []
    rows = (
        session.execute(
            text(
                "SELECT website FROM actor "
                "WHERE merged_into_actor_id IS NULL "
                "AND website IS NOT NULL "
                "AND btrim(website) <> '' "
                "AND (actor_type IS NULL OR lower(actor_type) <> 'aggregate')"
            )
        )
        .mappings()
        .all()
    )
    domains = [normalized_domain(str(row.get("website") or "")) for row in rows]
    return sorted({domain for domain in domains if domain})


def known_source_domains(config: dict[str, object]) -> list[str]:
    domains: list[str] = []
    sources = dict(config.get("sources", {}))
    for source in sources.values():
        if not isinstance(source, dict):
            continue
        for key in ("listing_url", "meeting_url"):
            value = str(source.get(key) or "")
            domain = normalized_domain(value)
            if domain:
                domains.append(domain)
        for key in ("seed_urls", "pagination_urls"):
            for url in source.get(key, []) or []:
                domain = normalized_domain(str(url))
                if domain:
                    domains.append(domain)
    return sorted(set(domains))


def triage_verdict(
    decision: TriageDecision,
    *,
    floor: float,
    entity_type: str | None = None,
    actor_thresholds: dict[str, float] | None = None,
) -> str:
    if is_triage_incomplete(decision):
        return "triage_incomplete"
    is_actor_decision = entity_type == "actor" or decision.engagement_signals is not None
    if is_actor_decision:
        if (
            not decision.is_entity_type
            or decision.is_own_page is False
            or decision.is_operating_org is False
            or decision.fit_score is None
        ):
            return "rejected"
        thresholds = actor_thresholds or {
            name: floor for name in ACTOR_REJECTION_CONDITION_NAMES
        }
        return "rejected" if fails_all_actor_conditions(
            decision,
            thresholds=thresholds,
        ) else "accepted"
    if not decision.accepted:
        return "rejected"
    is_person_decision = entity_type == "person" or decision.relevance_signals is not None
    if is_person_decision and not has_person_topic_evidence(decision):
        return "rejected"
    if float(decision.fit_score or 0.0) < floor:
        return "rejected"
    return "accepted"


def is_triage_incomplete(decision: TriageDecision) -> bool:
    return decision.reason.lower().startswith(TRIAGE_INCOMPLETE_REASON_PREFIX)


def normalized_domain(url: str) -> str:
    text_value = str(url or "").strip()
    if not text_value:
        return ""
    parsed = urlparse(text_value if "://" in text_value else f"https://{text_value}")
    host = (parsed.hostname or "").lower().strip(".")
    return host.removeprefix("www.")


def _normalized_domains(domains: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for value in domains:
        text = str(value or "").strip().lower()
        if not text:
            continue
        domain = normalized_domain(text) if "://" in text else text.removeprefix("www.")
        if domain:
            normalized.append(domain)
    return normalized


def _domain_matches(domain: str, listed: str) -> bool:
    return domain == listed or domain.endswith(f".{listed}")


def _coerce_score(value: object) -> float | None:
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(score, 1.0))


def _clean_decision_reason(value: object) -> str:
    reason = str(value or "").strip()
    if not reason:
        return "no reason returned"
    if _reason_is_urlish(reason):
        return "LLM returned URL instead of reasoning"
    return reason


def _reason_is_urlish(reason: str) -> bool:
    if "|||" in reason:
        return True
    compact = reason.strip()
    parsed = urlparse(compact)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return True
    if any(char.isspace() for char in compact):
        return False
    bare = urlparse(f"https://{compact}")
    host = (bare.hostname or "").lower().removeprefix("www.")
    normalized = compact.lower().removeprefix("www.")
    return bool(host and "." in host and (normalized == host or normalized.startswith(f"{host}/")))


def _candidate_items_from_payload(payload: object) -> list[object] | None:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return None

    candidates = _candidate_items_from_value(payload.get("candidates"))
    if candidates is not None:
        return candidates

    for key in ("results", "items", "decisions", "response"):
        nested = _candidate_items_from_value(payload.get(key))
        if nested is not None:
            return nested
    return None


def _candidate_items_from_value(value: object) -> list[object] | None:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return None
    for key in ("candidates", "results", "items", "decisions"):
        nested = value.get(key)
        if isinstance(nested, list):
            return nested
        if isinstance(nested, dict):
            mapped = _candidate_items_from_mapping(nested)
            if mapped is not None:
                return mapped
    return _candidate_items_from_mapping(value)


def _candidate_items_from_mapping(mapping: dict[object, object]) -> list[object] | None:
    items: list[object] = []
    for key, value in mapping.items():
        if not isinstance(value, dict):
            continue
        item = dict(value)
        item.setdefault("url", str(key))
        items.append(item)
    return items or None
