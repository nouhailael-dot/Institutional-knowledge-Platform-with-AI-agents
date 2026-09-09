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
PARTNER_SIGNAL_NAMES = (
    "collaboration_surface",
    "open_programmes",
    "precedent",
    "route_in",
    "complementarity",
)
DEFAULT_ACTOR_PARTNER_FINDABILITY_FLOOR = 0.20
DEFAULT_ACTOR_FIT_WEIGHTS = {
    "partner_findability": 0.80,
    "distinctiveness": 0.20,
}
ACTOR_TRIAGE_SYSTEM_PROMPT = (
    "Evaluate actor candidates for GHUS open-web discovery, whose primary purpose is "
    "finding actionable partners for UM6P research groups. Use only the search-result "
    "title, snippet, URL, seeded sectors, public actor reference examples, and supplied "
    "deterministic coverage context. Do not infer facts from pages that have not been "
    "fetched. Evidence must come from a result published on the organisation's own site."
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
                else (
                    "Triage search results for GHUS open-web discovery. "
                    "Use only the title, snippet, URL, sectors, and reference examples. "
                    "Do not infer facts from pages you have not fetched."
                )
            ),
            user=json.dumps(user_payload, ensure_ascii=False, sort_keys=True),
            tool_name="triage_open_web_candidates",
            tool_description=(
                "Return actor identity, partner evidence, deterministic distinctiveness, "
                "fit score, and verdict."
                if entity_type == "actor"
                else "Return deterministic-search survivors with fit scores and reasons."
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
        return payload

    weights = actor_fit_weights(config)
    floor = actor_partner_findability_floor(config)
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
            "partner_findability_rule": (
                "Find collaboration evidence visible in the organisation's own result. For each "
                "named signal, return a short quote or paraphrase of the evidence, or null when "
                "the title and snippet do not establish it. Never return a boolean. The signals "
                "are: collaboration_surface (partnerships, industry collaboration, or technology "
                "transfer); open_programmes (membership, affiliate, sponsored research, visiting "
                "researcher, or open calls); precedent (existing university or research-institute "
                "partnerships, especially international); route_in (named partnerships contact, "
                "call for partners, or bookable/shared facilities); complementarity (capability, "
                "infrastructure, or market access UM6P lacks, or a stated need UM6P could meet)."
            ),
            "partner_floor_rule": (
                f"Partner-findability must be at least {floor:.2f} and have at least one evidence "
                "string to pass. Otherwise return verdict='reject' and reason='no partner route'."
            ),
            "distinctiveness_rule": (
                "Each candidate's coverage_context contains only hub/sector labels and aggregate "
                "counts. Reference existing_actor_count in the reasoning when useful. The "
                "application computes distinctiveness as 1 / (1 + existing_actor_count) and "
                "overwrites the returned distinctiveness. Do not infer it from prominence. "
                "Distinctiveness changes ranking only and must never cause rejection."
            ),
            "fit_score_rule": (
                "The application recomputes fit_score as partner_findability * "
                f"{weights['partner_findability']:.2f} + deterministic distinctiveness * "
                f"{weights['distinctiveness']:.2f}. Partner-findability dominates."
            ),
            "actor_fit_weights": weights,
            "actor_partner_findability_floor": floor,
        }
    )
    return payload


def _triage_input_schema(entity_type: str) -> dict[str, object]:
    if entity_type == "actor":
        item_schema = _actor_triage_item_schema()
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
    properties: dict[str, object] = {
        "url": {"type": "string"},
        "is_own_page": {"type": "boolean"},
        "is_operating_org": {"type": "boolean"},
        "actor_type_guess": {"type": ["string", "null"]},
        "hub_matches": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "sector_codes": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "partner_signals": {
            "type": "object",
            "properties": {name: evidence_value for name in PARTNER_SIGNAL_NAMES},
            "required": list(PARTNER_SIGNAL_NAMES),
            "additionalProperties": False,
        },
        "partner_findability": {"type": "number", "minimum": 0, "maximum": 1},
        "distinctiveness": {"type": "number", "minimum": 0, "maximum": 1},
        "fit_score": {"type": "number", "minimum": 0, "maximum": 1},
        "verdict": {"type": "string", "enum": ["accept", "reject"]},
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
    signals = _clean_partner_signals(item.get("partner_signals"))
    partner_findability = _coerce_score(item.get("partner_findability"))
    if partner_findability is None:
        partner_findability = sum(value is not None for value in signals.values()) / len(
            PARTNER_SIGNAL_NAMES
        )

    hub_matches = _clean_string_tuple(item.get("hub_matches"))
    sector_codes = tuple(value.upper() for value in _clean_string_tuple(item.get("sector_codes")))
    existing_actor_count = _existing_actor_count_for_candidate(
        url=url,
        hub_matches=hub_matches,
        sector_codes=sector_codes,
        actor_context=actor_context,
    )
    distinctiveness = actor_distinctiveness_score(existing_actor_count)
    fit_score = actor_fit_score(partner_findability, distinctiveness, config=config)

    legacy_entity_type = item.get("is_entity_type")
    is_operating_org = _coerce_optional_bool(
        item.get("is_operating_org"),
        fallback=legacy_entity_type,
    )
    is_own_page = _coerce_optional_bool(
        item.get("is_own_page"),
        fallback=legacy_entity_type,
    )
    plausible_sector = bool(
        item.get("plausible_sector") if "plausible_sector" in item else sector_codes
    )
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
        partner_signals=signals,
        partner_findability=partner_findability,
        distinctiveness=distinctiveness,
        existing_actor_count=existing_actor_count,
        verdict=str(item.get("verdict") or "").strip().lower() or None,
    )
    verdict = triage_verdict(
        decision,
        floor=0.0,
        entity_type="actor",
        partner_floor=actor_partner_findability_floor(config),
    )
    reason = decision.reason
    if verdict == "rejected" and decision.accepted and not has_partner_route(
        decision,
        floor=actor_partner_findability_floor(config),
    ):
        reason = "no partner route"
    return replace(decision, verdict=verdict, reason=reason)


def _clean_partner_signals(value: object) -> dict[str, str | None]:
    mapping = value if isinstance(value, dict) else {}
    signals: dict[str, str | None] = {}
    for name in PARTNER_SIGNAL_NAMES:
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
                "LEFT JOIN actor ON actor.actor_id = hub_actor.actor_id "
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


def actor_partner_findability_floor(config: dict[str, object]) -> float:
    return _bounded_config_score(
        config.get(
            "actor_partner_findability_floor",
            DEFAULT_ACTOR_PARTNER_FINDABILITY_FLOOR,
        ),
        key="actor_partner_findability_floor",
    )


def actor_fit_weights(config: dict[str, object]) -> dict[str, float]:
    configured = dict(config.get("actor_fit_weights", {}) or {})
    try:
        partner_weight = float(
            configured.get(
                "partner_findability",
                DEFAULT_ACTOR_FIT_WEIGHTS["partner_findability"],
            )
        )
        distinctiveness_weight = float(
            configured.get(
                "distinctiveness",
                DEFAULT_ACTOR_FIT_WEIGHTS["distinctiveness"],
            )
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError("open_web_discovery.actor_fit_weights must be numeric") from exc
    if partner_weight < 0 or distinctiveness_weight < 0:
        raise RuntimeError("open_web_discovery.actor_fit_weights must be non-negative")
    total = partner_weight + distinctiveness_weight
    if total <= 0:
        raise RuntimeError("open_web_discovery.actor_fit_weights must have a positive total")
    return {
        "partner_findability": partner_weight / total,
        "distinctiveness": distinctiveness_weight / total,
    }


def actor_distinctiveness_score(existing_actor_count: int | None) -> float:
    if existing_actor_count is None:
        return 0.0
    return 1.0 / (1.0 + max(0, int(existing_actor_count)))


def actor_fit_score(
    partner_findability: float,
    distinctiveness: float,
    *,
    config: dict[str, object],
) -> float:
    weights = actor_fit_weights(config)
    return max(
        0.0,
        min(
            1.0,
            partner_findability * weights["partner_findability"]
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


def has_partner_route(decision: TriageDecision, *, floor: float) -> bool:
    signals = decision.partner_signals or {}
    has_evidence = any(bool(value) for value in signals.values())
    score = decision.partner_findability
    return has_evidence and score is not None and score >= floor


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
    return sorted(set(_normalized_domains(domains)))


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
    partner_floor: float | None = None,
) -> str:
    if is_triage_incomplete(decision):
        return "triage_incomplete"
    if not decision.accepted:
        return "rejected"
    is_actor_decision = entity_type == "actor" or decision.partner_signals is not None
    if is_actor_decision:
        required_partner_score = floor if partner_floor is None else partner_floor
        return (
            "accepted"
            if has_partner_route(decision, floor=required_partner_score)
            else "rejected"
        )
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
