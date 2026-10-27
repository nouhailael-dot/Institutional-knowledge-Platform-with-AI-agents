"""Stage records a GHUS person supplied through the Data Feed, for Review.

    python -m agents.datafeed.stage_import --batch BATCH.json            # check only
    python -m agents.datafeed.stage_import --batch BATCH.json --live     # stage

The platform's Data Feed page (spreadsheet upload or manual form) validates
and previews a batch, then hands it here. Nothing canonical is written: each
record is staged exactly where open-web discovery stages its finds -

    actor   -> search_candidate (score_band 'review')
    event   -> staged_record + event_review_queue
    person  -> staged_record + source + person_review_queue

- so it appears in Review, and only a GHUS reviewer's decision admits it,
through ``agents.review.admission`` and the approved writer
``agents.discovery.promote``. Admitted records are labelled with their origin
(``ghus_uploaded_doc`` or ``ghus_manual``) and start Parked; nothing here or
there makes a record Verified.

Check mode (the default) applies the backend's own rules to every row and
reads the database (records already waiting in Review, match targets), but
writes nothing. ``--live`` also needs ``DATAFEED_WRITES_ENABLED=true``; it
re-checks, refuses the whole batch if any row fails, and stages everything in
ONE transaction: an interrupted import leaves nothing behind and can simply be
sent again. Sending the same batch twice stages it once (``batch_key``), and a
row identical to one already waiting in Review from an earlier import is not
staged again.

Admission. Every live batch names its uploader and carries their attestation
that the records come from a GHUS source; that is recorded with the import.
``admission`` is "review" (the default: every record waits in Review) or
"verified": the uploader also attests they are authorized GHUS staff verifying
these records (policy of 2026-10-26, migration 590). Then each NEW actor with a
category type is admitted at once through ``agents.review.admission`` - the
approved path, entity resolution included - and verified by a labelled
``ghus_import`` event naming the uploader and the file and row. A record that
matches one on the map, lacks a type, or that admission refuses stays in
Review, and the result says why. Events and people always go to Review.

Output: one JSON object on stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]

CONTRACT = "ghus-datafeed-batch/1"
SOURCE_NAME = "ghus_data_feed"
RECORD_TYPES = ("actor", "event", "person")
ADMISSIONS = ("review", "verified")
METHODS = {"upload": "ghus_uploaded_doc", "manual": "ghus_manual"}
# Per-fact origin vocabulary (source_origin_definition, Architecture V2 190).
FACT_ORIGINS = {"upload": "uploaded_document", "manual": "ghus_manual"}
MAX_ROWS = 1000
MAX_TEXT = 4000
REJECT_KEYS = re.compile(r"^_")          # no pipeline-internal key from outside
RECURRENCE = ("annual", "recurring", "one_time")
EVENT_FORMATS = ("in_person", "online", "hybrid")
PARENT_LINKS = ("unit_of", "operated_by")
SECTOR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,19}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# Light Pull boxes a person may supply as plain text. Rankings and a startup's
# stage/TRL need structured, published evidence and stay with the Light Pull
# reader; who/where/what boxes are the record's own columns.
SUPPLIED_LIGHT_BOXES = frozenset({
    "recent_activity", "funding_signal", "international_connection", "um6p_ocp_connection",
    "topic_unit_and_work", "institution_control", "land_grant_designation",
    "relevant_centers_programs", "parent_and_center_type", "topic_research_focus",
    "active_recent_projects", "main_funders", "sponsoring_agency",
    "formal_national_designation", "topic_program_area", "facility_type_operator",
    "testing_demonstration_scope", "current_project", "clinical_research_focus",
    "parent_academic_link", "hospital_type_scale", "current_initiative",
    "ownership_and_size", "topic_business_segment_product", "mapped_geography_operations",
    "technology_and_problem", "founding_year_location", "funding_stage",
    "pilot_customer_evidence", "platform_type_operator", "sector_focus",
    "platform_offerings", "scale_indicator", "investor_type_headquarters",
    "sector_stage_focus", "geographic_focus", "published_fund_size",
    "topic_investment_thesis", "jurisdiction_parent_agency", "topic_mandate_program",
    "visible_funding_programs", "mission_sector_focus", "relevant_program",
    "programs_grant_themes", "association_type", "sector_geographic_scope", "member_types",
    "current_initiative_working_group", "linked_members", "network_scope_locations",
})
PERSON_FACTS = ("bio", "department", "expertise", "work_location", "relevant_work")


class DataFeedRefused(ValueError):
    """The batch cannot be staged; the message says why, in plain words."""


# ------------------------------------------------------------------ helpers
def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def slug(value: Any) -> str:
    text_ = unicodedata.normalize("NFKD", _clean(value).casefold())
    text_ = "".join(ch for ch in text_ if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "-", text_).strip("-")


def _url(value: Any) -> str | None:
    raw = _clean(value)
    if not raw:
        return None
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname or "." not in parts.hostname:
        raise DataFeedRefused(f"{raw[:80]!r} is not a web address (http:// or https://)")
    return raw


def _day(value: Any, label: str) -> str | None:
    raw = _clean(value)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError as exc:
        raise DataFeedRefused(f"{label} {raw!r} is not a date (YYYY-MM-DD)") from exc


def domain_of(url: str | None) -> str | None:
    from agents.discovery.search.actor_quality import registrable_domain

    return registrable_domain(url) if url else None


def natural_key(record_type: str, payload: Mapping[str, Any]) -> str:
    """One identity key per record, the same however often it is sent."""
    if record_type == "actor":
        domain = domain_of(payload.get("website"))
        if domain:
            return f"actor|{domain}"
        return f"actor|{slug(payload.get('name'))}|{_clean(payload.get('state_code')).upper()}"
    if record_type == "event":
        return f"{slug(payload.get('name'))}|{payload.get('start_date') or 'undated'}"
    return f"{slug(payload.get('name'))}|{slug(payload.get('affiliation'))}"


def batch_key(batch: Mapping[str, Any]) -> str:
    """Same file (or same manual records) of the same type -> same key."""
    basis: dict[str, Any] = {
        "record_type": batch.get("record_type"),
        "template_version": batch.get("template_version"),
        "method": batch.get("method"),
    }
    if batch.get("method") == "upload" and batch.get("file_sha256"):
        basis["file_sha256"] = batch["file_sha256"]
    else:
        basis["rows"] = [row.get("payload") for row in batch.get("rows") or []]
    raw = json.dumps(basis, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ checks
def check_header(batch: Mapping[str, Any]) -> None:
    if batch.get("contract") != CONTRACT:
        raise DataFeedRefused(f"unsupported batch contract {batch.get('contract')!r}")
    if batch.get("record_type") not in RECORD_TYPES:
        raise DataFeedRefused("record_type must be actor, event or person")
    if batch.get("method") not in METHODS:
        raise DataFeedRefused("method must be upload or manual")
    if not _clean(batch.get("template_version")):
        raise DataFeedRefused("template_version is required")
    if not _clean(batch.get("import_name")) or len(_clean(batch.get("import_name"))) > 120:
        raise DataFeedRefused("an import name of 1-120 characters is required")
    if batch.get("method") == "upload" and not re.fullmatch(
            r"[0-9a-f]{64}", str(batch.get("file_sha256") or "")):
        raise DataFeedRefused("an uploaded batch needs the file's SHA-256")
    rows = batch.get("rows")
    if not isinstance(rows, list) or not rows:
        raise DataFeedRefused("the batch has no records")
    if len(rows) > MAX_ROWS:
        raise DataFeedRefused(f"at most {MAX_ROWS} records per import")
    admission = batch.get("admission") or "review"
    if admission not in ADMISSIONS:
        raise DataFeedRefused("admission must be review or verified")
    if admission == "verified":
        attestation = batch.get("attestation") or {}
        if batch.get("record_type") != "actor":
            raise DataFeedRefused("only organizations can be imported as Verified; events and "
                                  "people go to Review")
        if not _clean(batch.get("uploaded_by")):
            raise DataFeedRefused("importing as Verified needs the uploader's name")
        if not (attestation.get("source") is True and attestation.get("authorized") is True):
            raise DataFeedRefused("importing as Verified needs the uploader's attestation of "
                                  "the source and of their authority")


def check_uploader(batch: Mapping[str, Any]) -> None:
    """A live import names who sends it, and they confirm where it comes from."""
    if not _clean(batch.get("uploaded_by")) or len(_clean(batch.get("uploaded_by"))) > 120:
        raise DataFeedRefused("the uploader's name (1-120 characters) is required")
    if (batch.get("attestation") or {}).get("source") is not True:
        raise DataFeedRefused("the uploader must confirm the records come from a GHUS source")


def _text_fields(payload: Mapping[str, Any]) -> None:
    for key, value in payload.items():
        if REJECT_KEYS.match(str(key)):
            raise DataFeedRefused(f"field {key!r} cannot be supplied")
        if isinstance(value, str) and len(value) > MAX_TEXT:
            raise DataFeedRefused(f"{key} is longer than {MAX_TEXT} characters")


def check_actor(payload: Mapping[str, Any], *, method: str, submitted_at: str) -> list[str]:
    from agents.collection.light_pull import _fact
    from agents.common.actor_classification import CATCH_ALL_TYPE_CODES, load_category_catalog

    problems: list[str] = []
    if not _clean(payload.get("name")):
        problems.append("Official name is required.")
    category = _clean(payload.get("actor_category"))
    type_code = _clean(payload.get("category_type"))
    catalog = load_category_catalog()
    if category not in catalog.by_code:
        problems.append(f"Actor Category {category or '(empty)'!r} is not one of the 12 categories.")
    elif type_code and not catalog.validates(category, type_code):
        problems.append(f"Category Type {type_code!r} is not a type of {category!r}.")
    if (type_code in CATCH_ALL_TYPE_CODES or payload.get("category_needs_review")) \
            and not _clean(payload.get("category_note")):
        problems.append("A 'Not Applicable' type or a flagged category needs a one-line note.")
    from agents.collection.light_pull import _sentence_count
    from agents.common.actor_classification import (
        ActorClassificationError,
        classification_from_payload,
    )

    description = _clean(payload.get("description"))
    if not description:
        problems.append("Description is required: it is the evidence of the organization's "
                        "main job.")
    elif not 1 <= _sentence_count(description) <= 3:
        problems.append("Description must be 1-3 sentences.")
    if description and type_code:
        # The same V2 classification rules admission applies (a national lab's
        # designation, a startup's stage and origin...), checked now rather than
        # at Review. Without a type the record waits for one in Review.
        try:
            classification_from_payload(
                {**payload, "classification_evidence": classification_evidence(payload)})
        except ActorClassificationError as exc:
            problems.append(f"Classification: {exc}.")
    try:
        website = _url(payload.get("website"))
        source = _url(payload.get("source_url"))
    except DataFeedRefused as exc:
        problems.append(str(exc))
        website = source = None
    if not (website or source):
        problems.append("A Website or a Source URL is required, so the record can be checked.")
    for code in [payload.get("primary_sector"), *(payload.get("sector_codes") or [])]:
        if _clean(code) and not SECTOR_CODE.match(_clean(code)):
            problems.append(f"{code!r} is not a sector code.")
    topic = _clean(payload.get("topic_id"))
    if topic and not UUID_RE.match(topic):
        problems.append("topic_id must be a topic's id.")
    parent = payload.get("parent_connection")
    if parent is not None and (
            not isinstance(parent, Mapping) or parent.get("relationship_type") not in PARENT_LINKS
            or not UUID_RE.match(_clean(parent.get("actor_id")))):
        problems.append("A parent link needs an existing parent and 'unit_of' or 'operated_by'.")
    boxes = payload.get("light_pull_values") or {}
    if not isinstance(boxes, Mapping):
        problems.append("light_pull_values must be an object.")
        boxes = {}
    for key, value in boxes.items():
        if key not in SUPPLIED_LIGHT_BOXES:
            problems.append(f"{key!r} cannot be supplied in a spreadsheet.")
            continue
        try:
            _fact(key, _evidence(value, source or website or "", method, submitted_at),
                  base_url=source or website or "https://invalid.example",
                  date_read=datetime.fromisoformat(submitted_at),
                  actor_category=category, category_type=type_code)
        except (ValueError, TypeError) as exc:
            problems.append(f"{key}: {exc}")
    return problems


def check_event(payload: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    if not _clean(payload.get("name")):
        problems.append("Event name is required.")
    try:
        start = _day(payload.get("start_date"), "Start date")
        end = _day(payload.get("end_date"), "End date")
        if not start:
            problems.append("Start date is required.")
        if start and end and end < start:
            problems.append("End date is before the start date.")
    except DataFeedRefused as exc:
        problems.append(str(exc))
    try:
        if not (_url(payload.get("website")) or _url(payload.get("source_url"))):
            problems.append("An Official event URL or a Source URL is required.")
        _url(payload.get("registration_url"))
    except DataFeedRefused as exc:
        problems.append(str(exc))
    if payload.get("recurring_pattern") and payload["recurring_pattern"] not in RECURRENCE:
        problems.append("Recurrence must be annual, recurring or one-time.")
    if payload.get("event_format") and payload["event_format"] not in EVENT_FORMATS:
        problems.append("Format must be in person, online or hybrid.")
    for code in payload.get("sector_codes") or []:
        if not SECTOR_CODE.match(_clean(code)):
            problems.append(f"{code!r} is not a sector code.")
    return problems


def check_person(payload: Mapping[str, Any]) -> list[str]:
    from agents.discovery.normalize import is_institution_affiliation

    problems: list[str] = []
    if not _clean(payload.get("name")):
        problems.append("Full name is required.")
    affiliation = _clean(payload.get("affiliation"))
    if not affiliation:
        problems.append("Organization is required: a person is always linked to one.")
    elif not is_institution_affiliation(affiliation):
        problems.append(f"Organization {affiliation!r} does not read as an institution's name "
                        "(e.g. 'University of Arizona', 'Tucuvi Inc.'). A department or a role "
                        "goes in its own column.")
    try:
        urls = [_url(payload.get(k)) for k in ("source_url", "public_profile_url",
                                              "bio_url", "linkedin_url")]
    except DataFeedRefused as exc:
        problems.append(str(exc))
        urls = []
    if not any(urls):
        problems.append("A Source URL, an official biography URL or a LinkedIn URL is required.")
    linkedin = _clean(payload.get("linkedin_url"))
    if linkedin and "linkedin.com/" not in linkedin.casefold():
        problems.append("The LinkedIn URL is not a linkedin.com address.")
    for code in payload.get("sector_codes") or []:
        if not SECTOR_CODE.match(_clean(code)):
            problems.append(f"{code!r} is not a sector code.")
    return problems


def classification_evidence(payload: Mapping[str, Any]) -> dict[str, str]:
    """The evidence the V2 classification rules read, from what the person supplied.

    The main job is the record's own description (what it mainly does); a
    national laboratory's designation and a startup's published development
    stage are their own columns; a startup's origin is the type GHUS chose.
    Nothing is inferred.
    """
    from agents.common.actor_classification import STARTUP_ORIGIN_TYPES

    boxes = payload.get("light_pull_values") or {}
    evidence = {"main_job": _clean(payload.get("description"))}
    if _clean(boxes.get("formal_national_designation")):
        evidence["national_designation"] = _clean(boxes["formal_national_designation"])
    if _clean(payload.get("development_stage")):
        evidence["development_stage"] = _clean(payload["development_stage"])
    if payload.get("category_type") in STARTUP_ORIGIN_TYPES:
        evidence["startup_origin"] = str(payload["category_type"])
    return {k: v for k, v in evidence.items() if v}


def _evidence(value: Any, source_url: str, method: str, submitted_at: str) -> dict:
    return {"collection_state": "found", "value": value, "source_url": source_url,
            "date_read": submitted_at, "confidence": "medium",
            "source_origin": FACT_ORIGINS[method]}


# ------------------------------------------------------------------ database
def existing_batch(session, key: str) -> str | None:
    return session.execute(text(
        "SELECT run_id::text FROM scrape_run WHERE source_name = :source "
        "AND config->'datafeed'->>'batch_key' = :key ORDER BY started_at LIMIT 1"
    ), {"source": SOURCE_NAME, "key": key}).scalar()


def pending_keys(session, record_type: str, keys: list[str]) -> dict[str, str]:
    """Natural key -> import name, for records an earlier import left waiting in Review."""
    if not keys:
        return {}
    if record_type == "actor":
        sql = ("SELECT c.record_preview->'data_feed'->>'natural_key' AS key, "
               "sr.config->'datafeed'->>'import_name' AS name FROM search_candidate c "
               "JOIN scrape_run sr ON sr.run_id = c.run_id WHERE sr.source_name = :source "
               "AND c.review_status IN ('pending', 'deferred') "
               "AND c.record_preview->'data_feed'->>'natural_key' = ANY(:keys)")
    else:
        queue = "event_review_queue" if record_type == "event" else "person_review_queue"
        sql = (f"SELECT s.natural_key AS key, sr.config->'datafeed'->>'import_name' AS name "
               f"FROM staged_record s JOIN scrape_run sr ON sr.run_id = s.run_id "
               f"JOIN {queue} q ON q.staged_record_id = s.staged_record_id "
               f"WHERE sr.source_name = :source AND q.status IN ('pending', 'deferred') "
               f"AND s.entity_type = :entity AND s.natural_key = ANY(:keys)")
    rows = session.execute(text(sql), {"source": SOURCE_NAME, "keys": keys,
                                       "entity": record_type}).mappings()
    return {str(r["key"]): str(r["name"] or "an earlier import") for r in rows}


def known_ids(session, table: str, ids: list[str]) -> set[str]:
    column = {"actor": "actor_id", "event": "event_id", "person": "person_id",
              "topic": "topic_id"}[table]
    ids = [i for i in ids if UUID_RE.match(i)]
    if not ids:
        return set()
    return {str(v) for v in session.execute(text(
        f"SELECT {column}::text FROM {table} WHERE {column}::text = ANY(:ids)"), {"ids": ids}
    ).scalars()}


# ------------------------------------------------------------------ the batch
def check_batch(session, batch: Mapping[str, Any]) -> dict[str, Any]:
    """Every row against the backend's own rules, plus what the database holds. No writes."""
    check_header(batch)
    record_type, method = batch["record_type"], batch["method"]
    submitted_at = str(batch.get("submitted_at") or datetime.now(UTC).isoformat())
    datetime.fromisoformat(submitted_at)
    key = batch_key(batch)
    rows_out: list[dict[str, Any]] = []
    keys: list[str] = []
    for row in batch["rows"]:
        payload = dict(row.get("payload") or {})
        problems: list[str] = []
        try:
            _text_fields(payload)
            if record_type == "actor":
                problems += check_actor(payload, method=method, submitted_at=submitted_at)
            elif record_type == "event":
                problems += check_event(payload)
            else:
                problems += check_person(payload)
        except DataFeedRefused as exc:
            problems.append(str(exc))
        nkey = natural_key(record_type, payload) if not problems else None
        if nkey:
            keys.append(nkey)
        rows_out.append({"row_number": row.get("row_number"), "natural_key": nkey,
                         "errors": problems, "warnings": [], "outcome": None})
    seen: dict[str, Any] = {}
    for out in rows_out:
        if out["natural_key"] and out["natural_key"] in seen:
            out["errors"].append(f"Same record as row {seen[out['natural_key']]}.")
        elif out["natural_key"]:
            seen[out["natural_key"]] = out["row_number"]
    waiting = pending_keys(session, record_type, keys)
    match_table = record_type
    match_ids = [str((row.get("match") or {}).get("entity_id") or "") for row in batch["rows"]]
    parent_ids = [str(((row.get("payload") or {}).get("parent_connection") or {}).get("actor_id")
                      or "") for row in batch["rows"]]
    topic_ids = [str((row.get("payload") or {}).get("topic_id") or "") for row in batch["rows"]]
    known_match = known_ids(session, match_table, match_ids)
    known_parent = known_ids(session, "actor", parent_ids)
    known_topic = known_ids(session, "topic", topic_ids)
    for row, out, match_id, parent_id, topic_id in zip(batch["rows"], rows_out, match_ids,
                                                       parent_ids, topic_ids):
        if parent_id and parent_id not in known_parent:
            out["errors"].append("The parent organisation is not on the map.")
        if topic_id and topic_id not in known_topic:
            out["errors"].append("The topic is not one of the database's topics.")
        if match_id and match_id not in known_match:
            out["warnings"].append("The suggested existing record no longer exists; Review "
                                   "will check identity again.")
        if out["errors"]:
            out["outcome"] = "failed_validation"
        elif out["natural_key"] in waiting:
            out["outcome"] = "already_awaiting_review"
            out["warnings"].append(f"Already waiting in Review from “{waiting[out['natural_key']]}”;"
                                   " it is not staged again.")
        else:
            out["outcome"] = "would_stage"
    existing = existing_batch(session, key)
    return {"batch_key": key, "already_imported_run_id": existing, "rows": rows_out,
            "known_match_ids": sorted(known_match)}


def stage_batch(session, batch: Mapping[str, Any]) -> dict[str, Any]:
    """Check, then stage every record in one transaction. Caller commits."""
    checked = check_batch(session, batch)
    if checked["already_imported_run_id"]:
        return {**checked, "status": "already_imported",
                "run_id": checked["already_imported_run_id"]}
    failed = [r for r in checked["rows"] if r["errors"]]
    if failed:
        raise DataFeedRefused(f"{len(failed)} record(s) failed the checks; nothing was staged")
    record_type, method = batch["record_type"], batch["method"]
    submitted_at = str(batch.get("submitted_at") or datetime.now(UTC).isoformat())
    run_id = str(uuid.uuid4())
    origin = METHODS[method]
    check_uploader(batch)
    provenance = {
        "batch_key": checked["batch_key"], "contract": CONTRACT,
        "admission": batch.get("admission") or "review",
        "attestation": {k: (batch.get("attestation") or {}).get(k)
                        for k in ("source", "authorized", "text")},
        "template_version": batch["template_version"], "record_type": record_type,
        "method": method, "import_name": _clean(batch["import_name"]),
        "file_name": _clean(batch.get("file_name")) or None,
        "file_sha256": batch.get("file_sha256"),
        # Only a signed-in identity is recorded; there is none yet, so NULL.
        "uploaded_by": _clean(batch.get("uploaded_by")) or None,
        "submitted_at": submitted_at,
    }
    session.execute(text(
        "INSERT INTO scrape_run (run_id, source_name, entity_type, mode, status, started_at, "
        "finished_at, stats, config, cost_usd, status_reason) VALUES (CAST(:run_id AS uuid), "
        ":source, :entity, 'live', 'running', now(), NULL, '{}'::jsonb, CAST(:config AS jsonb), "
        "0, NULL)"
    ), {"run_id": run_id, "source": SOURCE_NAME, "entity": record_type,
        "config": json.dumps({"datafeed": provenance}, sort_keys=True)})
    known_match = set(checked["known_match_ids"])
    staged = waiting = 0
    for row, out in zip(batch["rows"], checked["rows"]):
        if out["outcome"] == "already_awaiting_review":
            waiting += 1
            continue
        payload = {k: v for k, v in dict(row.get("payload") or {}).items()
                   if not REJECT_KEYS.match(str(k))}
        match = dict(row.get("match") or {})
        if str(match.get("entity_id") or "") not in known_match:
            match = {"kind": "new"}
        block = {**provenance, "row_number": row.get("row_number"),
                 "natural_key": out["natural_key"], "match": match,
                 "original_values": row.get("original") or {},
                 "warnings": list(row.get("warnings") or []) + out["warnings"]}
        payload["_record_origin"] = origin
        payload["data_feed"] = block
        if record_type == "actor":
            out["source_table"], out["source_id"] = "search_candidate", _stage_actor(
                session, run_id, payload, method=method, submitted_at=submitted_at)
        elif record_type == "event":
            out["source_table"], out["source_id"] = "event_review_queue", _stage_event(
                session, run_id, payload, out["natural_key"], match, submitted_at)
        else:
            out["source_table"], out["source_id"] = "person_review_queue", _stage_person(
                session, run_id, payload, out["natural_key"], match, method, submitted_at)
        out["outcome"] = "staged"
        staged += 1
    stats = {"datafeed": {**provenance, "rows_sent": len(batch["rows"]), "staged": staged,
                          "already_awaiting_review": waiting,
                          "rows_total": batch.get("rows_total"),
                          "rows_invalid": batch.get("rows_invalid")}}
    session.execute(text(
        "UPDATE scrape_run SET status = 'succeeded', finished_at = now(), "
        "stats = CAST(:stats AS jsonb) WHERE run_id = CAST(:run_id AS uuid)"
    ), {"run_id": run_id, "stats": json.dumps(stats, sort_keys=True, default=str)})
    return {**checked, "status": "staged", "run_id": run_id, "staged": staged,
            "already_awaiting_review": waiting}


def _stage_actor(session, run_id: str, payload: dict, *, method: str, submitted_at: str) -> str:
    website = _url(payload.get("website"))
    source = _url(payload.get("source_url")) or website
    payload["classification_evidence"] = classification_evidence(payload)
    boxes = payload.pop("light_pull_values", None) or {}
    payload["light_pull_evidence"] = {
        key: _evidence(value, source, method, submitted_at) for key, value in boxes.items()}
    candidate_id = str(uuid.uuid4())
    session.execute(text(
        "INSERT INTO search_candidate (candidate_id, run_id, entity_type, query, provider, url, "
        "title, snippet, domain, triage_verdict, triage_reason, page_fetched, record_preview, "
        "score_band, qualification_paths, review_status) VALUES (CAST(:candidate_id AS uuid), "
        "CAST(:run_id AS uuid), 'actor', :query, :provider, :url, :title, :snippet, :domain, "
        ":verdict, :reason, false, CAST(:preview AS jsonb), 'review', '[]'::jsonb, 'pending')"
    ), {"candidate_id": candidate_id, "run_id": run_id,
        "query": f"Data Feed: {payload['data_feed']['import_name']}"[:500],
        "provider": SOURCE_NAME, "url": source, "title": _clean(payload.get("name")),
        "snippet": _clean(payload.get("description"))[:500] or None,
        "domain": domain_of(website or source) or "", "verdict": SOURCE_NAME,
        "reason": "Supplied by GHUS through the Data Feed; waits for a GHUS decision.",
        "preview": json.dumps(payload, sort_keys=True, default=str)})
    return candidate_id


def _staged_row(session, run_id: str, entity: str, nkey: str, source_url: str,
                payload: dict, submitted_at: str) -> str:
    staged_id = str(uuid.uuid4())
    session.execute(text(
        "INSERT INTO staged_record (staged_record_id, run_id, entity_type, natural_key, "
        "source_url, prompt_version, extracted_at, payload, normalized_payload, sector_codes, "
        "sector_match, route, status) VALUES (CAST(:id AS uuid), CAST(:run_id AS uuid), "
        ":entity, :nkey, :source_url, :version, :at, CAST(:original AS jsonb), "
        "CAST(:payload AS jsonb), :sectors, 'in_sector', '{}'::jsonb, 'staged')"
    ), {"id": staged_id, "run_id": run_id, "entity": entity, "nkey": nkey,
        "source_url": source_url, "version": f"datafeed:{payload['data_feed']['template_version']}",
        "at": submitted_at,
        "original": json.dumps(payload["data_feed"]["original_values"], sort_keys=True,
                               default=str),
        "payload": json.dumps(payload, sort_keys=True, default=str),
        "sectors": [str(c) for c in payload.get("sector_codes") or []]})
    return staged_id


def _stage_event(session, run_id: str, payload: dict, nkey: str, match: dict,
                 submitted_at: str) -> str:
    source = _url(payload.get("source_url")) or _url(payload.get("website"))
    payload.setdefault("title", payload.get("name"))
    payload["next_date"] = payload.get("start_date")
    staged_id = _staged_row(session, run_id, "event", nkey, source, payload, submitted_at)
    queue_id = str(uuid.uuid4())
    candidate = match.get("entity_id") if match.get("kind") in ("existing", "possible") else None
    session.execute(text(
        "INSERT INTO event_review_queue (event_review_id, staged_record_id, candidate_event_id, "
        "similarity_score, staged_title, candidate_title, shared_start_date, status, "
        "review_kind, notes) VALUES (CAST(:id AS uuid), CAST(:staged AS uuid), "
        "CAST(:candidate AS uuid), :score, :title, :candidate_title, CAST(:start AS date), "
        "'pending', :kind, :notes)"
    ), {"id": queue_id, "staged": staged_id, "candidate": candidate,
        "score": match.get("score") if candidate else None, "title": _clean(payload["name"]),
        "candidate_title": match.get("name") if candidate else None,
        "start": payload.get("start_date"),
        "kind": "fuzzy_match" if candidate else "rubric_band",
        "notes": f"Data Feed import: {payload['data_feed']['import_name']}"})
    return queue_id


def _stage_person(session, run_id: str, payload: dict, nkey: str, match: dict, method: str,
                  submitted_at: str) -> str:
    from agents.common.provenance import insert_source

    source = (_url(payload.get("source_url")) or _url(payload.get("bio_url"))
              or _url(payload.get("linkedin_url")))
    payload["public_profile_url"] = (_url(payload.get("linkedin_url"))
                                     or _url(payload.get("bio_url")))
    facts = {k: payload[k] for k in PERSON_FACTS if payload.get(k) not in (None, "", [])}
    payload["facts"] = {**facts, "evidence": {
        k: {"source_url": source, "date_read": submitted_at,
            "source_origin": FACT_ORIGINS[method], "quote": None} for k in facts}}
    staged_id = _staged_row(session, run_id, "person", nkey, source, payload, submitted_at)
    block = payload["data_feed"]
    source_id = insert_source(
        session, source_url=source, fetched_at=submitted_at, source_type=(
            "spreadsheet" if method == "upload" else "ghus_manual_entry"),
        trust_tier="candidate",
        description=(f"GHUS Data Feed {'upload' if method == 'upload' else 'manual entry'}: "
                     f"{block['import_name']}"
                     + (f" ({block['file_name']}, row {block['row_number']})"
                        if block.get("file_name") else "")))
    queue_id = str(uuid.uuid4())
    candidate = match.get("entity_id") if match.get("kind") in ("existing", "possible") else None
    session.execute(text(
        "INSERT INTO person_review_queue (person_review_id, staged_record_id, source_id, "
        "candidate_person_id, score, staged_name, affiliation, role, public_profile_url, "
        "research_area, candidate_name, source_url, status, notes, review_kind, "
        "identity_outcome, affiliation_raw) VALUES (CAST(:id AS uuid), CAST(:staged AS uuid), "
        "CAST(:source_id AS uuid), CAST(:candidate AS uuid), :score, :name, :affiliation, "
        ":role, :profile, :research, :candidate_name, :source_url, 'pending', :notes, "
        "'identity', :outcome, :affiliation)"
    ), {"id": queue_id, "staged": staged_id, "source_id": source_id, "candidate": candidate,
        "score": match.get("score") if candidate else None, "name": _clean(payload["name"]),
        "affiliation": _clean(payload.get("affiliation")) or None,
        "role": _clean(payload.get("role"))[:255] or None,
        "profile": payload.get("public_profile_url"),
        "research": _clean(payload.get("research_area")) or None,
        "candidate_name": match.get("name") if candidate else None, "source_url": source,
        "notes": f"Data Feed import: {block['import_name']}",
        "outcome": "possible_duplicate" if candidate else None})
    return queue_id


# ------------------------------------------------------------------ command
def import_reason(batch: Mapping[str, Any], row_number: Any) -> str:
    where = (f"file {_clean(batch.get('file_name'))}, row {row_number}, SHA-256 "
             f"{str(batch.get('file_sha256') or '')[:12]}" if batch.get("file_name")
             else f"manual entry, record {row_number}")
    return (f"Imported as Verified by {_clean(batch.get('uploaded_by'))} through the GHUS Data "
            f"Feed (import '{_clean(batch.get('import_name'))}', {where}). The uploader attested "
            "that they are authorized GHUS staff and that the record comes from a GHUS source.")


def admit_verified(session, batch: Mapping[str, Any], result: Mapping[str, Any]) -> list[dict]:
    """Admit each eligible new actor of a staged batch as Verified, one at a time.

    Each goes through agents.review.admission.apply_review_decision (its own
    transaction, idempotent on the batch and row), so a refusal leaves that
    record waiting in Review and the others stand.
    """
    from agents.review.admission import apply_review_decision

    uploader = _clean(batch.get("uploaded_by"))
    by_row = {row.get("row_number"): row for row in batch["rows"]}
    outcomes = []
    for row in result.get("rows") or []:
        if row.get("outcome") != "staged" or row.get("source_table") != "search_candidate":
            continue
        sent = by_row.get(row.get("row_number")) or {}
        payload = sent.get("payload") or {}
        kind = (sent.get("match") or {}).get("kind") or "new"
        item = {"row_number": row.get("row_number"), "source_id": row.get("source_id")}
        if kind != "new":
            outcomes.append({**item, "outcome": "awaiting_review",
                             "reason": "It may already be on the map; a reviewer decides."})
            continue
        if not _clean(payload.get("category_type")):
            outcomes.append({**item, "outcome": "awaiting_review",
                             "reason": "No Category Type; a reviewer chooses one in Review."})
            continue
        try:
            done = apply_review_decision(session, {
                "entity_type": "actor", "decision_kind": "new",
                "source_ref": {"table": "search_candidate", "id": row["source_id"]},
                "reviewer": uploader, "edited_payload": {},
                "idempotency_key": f"datafeed-import:{result['batch_key']}:{row.get('row_number')}",
                "notes": "Data Feed import admitted as Verified on the uploader's attestation.",
            }, import_verification={"by": uploader,
                                    "reason": import_reason(batch, row.get("row_number"))})
            outcomes.append({**item, "outcome": "approved_verified",
                             "entity_id": done.get("canonical_entity_id"),
                             "promotion_action": done.get("promotion_action")})
        except Exception as exc:  # noqa: BLE001 - one record must not stop the others
            session.rollback()
            outcomes.append({**item, "outcome": "awaiting_review",
                             "reason": f"Admission refused: {exc}"[:300]})
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch", required=True, help="the batch JSON file")
    parser.add_argument("--live", action="store_true", help="stage; absent means check only")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    if args.live and os.environ.get("DATAFEED_WRITES_ENABLED", "").lower() != "true":
        print(json.dumps({"status": "refused",
                          "error": "Data Feed writes are not enabled for this database."}))
        return 2
    from agents.collection.discovery_requests import open_session

    batch = json.loads(Path(args.batch).read_text(encoding="utf-8"))
    try:
        with open_session() as session:
            if args.live:
                with session.begin():
                    result = stage_batch(session, batch)
                if result.get("status") == "staged" and batch.get("admission") == "verified":
                    result["admissions"] = admit_verified(session, batch, result)
            else:
                result = {**check_batch(session, batch), "status": "checked"}
                session.rollback()
    except DataFeedRefused as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}))
        return 2
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
