"""Staging writes for discovery records."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import text

SECTOR_MATCH_VALUES = {"in_sector", "out_of_sector"}


@dataclass
class StagedRecord:
    run_id: str
    entity_type: str
    natural_key: str
    source_url: str
    payload: dict[str, object]
    normalized_payload: dict[str, object]
    prompt_version: str
    extracted_at: str
    raw_document_id: Optional[str] = None
    staged_record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sector_codes: list[str] = field(default_factory=list)
    sector_match: str = "in_sector"
    route: Optional[dict[str, object]] = None
    status: str = "staged"
    target_entity_id: Optional[str] = None


class InMemoryStageStore:
    def __init__(self):
        self.rows: dict[tuple[str, str, str], StagedRecord] = {}

    def upsert(self, record: StagedRecord) -> StagedRecord:
        key = (record.run_id, record.entity_type, record.natural_key)
        existing = self.rows.get(key)
        if existing:
            record.staged_record_id = existing.staged_record_id
        self.rows[key] = record
        return record

    def row_count(self) -> int:
        return len(self.rows)


class SQLStageStore:
    def __init__(self, session):
        self.session = session

    def upsert(self, record: StagedRecord) -> StagedRecord:
        row_id = self.session.execute(
            text(
                "INSERT INTO staged_record (staged_record_id, run_id, raw_document_id, "
                "entity_type, natural_key, source_url, prompt_version, extracted_at, "
                "payload, normalized_payload, sector_codes, sector_match, route, status, target_entity_id) "
                "VALUES (CAST(:staged_record_id AS uuid), CAST(:run_id AS uuid), "
                "CAST(:raw_document_id AS uuid), :entity_type, :natural_key, :source_url, "
                ":prompt_version, :extracted_at, CAST(:payload AS jsonb), "
                "CAST(:normalized_payload AS jsonb), :sector_codes, :sector_match, "
                "CAST(:route AS jsonb), :status, CAST(:target_entity_id AS uuid)) "
                "ON CONFLICT (run_id, entity_type, natural_key) DO UPDATE SET "
                "raw_document_id = EXCLUDED.raw_document_id, source_url = EXCLUDED.source_url, "
                "prompt_version = EXCLUDED.prompt_version, extracted_at = EXCLUDED.extracted_at, "
                "payload = EXCLUDED.payload, normalized_payload = EXCLUDED.normalized_payload, "
                "sector_codes = EXCLUDED.sector_codes, sector_match = EXCLUDED.sector_match, route = EXCLUDED.route, "
                "status = EXCLUDED.status, target_entity_id = EXCLUDED.target_entity_id, "
                "updated_at = now() RETURNING staged_record_id::text"
            ),
            _params(record),
        ).scalar_one()
        self.session.commit()
        record.staged_record_id = str(row_id)
        return record


def stage_record(
    store,
    *,
    run_id: str,
    raw_document_id: Optional[str],
    entity_type: str,
    record: dict[str, object],
    prompt_version: str,
) -> StagedRecord:
    natural_key = str(record.get("natural_key") or "").strip()
    if not natural_key:
        raise ValueError("cannot stage record without natural_key")
    source_url = str(record.get("source_url") or "").strip()
    extracted_at = str(record.get("extracted_at") or "").strip()
    sector_match = _sector_match(record.get("sector_match"))
    staged = StagedRecord(
        run_id=run_id,
        raw_document_id=raw_document_id,
        entity_type=entity_type,
        natural_key=natural_key,
        source_url=source_url,
        payload=record.copy(),
        normalized_payload=record.copy(),
        prompt_version=prompt_version,
        extracted_at=extracted_at,
        sector_codes=[str(code) for code in record.get("sector_codes", [])],
        sector_match=sector_match,
        status="staged",
    )
    return store.upsert(staged)


def mark_routed(store, staged: StagedRecord, route) -> StagedRecord:
    if staged.sector_match == "out_of_sector":
        raise RuntimeError("out_of_sector staged records must not be routed or promoted")
    staged.route = {
        "zone": route.zone,
        "score": route.score,
        "target_entity_id": route.target_entity_id,
        "candidate_ids": route.candidate_ids,
        "metadata": getattr(route, "metadata", {}),
    }
    staged.status = f"routed_{route.zone}"
    staged.target_entity_id = route.target_entity_id
    return store.upsert(staged)


def _params(record: StagedRecord) -> dict[str, object]:
    return {
        "staged_record_id": record.staged_record_id,
        "run_id": record.run_id,
        "raw_document_id": record.raw_document_id,
        "entity_type": record.entity_type,
        "natural_key": record.natural_key,
        "source_url": record.source_url,
        "prompt_version": record.prompt_version,
        "extracted_at": record.extracted_at,
        "payload": json.dumps(record.payload, sort_keys=True, default=str),
        "normalized_payload": json.dumps(record.normalized_payload, sort_keys=True, default=str),
        "sector_codes": record.sector_codes,
        "sector_match": record.sector_match,
        "route": json.dumps(record.route or {}, sort_keys=True, default=str),
        "status": record.status,
        "target_entity_id": record.target_entity_id,
    }


def _sector_match(value: object) -> str:
    sector_match = str(value or "in_sector").strip()
    if sector_match not in SECTOR_MATCH_VALUES:
        raise ValueError(f"sector_match must be one of {sorted(SECTOR_MATCH_VALUES)}, got {sector_match!r}")
    return sector_match
