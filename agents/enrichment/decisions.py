"""Apply/proposal decisions for field-level enrichment."""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from agents.common.provenance import insert_field_proposal, insert_source
from agents.enrichment.fields import FieldPolicy
from agents.enrichment.gaps import is_gap, is_present, sql_gap_condition
from agents.enrichment.specs import EntitySpec

logger = logging.getLogger(__name__)

AI_CONFIDENCE = 0.70
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True)
class FieldOutcome:
    action: str
    reason: str
    proposal_id: Optional[str] = None
    source_id: Optional[str] = None


def classify_field_candidate(
    *,
    policy: FieldPolicy,
    current_value: object,
    proposed_value: object,
    source_url: Optional[str],
    confidence: float,
    needs_human_review: bool = False,
) -> FieldOutcome:
    if is_gap(proposed_value):
        return FieldOutcome("no_candidate_value", "candidate did not provide a usable value")
    if not source_url or is_gap(source_url):
        return FieldOutcome("missing_source_url", "candidate has no source_url; proposal/write refused")
    if is_present(current_value):
        return FieldOutcome("propose_existing_value", "current value is non-empty; overwrite refused")
    if needs_human_review:
        return FieldOutcome("propose_human_review", "candidate requested human review")
    if policy.auto_apply_floor is None:
        return FieldOutcome("propose_no_floor", "field has no auto-apply floor")
    if confidence < policy.auto_apply_floor:
        return FieldOutcome(
            "propose_below_floor",
            f"confidence {confidence:.4f} below auto-apply floor {policy.auto_apply_floor:.4f}",
        )
    return FieldOutcome("apply", "confidence meets field auto-apply floor")


def apply_or_propose_field(
    session,
    *,
    run_id: str,
    spec: EntitySpec,
    policy: FieldPolicy,
    entity_id: str,
    field_name: str,
    proposed_value: object,
    source_url: Optional[str],
    confidence: float,
    reason: str,
    live: bool,
    needs_human_review: bool = False,
) -> FieldOutcome:
    _assert_identifier(spec.table_name)
    _assert_identifier(spec.id_column)
    _assert_identifier(field_name)
    if field_name not in spec.fields:
        raise ValueError(f"{field_name!r} is not a column in {spec.entity_type}")
    if not policy.enrichable:
        raise ValueError(f"{spec.entity_type}.{field_name} is not enrichable")

    current_value = _select_current_value(session, spec, entity_id, field_name, for_update=live)
    outcome = classify_field_candidate(
        policy=policy,
        current_value=current_value,
        proposed_value=proposed_value,
        source_url=source_url,
        confidence=confidence,
        needs_human_review=needs_human_review,
    )

    if outcome.action == "apply":
        if not live:
            return FieldOutcome("would_apply", outcome.reason)
        # This is the explicit last-moment guard: if another process filled the
        # gap after candidate selection, the canonical update becomes a proposal.
        latest_value = _select_current_value(session, spec, entity_id, field_name, for_update=True)
        if is_present(latest_value):
            return _write_proposal(
                session,
                run_id=run_id,
                spec=spec,
                entity_id=entity_id,
                field_name=field_name,
                proposed_value=proposed_value,
                current_value=latest_value,
                source_url=str(source_url),
                confidence=confidence,
                reason="current value was filled before write; overwrite refused",
                live=live,
                action="proposed_existing_value",
            )
        source_id = insert_source(
            session,
            source_url=str(source_url),
            fetched_at=datetime.now(timezone.utc),
            description=f"Agent enrichment for {spec.entity_type}.{field_name}",
            source_type="agent_enrichment",
            trust_tier="candidate",
        )
        _update_canonical_gap(
            session,
            spec=spec,
            entity_id=entity_id,
            field_name=field_name,
            proposed_value=proposed_value,
            source_id=source_id,
        )
        return FieldOutcome("applied", outcome.reason, source_id=source_id)

    if outcome.action.startswith("propose_"):
        if not live:
            return FieldOutcome("would_" + outcome.action, outcome.reason)
        return _write_proposal(
            session,
            run_id=run_id,
            spec=spec,
            entity_id=entity_id,
            field_name=field_name,
            proposed_value=proposed_value,
            current_value=current_value,
            source_url=str(source_url),
            confidence=confidence,
            reason=reason or outcome.reason,
            live=live,
            action=outcome.action.replace("propose_", "proposed_"),
        )

    if outcome.action == "missing_source_url":
        logger.warning(
            "refused %s.%s enrichment for %s because source_url is missing",
            spec.entity_type,
            field_name,
            entity_id,
        )
    return outcome


def record_field_proposal(
    session,
    *,
    run_id: str,
    spec: EntitySpec,
    entity_id: str,
    field_name: str,
    proposed_value: object,
    current_value: object,
    source_url: str,
    confidence: Optional[float],
    reason: str,
) -> str:
    if is_gap(source_url):
        raise ValueError("field_proposal.source_url must be non-null")
    staged_record_id = _insert_enrichment_staged_record(
        session,
        run_id=run_id,
        spec=spec,
        entity_id=entity_id,
        field_name=field_name,
        proposed_value=proposed_value,
        current_value=current_value,
        source_url=source_url,
        confidence=confidence,
        reason=reason,
    )
    return insert_field_proposal(
        session,
        run_id=run_id,
        staged_record_id=staged_record_id,
        entity_type=spec.entity_type,
        entity_id=entity_id,
        field_name=field_name,
        proposed_value=proposed_value,
        current_value=current_value,
        source_url=source_url,
        confidence=confidence,
        reason=reason,
    )


def _write_proposal(
    session,
    *,
    run_id: str,
    spec: EntitySpec,
    entity_id: str,
    field_name: str,
    proposed_value: object,
    current_value: object,
    source_url: str,
    confidence: Optional[float],
    reason: str,
    live: bool,
    action: str,
) -> FieldOutcome:
    if not live:
        return FieldOutcome("would_" + action, reason)
    proposal_id = record_field_proposal(
        session,
        run_id=run_id,
        spec=spec,
        entity_id=entity_id,
        field_name=field_name,
        proposed_value=proposed_value,
        current_value=current_value,
        source_url=source_url,
        confidence=confidence,
        reason=reason,
    )
    return FieldOutcome(action, reason, proposal_id=proposal_id)


def _select_current_value(session, spec: EntitySpec, entity_id: str, field_name: str, *, for_update: bool):
    suffix = " FOR UPDATE" if for_update else ""
    row = session.execute(
        text(
            f"SELECT {field_name} AS current_value "
            f"FROM {spec.table_name} "
            f"WHERE {spec.id_column} = CAST(:entity_id AS uuid)"
            f"{suffix}"
        ),
        {"entity_id": entity_id},
    ).mappings().first()
    if row is None:
        raise RuntimeError(f"{spec.entity_type} {entity_id} does not exist")
    return row["current_value"]


def _update_canonical_gap(
    session,
    *,
    spec: EntitySpec,
    entity_id: str,
    field_name: str,
    proposed_value: object,
    source_id: str,
) -> None:
    set_clauses = [f"{field_name} = :value"]
    params: dict[str, object] = {
        "entity_id": entity_id,
        "value": proposed_value,
        "source_id": source_id,
        "confidence": AI_CONFIDENCE,
    }
    if spec.source_id_column:
        _assert_identifier(spec.source_id_column)
        set_clauses.append(f"{spec.source_id_column} = CAST(:source_id AS uuid)")
    if spec.verification_status_column:
        _assert_identifier(spec.verification_status_column)
        set_clauses.append(f"{spec.verification_status_column} = 'ai_inferred'")
    if spec.confidence_column:
        _assert_identifier(spec.confidence_column)
        set_clauses.append(f"{spec.confidence_column} = :confidence")
    if spec.updated_at_column:
        _assert_identifier(spec.updated_at_column)
        set_clauses.append(f"{spec.updated_at_column} = now()")

    result = session.execute(
        text(
            f"UPDATE {spec.table_name} "
            f"SET {', '.join(set_clauses)} "
            f"WHERE {spec.id_column} = CAST(:entity_id AS uuid) "
            f"AND ({sql_gap_condition(field_name)})"
        ),
        params,
    )
    if getattr(result, "rowcount", 1) != 1:
        raise RuntimeError(
            f"refused to update {spec.entity_type}.{field_name}: gap guard matched zero rows"
        )


def _insert_enrichment_staged_record(
    session,
    *,
    run_id: str,
    spec: EntitySpec,
    entity_id: str,
    field_name: str,
    proposed_value: object,
    current_value: object,
    source_url: str,
    confidence: Optional[float],
    reason: str,
) -> str:
    staged_record_id = str(uuid.uuid4())
    natural_key = f"enrichment:{spec.entity_type}:{entity_id}:{field_name}"
    payload = {
        "entity_id": entity_id,
        "field_name": field_name,
        "proposed_value": proposed_value,
        "current_value": current_value,
        "source_url": source_url,
        "confidence": confidence,
        "reason": reason,
    }
    row = session.execute(
        text(
            "INSERT INTO staged_record (staged_record_id, run_id, raw_document_id, "
            "entity_type, natural_key, source_url, prompt_version, extracted_at, "
            "payload, normalized_payload, status, target_entity_id) "
            "VALUES (CAST(:staged_record_id AS uuid), CAST(:run_id AS uuid), NULL, "
            ":entity_type, :natural_key, :source_url, :prompt_version, :extracted_at, "
            "CAST(:payload AS jsonb), CAST(:payload AS jsonb), 'proposed', "
            "CAST(:entity_id AS uuid)) "
            "ON CONFLICT (run_id, entity_type, natural_key) DO UPDATE SET "
            "source_url = EXCLUDED.source_url, payload = EXCLUDED.payload, "
            "normalized_payload = EXCLUDED.normalized_payload, updated_at = now() "
            "RETURNING staged_record_id::text"
        ),
        {
            "staged_record_id": staged_record_id,
            "run_id": run_id,
            "entity_type": spec.entity_type,
            "natural_key": natural_key,
            "source_url": source_url,
            "prompt_version": "enrichment_v1",
            "extracted_at": datetime.now(timezone.utc),
            "payload": json.dumps(payload, sort_keys=True, default=str),
            "entity_id": entity_id,
        },
    ).scalar_one()
    return str(row)


def _assert_identifier(value: str) -> None:
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
