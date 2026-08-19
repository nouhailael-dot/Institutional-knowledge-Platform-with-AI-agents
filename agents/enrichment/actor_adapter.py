"""Actor-specific adapter that preserves the existing candidate pipeline."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from agents.enrichment.decisions import classify_field_candidate, record_field_proposal
from agents.enrichment.fields import FieldPolicy
from agents.enrichment.gaps import is_gap, is_present
from agents.enrichment.specs import get_entity_spec
from src.enrichment.actor_enrichment_candidates import (
    AI_CONFIDENCE,
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
            current_value = getattr(actor, field)
            outcome = classify_field_candidate(
                policy=policy,
                current_value=current_value,
                proposed_value=decision.get(field),
                source_url=source_url,
                confidence=float(decision["confidence"]),
                needs_human_review=bool(decision["needs_human_review"]),
            )
            if outcome.action == "apply":
                if not self.apply:
                    would_apply = True
                    continue
                if is_present(getattr(actor, field)):
                    self._proposal_or_warning(
                        actor,
                        field=field,
                        proposed_value=decision.get(field),
                        current_value=getattr(actor, field),
                        source_url=source_url,
                        confidence=float(decision["confidence"]),
                        reason="current value was filled before write; overwrite refused",
                    )
                    proposals += 1
                    continue
                setattr(actor, field, decision.get(field))
                changed_fields.append(field)
            elif outcome.action == "propose_below_floor":
                low_confidence_seen = True
                if self._proposal_or_warning(
                    actor,
                    field=field,
                    proposed_value=decision.get(field),
                    current_value=current_value,
                    source_url=source_url,
                    confidence=float(decision["confidence"]),
                    reason=outcome.reason,
                ):
                    proposals += 1
            elif outcome.action.startswith("propose_"):
                if self._proposal_or_warning(
                    actor,
                    field=field,
                    proposed_value=decision.get(field),
                    current_value=current_value,
                    source_url=source_url,
                    confidence=float(decision["confidence"]),
                    reason=outcome.reason,
                ):
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
            source = self._get_or_create_source(actor, decision)
            actor.source_id = source.source_id
            actor.verification_status = "ai_inferred"
            actor.confidence = AI_CONFIDENCE
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

    def _proposal_or_warning(
        self,
        actor,
        *,
        field: str,
        proposed_value: object,
        current_value: object,
        source_url: Optional[str],
        confidence: float,
        reason: str,
    ) -> bool:
        if not self.apply:
            return True
        if not self.proposal_run_id:
            logger.warning(
                "actor enrichment field proposal skipped because no proposal_run_id was provided: actor=%s field=%s",
                actor.actor_id,
                field,
            )
            return False
        if is_gap(source_url):
            logger.warning(
                "actor enrichment field proposal skipped because source_url is missing: actor=%s field=%s",
                actor.actor_id,
                field,
            )
            return False
        record_field_proposal(
            self.session,
            run_id=self.proposal_run_id,
            spec=self.actor_spec,
            entity_id=str(actor.actor_id),
            field_name=field,
            proposed_value=proposed_value,
            current_value=current_value,
            source_url=str(source_url),
            confidence=confidence,
            reason=reason,
        )
        return True
