"""Durable, transactional human review of persisted map discoveries.

The default store is deliberately local and cannot approve into canonical data.
Tests may enable the SQLite canonical mirror explicitly; production admission
stays fail-closed until the database owner installs the SQL contract and wires a
dedicated writer using separate credentials.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

STATUSES = ("pending_review", "approved", "rejected_by_reviewer")
ENTITY_TYPES = ("actor", "person", "event")
DECISION_KINDS = ("same_existing", "new", "reject", "defer")
REJECTION_REASONS = (
    "Not relevant to GHUS sectors",
    "Not an organisation / event / person page",
    "Duplicate of an existing record",
    "Outside target geography",
    "Past event with no useful participants",
    "Insufficient evidence on the page",
    "Other",
)
REVIEWABLE_RUN_STATUSES = (
    "done", "interrupted", "cancelled", "cost_unknown", "budget_stopped", "error",
)
REVIEW_INBOXES = ("current", "history", "actionable", "incomplete", "development", "all")

_UUID_OR_RUN_ID = re.compile(
    r"^(?:(?:discovery|run|actor|candidate)\s*[:#_-]\s*)?"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_PLACEHOLDER_ACTOR_NAMES = {
    "actor", "company", "organization", "organisation", "discovery", "n/a", "na",
    "none", "null", "placeholder", "tbd", "unknown", "unknown actor",
    "unknown company", "unknown organization", "unnamed", "unnamed actor",
}

EDITABLE_FIELDS = {
    "actor": (
        "name", "actor_category", "category_type", "category_note",
        "actor_type", "actor_type_raw", "description", "website",
        "location_city", "state", "region", "country", "primary_technical_focus",
        "technical_approach", "current_activities", "technology_ip_notes",
        "key_constraints", "funding_summary", "estimated_trl",
        "primary_lifecycle_role",
    ),
    "person": (
        "name", "affiliation", "affiliation_raw", "role",
        "public_profile_url", "research_area",
    ),
    "event": (
        "name", "event_type", "description", "location", "website", "next_date",
        "recurring_pattern", "sponsoring_orgs", "thematic_focus",
        "expected_attendance", "access_type",
    ),
}

FIELD_LIMITS = {
    "actor": {
        "name": 255, "actor_category": 80, "category_type": 120,
        "category_note": 500, "actor_type": 40, "actor_type_raw": 255,
        "website": 500, "location_city": 120, "state": 80, "region": 120,
        "country": 80,
        "primary_lifecycle_role": 30,
    },
    "person": {"name": 255, "role": 120, "public_profile_url": 500},
    "event": {
        "name": 255, "event_type": 120, "location": 255, "website": 500,
        "expected_attendance": 120, "access_type": 120, "recurring_pattern": 60,
    },
}

PAYLOAD_ALIASES = {
    "actor": {"city": "location_city"},
    "person": {
        "full_name": "name", "organization_name": "affiliation", "title": "role",
        "profile_url": "public_profile_url", "linkedin_url": "public_profile_url",
    },
    "event": {"title": "name", "start_date": "next_date", "city": "location"},
}

INTERNAL_METADATA_FIELDS = (
    "_judge", "_url_status", "_selected", "_rank", "_why", "_floor",
    "_verification", "verification", "verification_results", "judge_results",
    "uncertainties", "missing_fields", "duplicate_of", "_duplicate",
    "_database_status", "database_status", "_existing_id",
)


class ReviewError(RuntimeError):
    pass


class ReviewValidationError(ReviewError):
    pass


class ReviewConflict(ReviewError):
    pass


class ReviewNotConfigured(ReviewError):
    pass


class DuplicateRisk(ReviewConflict):
    def __init__(self, matches: list[dict[str, Any]]):
        self.matches = matches
        super().__init__("A possible canonical duplicate requires resolution before approval.")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _loads(value: str | None, default: Any) -> Any:
    if value is None:
        return deepcopy(default)
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return deepcopy(default)


def _now() -> float:
    return time.time()


def _clean_text(value: Any, *, required: bool = False, max_length: int = 5000) -> str | None:
    if value is None:
        if required:
            raise ReviewValidationError("A required value is missing.")
        return None
    if not isinstance(value, str):
        raise ReviewValidationError("Text fields must contain text or null.")
    value = value.strip()
    if required and not value:
        raise ReviewValidationError("A required value cannot be empty.")
    if len(value) > max_length:
        raise ReviewValidationError(f"A text value exceeds the {max_length}-character limit.")
    return value or None


def _candidate_id(run_id: str, entity_type: str, source_index: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"ghus-review:{run_id}:{entity_type}:{source_index}"))


def _external_candidate_id(source_key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"ghus-review-external:{source_key}"))


def _candidate_name(entity_type: str, payload: dict[str, Any]) -> str:
    if entity_type == "person":
        return str(payload.get("full_name") or payload.get("name") or "Unnamed person")
    return str(payload.get("name") or f"Unnamed {entity_type}")


def _actor_identity_reason(candidate: dict[str, Any]) -> str | None:
    if candidate.get("entity_type") != "actor":
        return None
    payload = candidate.get("reviewed_payload") or candidate.get("original_payload") or {}
    name = str(payload.get("name") or "").strip()
    if not name:
        return "missing_actor_name"
    normalized = " ".join(name.casefold().split())
    if normalized in _PLACEHOLDER_ACTOR_NAMES or normalized.startswith("unnamed actor"):
        return "placeholder_actor_name"
    if (_UUID_OR_RUN_ID.fullmatch(name)
            or name == str(candidate.get("source_run_id") or "")
            or name == str(candidate.get("source_index") or "")
            or name == str(candidate.get("candidate_id") or "")):
        return "identifier_used_as_actor_name"
    return None


def _run_kind(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("agent_metadata") or {}
    source_table = str(metadata.get("source_table") or "").casefold()
    configured = str(metadata.get("review_run_type") or "").casefold()
    source_run_id = str(candidate.get("source_run_id") or "")
    if source_table == "review_item" or configured == "architecture_v2_review":
        return "architecture_v2_review"
    if source_run_id.startswith("discovery:") or source_table in {
        "search_candidate", "event_review_queue", "person_review_queue",
    }:
        return "discovery"
    if configured == "build_the_map" or not source_run_id.startswith(("discovery:", "v2-review:")):
        return "build_the_map"
    return "other"


def _is_development_candidate(candidate: dict[str, Any]) -> bool:
    metadata = candidate.get("agent_metadata") or {}
    environment = str(metadata.get("source_environment") or "").casefold()
    mode = str(metadata.get("review_run_mode") or metadata.get("run_mode") or "").casefold()
    intent = str(metadata.get("review_run_intent") or "").casefold()
    return (
        environment in {"test", "testing", "development", "dev", "staging"}
        or mode == "dry_run"
        or intent in {"test", "development", "migration_validation", "synthetic_validation"}
    )


def _run_timestamp(candidate: dict[str, Any]) -> float:
    metadata = candidate.get("agent_metadata") or {}
    for key in ("review_run_finished_at", "review_run_started_at", "review_record_created_at"):
        value = metadata.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return float(candidate.get("created_at") or 0)


def _discovery_run_key(candidate: dict[str, Any]) -> tuple[str, str, str] | None:
    metadata = candidate.get("agent_metadata") or {}
    if _run_kind(candidate) != "discovery":
        return None
    intent = str(metadata.get("review_run_intent") or "")
    # Explicit manual runs are independent. No schedule is inferred from an ID.
    if intent == "manual":
        return None
    timestamp = metadata.get("review_run_finished_at")
    status = metadata.get("review_run_status") or metadata.get("run_status")
    if not isinstance(timestamp, (int, float)) or status not in {
        "done", "completed", "success", "succeeded", "attention",
    }:
        return None
    return (
        str(metadata.get("review_run_source") or "open_web_search"),
        str(metadata.get("review_run_entity_type") or candidate["entity_type"]),
        intent,
    )


def _date_label(timestamp: float | None) -> str:
    if not timestamp:
        return ""
    moment = datetime.fromtimestamp(timestamp, timezone.utc)
    return f"{moment.strftime('%b')} {moment.day}, {moment.year}"


def _run_label(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("agent_metadata") or {}
    existing = str(metadata.get("review_run_label") or "").strip()
    if existing:
        return existing
    kind = _run_kind(candidate)
    if kind == "build_the_map":
        prefix = "Build the Map"
    elif kind == "architecture_v2_review":
        prefix = "Architecture V2 Review"
    elif kind == "discovery":
        entity = str(metadata.get("review_run_entity_type") or candidate.get("entity_type") or "")
        intent = metadata.get("review_run_intent")
        prefix = ("Weekly Discovery" if intent == "weekly" else "Manual Discovery"
                  if intent == "manual" else f"{entity.replace('_', ' ').title()} Discovery"
                  if entity else "Discovery")
    else:
        prefix = "Discovery run"
    date_label = _date_label(_run_timestamp(candidate))
    return f"{prefix} — {date_label}" if date_label else prefix


def _editable_payload(entity_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    for source, target in PAYLOAD_ALIASES[entity_type].items():
        if target not in normalized and source in normalized:
            normalized[target] = normalized[source]
    if entity_type == "actor" and not str(normalized.get("actor_category") or "").strip():
        # Transitional dual-read only: legacy Agent 3 results still emit actor_type.
        # Keep the original field and expose the same recorded value as the category;
        # category_type remains empty unless the source actually supplied it.
        legacy_category = normalized.get("actor_type")
        if str(legacy_category or "").strip():
            normalized["actor_category"] = deepcopy(legacy_category)
    return {
        field: deepcopy(normalized[field])
        for field in EDITABLE_FIELDS[entity_type]
        if field in normalized and not isinstance(normalized[field], (dict, list))
    }


def _duplicate_state(payload: dict[str, Any]) -> str:
    raw = str(payload.get("_database_status") or payload.get("database_status") or "").lower()
    if payload.get("duplicate_of") or payload.get("_duplicate") or "duplicate" in raw:
        return "possible_duplicate"
    if payload.get("_existing_id") or "existing" in raw or "already" in raw:
        return "already_exists"
    if raw == "new":
        return "new"
    return "not_checked"


def _evidence(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for source in payload.get("sources") or []:
        if not isinstance(source, dict) or not isinstance(source.get("url"), str):
            continue
        url = source["url"].strip()
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            continue
        out.append({
            "url": url,
            "supports": str(source.get("supports") or "").strip(),
            "evidence_type": str(source.get("evidence_type") or "").strip(),
        })
    return out


def _metadata(payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    metadata = {key: deepcopy(payload[key]) for key in INTERNAL_METADATA_FIELDS if key in payload}
    for key in ("workflow", "selection_note", "coverage_gaps", "coverage_note", "partial"):
        if key in result:
            metadata[key] = deepcopy(result[key])
    return metadata


def _normalized_entities(result: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    groups = result.get("entities") if isinstance(result, dict) else None
    if not isinstance(groups, dict):
        return []
    rows: list[tuple[str, str, dict[str, Any]]] = []
    for entity_type in ENTITY_TYPES:
        group = groups.get(entity_type)
        if not isinstance(group, list):
            continue
        for index, payload in enumerate(group):
            if isinstance(payload, dict):
                rows.append((entity_type, str(index), deepcopy(payload)))

    # Organization-first results already include a normalized person collection.
    # Only recover nested people for legacy results where that collection is absent.
    if "person" not in groups:
        seen: set[tuple[str, str]] = set()
        for actor_index, actor in enumerate(groups.get("actor") or []):
            if not isinstance(actor, dict):
                continue
            for person_index, person in enumerate(actor.get("people") or []):
                if not isinstance(person, dict):
                    continue
                identity = (
                    str(person.get("full_name") or person.get("name") or "").casefold().strip(),
                    str(person.get("organization_name") or actor.get("name") or "").casefold().strip(),
                )
                if not identity[0] or identity in seen:
                    continue
                seen.add(identity)
                recovered = deepcopy(person)
                recovered.setdefault("organization_name", actor.get("name"))
                rows.append(("person", f"nested:{actor_index}:{person_index}", recovered))
    return rows


class ReviewStore:
    """SQLite review repository with an explicitly test-only canonical mirror."""

    def __init__(self, path: str | Path | None = None, *, enable_test_canonical: bool = False):
        root = Path(__file__).resolve().parents[2]
        self.path = Path(path or os.environ.get("REVIEW_STORE_DB") or root / ".review" / "review.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.enable_test_canonical = enable_test_canonical
        self._initialize()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS review_candidate (
                    candidate_id TEXT PRIMARY KEY,
                    source_run_id TEXT NOT NULL,
                    source_index TEXT NOT NULL,
                    source_description TEXT NOT NULL DEFAULT '',
                    entity_type TEXT NOT NULL CHECK (entity_type IN ('actor','person','event')),
                    display_name TEXT NOT NULL,
                    original_payload TEXT NOT NULL,
                    reviewed_payload TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    agent_metadata TEXT NOT NULL,
                    duplicate_state TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN
                        ('pending_review','approved','rejected_by_reviewer')),
                    created_at REAL NOT NULL,
                    reviewed_at REAL,
                    reviewer TEXT,
                    review_notes TEXT,
                    rejection_reason TEXT,
                    canonical_entity_id TEXT,
                    decision_kind TEXT,
                    admission_state TEXT NOT NULL DEFAULT 'not_applied',
                    admission_error TEXT,
                    admission_outcome TEXT,
                    UNIQUE(source_run_id, entity_type, source_index)
                );
                CREATE INDEX IF NOT EXISTS review_candidate_status
                    ON review_candidate(status, entity_type, source_run_id);
                CREATE TABLE IF NOT EXISTS review_decision (
                    decision_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    candidate_id TEXT NOT NULL UNIQUE REFERENCES review_candidate(candidate_id),
                    decision TEXT NOT NULL CHECK (decision IN ('approved','rejected_by_reviewer')),
                    reviewer TEXT NOT NULL,
                    decided_at REAL NOT NULL,
                    original_payload TEXT NOT NULL,
                    final_payload TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    source_run_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    notes TEXT
                );
                CREATE TABLE IF NOT EXISTS review_rejection (
                    candidate_id TEXT PRIMARY KEY REFERENCES review_candidate(candidate_id),
                    status TEXT NOT NULL CHECK (status = 'rejected_by_reviewer'),
                    original_payload TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    rejected_at REAL NOT NULL,
                    rejection_reason TEXT NOT NULL,
                    source_run_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    evidence TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_admission_attempt (
                    idempotency_key TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL REFERENCES review_candidate(candidate_id),
                    decision_kind TEXT NOT NULL CHECK (decision_kind IN
                        ('same_existing','new','reject','defer')),
                    state TEXT NOT NULL CHECK (state IN ('applied','failed')),
                    outcome TEXT,
                    error TEXT,
                    attempted_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_sync_state (
                    source TEXT PRIMARY KEY,
                    last_attempt_at REAL,
                    last_success_at REAL,
                    last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS test_canonical_actor (
                    entity_id TEXT PRIMARY KEY, name TEXT NOT NULL, website TEXT,
                    payload TEXT NOT NULL, source_run_id TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS test_canonical_person (
                    entity_id TEXT PRIMARY KEY, full_name TEXT NOT NULL,
                    public_profile_url TEXT, payload TEXT NOT NULL,
                    source_run_id TEXT NOT NULL, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS test_canonical_event (
                    entity_id TEXT PRIMARY KEY, name TEXT NOT NULL, website TEXT,
                    payload TEXT NOT NULL, source_run_id TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
            """)
            existing = {
                row["name"] for row in db.execute("PRAGMA table_info(review_candidate)")
            }
            additions = {
                "decision_kind": "TEXT",
                "admission_state": "TEXT NOT NULL DEFAULT 'not_applied'",
                "admission_error": "TEXT",
                "admission_outcome": "TEXT",
            }
            for name, definition in additions.items():
                if name not in existing:
                    db.execute(f"ALTER TABLE review_candidate ADD COLUMN {name} {definition}")

    @property
    def admission_configured(self) -> bool:
        return self.enable_test_canonical

    def set_sync_state(self, source: str, *, success: bool, error: str | None = None) -> None:
        now = _now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO review_sync_state(source,last_attempt_at,last_success_at,last_error) "
                "VALUES(?,?,?,?) ON CONFLICT(source) DO UPDATE SET "
                "last_attempt_at=excluded.last_attempt_at, "
                "last_success_at=CASE WHEN excluded.last_error IS NULL THEN excluded.last_attempt_at "
                "ELSE review_sync_state.last_success_at END, last_error=excluded.last_error",
                (source, now, now if success else None, error),
            )

    def sync_state(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM review_sync_state ORDER BY source"
            )]

    def sync_run_store(self, run_store) -> int:
        """Import terminal persisted result bundles without mutating the map store."""
        with run_store.connect() as source:
            runs = source.execute(
                "SELECT id, description, result, status, created, updated FROM runs "
                "WHERE result IS NOT NULL AND status IN (?,?,?,?,?,?) ORDER BY created",
                REVIEWABLE_RUN_STATUSES,
            ).fetchall()
        inserted = 0
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for run in runs:
                result = _loads(run["result"], {})
                for entity_type, source_index, payload in _normalized_entities(result):
                    candidate_id = _candidate_id(run["id"], entity_type, source_index)
                    now = _now()
                    metadata = _metadata(payload, result)
                    metadata.update({
                        "source_environment": "operational",
                        "review_run_type": "build_the_map",
                        "review_run_source": "build_the_map",
                        "review_run_entity_type": entity_type,
                        "review_run_status": run["status"],
                        "review_run_started_at": float(run["created"]),
                        "review_run_finished_at": float(run["updated"]),
                    })
                    cursor = db.execute(
                        "INSERT OR IGNORE INTO review_candidate "
                        "(candidate_id,source_run_id,source_index,source_description,entity_type,"
                        "display_name,original_payload,reviewed_payload,evidence,agent_metadata,"
                        "duplicate_state,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,? ,?)",
                        (candidate_id, run["id"], source_index, run["description"] or "",
                         entity_type, _candidate_name(entity_type, payload), _json(payload),
                         _json(_editable_payload(entity_type, payload)), _json(_evidence(payload)),
                          _json(metadata),
                         _duplicate_state(payload), "pending_review", now),
                    )
                    inserted += cursor.rowcount
                    if not cursor.rowcount:
                        db.execute(
                            "UPDATE review_candidate SET evidence=?,agent_metadata=?,duplicate_state=? "
                            "WHERE candidate_id=? AND status='pending_review'",
                            (_json(_evidence(payload)), _json(metadata),
                             _duplicate_state(payload), candidate_id),
                        )
        return inserted

    def sync_external_candidates(self, candidates: list[dict[str, Any]]) -> int:
        """Copy normalized candidates from a read-only external review source.

        The external source supplies an immutable stable key.  Existing pending
        candidates receive refreshed evidence and agent metadata only; reviewer
        edits and the original captured payload are never overwritten.
        """
        inserted = 0
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for candidate in candidates:
                source_key = str(candidate.get("source_key") or "").strip()
                source_run_id = str(candidate.get("source_run_id") or "").strip()
                entity_type = str(candidate.get("entity_type") or "").strip()
                payload = candidate.get("payload")
                if not source_key or not source_run_id:
                    raise ReviewValidationError(
                        "An external review candidate is missing its stable source identity."
                    )
                if entity_type not in ENTITY_TYPES or not isinstance(payload, dict):
                    raise ReviewValidationError(
                        "An external review candidate has an unsupported entity payload."
                    )
                source_index = str(candidate.get("source_index") or source_key)
                candidate_id = _external_candidate_id(source_key)
                evidence = candidate.get("evidence")
                metadata = candidate.get("agent_metadata")
                evidence = evidence if isinstance(evidence, list) else _evidence(payload)
                metadata = metadata if isinstance(metadata, dict) else {}
                duplicate_state = str(candidate.get("duplicate_state") or "not_checked")
                if duplicate_state not in {"new", "already_exists", "possible_duplicate", "not_checked"}:
                    duplicate_state = "not_checked"
                created_at = candidate.get("created_at")
                if not isinstance(created_at, (int, float)):
                    created_at = _now()
                cursor = db.execute(
                    "INSERT OR IGNORE INTO review_candidate "
                    "(candidate_id,source_run_id,source_index,source_description,entity_type,"
                    "display_name,original_payload,reviewed_payload,evidence,agent_metadata,"
                    "duplicate_state,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (candidate_id, source_run_id, source_index,
                     str(candidate.get("source_description") or "External discovery review"),
                     entity_type, _candidate_name(entity_type, payload), _json(payload),
                     _json(_editable_payload(entity_type, payload)), _json(evidence),
                     _json(metadata), duplicate_state, "pending_review", float(created_at)),
                )
                inserted += cursor.rowcount
                if not cursor.rowcount:
                    db.execute(
                        "UPDATE review_candidate SET evidence=?,agent_metadata=?,duplicate_state=? "
                        "WHERE candidate_id=? AND status='pending_review'",
                        (_json(evidence), _json(metadata), duplicate_state, candidate_id),
                    )
        return inserted

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for field, default in (
            ("original_payload", {}), ("reviewed_payload", {}),
            ("evidence", []), ("agent_metadata", {}), ("admission_outcome", None),
        ):
            if field in item:
                item[field] = _loads(item[field], default)
        item["editable_fields"] = list(EDITABLE_FIELDS.get(item.get("entity_type"), ()))
        item["field_constraints"] = {
            field: {"max_length": length}
            for field, length in FIELD_LIMITS.get(item.get("entity_type"), {}).items()
        }
        item["rejection_reasons"] = list(REJECTION_REASONS)
        metadata = item.get("agent_metadata", {})
        if item.get("entity_type") == "actor":
            for field in (
                "actor_topics", "hub_assignments", "existing_memberships",
                "hub_proposal_memberships",
            ):
                if not isinstance(metadata.get(field), list):
                    metadata[field] = []
        item["top_matches"] = metadata.get("top_matches") or []
        item["run_label"] = _run_label(item)
        item["identity_issue"] = _actor_identity_reason(item)
        return item

    @staticmethod
    def _annotate_inboxes(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        latest_runs: dict[tuple[str, str, str], tuple[float, str]] = {}
        for candidate in candidates:
            if _run_kind(candidate) != "discovery" or _is_development_candidate(candidate):
                continue
            metadata = candidate.get("agent_metadata") or {}
            key = _discovery_run_key(candidate)
            if key is None:
                continue
            value = (float(metadata["review_run_finished_at"]), str(candidate["source_run_id"]))
            if value > latest_runs.get(key, (-1.0, "")):
                latest_runs[key] = value

        for candidate in candidates:
            candidate["run_label"] = _run_label(candidate)
            candidate["identity_issue"] = _actor_identity_reason(candidate)
            if _is_development_candidate(candidate):
                candidate["inbox"] = "development"
                candidate["inbox_reason"] = "explicit_test_development_or_dry_run"
                continue
            if candidate["identity_issue"]:
                candidate["inbox"] = "incomplete"
                candidate["inbox_reason"] = candidate["identity_issue"]
                continue
            if _run_kind(candidate) == "discovery":
                metadata = candidate.get("agent_metadata") or {}
                run_status = metadata.get("review_run_status") or metadata.get("run_status")
                if run_status in {"running", "queued", "pending", "starting"}:
                    candidate["inbox"] = "history"
                    candidate["inbox_reason"] = "run_not_completed"
                    continue
                key = _discovery_run_key(candidate)
                if key and latest_runs.get(key, (None, None))[1] != candidate["source_run_id"]:
                    candidate["inbox"] = "history"
                    candidate["inbox_reason"] = "previous_completed_discovery_run"
                    continue
            candidate["inbox"] = "current"
            candidate["inbox_reason"] = "current_actionable"

        # Safe duplicate suppression affects only Current. It never deletes a row.
        # Distinct review kinds/topics are independent decisions. Shared domains
        # alone cannot identify an actor (e.g. departments at one university).
        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for candidate in candidates:
            if candidate.get("inbox") != "current":
                continue
            metadata = candidate.get("agent_metadata") or {}
            kind = _run_kind(candidate)
            key = None
            if kind == "architecture_v2_review" and metadata.get("entity_id"):
                key = (
                    "v2", str(metadata["entity_id"]), str(metadata.get("topic_id") or ""),
                    str(metadata.get("review_kind") or ""),
                    candidate.get("status"),
                )
            elif kind == "discovery" and candidate.get("entity_type") == "actor":
                identity = metadata.get("entity_id") or (candidate.get("original_payload") or {}).get("_existing_id")
                if identity:
                    key = (
                        "discovery-entity", candidate.get("source_run_id"),
                        str(identity), str(metadata.get("topic_id") or ""),
                        str(metadata.get("review_kind") or ""), candidate.get("status"),
                    )
            if key:
                groups.setdefault(key, []).append(candidate)
        for group in groups.values():
            if len(group) < 2:
                continue
            keep = max(group, key=lambda item: (float(item.get("created_at") or 0), item["candidate_id"]))
            for candidate in group:
                if candidate is keep:
                    continue
                candidate["inbox"] = "history"
                candidate["inbox_reason"] = "repeated_sighting_preserved"
                candidate["superseded_by_candidate_id"] = keep["candidate_id"]
        return candidates

    def get(self, candidate_id: str) -> dict[str, Any]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM review_candidate").fetchall()
        candidates = self._annotate_inboxes([self._decode(row) for row in rows])
        item = next((candidate for candidate in candidates if candidate["candidate_id"] == candidate_id), None)
        if item is None:
            raise KeyError(candidate_id)
        return item

    def list(self, *, status: str | None = "pending_review", entity_type: str | None = None,
             source_run_id: str | None = None, search: str | None = None,
             inbox: str = "current") -> dict[str, Any]:
        if status not in (*STATUSES, None, "all"):
            raise ReviewValidationError("Unsupported review status.")
        if entity_type not in (*ENTITY_TYPES, None, "all"):
            raise ReviewValidationError("Unsupported entity type.")
        if inbox not in REVIEW_INBOXES:
            raise ReviewValidationError("Unsupported review inbox.")
        with self.connect() as db:
            rows = db.execute("SELECT * FROM review_candidate").fetchall()
        candidates = self._annotate_inboxes([self._decode(row) for row in rows])

        needle = str(search or "").strip().casefold()

        def common(candidate: dict[str, Any], *, include_source: bool = True) -> bool:
            if entity_type not in (None, "all") and candidate["entity_type"] != entity_type:
                return False
            if include_source and source_run_id and candidate["source_run_id"] != source_run_id:
                return False
            return not needle or needle in json.dumps(
                [candidate.get("display_name"), candidate.get("reviewed_payload")],
                ensure_ascii=False, default=str,
            ).casefold()

        def in_inbox(candidate: dict[str, Any], selected: str) -> bool:
            if selected == "all":
                return True
            if selected == "actionable":
                return candidate["inbox"] in {"current", "history"}
            return candidate["inbox"] == selected

        count_base = [candidate for candidate in candidates if common(candidate) and in_inbox(candidate, inbox)]
        counts = {
            selected_status: sum(candidate["status"] == selected_status for candidate in count_base)
            for selected_status in STATUSES
        }
        selected = [
            candidate for candidate in count_base
            if status in (None, "all") or candidate["status"] == status
        ]
        selected.sort(key=lambda candidate: (
            STATUSES.index(candidate["status"]), -float(candidate.get("created_at") or 0)
        ))

        inbox_counts = {}
        for selected_inbox in REVIEW_INBOXES:
            inbox_counts[selected_inbox] = sum(
                common(candidate)
                and (status in (None, "all") or candidate["status"] == status)
                and in_inbox(candidate, selected_inbox)
                for candidate in candidates
            )

        map_candidates = [
            candidate for candidate in candidates
            if common(candidate, include_source=False)
            and (status in (None, "all") or candidate["status"] == status)
            and in_inbox(candidate, inbox)
        ]
        grouped_maps: dict[str, dict[str, Any]] = {}
        for candidate in map_candidates:
            run_id = candidate["source_run_id"]
            mapped = grouped_maps.setdefault(run_id, {
                "source_run_id": run_id,
                "description": candidate["run_label"],
                "run_label": candidate["run_label"],
                "candidate_count": 0,
            })
            mapped["candidate_count"] += 1
        maps = sorted(grouped_maps.values(), key=lambda item: (item["description"], item["source_run_id"]))
        return {
            "candidates": selected,
            "counts": counts,
            "inbox": inbox,
            "inbox_counts": inbox_counts,
            "source_maps": maps,
            "admission_configured": self.admission_configured,
            "last_sync": self.sync_state(),
        }

    @staticmethod
    def validate_payload(entity_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ReviewValidationError("The reviewed payload must be an object.")
        allowed = set(EDITABLE_FIELDS[entity_type])
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ReviewValidationError("Unsupported reviewed fields: " + ", ".join(unknown))
        cleaned: dict[str, Any] = {}
        for field, value in payload.items():
            if field == "estimated_trl":
                if value in (None, ""):
                    cleaned[field] = None
                else:
                    try:
                        trl = int(value)
                    except (TypeError, ValueError) as exc:
                        raise ReviewValidationError("estimated_trl must be an integer from 1 to 9.") from exc
                    if not 1 <= trl <= 9:
                        raise ReviewValidationError("estimated_trl must be an integer from 1 to 9.")
                    cleaned[field] = trl
            elif isinstance(value, (dict, list)):
                raise ReviewValidationError(f"{field} must be a scalar value.")
            elif isinstance(value, str):
                cleaned[field] = _clean_text(value)
            elif value is None or isinstance(value, (int, float, bool)):
                cleaned[field] = value
            else:
                raise ReviewValidationError(f"Unsupported value for {field}.")
        for field, limit in FIELD_LIMITS[entity_type].items():
            if field in cleaned and isinstance(cleaned[field], str):
                cleaned[field] = _clean_text(cleaned[field], max_length=limit)
        cleaned["name"] = _clean_text(
            cleaned.get("name"), required=True,
            max_length=FIELD_LIMITS[entity_type]["name"],
        )
        if entity_type == "person":
            cleaned["affiliation"] = _clean_text(
                cleaned.get("affiliation"), required=True, max_length=5000
            )
            cleaned["role"] = _clean_text(
                cleaned.get("role"), required=True, max_length=120
            )
        return cleaned

    def update(self, candidate_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM review_candidate WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise KeyError(candidate_id)
            if row["status"] != "pending_review":
                raise ReviewConflict("Only pending candidates can be edited.")
            current = _loads(row["reviewed_payload"], {})
            unknown = sorted(set(fields) - set(EDITABLE_FIELDS[row["entity_type"]]))
            if unknown:
                raise ReviewValidationError("Unsupported reviewed fields: " + ", ".join(unknown))
            current.update(fields)
            cleaned = self.validate_payload(row["entity_type"], {
                key: value for key, value in current.items()
                if key in EDITABLE_FIELDS[row["entity_type"]]
            })
            db.execute(
                "UPDATE review_candidate SET reviewed_payload=?,display_name=? WHERE candidate_id=?",
                (_json(cleaned), _candidate_name(row["entity_type"], cleaned), candidate_id),
            )
        return self.get(candidate_id)

    def _existing_decision(self, db, idempotency_key: str, candidate_id: str,
                           decision: str) -> dict[str, Any] | None:
        row = db.execute(
            "SELECT candidate_id,decision FROM review_decision WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        if row["candidate_id"] != candidate_id or row["decision"] != decision:
            raise ReviewConflict("That idempotency key was already used for another decision.")
        candidate = db.execute(
            "SELECT * FROM review_candidate WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
        return self._decode(candidate)

    def _duplicate_matches(self, db, entity_type: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        table = f"test_canonical_{entity_type}"
        if entity_type == "person":
            name = payload.get("full_name") or payload.get("name")
            url = payload.get("public_profile_url") or payload.get("profile_url") or payload.get("linkedin_url")
            rows = db.execute(
                f"SELECT entity_id,full_name AS name,public_profile_url AS website FROM {table} "
                "WHERE lower(full_name)=lower(?) OR (? IS NOT NULL AND public_profile_url=?)",
                (name, url, url),
            ).fetchall()
        else:
            name, url = payload.get("name"), payload.get("website")
            rows = db.execute(
                f"SELECT entity_id,name,website FROM {table} "
                "WHERE lower(name)=lower(?) OR (? IS NOT NULL AND website=?)",
                (name, url, url),
            ).fetchall()
        return [dict(row) for row in rows]

    def _insert_canonical(self, db, entity_type: str, payload: dict[str, Any],
                          source_run_id: str) -> str:
        entity_id, now = str(uuid4()), _now()
        if entity_type == "person":
            name = payload.get("full_name") or payload.get("name")
            url = payload.get("public_profile_url") or payload.get("profile_url") or payload.get("linkedin_url")
            db.execute(
                "INSERT INTO test_canonical_person "
                "(entity_id,full_name,public_profile_url,payload,source_run_id,created_at) "
                "VALUES(?,?,?,?,?,?)", (entity_id, name, url, _json(payload), source_run_id, now),
            )
        elif entity_type == "actor":
            db.execute(
                "INSERT INTO test_canonical_actor "
                "(entity_id,name,website,payload,source_run_id,created_at) VALUES(?,?,?,?,?,?)",
                (entity_id, payload["name"], payload.get("website"), _json(payload), source_run_id, now),
            )
        else:
            db.execute(
                "INSERT INTO test_canonical_event "
                "(entity_id,name,website,payload,source_run_id,created_at) VALUES(?,?,?,?,?,?)",
                (entity_id, payload["name"], payload.get("website"), _json(payload), source_run_id, now),
            )
        return entity_id

    def approve(self, candidate_id: str, *, reviewer: str, idempotency_key: str,
                notes: str | None = None, edited_payload: dict[str, Any] | None = None,
                confirmed: bool = False) -> dict[str, Any]:
        reviewer = _clean_text(reviewer, required=True, max_length=120)
        idempotency_key = _clean_text(idempotency_key, required=True, max_length=200)
        notes = _clean_text(notes, max_length=5000)
        if confirmed is not True:
            raise ReviewValidationError("Explicit confirmation is required.")
        if not self.enable_test_canonical:
            raise ReviewNotConfigured(
                "Canonical review admission is not configured. The database owner must install "
                "the review schema and connect a dedicated transactional writer."
            )
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = self._existing_decision(db, idempotency_key, candidate_id, "approved")
            if previous:
                return previous
            row = db.execute(
                "SELECT * FROM review_candidate WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise KeyError(candidate_id)
            if row["status"] != "pending_review":
                raise ReviewConflict("This candidate has already been decided.")
            payload = edited_payload if edited_payload is not None else _loads(row["reviewed_payload"], {})
            payload = self.validate_payload(row["entity_type"], payload)
            matches = self._duplicate_matches(db, row["entity_type"], payload)
            if matches:
                raise DuplicateRisk(matches)
            canonical_id = self._insert_canonical(
                db, row["entity_type"], payload, row["source_run_id"]
            )
            decided_at, decision_id = _now(), str(uuid4())
            db.execute(
                "INSERT INTO review_decision "
                "(decision_id,idempotency_key,candidate_id,decision,reviewer,decided_at,"
                "original_payload,final_payload,evidence,source_run_id,entity_type,notes) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (decision_id, idempotency_key, candidate_id, "approved", reviewer, decided_at,
                 row["original_payload"], _json(payload), row["evidence"], row["source_run_id"],
                 row["entity_type"], notes),
            )
            db.execute(
                "UPDATE review_candidate SET status='approved',reviewed_payload=?,reviewed_at=?,"
                "reviewer=?,review_notes=?,canonical_entity_id=? WHERE candidate_id=?",
                (_json(payload), decided_at, reviewer, notes, canonical_id, candidate_id),
            )
        return self.get(candidate_id)

    def reject(self, candidate_id: str, *, reviewer: str, rejection_reason: str,
               idempotency_key: str, notes: str | None = None,
               confirmed: bool = False) -> dict[str, Any]:
        reviewer = _clean_text(reviewer, required=True, max_length=120)
        rejection_reason = _clean_text(rejection_reason, required=True, max_length=5000)
        idempotency_key = _clean_text(idempotency_key, required=True, max_length=200)
        notes = _clean_text(notes, max_length=5000)
        if confirmed is not True:
            raise ReviewValidationError("Explicit confirmation is required.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = self._existing_decision(
                db, idempotency_key, candidate_id, "rejected_by_reviewer"
            )
            if previous:
                return previous
            row = db.execute(
                "SELECT * FROM review_candidate WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise KeyError(candidate_id)
            if row["status"] != "pending_review":
                raise ReviewConflict("This candidate has already been decided.")
            decided_at, decision_id = _now(), str(uuid4())
            db.execute(
                "INSERT INTO review_rejection "
                "(candidate_id,status,original_payload,reviewer,rejected_at,rejection_reason,"
                "source_run_id,entity_type,evidence) VALUES(?,?,?,?,?,?,?,?,?)",
                (candidate_id, "rejected_by_reviewer", row["original_payload"], reviewer,
                 decided_at, rejection_reason, row["source_run_id"], row["entity_type"],
                 row["evidence"]),
            )
            db.execute(
                "INSERT INTO review_decision "
                "(decision_id,idempotency_key,candidate_id,decision,reviewer,decided_at,"
                "original_payload,final_payload,evidence,source_run_id,entity_type,notes) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (decision_id, idempotency_key, candidate_id, "rejected_by_reviewer", reviewer,
                 decided_at, row["original_payload"], row["reviewed_payload"], row["evidence"],
                 row["source_run_id"], row["entity_type"], notes),
            )
            db.execute(
                "UPDATE review_candidate SET status='rejected_by_reviewer',reviewed_at=?,"
                "reviewer=?,review_notes=?,rejection_reason=? WHERE candidate_id=?",
                (decided_at, reviewer, notes, rejection_reason, candidate_id),
            )
        return self.get(candidate_id)

    def admission_request(
        self,
        candidate_id: str,
        *,
        decision_kind: str,
        reviewer: str,
        idempotency_key: str,
        target_id: str | None = None,
        notes: str | None = None,
        edited_payload: dict[str, Any] | None = None,
        hub_ids: list[str] | None = None,
        proposed_hub: dict[str, Any] | None = None,
        rejection_reason: str | None = None,
        rejection_reason_other: str | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Validate and shape the authoritative admission request without writing it."""
        if decision_kind not in DECISION_KINDS:
            raise ReviewValidationError("Unsupported review decision.")
        reviewer = _clean_text(reviewer, required=True, max_length=120)
        idempotency_key = _clean_text(idempotency_key, required=True, max_length=200)
        notes = _clean_text(notes, max_length=5000)
        if confirmed is not True:
            raise ReviewValidationError("Explicit confirmation is required.")
        candidate = self.get(candidate_id)
        if candidate["status"] != "pending_review":
            raise ReviewConflict("This candidate has already been decided.")
        if decision_kind == "same_existing" and not str(target_id or "").strip():
            raise ReviewValidationError("Select the existing record for a same-existing decision.")
        if decision_kind == "reject":
            if rejection_reason not in REJECTION_REASONS:
                raise ReviewValidationError("Select one of the fixed rejection reasons.")
            if rejection_reason == "Other" and not str(rejection_reason_other or "").strip():
                raise ReviewValidationError("Explain the Other rejection reason.")
        payload = edited_payload if edited_payload is not None else candidate["reviewed_payload"]
        payload = self.validate_payload(candidate["entity_type"], payload)
        metadata = candidate["agent_metadata"]
        source_table = str(metadata.get("source_table") or "").strip()
        if source_table == "search_candidate":
            source_id = metadata.get("source_candidate_id")
        else:
            source_id = metadata.get("review_queue_id")
        if source_table not in {
            "search_candidate", "event_review_queue", "person_review_queue"
        } or not str(source_id or "").strip():
            raise ReviewValidationError(
                "This candidate has no authoritative PostgreSQL source reference."
            )
        return {
            "entity_type": candidate["entity_type"],
            "source_ref": {"table": source_table, "id": str(source_id)},
            "decision_kind": decision_kind,
            "target_id": str(target_id or "").strip() or None,
            "edited_payload": payload,
            "hub_ids": [str(value).strip() for value in (hub_ids or []) if str(value).strip()],
            "proposed_hub": proposed_hub,
            "reviewer": reviewer,
            "rejection_reason": rejection_reason,
            "rejection_reason_other": _clean_text(rejection_reason_other, max_length=5000),
            "notes": notes,
            "idempotency_key": idempotency_key,
        }

    def record_admission_failure(
        self, candidate_id: str, *, idempotency_key: str,
        decision_kind: str, error: str,
    ) -> dict[str, Any]:
        safe_error = _clean_text(error, required=True, max_length=1000)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO review_admission_attempt "
                "(idempotency_key,candidate_id,decision_kind,state,error,attempted_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(idempotency_key) DO UPDATE SET "
                "state='failed',error=excluded.error,attempted_at=excluded.attempted_at",
                (idempotency_key, candidate_id, decision_kind, "failed", safe_error, _now()),
            )
            db.execute(
                "UPDATE review_candidate SET admission_state='failed',admission_error=?,"
                "decision_kind=? WHERE candidate_id=? AND status='pending_review'",
                (safe_error, decision_kind, candidate_id),
            )
        return self.get(candidate_id)

    def record_admission_success(
        self, candidate_id: str, *, idempotency_key: str,
        decision_kind: str, reviewer: str, notes: str | None,
        rejection_reason: str | None, outcome: dict[str, Any],
    ) -> dict[str, Any]:
        status = (
            "approved" if decision_kind in {"same_existing", "new"}
            else "rejected_by_reviewer" if decision_kind == "reject"
            else "pending_review"
        )
        now = _now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT candidate_id,state FROM review_admission_attempt WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing and existing["candidate_id"] != candidate_id:
                raise ReviewConflict("That idempotency key belongs to another candidate.")
            db.execute(
                "INSERT INTO review_admission_attempt "
                "(idempotency_key,candidate_id,decision_kind,state,outcome,attempted_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(idempotency_key) DO UPDATE SET "
                "state='applied',outcome=excluded.outcome,error=NULL,"
                "attempted_at=excluded.attempted_at",
                (idempotency_key, candidate_id, decision_kind, "applied", _json(outcome), now),
            )
            cursor = db.execute(
                "UPDATE review_candidate SET status=?,decision_kind=?,admission_state='applied',"
                "admission_error=NULL,admission_outcome=?,reviewed_at=?,reviewer=?,"
                "review_notes=?,rejection_reason=?,canonical_entity_id=? "
                "WHERE candidate_id=? AND status='pending_review'",
                (
                    status, decision_kind, _json(outcome), now, reviewer, notes,
                    rejection_reason, outcome.get("canonical_entity_id"), candidate_id,
                ),
            )
            if cursor.rowcount != 1 and not existing:
                raise ReviewConflict("This candidate has already been decided.")
        return self.get(candidate_id)

    def canonical_rows(self, entity_type: str) -> list[dict[str, Any]]:
        if entity_type not in ENTITY_TYPES:
            raise ReviewValidationError("Unsupported entity type.")
        with self.connect() as db:
            rows = db.execute(f"SELECT * FROM test_canonical_{entity_type} ORDER BY created_at").fetchall()
        out = [dict(row) for row in rows]
        for row in out:
            row["payload"] = _loads(row["payload"], {})
        return out

    def rejection(self, candidate_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM review_rejection WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["original_payload"] = _loads(out["original_payload"], {})
        out["evidence"] = _loads(out["evidence"], [])
        return out
