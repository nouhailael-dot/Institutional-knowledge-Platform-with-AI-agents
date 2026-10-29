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
import tempfile
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

from .taxonomy import (
    CATEGORY_LABELS,
    SELECTABLE_SECTOR_CODES,
    NOT_APPLICABLE,
    TaxonomyError,
    region_for_state,
    validate_pair,
)

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

EDITABLE_FIELDS = {
    "actor": (
        "name", "actor_category", "category_type", "category_note",
        "actor_type", "actor_type_raw", "description", "website",
        "primary_sector",
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
        "primary_sector": 20,
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

_UUID_PATTERN = re.compile(
    r"(?:discovery:|v2-review:)?[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}"
    r"-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)

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



def reviewFieldName(field: str) -> str:
    """The field as the Review screen labels it."""
    return {
        "primary_lifecycle_role": "Lifecycle role",
        "primary_sector": "Primary sector",
        "category_note": "Category note",
        "actor_type_raw": "Type as written on the page",
        "location_city": "City",
    }.get(field, field.replace("_", " ").capitalize())


def _candidate_id(run_id: str, entity_type: str, source_index: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"ghus-review:{run_id}:{entity_type}:{source_index}"))


def _external_candidate_id(source_key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"ghus-review-external:{source_key}"))


def _candidate_name(entity_type: str, payload: dict[str, Any]) -> str:
    if entity_type == "person":
        return str(payload.get("full_name") or payload.get("name") or "Unnamed person")
    return str(payload.get("name") or f"Unnamed {entity_type}")


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


# --------------------------------------------------------------- WS4: run groups
# The redesign cutoff. Everything created before it is shown together as the
# Pre-Redesign Backlog; everything after it is shown under its own run.
#
# This is a VIEW-LEVEL grouping and nothing else. Stored source_run_id values
# and provenance are never rewritten, and the original run stays visible under
# Audit & Details.
BACKLOG_GROUP_KEY = "pre_redesign_backlog"
BACKLOG_GROUP_LABEL = "Pre-Redesign Backlog"
DEFAULT_REVIEW_REDESIGN_CUTOFF = "2026-10-08T00:00:00Z"

TRIGGER_TYPES = ("manual", "subscription", "scheduled_event", "migration")
TRIGGER_LABELS = {
    "manual": "Manual",
    "subscription": "Subscription",
    "scheduled_event": "Scheduled Event",
    "migration": "Migration",
}
NOT_RECORDED = "Not Recorded"


def review_redesign_cutoff() -> float:
    """The cutoff as a POSIX timestamp. Configurable, never hard-coded in a view."""

    raw = (os.environ.get("REVIEW_REDESIGN_CUTOFF") or "").strip()
    for candidate in (raw, DEFAULT_REVIEW_REDESIGN_CUTOFF):
        if not candidate:
            continue
        try:
            text = candidate.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            continue
    raise ReviewValidationError("REVIEW_REDESIGN_CUTOFF is not an ISO-8601 timestamp.")


def _run_trigger(description: Any, source_run_id: Any, recorded: Any = None) -> str:
    """The run's trigger. Recorded value first; derived only as a fallback.

    ``collection_run.trigger_type`` is the authoritative source and arrives with
    backend migration 530. When it is present it is used as-is. Until then the
    trigger is read off the run description, and anything unrecognised stays
    "manual" rather than being guessed at.
    """

    stated = str(recorded or "").strip().casefold()
    if stated in TRIGGER_TYPES:
        return stated
    text = f"{description or ''} {source_run_id or ''}".casefold()
    if "migration" in text or "existing_canonical" in text:
        return "migration"
    if "subscription" in text:
        return "subscription"
    if "schedule" in text or "weekly" in text or "monthly" in text:
        return "scheduled_event"
    return "manual"


# Sectors present in the database (including ones added in Review). The
# application registers them whenever it reads the sector list.
DATABASE_SECTOR_CODES: set[str] = set()


def register_sector_codes(codes) -> None:
    DATABASE_SECTOR_CODES.update(str(code).strip().upper() for code in codes if str(code).strip())


# The map's own review items are keyed per topic ("v2-review:<topic>"), which
# split them into several identically labelled groups. They are one group.
MAP_CHECKS_PREFIX = "v2-review:"
ACTOR_UPDATE_PREFIX = "actor-update:"
# Records GHUS supplied through the Data Feed (a spreadsheet or the form).
DATAFEED_PREFIX = "datafeed:"
DATAFEED_LABEL = "Data Feed import"
# Review items about one box's value (raised by the Phase 11 fact writer).
FACT_REVIEW_KINDS = ("fact_conflict", "pending_update")
MAP_CHECKS_KEY = "map-checks"
MAP_CHECKS_LABEL = "Map checks"

_DISCOVERY_KIND = re.compile(r"^Open-web (actor|event|person) discovery", re.IGNORECASE)
_REQUEST_TITLE = re.compile(r"^Discovery request:\s*(.+?)\s*(?:·|$)")


def _short_day(when: Any) -> str | None:
    try:
        stamp = float(when)
    except (TypeError, ValueError):
        return None
    if stamp <= 0:
        return None
    # US calendar, as everywhere on the platform: 10/26/2026.
    return datetime.fromtimestamp(stamp, tz=timezone.utc).strftime("%m/%d/%Y")


# The four kinds of run a reviewer chooses between (the Review page's Run Type).
RUN_TYPES = ("discovery_actors", "discovery_events", "discovery_people", "actor_updates",
             "data_feed")


def run_type_of(source_run_id: Any, entity_types: Any) -> str:
    """Which kind of run this is, from what is recorded - never guessed.

    An actor update run is keyed "actor-update:<run>"; a discovery run by the
    kind of record it produced (a run produces one kind: actors, events or
    people). The map's own checks are their own kind.
    """
    run_id = str(source_run_id or "")
    if run_id.startswith(ACTOR_UPDATE_PREFIX):
        return "actor_updates"
    if run_id.startswith(DATAFEED_PREFIX):
        return "data_feed"
    if run_id.startswith(MAP_CHECKS_PREFIX):
        return "map_checks"
    kinds = {k for k in str(entity_types or "").split(",") if k}
    if kinds == {"event"}:
        return "discovery_events"
    if kinds == {"person"}:
        return "discovery_people"
    return "discovery_actors"


def run_name(description: Any, source_run_id: Any) -> str:
    """The run's own name, without its kind or date.

        "Grid-scale battery storage organizations in Texas"  (a Discovery request)
        "CPower Energy"                                      (an actor update)
        "Actor discovery (test run)"                         (an unnamed open-web run)
    """
    parts = _run_label(description, source_run_id).split(" · ")
    if parts[0] in ("Monitoring request", "Organization update", DATAFEED_LABEL) and len(parts) > 1:
        return " · ".join(parts[1:])
    if parts[0] == "Explore and Map" and len(parts) > 1:
        return "Explore and Map: " + " · ".join(parts[1:])
    return parts[0] + (f" ({' · '.join(parts[1:])})" if len(parts) > 1 else "")


def _run_label(description: Any, source_run_id: Any, when: Any = None) -> str:
    """What a run IS, in words a reviewer reads - never a UUID or a code.

        Monitoring request · Water technology organizations in the Great Lakes · Oct 15, 2026
        Actor discovery · test run · Oct 7, 2026
        Map checks · locations and links
        Explore and Map · find companies in the US that focus on…
    """

    raw = " ".join(str(description or "").split())
    run_id = str(source_run_id or "")
    day = _short_day(when)
    request = _REQUEST_TITLE.match(raw)
    kind = _DISCOVERY_KIND.match(raw)
    if request:
        parts = ["Monitoring request", request.group(1)]
    elif kind:
        parts = [f"{kind.group(1).capitalize()} discovery"]
        if "dry_run" in raw or "dry run" in raw.casefold():
            parts.append("test run")
    elif run_id.startswith(DATAFEED_PREFIX):
        # "Data Feed import · Kansas water actors · actors.xlsx · Oct 26, 2026"
        parts = [DATAFEED_LABEL, raw.removeprefix(f"{DATAFEED_LABEL}:").strip()]
    elif run_id.startswith(ACTOR_UPDATE_PREFIX):
        # "Actor update · CPower Energy · Oct 19, 2026": what an update wrote,
        # and anything it raised for a person (conflicts, links, hubs).
        # Stored descriptions still start "Actor update:"; the page says Organization update.
        parts = ["Organization update", raw.removeprefix("Actor update:").strip()]
    elif run_id.startswith(MAP_CHECKS_PREFIX) or raw.startswith("Architecture V2"):
        # Review items the map itself raised - a verification, a place that
        # would not geocode, a link or a hub to confirm. No run is behind them,
        # so no date; the review reason says which check each one is.
        return MAP_CHECKS_LABEL
    elif raw:
        # A Build the Map run: its description is what the person asked for.
        words = _UUID_PATTERN.sub("", raw).split()
        prompt = " ".join(words[:8]) + ("…" if len(words) > 8 else "")
        parts = ["Explore and Map", prompt]
    else:
        parts = ["Discovery run"]
    if day:
        parts.append(day)
    return " · ".join(part for part in parts if part)


# Why an item is waiting for a person, in plain words. The queue's review
# reason used to be the source's internal code - "rubric_band", "fuzzy_match",
# "relationship_review" - or nothing at all for most discovery results. It is
# now one of these, derived only from what the source recorded: the kind of
# review item, or the agent's own gate sentences (agents/discovery/search/
# actor_quality.py). Nothing is inferred from the payload.
_KIND_REASONS = {
    "fuzzy_match": "possible_duplicate",
    "possible_duplicate": "possible_duplicate",
    "rubric_band": "borderline_score",
    "geocode_failed": "location_unplaced",
    "relationship_review": "relationship_check",
}
# Most actionable first: the first sentence found names the reason.
_GATE_REASONS = (
    ("the page is about it, not by it", "third_party_page"),
    ("No official website is stated", "website_unverified"),
    ("presents this as a web page", "page_not_organisation"),
    ("does not mention the requested sub-topic", "focus_unconfirmed"),
    ("rubric criteria are evidenced", "thin_evidence"),
    ("does not establish that this is an operating organisation", "thin_evidence"),
    ("names no concrete programmes", "thin_evidence"),
    ("description is missing, too short, or a tagline", "weak_description"),
    ("engagement priority", "low_priority"),
    ("below the accept threshold", "borderline_score"),
)


def derive_review_reason(metadata: dict[str, Any], entity_type: Any = None) -> str | None:
    if "data_feed" in metadata:
        # Supplied by GHUS through the Data Feed: no agent scored it.
        return "possible_duplicate" if metadata.get("top_matches") else "data_feed"
    kind = str(metadata.get("review_kind") or "").strip()
    if kind:
        return _KIND_REASONS.get(kind, kind)
    if not metadata.get("source_table"):
        if metadata.get("review_run_source") or metadata.get("workflow"):
            return "map_agent"
        return None
    said = str(metadata.get("triage_reason") or "")
    for fragment, reason in _GATE_REASONS:
        if fragment in said:
            return reason
    if str(entity_type or "") == "person":
        # Section 6: a person is never created without a person deciding.
        return "new_person"
    if metadata.get("score_band") == "review" or "-> review" in said:
        return "borderline_score"
    return "new_record"


def _validate_actor_classification(payload: dict[str, Any]) -> None:
    """No invalid category/type pair can be stored (WS1, decisions D3 and D4).

    Lenient in exactly one direction: a legacy record whose ``actor_category``
    predates Architecture V2 and carries no type passes through untouched, and
    the Review screen shows its type as "Pending Classification" rather than
    pretending it is Not Applicable. The moment a reviewer supplies a type, the
    pair is held to the Intern Guide catalog.
    """

    category = str(payload.get("actor_category") or "").strip()
    category_type = str(payload.get("category_type") or "").strip()
    if not category_type:
        # Decision D4: a legacy NULL type stays NULL and displays as pending.
        payload["category_type"] = None
        return
    try:
        validate_pair(category, category_type, allow_null_type=False)
    except TaxonomyError as exc:
        raise ReviewValidationError(str(exc)) from exc
    if category_type == NOT_APPLICABLE and not str(payload.get("category_note") or "").strip():
        raise ReviewValidationError(
            "Not Applicable is a deliberate choice, not a stand-in for missing data. "
            "Give a one-line classification note saying what the doubt is."
        )


def _require_classification_for_new_record(entity_type: str, payload: dict[str, Any]) -> None:
    """Decision D4: a record created after the redesign always carries a type.

    This guards the authoritative admission path only — the one that reaches the
    canonical writer through ``promote()`` — and only for a NEW actor. Two cases
    are deliberately left alone:

      * confirming a candidate as the SAME as an existing record, which changes
        no classification of its own;
      * the local test-canonical mirror, which exists to exercise the flow with
        legacy fixtures that predate Architecture V2 classification.

    A legacy NULL type stays NULL and keeps displaying as "Pending
    Classification". If nothing in the catalog fits a new record, the reviewer
    chooses Not Applicable and writes the one-line note, which is a decision
    rather than a gap.
    """

    if entity_type != "actor":
        return
    try:
        validate_pair(
            payload.get("actor_category"), payload.get("category_type"), allow_null_type=False
        )
    except TaxonomyError as exc:
        raise ReviewValidationError(str(exc)) from exc


def _validate_actor_sector(payload: dict[str, Any]) -> None:
    """The primary sector is a controlled value, or deliberately absent.

    Hub membership is decided on sector, so an uncontrolled value here would
    silently stop an actor matching any hub. Blank means Not Applicable, which
    is a choice a reviewer is allowed to make.
    """

    code = str(payload.get("primary_sector") or "").strip().upper()
    if not code:
        payload["primary_sector"] = None
        return
    allowed = SELECTABLE_SECTOR_CODES | DATABASE_SECTOR_CODES
    if code not in allowed:
        raise ReviewValidationError(
            f"{code!r} is not one of the configured sectors: " + ", ".join(sorted(allowed))
        )
    payload["primary_sector"] = code


def _derive_actor_region(payload: dict[str, Any]) -> None:
    """Region is computed from the state, never accepted from the client (D8)."""

    if "state" in payload or "country" in payload or "region" in payload:
        payload["region"] = region_for_state(payload.get("state"), payload.get("country"))


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

    def persistence_warnings(self) -> list[str]:
        """Reasons this store may not survive a restart or a redeploy.

        Until PostgreSQL can record that a pre-promotion candidate was decided,
        this SQLite file is the ONLY place that knows. A rejected candidate
        stays rejected because its row is here; PostgreSQL keeps serving it, and
        `sync_external_candidates` only declines to re-insert because the row
        exists. Lose the file and every rejection silently becomes pending
        again — the queue refills with work a reviewer already refused, and
        nothing looks broken.

        So this file is durable application state, not a cache, and anything
        that makes it disposable is worth saying out loud at startup.
        """

        warnings: list[str] = []
        configured = os.environ.get("REVIEW_STORE_DB", "").strip()
        root = Path(__file__).resolve().parents[2]

        if not configured:
            warnings.append(
                "REVIEW_STORE_DB is not set, so review decisions are stored at the "
                f"in-repository default ({self.path}). A redeploy or a fresh "
                "checkout starts with an empty store and every rejected candidate "
                "returns to the queue. Set REVIEW_STORE_DB to a path on persistent "
                "storage that is backed up."
            )
        else:
            try:
                inside_repo = self.path.resolve().is_relative_to(root)
            except (OSError, ValueError):
                inside_repo = False
            if inside_repo:
                warnings.append(
                    f"REVIEW_STORE_DB points inside the repository ({self.path}). "
                    "Deployments replace the working tree, which would discard "
                    "every recorded review decision."
                )

        try:
            temp_root = Path(tempfile.gettempdir()).resolve()
            if self.path.resolve().is_relative_to(temp_root):
                warnings.append(
                    f"REVIEW_STORE_DB is under the system temporary directory "
                    f"({self.path}). That storage is not durable."
                )
        except (OSError, ValueError):
            pass

        if warnings:
            try:
                with self.connect() as db:
                    decided = db.execute(
                        "SELECT count(*) FROM review_decision"
                    ).fetchone()[0]
            except sqlite3.Error:
                decided = None
            if decided:
                warnings.append(
                    f"{decided} review decision(s) are already recorded in this "
                    "store and would be lost with it."
                )
        return warnings

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
                CREATE TABLE IF NOT EXISTS review_change_decision (
                    idempotency_key TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL REFERENCES review_candidate(candidate_id),
                    actor_id TEXT,
                    review_item_id TEXT NOT NULL,
                    field_key TEXT,
                    choice TEXT NOT NULL CHECK (choice IN
                        ('keep_current','use_new','keep_both','confirm','refuse')),
                    reviewer TEXT NOT NULL,
                    notes TEXT,
                    decided_at REAL NOT NULL,
                    outcome TEXT
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
                # A card another card now shows (an actor's update profile), or
                # one no longer served (an update run on an inactive sector).
                # The row is kept, decisions and all; it is only not listed.
                "folded_into": "TEXT",
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
                "SELECT id, description, result, created FROM runs "
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
                    cursor = db.execute(
                        "INSERT OR IGNORE INTO review_candidate "
                        "(candidate_id,source_run_id,source_index,source_description,entity_type,"
                        "display_name,original_payload,reviewed_payload,evidence,agent_metadata,"
                        "duplicate_state,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,? ,?)",
                        (candidate_id, run["id"], source_index, run["description"] or "",
                         entity_type, _candidate_name(entity_type, payload), _json(payload),
                         _json(_editable_payload(entity_type, payload)), _json(_evidence(payload)),
                         _json(_metadata(payload, result)),
                         _duplicate_state(payload), "pending_review", now),
                    )
                    inserted += cursor.rowcount
                    if not cursor.rowcount:
                        db.execute(
                            "UPDATE review_candidate SET evidence=?,agent_metadata=?,duplicate_state=? "
                            "WHERE candidate_id=? AND status='pending_review'",
                            (_json(_evidence(payload)), _json(_metadata(payload, result)),
                             _duplicate_state(payload), candidate_id),
                        )
        return inserted

    def sync_external_candidates(self, candidates: list[dict[str, Any]],
                                 retired: dict[str, str] | None = None) -> int:
        """Copy normalized candidates from a read-only external review source.

        The external source supplies an immutable stable key.  Existing pending
        candidates receive refreshed evidence and agent metadata only; reviewer
        edits and the original captured payload are never overwritten.

        A candidate may name the source keys it now shows (``folds``): an
        actor's update profile shows its earlier per-run cards and per-change
        items. Those rows, while still pending, are folded into it - kept, not
        listed. ``retired`` keys are no longer served at all (an update run on
        an inactive sector); their pending rows are folded away the same way.
        Decided rows are never touched.
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
                    # The run label is refreshed too (e.g. once a run is known to
                    # belong to a Discovery request); it is never a reviewer edit.
                    db.execute(
                        "UPDATE review_candidate SET evidence=?,agent_metadata=?,duplicate_state=?,"
                        "source_description=? WHERE candidate_id=? AND status='pending_review'",
                        (_json(evidence), _json(metadata), duplicate_state,
                         str(candidate.get("source_description") or "External discovery review"),
                         candidate_id),
                    )
                    # Refresh the captured payload too, but ONLY while the
                    # reviewer has not touched it. Enrichment runs after a
                    # candidate first appears - Light Pull fills in location,
                    # sector and the rest - and without this the screen keeps
                    # showing the empty first capture forever while the facts
                    # beside it update. The reviewed copy still wins the moment
                    # it differs from the original, so no edit is ever lost.
                    # "Untouched" means the reviewed copy is still exactly what
                    # the stored original yields. (Comparing the two raw copies
                    # never matched - the editable copy always drops a few
                    # internal keys - so nothing was ever refreshed.)
                    current = db.execute(
                        "SELECT original_payload, reviewed_payload FROM review_candidate "
                        "WHERE candidate_id=? AND status='pending_review'",
                        (candidate_id,),
                    ).fetchone()
                    if current is not None:
                        stored = json.loads(current["original_payload"] or "{}")
                        untouched = (json.loads(current["reviewed_payload"] or "{}")
                                     == _editable_payload(entity_type, stored))
                        if untouched:
                            db.execute(
                                "UPDATE review_candidate SET original_payload=?,"
                                "reviewed_payload=? WHERE candidate_id=? "
                                "AND status='pending_review'",
                                (_json(payload), _json(_editable_payload(entity_type, payload)),
                                 candidate_id),
                            )
            for candidate in candidates:
                folds = [str(key) for key in candidate.get("folds") or [] if key]
                if not folds:
                    continue
                target = _external_candidate_id(str(candidate["source_key"]).strip())
                db.executemany(
                    "UPDATE review_candidate SET folded_into=? WHERE candidate_id=? "
                    "AND candidate_id<>? AND status='pending_review'",
                    [(target, _external_candidate_id(key), target) for key in folds],
                )
                # The profile itself is always listed.
                db.execute("UPDATE review_candidate SET folded_into=NULL WHERE candidate_id=?",
                           (target,))
            for key, reason in (retired or {}).items():
                db.execute(
                    "UPDATE review_candidate SET folded_into=? WHERE candidate_id=? "
                    "AND status='pending_review' AND folded_into IS NULL",
                    (str(reason or "retired"), _external_candidate_id(str(key))),
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
        item["top_matches"] = item.get("agent_metadata", {}).get("top_matches") or []
        metadata = item.get("agent_metadata") or {}
        # The review reason drives the badge and the queue filter: why this item
        # is waiting for a person, from what its source recorded (see
        # derive_review_reason). Never inferred from the payload.
        item["review_reason"] = derive_review_reason(metadata, item.get("entity_type"))
        item["record_status"] = str(metadata.get("record_status") or "").strip() or None
        # View-level run grouping: one group per run, each with its own label.
        # (Runs before the redesign cutoff used to be merged into one backlog
        # group, which on a long-running database hid every run.)
        run_id = str(item.get("source_run_id") or "")
        item["run_group_key"] = MAP_CHECKS_KEY if run_id.startswith(MAP_CHECKS_PREFIX) else run_id
        item["run_label"] = _run_label(item.get("source_description"), item.get("source_run_id"),
                                       item.get("created_at"))
        metadata = item.get("agent_metadata") or {}
        item["run_trigger"] = _run_trigger(
            item.get("source_description"), item.get("source_run_id"),
            metadata.get("trigger_type"),
        )
        item["run_cadence"] = str(metadata.get("cadence") or "").strip() or None
        # Never defaulted and never inferred: an unknown initiator says so.
        item["run_initiated_by"] = str(metadata.get("initiated_by") or "").strip() or NOT_RECORDED
        return item

    def get(self, candidate_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM review_candidate WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise KeyError(candidate_id)
            item = self._decode(row)
            metadata = item.get("agent_metadata") or {}
            if metadata.get("review_kind") == "actor_profile":
                decided = [dict(r) for r in db.execute(
                    "SELECT review_item_id, field_key, choice, reviewer, notes, decided_at "
                    "FROM review_change_decision WHERE actor_id=? ORDER BY decided_at DESC",
                    (str(metadata.get("entity_id") or ""),),
                )]
                done = {d["review_item_id"] for d in decided}
                # Decided here but not yet re-read from the map: shown as decided.
                metadata["changes"] = [c for c in metadata.get("changes") or []
                                       if c.get("review_item_id") not in done]
                metadata["decided_changes"] = decided
        return item

    def list(self, *, status: str | None = "pending_review", entity_type: str | None = None,
             source_run_id: str | None = None, search: str | None = None,
             run_group: str | None = None, actor_category: str | None = None,
             review_reason: str | None = None, region: str | None = None) -> dict[str, Any]:
        if status not in (*STATUSES, None, "all"):
            raise ReviewValidationError("Unsupported review status.")
        if entity_type not in (*ENTITY_TYPES, None, "all"):
            raise ReviewValidationError("Unsupported entity type.")
        if actor_category and actor_category != "all" and actor_category not in CATEGORY_LABELS:
            raise ReviewValidationError("Unsupported actor category.")
        where, params = ["folded_into IS NULL"], []
        if status not in (None, "all"):
            where.append("status=?"); params.append(status)
        if entity_type not in (None, "all"):
            where.append("entity_type=?"); params.append(entity_type)
        if source_run_id:
            where.append("source_run_id=?"); params.append(source_run_id)
        if search and search.strip():
            where.append("(lower(display_name) LIKE ? OR lower(reviewed_payload) LIKE ?)")
            needle = f"%{search.strip().casefold()}%"
            params.extend((needle, needle))
        if run_group == MAP_CHECKS_KEY:
            where.append("source_run_id LIKE ?")
            params.append(f"{MAP_CHECKS_PREFIX}%")
        elif run_group and run_group != "all":
            where.append("source_run_id=?")
            params.append(run_group)
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM review_candidate" + clause +
                " ORDER BY CASE status WHEN 'pending_review' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, created_at",
                params,
            ).fetchall()
            counts = {row["status"]: row["n"] for row in db.execute(
                "SELECT status,count(*) AS n FROM review_candidate WHERE folded_into IS NULL "
                "GROUP BY status"
            )}
            maps = [dict(row) for row in db.execute(
                "SELECT source_run_id, max(source_description) AS description, count(*) AS candidate_count "
                "FROM review_candidate WHERE folded_into IS NULL GROUP BY source_run_id "
                "ORDER BY source_run_id"
            )]
        candidates = [self._decode(row) for row in rows]
        # Category, review reason and region live inside JSON payloads, so they
        # are filtered after decoding rather than in SQL. Deterministic either
        # way: the SQL order is preserved.
        if actor_category and actor_category != "all":
            candidates = [
                item for item in candidates
                if str(item["reviewed_payload"].get("actor_category") or "") == actor_category
            ]
        # The reason filter offers only the reasons actually waiting, with how
        # many: counted before it is applied, so choosing one keeps the others
        # in the list.
        reason_counts: dict[str, int] = {}
        for item in candidates:
            if item.get("review_reason"):
                reason_counts[item["review_reason"]] = reason_counts.get(item["review_reason"], 0) + 1
        if review_reason and review_reason != "all":
            candidates = [item for item in candidates if item.get("review_reason") == review_reason]
        if region and region != "all":
            candidates = [
                item for item in candidates
                if region_for_state(
                    item["reviewed_payload"].get("state"),
                    item["reviewed_payload"].get("country"),
                ) == region
            ]
        return {
            "candidates": candidates,
            "counts": {key: counts.get(key, 0) for key in STATUSES},
            "source_maps": maps,
            "run_groups": self.run_groups(),
            "reason_counts": dict(sorted(reason_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
            "review_redesign_cutoff": review_redesign_cutoff(),
            "admission_configured": self.admission_configured,
            "last_sync": self.sync_state(),
        }

    def run_groups(self) -> list[dict[str, Any]]:
        """Queue groups: one per run, newest first, each with a readable label.

        A pure projection over what is already stored. Deterministic: newest
        run first, then by run id, so the same data always renders the same
        queue. Discovery requests, open-web runs, Build the Map runs and the
        map's own checks sit side by side, each labelled for what it is.
        """

        with self.connect() as db:
            rows = db.execute(
                "SELECT source_run_id, max(source_description) AS description, "
                "count(*) AS candidate_count, min(created_at) AS earliest, "
                "max(created_at) AS latest, "
                "sum(CASE WHEN status='pending_review' THEN 1 ELSE 0 END) AS pending_count, "
                "group_concat(DISTINCT entity_type) AS entity_types "
                "FROM review_candidate WHERE folded_into IS NULL GROUP BY source_run_id"
            ).fetchall()
            by_status = db.execute(
                "SELECT source_run_id, status, count(*) AS n FROM review_candidate "
                "WHERE folded_into IS NULL GROUP BY source_run_id, status"
            ).fetchall()
        status_counts: dict[str, dict[str, int]] = {}
        for row in by_status:
            status_counts.setdefault(str(row["source_run_id"]), {})[str(row["status"])] = int(row["n"])
        groups: list[dict[str, Any]] = []
        checks: dict[str, Any] | None = None
        for row in rows:
            if str(row["source_run_id"] or "").startswith(MAP_CHECKS_PREFIX):
                if checks is None:
                    checks = {
                        "key": MAP_CHECKS_KEY, "label": MAP_CHECKS_LABEL, "trigger": None,
                        "trigger_label": None, "initiated_by": NOT_RECORDED,
                        "candidate_count": 0, "pending_count": 0, "earliest": 0.0,
                        "latest": 0.0, "is_backlog": False, "source_run_ids": [],
                        "run_type": "map_checks", "run_name": MAP_CHECKS_LABEL, "run_date": None,
                        "status_counts": {},
                    }
                checks["candidate_count"] += int(row["candidate_count"] or 0)
                checks["pending_count"] += int(row["pending_count"] or 0)
                checks["latest"] = max(checks["latest"], float(row["latest"] or 0))
                checks["source_run_ids"].append(row["source_run_id"])
                for status, n in status_counts.get(str(row["source_run_id"]), {}).items():
                    checks["status_counts"][status] = checks["status_counts"].get(status, 0) + n
                continue
            trigger = _run_trigger(row["description"], row["source_run_id"])
            groups.append({
                "key": row["source_run_id"],
                "label": _run_label(row["description"], row["source_run_id"], row["earliest"]),
                "trigger": trigger,
                "trigger_label": TRIGGER_LABELS[trigger],
                "initiated_by": NOT_RECORDED,
                "candidate_count": int(row["candidate_count"] or 0),
                "pending_count": int(row["pending_count"] or 0),
                "earliest": float(row["earliest"] or 0),
                "latest": float(row["latest"] or 0),
                "is_backlog": False,
                "source_run_ids": [row["source_run_id"]],
                "run_type": run_type_of(row["source_run_id"], row["entity_types"]),
                "run_name": run_name(row["description"], row["source_run_id"]),
                "run_date": _short_day(row["earliest"]) or None,
                "status_counts": status_counts.get(str(row["source_run_id"]), {}),
            })
        groups.sort(key=lambda group: (-group["latest"], str(group["key"])))
        if checks is not None:
            checks["source_run_ids"].sort(key=str)
            # Ongoing rather than a run: listed after the runs, always in the same place.
            groups.append(checks)
        # Two runs of the same kind on the same day would read identically
        # ("Actor discovery · test run · Oct 7, 2026" twice): give those the time.
        seen: dict[str, int] = {}
        for group in groups:
            seen[group["label"]] = seen.get(group["label"], 0) + 1
        for group in groups:
            if seen[group["label"]] > 1 and group["earliest"]:
                stamp = datetime.fromtimestamp(group["earliest"], tz=timezone.utc)
                group["label"] = f"{group['label']} · {stamp:%H:%M} UTC"
                if group.get("run_date"):
                    group["run_date"] = f"{group['run_date']} · {stamp:%H:%M} UTC"
        return groups

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
                try:
                    cleaned[field] = _clean_text(cleaned[field], max_length=limit)
                except ReviewValidationError as exc:
                    # Which field, and by how much. The agent sometimes writes a
                    # sentence into a short column ("Government agency managing
                    # state water resources" into the 30-character lifecycle
                    # role); without the field name a reviewer could not tell
                    # what to shorten, and the candidate could never be decided.
                    raise ReviewValidationError(
                        f"{reviewFieldName(field)} is {len(cleaned[field])} characters; "
                        f"the limit is {limit}. Shorten it to save this record."
                    ) from exc
        cleaned["name"] = _clean_text(
            cleaned.get("name"), required=True,
            max_length=FIELD_LIMITS[entity_type]["name"],
        )
        if entity_type == "actor":
            _validate_actor_classification(cleaned)
            _validate_actor_sector(cleaned)
            _derive_actor_region(cleaned)
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
        keep_both: bool = False,
        notes: str | None = None,
        edited_payload: dict[str, Any] | None = None,
        hub_ids: list[str] | None = None,
        proposed_hub: dict[str, Any] | None = None,
        rejection_reason: str | None = None,
        rejection_reason_other: str | None = None,
        confirmed: bool = False,
        ghus_notes: str | None = None,
    ) -> dict[str, Any]:
        """Validate and shape the authoritative admission request without writing it."""
        if decision_kind not in DECISION_KINDS:
            raise ReviewValidationError("Unsupported review decision.")
        reviewer = _clean_text(reviewer, required=True, max_length=120)
        idempotency_key = _clean_text(idempotency_key, required=True, max_length=200)
        notes = _clean_text(notes, max_length=5000)
        # GHUS analyst notes ("written only by GHUS"): kept on the actor or event
        # it admits, by the backend's approved writer. People have no notes yet.
        ghus_notes = _clean_text(ghus_notes, max_length=5000)
        if confirmed is not True:
            raise ReviewValidationError("Explicit confirmation is required.")
        candidate = self.get(candidate_id)
        if candidate["status"] != "pending_review":
            raise ReviewConflict("This candidate has already been decided.")
        metadata = candidate["agent_metadata"]
        if ghus_notes and candidate["entity_type"] not in {"actor", "event"}:
            raise ReviewValidationError("Analyst notes are kept for organizations and events only.")
        if ghus_notes and decision_kind not in {"new", "same_existing"}:
            raise ReviewValidationError("Analyst notes are saved when the record is verified.")
        if candidate.get("folded_into"):
            raise ReviewConflict("This card is now part of the actor's update profile; "
                                 "decide it there.")
        if (metadata.get("review_kind") == "actor_profile" and decision_kind == "new"
                and metadata.get("changes")):
            raise ReviewValidationError(
                f"Decide the {len(metadata['changes'])} change(s) to review first.")
        if keep_both:
            field_key = (metadata.get("fact_change") or {}).get("field_key") or (
                metadata.get("pipeline") or {}).get("field_key")
            if (decision_kind != "new" or metadata.get("source_table") != "review_item"
                    or metadata.get("review_kind") not in FACT_REVIEW_KINDS
                    or field_key != "location"):
                raise ReviewValidationError("Keep both is available only for a location fact review.")

        if str(metadata.get("source_table") or "") == "actor_update":
            # What an update wrote is already on the map, through the backend's
            # fact writer, with its sources and history. A reviewer says it
            # looks right, or flags it with a note; neither changes the map.
            if decision_kind not in {"new", "reject"}:
                raise ReviewValidationError("Say it looks right or flag it; or leave it.")
            return {
                "decision_kind": "acknowledge_update", "local_only": True,
                "looks_right": decision_kind == "new", "run_id": metadata.get("run_id"),
                "actor_id": metadata.get("entity_id"), "reviewer": reviewer, "notes": notes,
                "idempotency_key": idempotency_key,
            }
        pipeline = metadata.get("pipeline") if isinstance(metadata.get("pipeline"), dict) else {}
        from_item = str(metadata.get("source_table") or "") == "review_item"
        review_kind = str(metadata.get("review_kind") or "")
        if from_item and review_kind == "relationship_review":
            # A link between two actors: confirm it (with its source) or not.
            # The edge is written by the backend's approved writer, never here.
            if decision_kind not in {"new", "reject"}:
                raise ReviewValidationError(
                    "Confirm the link or say it is not one; or leave it in the queue.")
            source_url = str(pipeline.get("source_url") or "").strip()
            if decision_kind == "new" and not source_url:
                raise ReviewValidationError(
                    "This link has no source page on record, so it cannot be confirmed here. "
                    "Say it is not a link, or leave it in the queue.")
            return {
                "decision_kind": "resolve_relationship",
                "review_item_id": str(metadata.get("review_item_id") or ""),
                "approve": decision_kind == "new",
                "source_url": source_url or None,
                "relationship_type": pipeline.get("proposed_relationship_type"),
                "reviewer": reviewer,
                "notes": notes,
                "idempotency_key": idempotency_key,
            }
        if from_item and review_kind == "hub_assignment" and pipeline.get("proposal") == "membership":
            # A hub an unassigned actor now fits: add it, or keep it out.
            if decision_kind not in {"new", "reject"}:
                raise ReviewValidationError(
                    "Add it to the hub or keep it out; or leave it in the queue.")
            return {
                "decision_kind": "resolve_hub_membership",
                "review_item_id": str(metadata.get("review_item_id") or ""),
                "accept": decision_kind == "new",
                "reviewer": reviewer,
                "notes": notes,
                "idempotency_key": idempotency_key,
            }
        if (str(metadata.get("source_table") or "") == "review_item"
                and str(metadata.get("review_kind") or "") in FACT_REVIEW_KINDS):
            # Two values for one box: the one on the map and one an update
            # found. "Use the new value" (new) or "Keep the current value"
            # (reject); the backend's approved writer keeps both facts either way.
            if decision_kind not in {"new", "reject"}:
                raise ReviewValidationError(
                    "Choose the new value or keep the current one; or leave it in the queue.")
            return {
                "decision_kind": "resolve_fact",
                "review_item_id": str(metadata.get("review_item_id") or ""),
                "accept": decision_kind == "new" and not keep_both,
                **({"keep_both": True} if keep_both else {}),
                "reviewer": reviewer,
                "notes": notes,
                "idempotency_key": idempotency_key,
            }
        if decision_kind == "same_existing" and not str(target_id or "").strip():
            raise ReviewValidationError("Select the existing record for a same-existing decision.")
        if decision_kind == "reject":
            if rejection_reason not in REJECTION_REASONS:
                raise ReviewValidationError("Select one of the fixed rejection reasons.")
            if rejection_reason == "Other" and not str(rejection_reason_other or "").strip():
                raise ReviewValidationError("Explain the Other rejection reason.")
        if (str(metadata.get("source_table") or "") == "review_item"
                and str(metadata.get("review_kind") or "") == "verify_actor"):
            # The actor already exists (Parked). Verify / Reject here is the
            # GHUS topic-level verification decision on it - the one Deep Pull
            # requires - applied by the backend's approved writer. Nothing is
            # created and no field is edited by this decision.
            if decision_kind not in {"new", "same_existing", "reject"}:
                raise ReviewValidationError(
                    "An actor awaiting verification is verified or rejected; "
                    "leave it in the queue to decide later.")
            return {
                "decision_kind": "verify_actor",
                "review_item_id": str(metadata.get("review_item_id") or ""),
                "verified": decision_kind != "reject",
                "rejection_reason": rejection_reason if decision_kind == "reject" else None,
                "reviewer": reviewer,
                "notes": notes,
                "ghus_notes": ghus_notes,
                "idempotency_key": idempotency_key,
            }
        payload = edited_payload if edited_payload is not None else candidate["reviewed_payload"]
        payload = self.validate_payload(candidate["entity_type"], payload)
        if decision_kind == "new":
            _require_classification_for_new_record(candidate["entity_type"], payload)
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
            "ghus_notes": ghus_notes,
            "idempotency_key": idempotency_key,
        }

    CHANGE_CHOICES = {
        "fact": ("keep_current", "use_new", "keep_both"),
        "relationship": ("confirm", "refuse"),
        "hub": ("confirm", "refuse"),
        "category_type": ("confirm", "refuse"),
    }

    def change_request(self, candidate_id: str, review_item_id: str, *, choice: str,
                       reviewer: str, idempotency_key: str, notes: str | None = None,
                       confirmed: bool = False) -> dict[str, Any]:
        """Shape one change decision on an actor's update profile, without writing it.

        The change is one the map raised and still holds pending: a value to
        keep or replace, a link to confirm, a hub to join. The backend's
        approved writer applies it; nothing is written here.
        """
        reviewer = _clean_text(reviewer, required=True, max_length=120)
        idempotency_key = _clean_text(idempotency_key, required=True, max_length=200)
        notes = _clean_text(notes, max_length=5000)
        if confirmed is not True:
            raise ReviewValidationError("Explicit confirmation is required.")
        candidate = self.get(candidate_id)
        metadata = candidate["agent_metadata"]
        if metadata.get("review_kind") != "actor_profile":
            raise ReviewValidationError("Only an actor's update profile holds changes.")
        if candidate["status"] != "pending_review":
            raise ReviewConflict("This profile has already been reviewed.")
        change = next((c for c in metadata.get("changes") or []
                       if c.get("review_item_id") == review_item_id), None)
        if change is None:
            raise ReviewConflict("This change has already been decided, or is no longer pending.")
        allowed = self.CHANGE_CHOICES.get(change.get("kind"), ())
        if choice not in allowed:
            raise ReviewValidationError("Unsupported choice for this change.")
        if choice == "keep_both" and not change.get("can_keep_both"):
            raise ReviewValidationError(
                "Keep both applies only to a location: every other box holds one current value.")
        base = {"review_item_id": review_item_id, "reviewer": reviewer, "notes": notes,
                "idempotency_key": idempotency_key}
        if change["kind"] == "fact":
            return {**base, "decision_kind": "resolve_fact", "accept": choice == "use_new",
                    "keep_both": choice == "keep_both"}
        if change["kind"] == "relationship":
            source_url = str(change.get("source_url") or "").strip()
            if choice == "confirm" and not source_url:
                raise ReviewValidationError(
                    "This link has no source page on record, so it cannot be confirmed here.")
            return {**base, "decision_kind": "resolve_relationship", "approve": choice == "confirm",
                    "source_url": source_url or None,
                    "relationship_type": change.get("relationship_type")}
        if change["kind"] == "category_type":
            return {**base, "decision_kind": "resolve_category_type",
                    "accept": choice == "confirm"}
        return {**base, "decision_kind": "resolve_hub_membership", "accept": choice == "confirm"}

    def record_change_decision(self, candidate_id: str, review_item_id: str, *, choice: str,
                               reviewer: str, idempotency_key: str, notes: str | None,
                               outcome: dict[str, Any]) -> dict[str, Any]:
        """Record an applied change decision; the profile lists it as decided at once."""
        candidate = self.get(candidate_id)
        metadata = candidate["agent_metadata"]
        change = next((c for c in metadata.get("changes") or []
                       if c.get("review_item_id") == review_item_id), {})
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO review_change_decision (idempotency_key,candidate_id,actor_id,"
                "review_item_id,field_key,choice,reviewer,notes,decided_at,outcome) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(idempotency_key) DO NOTHING",
                (idempotency_key, candidate_id, str(metadata.get("entity_id") or ""),
                 review_item_id, change.get("field_key"), choice,
                 _clean_text(reviewer, required=True, max_length=120),
                 _clean_text(notes, max_length=5000), _now(), _json(outcome)),
            )
        return self.get(candidate_id)

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

    def category_decision_request(
        self,
        candidate_ids: list[str],
        *,
        reviewer: str,
        idempotency_key: str,
        notes: str | None = None,
        categories: dict[str, str] | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Shape one all-or-nothing GHUS category confirmation for category_doubt reviews.

        Each item confirms the category shown in the reviewed record (or an explicit
        override). Collections of organizations are refused: they need a separate
        GHUS disposition, not a category.
        """
        reviewer = _clean_text(reviewer, required=True, max_length=120)
        idempotency_key = _clean_text(idempotency_key, required=True, max_length=200)
        notes = _clean_text(notes, max_length=5000)
        if confirmed is not True:
            raise ReviewValidationError("Explicit confirmation is required.")
        ids = list(dict.fromkeys(
            str(value).strip() for value in candidate_ids or [] if str(value).strip()
        ))
        if not ids:
            raise ReviewValidationError("Select at least one category review.")
        if len(ids) > 500:
            raise ReviewValidationError("Confirm at most 500 categories at once.")
        overrides = categories or {}
        items = []
        for candidate_id in ids:
            candidate = self.get(candidate_id)
            name = candidate["display_name"]
            if candidate["status"] != "pending_review":
                raise ReviewConflict(f"{name} has already been decided.")
            metadata = candidate["agent_metadata"]
            if (metadata.get("source_table") != "review_item"
                    or metadata.get("review_kind") != "category_doubt"):
                raise ReviewValidationError(f"{name} is not a category review.")
            if (metadata.get("pipeline") or {}).get("is_true_aggregate"):
                raise ReviewValidationError(
                    f"{name} is a collection of organizations; it needs a GHUS disposition, "
                    "not a category."
                )
            category = _clean_text(
                overrides.get(candidate_id) or candidate["reviewed_payload"].get("actor_category"),
                max_length=80,
            )
            if not category:
                raise ReviewValidationError(f"Choose an actor category for {name}.")
            items.append({
                "candidate_id": candidate_id,
                "review_item_id": str(metadata.get("review_item_id")),
                "actor_category": category,
            })
        return {
            "decision_kind": "confirm_category",
            "reviewer": reviewer,
            "idempotency_key": idempotency_key,
            "notes": notes,
            "items": items,
        }

    LOCATION_REVIEW_KINDS = ("geocode", "geocode_failed")

    def review_item_decision_request(
        self,
        candidate_id: str,
        *,
        decision_kind: str,
        reviewer: str,
        idempotency_key: str,
        notes: str | None = None,
        city: str | None = None,
        state: str | None = None,
        country: str | None = None,
        keep_unlocated: bool = False,
        approve: bool = False,
        source_url: str | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Shape a GHUS decision on a V2 location or relationship review item."""
        reviewer = _clean_text(reviewer, required=True, max_length=120)
        idempotency_key = _clean_text(idempotency_key, required=True, max_length=200)
        notes = _clean_text(notes, max_length=5000)
        if confirmed is not True:
            raise ReviewValidationError("Explicit confirmation is required.")
        candidate = self.get(candidate_id)
        if candidate["status"] != "pending_review":
            raise ReviewConflict(f"{candidate['display_name']} has already been decided.")
        metadata = candidate["agent_metadata"]
        kind = metadata.get("review_kind")
        if metadata.get("source_table") != "review_item":
            raise ReviewValidationError("This candidate is not a V2 review item.")
        request: dict[str, Any] = {
            "decision_kind": decision_kind,
            "reviewer": reviewer,
            "idempotency_key": idempotency_key,
            "notes": notes,
            "review_item_id": str(metadata.get("review_item_id")),
            "candidate_id": candidate_id,
        }
        if decision_kind == "resolve_location":
            if kind not in self.LOCATION_REVIEW_KINDS:
                raise ReviewValidationError("This is not a location review.")
            if keep_unlocated:
                if not notes:
                    raise ReviewValidationError("Explain why the actor stays unlocated.")
            elif not (_clean_text(city) and _clean_text(state)):
                raise ReviewValidationError("Enter the actor's city and state.")
            request.update({"city": _clean_text(city, max_length=120),
                            "state": _clean_text(state, max_length=80),
                            "country": _clean_text(country, max_length=80) or "US",
                            "keep_unlocated": bool(keep_unlocated)})
        elif decision_kind == "resolve_relationship":
            if kind != "relationship_review":
                raise ReviewValidationError("This is not a relationship review.")
            if approve and not _clean_text(source_url):
                raise ReviewValidationError("Approving a relationship needs its source URL.")
            request.update({"approve": bool(approve),
                            "source_url": _clean_text(source_url, max_length=2000)})
        else:
            raise ReviewValidationError("Unsupported review item decision.")
        return request

    def record_review_item_success(
        self, request: dict[str, Any], outcome: dict[str, Any]
    ) -> dict[str, Any]:
        """Mark the local candidate decided once GHUS has committed the decision."""
        rejected = request["decision_kind"] == "resolve_relationship" and not request.get("approve")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE review_candidate SET status=?,decision_kind=?,admission_state='applied',"
                "admission_error=NULL,admission_outcome=?,reviewed_at=?,reviewer=?,review_notes=? "
                "WHERE candidate_id=? AND status='pending_review'",
                ("rejected_by_reviewer" if rejected else "approved", request["decision_kind"],
                 _json(outcome), _now(), request["reviewer"], request["notes"],
                 request["candidate_id"]),
            )
        return self.get(request["candidate_id"])

    def record_category_success(
        self, request: dict[str, Any], outcome: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Mark confirmed category reviews decided once GHUS has committed them."""
        now = _now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for item in request["items"]:
                db.execute(
                    "UPDATE review_candidate SET status='approved',decision_kind='confirm_category',"
                    "admission_state='applied',admission_error=NULL,admission_outcome=?,"
                    "reviewed_at=?,reviewer=?,review_notes=? "
                    "WHERE candidate_id=? AND status='pending_review'",
                    (_json(outcome), now, request["reviewer"], request["notes"],
                     item["candidate_id"]),
                )
        return [self.get(item["candidate_id"]) for item in request["items"]]

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
