"""Candidate triage for open-web discovery."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlparse

from agents.discovery.search.models import SearchResult, TriageDecision

logger = logging.getLogger(__name__)
TRIAGE_INCOMPLETE_REASON_PREFIX = "triage incomplete:"

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
    ) -> dict[str, TriageDecision]:
        if not candidates:
            return {}
        payload = self.llm_client.extract_with_tool(
            system=(
                "Triage search results for GHUS open-web discovery. "
                "Use only the title, snippet, URL, sectors, and reference examples. "
                "Do not infer facts from pages you have not fetched."
            ),
            user=json.dumps(
                {
                    "entity_type": entity_type,
                    "sectors": sectors,
                    "reference_examples": references,
                    "candidates": [result.__dict__ for result in candidates],
                    "decision_rule": (
                        "Return exactly one decision object for every candidate URL provided. "
                        "If a candidate is hard to judge, return is_entity_type=false, "
                        "plausible_sector=false, fit_score=null, and explain the uncertainty."
                    ),
                    "actor_quality_rule": (
                        "For actors, score substance and operating-entity quality, not just topic. "
                        "Reject grouping pages, consortium listings, category pages, and bare projects."
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            tool_name="triage_open_web_candidates",
            tool_description="Return deterministic-search survivors with fit scores and reasons.",
            input_schema={
                "type": "object",
                "properties": {
                    "candidates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string"},
                                "is_entity_type": {"type": "boolean"},
                                "plausible_sector": {"type": "boolean"},
                                "fit_score": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
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
                        },
                    }
                },
                "required": ["candidates"],
                "additionalProperties": False,
            },
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
            decisions[url] = TriageDecision(
                url=url,
                is_entity_type=bool(item.get("is_entity_type")),
                plausible_sector=bool(item.get("plausible_sector")),
                fit_score=_coerce_score(item.get("fit_score")),
                reason=str(item.get("reason") or "").strip() or "no reason returned",
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


def deterministic_rejection(
    result: SearchResult,
    *,
    raw_lookup: RawDocumentLookup,
    blocklist_domains: Iterable[str],
    known_source_domains: Iterable[str],
    non_content_paths: Iterable[str] = DEFAULT_NON_CONTENT_PATHS,
) -> DeterministicReject | None:
    domain = normalized_domain(result.url)
    if not domain:
        return DeterministicReject("invalid URL", domain="")
    if raw_lookup.has_seen_raw_url(result.url):
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


def triage_verdict(decision: TriageDecision, *, floor: float) -> str:
    if is_triage_incomplete(decision):
        return "triage_incomplete"
    if not decision.accepted:
        return "rejected"
    if float(decision.fit_score or 0.0) < floor:
        return "rejected"
    return "accepted"


def is_triage_incomplete(decision: TriageDecision) -> bool:
    return decision.reason.lower().startswith(TRIAGE_INCOMPLETE_REASON_PREFIX)


def normalized_domain(url: str) -> str:
    parsed = urlparse(url)
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
