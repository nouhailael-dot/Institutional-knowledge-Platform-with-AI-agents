"""Stable Architecture V2 fact-write contract shared by Light and Deep Pull."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

COLLECTION_STATES = frozenset({"found", "not_found", "not_yet_collected"})
CONFIDENCE_LEVELS = frozenset({"high", "medium", "low"})
SOURCE_ORIGINS = frozenset({"imported", "newly_found", "uploaded_document", "ghus_manual"})


@dataclass(frozen=True)
class ActorFactWrite:
    actor_id: str
    topic_id: str
    field_key: str
    fact_type: str
    layer: int
    value: Any
    collection_state: str
    source_url: str
    source_origin: str
    date_read: datetime
    confidence: str
    created_by: str
    request_id: str | None = None


def _uuid(value: Any, field: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be a UUID") from exc


def validate_actor_fact(write: ActorFactWrite) -> ActorFactWrite:
    if not str(write.field_key or "").strip():
        raise ValueError("field_key is required")
    if not str(write.fact_type or "").strip():
        raise ValueError("fact_type is required")
    if write.layer not in {1, 2, 3}:
        raise ValueError("layer must be 1, 2, or 3")
    if write.collection_state not in COLLECTION_STATES:
        raise ValueError("invalid collection_state")
    if write.collection_state == "found" and write.value is None:
        raise ValueError("found facts require a value")
    if write.collection_state != "found" and write.value is not None:
        raise ValueError("non-found facts must have a null value")
    parsed = urlsplit(str(write.source_url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("source_url must be an absolute HTTP(S) URL")
    if write.source_origin not in SOURCE_ORIGINS:
        raise ValueError("invalid source_origin")
    if write.confidence not in CONFIDENCE_LEVELS:
        raise ValueError("invalid confidence")
    if not isinstance(write.date_read, datetime) or write.date_read.tzinfo is None:
        raise ValueError("date_read must be timezone-aware")
    if not str(write.created_by or "").strip():
        raise ValueError("created_by is required")
    return ActorFactWrite(
        actor_id=_uuid(write.actor_id, "actor_id"),
        topic_id=_uuid(write.topic_id, "topic_id"),
        field_key=str(write.field_key).strip(),
        fact_type=str(write.fact_type).strip(),
        layer=write.layer,
        value=write.value,
        collection_state=write.collection_state,
        source_url=str(write.source_url).strip(),
        source_origin=write.source_origin,
        date_read=write.date_read,
        confidence=write.confidence,
        created_by=str(write.created_by).strip(),
        request_id=_uuid(write.request_id, "request_id") if write.request_id else None,
    )
