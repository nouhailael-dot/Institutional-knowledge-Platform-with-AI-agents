"""Actor-specific adapter that preserves the existing candidate pipeline."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from agents.enrichment.decisions import apply_or_propose_field
from agents.enrichment.fields import FieldPolicy
from agents.enrichment.gaps import is_gap
from agents.enrichment.specs import get_entity_spec
from src.enrichment.actor_enrichment_candidates import (
    DEFAULT_APPLY_THRESHOLD,
    SONNET,
    ActorEnrichmentCandidatePipeline,
)

logger = logging.getLogger(__name__)

LEGACY_ACTOR_FIELDS = ("description", "website", "location_city", "state", "country")


class PolicyActorEnrichmentCandidatePipeline(ActorEnrichmentCandidatePipeline):
    """Reuse actor candidate generation, but route writes through field policy."""

    def __init__(
        self,
        project_root: Path,
        session: Session,
        *,
        field_policies: dict[str, FieldPolicy],
        proposal_run_id: Optional[str] = None,
        limit: Optional[int] = None,
        apply: bool = False,
        apply_threshold: float = DEFAULT_APPLY_THRESHOLD,
        commit_every: int = 50,
        model: str = SONNET,
        use_wikidata: bool = False,
        use_openalex: bool = True,
        openalex_sleep_seconds: float = 2.0,
        use_web_search: bool = False,
        web_search_sleep_seconds: float = 0.5,
        web_search_result_limit: int = 3,
        include_unlinked: bool = False,
        deterministic_only: bool = False,
        revisit_missing: bool = False,
        use_claude: bool = False,
        max_claude_calls: Optional[int] = 25,
        max_claude_cost: Optional[float] = 0.50,
        min_claude_candidate_score: float = 0.72,
        missing_fields: Optional[list[str]] = None,
        stop_after_claude_budget: bool = False,
    ):
        self.field_policies = field_policies
        self.proposal_run_id = proposal_run_id
        self.actor_spec = get_entity_spec("actor")
        super().__init__(
            project_root,
            session,
            limit=limit,
            apply=apply,
            apply_threshold=apply_threshold,
            commit_every=commit_every,
            model=model,
            use_wikidata=use_wikidata,
            use_openalex=use_openalex,
            openalex_sleep_seconds=openalex_sleep_seconds,
            use_web_search=use_web_search,
            web_search_sleep_seconds=web_search_sleep_seconds,
            web_search_result_limit=web_search_result_limit,
            include_unlinked=include_unlinked,
            deterministic_only=deterministic_only,
            revisit_missing=revisit_missing,
            use_claude=use_claude,
            max_claude_calls=max_claude_calls,
            max_claude_cost=max_claude_cost,
            min_claude_candidate_score=min_claude_candidate_score,
            missing_fields=missing_fields,
            stop_after_claude_budget=stop_after_claude_budget,
        )

    def _apply_decision(self, actor, decision: dict) -> str:
        if not decision["matched"]:
            self.stats.no_match += 1
            return "no_match"

        source_url = decision.get("source_url")
        selected_fields = [field for field in self.missing_fields if field in self.field_policies]
        proposed_fields = [
            field
            for field in selected_fields
            if not is_gap(decision.get(field))
        ]
        if not proposed_fields:
            return "validated_no_update"

        if decision["needs_human_review"]:
            self.stats.needs_review += 1

        changed_fields: list[str] = []
        would_apply = False
        proposals = 0
        low_confidence_seen = False
        missing_source_seen = False

        for field in proposed_fields:
            policy = self.field_policies[field]
            outcome = apply_or_propose_field(
                self.session,
                run_id=self.proposal_run_id or str(actor.actor_id),
                spec=self.actor_spec,
                policy=policy,
                entity_id=str(actor.actor_id),
                field_name=field,
                proposed_value=decision.get(field),
                source_url=source_url,
                confidence=float(decision["confidence"]),
                reason="actor enrichment candidate",
                live=self.apply,
                needs_human_review=bool(decision["needs_human_review"]),
            )
            if outcome.action == "applied":
                changed_fields.append(field)
            elif outcome.action == "would_apply":
                would_apply = True
            elif outcome.action == "proposed_below_floor":
                low_confidence_seen = True
                proposals += 1
            elif outcome.action.startswith("proposed_"):
                proposals += 1
            elif outcome.action == "would_propose_below_floor":
                low_confidence_seen = True
                proposals += 1
            elif outcome.action.startswith("would_propose_"):
                proposals += 1
            elif outcome.action == "missing_source_url":
                missing_source_seen = True
                logger.warning(
                    "actor enrichment candidate for %s has no source_url; field=%s action=missing_source_url",
                    actor.actor_id,
                    field,
                )

        if low_confidence_seen:
            self.stats.skipped_low_confidence += 1

        if changed_fields:
            self.stats.applied += 1
            return "applied"

        if would_apply:
            self.stats.would_apply += 1
            return "would_apply"

        if proposals:
            return "field_proposal" if self.apply else "would_propose"

        if missing_source_seen:
            return "missing_source_url"
        return "validated_no_update"
