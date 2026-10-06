"""Propose categories for the Phase 12 actors whose legacy value cannot be mapped.

Dry run only: reads the isolated full-dump copy in a read-only transaction and
writes a proposal CSV for GHUS review. It never writes to any database.

Evidence is limited to what already exists on the actor row (name, website,
legacy source URL, scalar text fields). Generated template sentences such as
"... is an aggregate actor label ..." are removed first: they are the cause of
the wrong `aggregate` tags, not evidence about the organization. Text copied
onto many actors (hub-level boilerplate) is ignored for the same reason. No web
fetch.
"""

from __future__ import annotations

import csv
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
from psycopg2.extras import RealDictCursor

from agents.common.actor_classification import (
    ActorClassificationError,
    NonActorRecord,
    classify_actor_category_type,
    load_category_catalog,
)
from agents.common.llm import ClaudeToolClient

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence"
CSV_OUTPUT = EVIDENCE / "phase12_category_proposals.csv"
SUMMARY_OUTPUT = EVIDENCE / "phase12_category_proposals_summary.json"
EXPECTED_DATABASE = "ghus_v2_phase12_full_test"
MODEL = "claude-haiku-4-5"
SHARED_TEXT_THRESHOLD = 3
TEXT_FIELDS = ("description", "primary_technical_focus", "technical_approach", "current_activities")
TEMPLATE_PATTERNS = (
    re.compile(r"aggregate actor label", re.IGNORECASE),
    re.compile(r"aggregate mapping row", re.IGNORECASE),
    re.compile(r"^tracked in .* hub", re.IGNORECASE),
    re.compile(r"not a single named legal entity", re.IGNORECASE),
    re.compile(r"linked hub context", re.IGNORECASE),
)
CSV_FIELDS = (
    "actor_id", "name", "legacy_value", "is_true_aggregate", "proposed_category",
    "proposed_category_type", "confidence", "evidence", "evidence_basis",
    "category_note", "needs_review_reason",
)


def _url() -> str:
    raw = os.environ.get("V2_PHASE12_FULL_DATABASE_URL", "").strip()
    parsed = urlsplit(raw)
    if (parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 55432
            or parsed.path.removeprefix("/") != EXPECTED_DATABASE):
        raise RuntimeError("category proposals accept only the local full-dump copy")
    return raw


def _clean(text: str | None) -> str:
    """Drop generated template sentences; keep everything else verbatim."""
    sentences = re.split(r"(?<=[.;])\s+", (text or "").strip())
    kept = [s for s in sentences if s and not any(p.search(s) for p in TEMPLATE_PATTERNS)]
    return " ".join(kept).strip()


def _evidence(row: dict, shared: dict[str, set[str]]) -> tuple[str, list[str]]:
    parts, basis = [], []
    for field in TEXT_FIELDS:
        cleaned = _clean(row.get(field))
        if cleaned and cleaned not in shared[field]:
            parts.append(cleaned)
            basis.append(field)
    for field in ("website", "source_url"):
        if row.get(field):
            parts.append(f"{field}: {row[field]}")
            basis.append(field)
    return " ".join(parts)[:2000], basis


def _aggregate_check(client, name: str, evidence: str) -> dict:
    return client.extract_with_tool(
        system=(
            "Decide whether the record names ONE organization (a single university, lab, "
            "company, agency, consortium, network or programme with its own identity) or "
            "a BUCKET of several unnamed organizations grouped by kind or place (for "
            "example 'Seattle AI startups', 'Water Treatment Companies', 'Impact "
            "Investment Funds'). A named consortium or association is ONE organization. "
            "Use only the supplied name and evidence."
        ),
        user=json.dumps({"name": name, "evidence": evidence}),
        tool_name="classify_record_scope",
        tool_description="Single organization versus a bucket of organizations.",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "scope": {"type": "string", "enum": ["single_organization", "bucket"]},
                "reason": {"type": "string", "minLength": 1, "maxLength": 300},
            },
            "required": ["scope", "reason"],
        },
        max_tokens=300,
    ) or {}


def _confidence(doubt: bool, category_type: str, basis: list[str]) -> str:
    if doubt:
        return "low"
    text_basis = [b for b in basis if b in TEXT_FIELDS]
    if category_type != "other" and text_basis and ("website" in basis or len(text_basis) >= 2):
        return "high"
    return "medium"


def _one_line(text: str, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def _propose(client, catalog, shared, row: dict) -> dict:
    evidence, basis = _evidence(row, shared)
    result = {
        "actor_id": row["actor_id"], "name": row["name"],
        "legacy_value": row["actor_type"] if row["actor_type"] is not None else "<null>",
        "is_true_aggregate": False, "proposed_category": "", "proposed_category_type": "",
        "confidence": "low", "evidence": "", "evidence_basis": "+".join(basis) or "name_only",
        "category_note": "", "needs_review_reason": "",
    }
    scope = _aggregate_check(client, row["name"], evidence)
    if scope.get("scope") == "bucket":
        result.update(is_true_aggregate=True, evidence=_one_line(scope.get("reason", "")),
                      needs_review_reason="bucket of organizations; disposition decided by GHUS")
        return result
    try:
        classification = classify_actor_category_type(
            client, name=row["name"], self_description=evidence or row["name"], catalog=catalog,
        )
    except NonActorRecord as exc:
        result.update(evidence=_one_line(exc.evidence),
                      needs_review_reason=f"classified as {exc.record_kind}, not an organization")
        return result
    except ActorClassificationError as exc:
        result.update(needs_review_reason=f"classifier rejected: {_one_line(str(exc))}")
        return result
    result.update(
        proposed_category=classification.actor_category,
        proposed_category_type=classification.category_type,
        confidence=_confidence(classification.category_needs_review,
                               classification.category_type, basis),
        evidence=_one_line(classification.evidence.main_job),
        category_note=_one_line(classification.category_note or ""),
        needs_review_reason="classifier doubt" if classification.category_needs_review else "",
    )
    return result


def main() -> int:
    connection = psycopg2.connect(_url(), application_name="ghus_phase12_category_proposals")
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT a.actor_id::text, a.name, a.actor_type, a.website,
                       a.description, a.primary_technical_focus, a.technical_approach,
                       a.current_activities, s.url source_url
                FROM actor a LEFT JOIN source s ON s.source_id=a.source_id
                WHERE a.actor_category IS NULL ORDER BY a.name
            """)
            rows = [dict(row) for row in cursor.fetchall()]
            # Hub-level boilerplate was copied onto many actors; a value shared by
            # SHARED_TEXT_THRESHOLD or more actors says nothing about this one.
            shared = {}
            for field in TEXT_FIELDS:
                cursor.execute(f"SELECT {field} AS value FROM actor WHERE {field} IS NOT NULL")
                counts: dict[str, int] = {}
                for item in cursor.fetchall():
                    cleaned = _clean(item["value"])
                    counts[cleaned] = counts.get(cleaned, 0) + 1
                shared[field] = {v for v, n in counts.items() if n >= SHARED_TEXT_THRESHOLD}
        connection.rollback()
    finally:
        connection.close()

    catalog = load_category_catalog()
    client = ClaudeToolClient(MODEL)
    with ThreadPoolExecutor(max_workers=6) as pool:
        proposals = list(pool.map(lambda row: _propose(client, catalog, shared, row), rows))

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with CSV_OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(proposals)

    def tally(key: str) -> dict:
        counts: dict[str, int] = {}
        for item in proposals:
            counts[str(item[key])] = counts.get(str(item[key]), 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "database": EXPECTED_DATABASE,
        "mode": "dry_run_proposals_only",
        "database_mutated": False,
        "web_fetch": False,
        "model": MODEL,
        "evidence_policy": "name, website, legacy source URL, and text fields with template "
                           f"sentences removed and shared by fewer than {SHARED_TEXT_THRESHOLD} actors",
        "actors": len(proposals),
        "true_aggregates": sum(item["is_true_aggregate"] for item in proposals),
        "with_proposed_category": sum(bool(item["proposed_category"]) for item in proposals),
        "by_legacy_value": tally("legacy_value"),
        "by_proposed_category": tally("proposed_category"),
        "by_confidence": tally("confidence"),
        "llm_usage": client.usage.snapshot(),
    }
    SUMMARY_OUTPUT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "generated_at"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
