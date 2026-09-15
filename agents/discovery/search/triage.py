"""Candidate triage for open-web discovery."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import text

from agents.discovery.search.models import SearchResult, TriageDecision

logger = logging.getLogger(__name__)
TRIAGE_INCOMPLETE_REASON_PREFIX = "triage incomplete:"
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
PERSON_RELEVANCE_SIGNAL_NAMES = (
    "sector_intersection",
    "hub_or_held_affiliation",
    "actionable_role",
    "topic_evidence",
)
ACTOR_TRIAGE_SYSTEM_PROMPT = (
    "Apply a recall-oriented binary fetch gate to actor search results. Decide only whether "
    "the URL is plausibly an organisation's own substantive page worth fetching. A thin "
    "snippet is expected and is not grounds for rejection. Return only fetch and a one-line "
    "reason for every URL. Do not score, rank, infer page facts, or decide entity identity."
)
EVENT_TRIAGE_SYSTEM_PROMPT = (
    "Apply a recall-oriented binary fetch gate to event search results. Decide only whether "
    "the URL is plausibly the page of one real event worth fetching. A thin snippet, homepage, "
    "or missing date is not grounds for rejection. Reject clear aggregators, directories, news "
    "coverage, and non-event pages. Return only fetch and a one-line reason for every URL."
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
    "minesnewsroom.com",
)
ACTOR_NEWS_HOST_PREFIXES = ("newsroom.", "news.", "press.")
ACTOR_NEWS_PATH_FRAGMENTS = (
    "/news/",
    "/press/",
    "/newsroom/",
    "/announcements/",
    "/blog/",
    "/media/",
)
PERSON_DIRECTORY_AND_PROFILE_BLOCKLIST = (
    "academia.edu",
    "crunchbase.com",
    "google.com",
    "linkedin.com",
    "researchgate.net",
    "rocketreach.co",
    "zoominfo.com",
    "wikipedia.org",
    "researchgate.net",
    "semanticscholar.org",
    "orcid.org",
    "scholar.google.com",
    "muckrack.com",
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
                else EVENT_TRIAGE_SYSTEM_PROMPT
                if entity_type == "event"
                else PERSON_TRIAGE_SYSTEM_PROMPT
                if entity_type == "person"
                else (
                    "Triage search results for GHUS open-web discovery. "
                    "Use only the title, snippet, URL, sectors, and reference examples. "
                    "Do not infer facts from pages you have not fetched."
                )
            ),
            # Split so the stable prefix (sectors, references, rules) is cached and
            # only the candidate list varies. json.dumps(sort_keys=True) previously
            # put "candidates" ahead of "reference_examples" and "sectors", which
            # placed the varying content first and defeated prefix caching entirely.
            cached_user=json.dumps(
                {k: v for k, v in user_payload.items() if k != "candidates"},
                ensure_ascii=False,
                sort_keys=True,
            ),
            user=json.dumps(
                {"candidates": user_payload.get("candidates", [])},
                ensure_ascii=False,
                sort_keys=True,
            ),
            tool_name="triage_open_web_candidates",
            tool_description=(
                "Return one binary fetch decision and one-line reason for every URL."
                if entity_type in {"actor", "event"}
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
            if entity_type in {"actor", "event"}:
                decisions[url] = _gate_decision_from_item(
                    item, url=url, entity_type=entity_type
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
    if entity_type == "actor":
        return {
            "entity_type": "actor",
            "candidates": candidates,
            "decision_rule": (
                "Return exactly one object for every candidate URL. Set fetch=true when this "
                "could plausibly be an organisation's own substantive page. Bias toward recall: "
                "snippets are incomplete and the fetched page performs the real assessment. Set "
                "fetch=false only when the result itself clearly shows a third-party, news, "
                "directory, category, consortium-listing, or non-organisation page. Return no "
                "score and no other fields."
            ),
        }
    if entity_type == "event":
        return {
            "entity_type": "event",
            "candidates": candidates,
            "decision_rule": (
                "Return exactly one object for every candidate URL. Set fetch=true when the "
                "result could plausibly lead to one real event page. Bias toward recall. A thin "
                "snippet, homepage, or missing date is never a rejection reason. Set fetch=false "
                "only for clear event aggregators or directories, news coverage about an event, "
                "or pages clearly unrelated to a discrete event. Return no score or other fields."
            ),
        }
    payload: dict[str, object] = {
        "entity_type": entity_type,
        "sectors": sectors,
        "reference_examples": references,
        "candidates": candidates,
        "decision_rule": (
            "Return exactly one decision object for every candidate URL provided. "
            "If a candidate is hard to judge, reject it and explain the uncertainty."
        ),
    }
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


def _triage_input_schema(entity_type: str) -> dict[str, object]:
    if entity_type in {"actor", "event"}:
        item_schema = _gate_item_schema()
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


def _gate_item_schema() -> dict[str, object]:
    properties = {
        "url": {"type": "string"},
        "fetch": {"type": "boolean"},
        "reason": {"type": "string", "minLength": 1, "maxLength": 300},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _gate_decision_from_item(
    item: dict[str, object], *, url: str, entity_type: str
) -> TriageDecision:
    fetch = item.get("fetch")
    if not isinstance(fetch, bool):
        raise TriageResponseError(f"{entity_type} gate fetch must be boolean")
    return TriageDecision(
        url=url,
        is_entity_type=fetch,
        plausible_sector=fetch,
        fit_score=None,
        reason=_clean_decision_reason(item.get("reason")),
        verdict="accepted" if fetch else "rejected",
    )


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


def existing_actor_count_for_candidate(
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
    entity_type: str | None = None,
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
    if entity_type == "actor" and _is_actor_news_or_press_page(
        domain=domain,
        path=parsed.path,
    ):
        return DeterministicReject("news or press page on own domain", domain=domain)
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
) -> str:
    if is_triage_incomplete(decision):
        return "triage_incomplete"
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


def registrable_domain(url_or_domain: str) -> str:
    domain = normalized_domain(url_or_domain)
    labels = domain.split(".")
    if len(labels) <= 2:
        return domain
    if len(labels[-1]) == 2 and labels[-2] in {
        "ac",
        "co",
        "com",
        "edu",
        "gov",
        "net",
        "org",
    }:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _is_actor_news_or_press_page(*, domain: str, path: str) -> bool:
    lowered_path = str(path or "").casefold()
    return domain.startswith(ACTOR_NEWS_HOST_PREFIXES) or any(
        fragment in lowered_path for fragment in ACTOR_NEWS_PATH_FRAGMENTS
    )


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
