"""Provenance write helpers for agent-promoted facts."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text


def insert_source(
    session,
    *,
    source_url: str,
    fetched_at: Optional[str | datetime],
    description: str,
    source_type: str = "agent_discovery",
    trust_tier: str = "web",
) -> str:
    """Insert a source row and return its UUID as a string."""
    source_id = str(uuid.uuid4())
    retrieved_at = _coerce_datetime(fetched_at) or datetime.now(timezone.utc)
    session.execute(
        text(
            "INSERT INTO source (source_id, source_type, url, retrieved_at, "
            "description, trust_tier) VALUES (CAST(:source_id AS uuid), "
            ":source_type, :url, :retrieved_at, :description, :trust_tier)"
        ),
        {
            "source_id": source_id,
            "source_type": source_type,
            "url": source_url,
            "retrieved_at": retrieved_at,
            "description": description,
            "trust_tier": trust_tier,
        },
    )
    return source_id


def insert_field_proposal(
    session,
    *,
    run_id: str,
    staged_record_id: str,
    entity_type: str,
    entity_id: Optional[str],
    field_name: str,
    proposed_value: object,
    current_value: object,
    source_url: str,
    confidence: Optional[float],
    reason: str,
) -> str:
    proposal_id = str(uuid.uuid4())
    session.execute(
        text(
            "INSERT INTO field_proposal (proposal_id, run_id, staged_record_id, "
            "entity_type, entity_id, field_name, proposed_value, current_value, "
            "source_url, confidence, reason, status) VALUES (CAST(:proposal_id AS uuid), "
            "CAST(:run_id AS uuid), CAST(:staged_record_id AS uuid), :entity_type, "
            "CAST(:entity_id AS uuid), :field_name, :proposed_value, :current_value, "
            ":source_url, :confidence, :reason, 'pending')"
        ),
        {
            "proposal_id": proposal_id,
            "run_id": run_id,
            "staged_record_id": staged_record_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "field_name": field_name,
            "proposed_value": _string_or_none(proposed_value),
            "current_value": _string_or_none(current_value),
            "source_url": source_url,
            "confidence": confidence,
            "reason": reason,
        },
    )
    return proposal_id


def _coerce_datetime(value: Optional[str | datetime]) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _string_or_none(value: object) -> Optional[str]:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None
