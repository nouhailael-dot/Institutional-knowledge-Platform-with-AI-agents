"""Shared deterministic rubric scoring and bounded listwise reranking."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path

from agents.discovery.search.models import CandidateRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WeightedScore:
    total: float
    contributions: dict[str, float]


def evidence_item_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "present": {"type": "boolean"},
            "evidence": {"type": ["string", "null"], "maxLength": 500},
        },
        "required": ["present", "evidence"],
    }


def validate_evidence_item(value: object, *, entity_type: str, name: str) -> None:
    if not isinstance(value, dict) or set(value) != {"present", "evidence"}:
        raise RuntimeError(
            f"{entity_type} rubric item {name!r} must contain present and evidence"
        )
    present = value.get("present")
    evidence = value.get("evidence")
    if not isinstance(present, bool):
        raise TypeError(f"{entity_type} rubric item {name!r} present must be boolean")
    if evidence is not None and (
        not isinstance(evidence, str) or not evidence.strip()
    ):
        raise RuntimeError(
            f"{entity_type} rubric item {name!r} evidence must be text or null"
        )
    if present and evidence is None:
        raise RuntimeError(
            f"{entity_type} rubric item {name!r} needs evidence when present is true"
        )
    if not present and evidence is not None:
        raise RuntimeError(
            f"{entity_type} rubric item {name!r} must use null evidence when absent"
        )


def configured_weights(
    config: dict[str, object],
    *,
    entity_type: str,
    component_names: tuple[str, ...],
    defaults: dict[str, float],
) -> dict[str, float]:
    key = f"{entity_type}_rubric_weights"
    configured = dict(config.get(key, {}) or {})
    unknown = set(configured) - set(component_names)
    if unknown:
        raise RuntimeError(f"unknown {entity_type} rubric weight(s): {sorted(unknown)}")
    try:
        weights = {
            name: float(configured.get(name, defaults[name])) for name in component_names
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"open_web_discovery.{key} must be numeric and complete") from exc
    if any(value < 0 for value in weights.values()):
        raise RuntimeError(f"open_web_discovery.{key} must be non-negative")
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise RuntimeError(f"open_web_discovery.{key} must sum to 1.0")
    return weights


def weighted_score(
    values: dict[str, float],
    *,
    weights: dict[str, float],
) -> WeightedScore:
    if set(values) != set(weights):
        raise RuntimeError("rubric score values and configured weights do not match")
    if any(not 0.0 <= float(value) <= 1.0 for value in values.values()):
        raise RuntimeError("rubric score component values must be between 0 and 1")
    contributions = {
        name: round(float(values[name]) * weights[name], 6) for name in weights
    }
    return WeightedScore(
        total=round(sum(contributions.values()), 6),
        contributions=contributions,
    )


def score_thresholds(
    config: dict[str, object],
    *,
    entity_type: str,
    default_low: float,
    default_high: float,
) -> tuple[float, float]:
    values = dict(config.get(f"{entity_type}_score_thresholds", {}) or {})
    try:
        auto_low = float(values.get("auto_low", default_low))
        auto_high = float(values.get("auto_high", default_high))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{entity_type} score thresholds must be numeric") from exc
    if not 0.0 <= auto_low < auto_high <= 1.0:
        raise RuntimeError(
            f"{entity_type} score thresholds require 0 <= auto_low < auto_high <= 1"
        )
    return auto_low, auto_high


def score_band(
    score: float,
    config: dict[str, object],
    *,
    entity_type: str,
    default_low: float,
    default_high: float,
) -> str:
    auto_low, auto_high = score_thresholds(
        config,
        entity_type=entity_type,
        default_low=default_low,
        default_high=default_high,
    )
    if score >= auto_high:
        return "auto_high"
    if score < auto_low:
        return "auto_low"
    return "review"


class ListwiseReranker:
    def __init__(
        self,
        llm_client,
        *,
        entity_type: str,
        objective: str,
        max_tokens: int = 2048,
    ):
        self.llm_client = llm_client
        self.entity_type = entity_type
        self.objective = objective
        self.max_tokens = max_tokens

    def rerank_group(self, candidates: list[CandidateRecord]) -> list[tuple[str, str]]:
        if not candidates:
            return []
        payload = self.llm_client.extract_with_tool(
            system=(
                f"Order {self.entity_type} candidates from best to worst for {self.objective}. "
                "Use only the supplied rubric evidence and record preview. Do not rescore them."
            ),
            user=json.dumps(
                {
                    "candidates": [
                        {
                            "url": candidate.url,
                            "record": candidate.record_preview,
                            "rubric": candidate.rubric,
                            "rubric_score": candidate.fit_score,
                        }
                        for candidate in candidates
                    ]
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            tool_name=f"rank_{self.entity_type}_candidates",
            tool_description=(
                "Return every supplied URL once, ordered best to worst, with a rationale."
            ),
            input_schema=_rerank_schema(),
            max_tokens=self.max_tokens,
        )
        ordered = payload.get("candidates") if isinstance(payload, dict) else None
        if not isinstance(ordered, list):
            raise TypeError(
                f"{self.entity_type} listwise rerank returned a non-list candidates value"
            )
        expected = {candidate.url for candidate in candidates}
        result: list[tuple[str, str]] = []
        seen: set[str] = set()
        for item in ordered:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            rationale = str(item.get("rationale") or "").strip()
            if url in expected and url not in seen and rationale:
                result.append((url, rationale))
                seen.add(url)
        if seen != expected:
            raise RuntimeError(
                f"{self.entity_type} listwise rerank did not return every candidate exactly once"
            )
        return result


def rerank_top_candidates(
    candidates: list[CandidateRecord],
    *,
    reranker,
    config: dict[str, object],
    entity_type: str,
) -> tuple[list[CandidateRecord], list[str]]:
    top_n = _positive_int(
        config.get(f"{entity_type}_rerank_top_n", 40),
        f"{entity_type}_rerank_top_n",
    )
    group_size = _positive_int(
        config.get(f"{entity_type}_rerank_group_size", 10),
        f"{entity_type}_rerank_group_size",
    )
    if group_size > 10:
        raise RuntimeError(
            f"open_web_discovery.{entity_type}_rerank_group_size cannot exceed 10"
        )
    scored = sorted(
        [candidate for candidate in candidates if candidate.fit_score is not None],
        key=lambda candidate: (-float(candidate.fit_score or 0.0), candidate.url),
    )
    updates: dict[str, tuple[int, str]] = {}
    attention: list[str] = []
    position = 1
    for start in range(0, min(len(scored), top_n), group_size):
        group = scored[start : min(start + group_size, top_n)]
        try:
            order = reranker.rerank_group(group)
        except Exception as exc:  # noqa: BLE001 - preserve deterministic order and report it.
            logger.warning("%s listwise rerank group failed: %s", entity_type, exc)
            attention.append(
                f"{entity_type} rerank failed for group starting {start + 1}: {exc}"
            )
            order = [
                (candidate.url, "deterministic rubric order retained after rerank failure")
                for candidate in group
            ]
        for url, rationale in order:
            updates[url] = (position, rationale)
            position += 1
    return [
        replace(
            candidate,
            rerank_position=updates[candidate.url][0],
            rerank_reason=updates[candidate.url][1],
        )
        if candidate.url in updates
        else candidate
        for candidate in candidates
    ], attention


def write_cached_analysis(
    path: Path,
    *,
    prompt_version: str,
    rubric: dict[str, object],
    record: dict[str, object],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"prompt_version": prompt_version, "rubric": rubric, "record": record},
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def read_cached_analysis(path: Path, *, prompt_version: str) -> dict[str, object] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("prompt_version") != prompt_version:
        return None
    return payload


def _rerank_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "url": {"type": "string"},
                        "rationale": {"type": "string", "minLength": 1, "maxLength": 300},
                    },
                    "required": ["url", "rationale"],
                },
            }
        },
        "required": ["candidates"],
    }


def _positive_int(value: object, key: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"open_web_discovery.{key} must be an integer") from exc
    if result <= 0:
        raise RuntimeError(f"open_web_discovery.{key} must be positive")
    return result
