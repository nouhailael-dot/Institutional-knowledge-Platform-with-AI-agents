"""Create a sensitive-data-safe legacy-to-V2 semantic mapping matrix."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/evidence/legacy_to_v2_mapping_matrix_2026-10-06.json"
EXPECTED_DATABASE = "ghus_v2_phase12_report_test"

FINAL_TABLES = {
    "actor", "actor_category_definition", "actor_category_type_definition",
    "actor_location", "actor_ranking", "actor_topic", "canonical_write_audit",
    "collection_request", "collection_run", "contact_collection_authorization",
    "entity_edge", "event", "event_claim", "event_topic", "fact_resolution",
    "fetched_document", "hub", "hub_actor", "hub_center_review", "person",
    "person_topic", "proposed_hub", "proposed_hub_decision", "proposed_hub_member",
    "region_definition", "region_state", "review_item", "review_item_decision",
    "source", "source_origin_definition", "topic",
}

RELATED_TABLES = {
    "actor_capability_fact": ("actor_fact", "HISTORICAL FACT"),
    "actor_profile": ("actor_fact", "HISTORICAL FACT"),
    "actor_descendant_edge": ("entity_edge", "RELATED TABLE"),
    "organization_hierarchy": ("entity_edge", "RELATED TABLE"),
    "record_verification": ("actor_verification_event", "TRANSFORM"),
    "event_review_queue": ("review_item", "RELATED TABLE"),
    "person_review_queue": ("review_item", "RELATED TABLE"),
    "review_queue": ("review_item", "RELATED TABLE"),
}

TABLE_PURPOSES = {
    "actor": "canonical organization identity and legacy scalar profile",
    "actor_capability_fact": "legacy capability claims",
    "actor_profile": "legacy profile snapshots",
    "organization_hierarchy": "legacy parent-child relationships",
    "record_verification": "legacy explicit verification decisions",
    "hub_actor": "historical GHUS hub membership",
    "event": "canonical event records",
    "source": "retrieval and evidence identity",
    "search_candidate": "discovery staging and review history",
    "staged_record": "pre-canonical staged extraction",
    "raw_document": "retrieved raw document metadata",
    "scrape_run": "legacy collection run audit",
}

ACTOR_RULES = {
    "actor_category": (
        "actor", "actor_category", "TRANSFORM",
        "Apply the approved deterministic legacy-value to 12-category mapping; unmappable values remain reviewable and are retained in migration audit.",
    ),
    "actor_type_raw": (
        "actor_category_migration_audit", "legacy_category", "HISTORICAL FACT",
        "Preserve as historical classification evidence; never use it to bypass controlled category mapping.",
    ),
    "record_status": (
        "actor_verification_event", "decision_origin", "TRANSFORM",
        "Existing canonical population receives status verified by explicit GHUS migration policy; retain the old scalar in migration audit, not as a fabricated human decision.",
    ),
    "alternate_names": ("actor", "alt_names", "DIRECT", "Rename after application switch."),
    "location_city": ("actor", "city", "DIRECT", "Rename after application switch."),
    "state": (
        "actor", "state_code", "TRANSFORM",
        "Normalize only deterministic state names/codes; derive region through region_state; otherwise review.",
    ),
    "primary_technical_focus": ("actor_fact", "value", "HISTORICAL FACT", "Append as an imported legacy fact with baseline migration provenance."),
    "technical_approach": ("actor_fact", "value", "HISTORICAL FACT", "Append as an imported legacy fact with baseline migration provenance."),
    "current_activities": ("actor_fact", "value", "HISTORICAL FACT", "Append as an imported legacy fact with baseline migration provenance."),
    "technology_ip_notes": ("actor_fact", "value", "HISTORICAL FACT", "Append as an imported legacy fact with baseline migration provenance."),
    "key_constraints": ("actor_fact", "value", "HISTORICAL FACT", "Append as an imported legacy fact with baseline migration provenance."),
    "funding_summary": ("actor_fact", "value", "HISTORICAL FACT", "Append as an imported legacy fact with baseline migration provenance."),
    "estimated_trl": ("actor_fact", "value", "HISTORICAL FACT", "Append as an imported legacy fact with baseline migration provenance."),
    "primary_lifecycle_role": ("actor_fact", "value", "HISTORICAL FACT", "Append as an imported legacy fact; do not treat it as category or topic."),
    "source_id": ("actor", "source_id", "DIRECT", "Retain when referenced source exists; otherwise record missing provenance without inventing a source."),
}


def _url() -> str:
    raw = os.environ.get("V2_PHASE12_REPORT_DATABASE_URL", "").strip()
    parsed = urlsplit(raw)
    if (
        parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port != 55432
        or parsed.path.removeprefix("/") != EXPECTED_DATABASE
    ):
        raise RuntimeError("legacy inventory accepts only the named local report copy")
    return raw


def _shape(cursor, table: str, column: str, data_type: str) -> str:
    if data_type in {"character varying", "text", "character"}:
        query = sql.SQL(
            "SELECT max(length({column}::text)) max_length,"
            "count(DISTINCT {column}) distinct_count FROM {table}"
        ).format(column=sql.Identifier(column), table=sql.Identifier(table))
        cursor.execute(query)
        row = cursor.fetchone()
        return f"text(max_length={row['max_length'] or 0},distinct={row['distinct_count']})"
    if data_type == "ARRAY":
        return "array(values redacted)"
    if data_type in {"json", "jsonb"}:
        return "json object/array (values redacted)"
    if data_type == "uuid":
        return "uuid"
    if "timestamp" in data_type or data_type == "date":
        return data_type
    if data_type == "boolean":
        return "boolean"
    return f"{data_type} (values redacted)"


def _rule(table: str, column: str) -> tuple[str, str, str, str, bool, bool]:
    if table == "actor" and column in ACTOR_RULES:
        target_table, target_column, mapping_type, rule = ACTOR_RULES[column]
        review = mapping_type in {"REVIEW", "UNMAPPABLE"} or column in {"actor_category", "state"}
        return target_table, target_column, mapping_type, rule, True, review
    if table in RELATED_TABLES:
        target, mapping_type = RELATED_TABLES[table]
        rule = (
            "Migrate only semantically equivalent, evidence-backed values; preserve conflicts "
            "and unresolved rows for review rather than manufacturing meaning."
        )
        return target, column, mapping_type, rule, True, table == "organization_hierarchy"
    if table in FINAL_TABLES:
        return table, column, "DIRECT", "Retain the same semantic field in the final canonical object.", True, False
    if table in {"actor_sector", "event_sector", "sector", "hub_sector_strength"}:
        return table, column, "DIRECT", "Retain sector semantics; do not rename sector into controlled V2 topic.", True, False
    if table in {"search_candidate", "staged_record", "review_admission_decision", "field_proposal"}:
        return table, column, "DIRECT", "Retain as staging/review audit through retention; not a canonical actor field.", True, False
    if table in {"raw_document", "scrape_run", "discovered_domain", "strategic_document"}:
        return "collection_run/fetched_document", column, "RELATED TABLE", "Reconcile into collection audit only where request/run/document identity is deterministic; retain unmatched audit rows.", True, True
    return table, column, "DIRECT", "Preserve in its owning domain until that domain has an approved V2 replacement.", True, False


def main() -> int:
    connection = psycopg2.connect(_url(), application_name="ghus_phase12_legacy_inventory")
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT table_name,column_name,data_type,udt_name,ordinal_position
                FROM information_schema.columns
                WHERE table_schema='public'
                  AND table_name IN (
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema='public' AND table_type='BASE TABLE'
                  )
                ORDER BY table_name,ordinal_position
            """)
            columns = cursor.fetchall()
            rows = []
            for column in columns:
                table = column["table_name"]
                name = column["column_name"]
                count_query = sql.SQL("SELECT count({column}) value FROM {table}").format(
                    column=sql.Identifier(name), table=sql.Identifier(table)
                )
                cursor.execute(count_query)
                non_null = cursor.fetchone()["value"]
                target_table, target_column, kind, rule, preserved, review = _rule(table, name)
                rows.append({
                    "legacy_table": table,
                    "legacy_column": name,
                    "current_meaning": f"{TABLE_PURPOSES.get(table, table.replace('_', ' '))}: {name.replace('_', ' ')}",
                    "data_type": column["data_type"],
                    "non_null_rows": non_null,
                    "sample_value_shape": _shape(cursor, table, name, column["data_type"]),
                    "final_v2_table": target_table,
                    "final_v2_field": target_column,
                    "mapping_type": kind,
                    "transformation_rule": rule,
                    "provenance_treatment": "Retain existing provenance; otherwise label baseline migration honestly without inventing URL, reviewer, timestamp, topic, relationship, or coordinates.",
                    "information_preserved": preserved,
                    "human_review_required": review,
                    "removable_at_final_cutover": table in RELATED_TABLES or (table == "actor" and name in ACTOR_RULES),
                })
            cursor.execute("""
                SELECT table_name FROM information_schema.views
                WHERE table_schema='public' ORDER BY table_name
            """)
            views = [row["table_name"] for row in cursor.fetchall()]
        connection.rollback()
    finally:
        connection.close()
    artifact = {
        "generated_at": datetime.now(UTC).isoformat(),
        "database": EXPECTED_DATABASE,
        "mode": "read_only_semantic_inventory",
        "column_count": len(rows),
        "table_count": len({row["legacy_table"] for row in rows}),
        "views_inventory": views,
        "mapping_rows": rows,
        "policy": "preserve useful meaning; never invent missing semantics or provenance",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({artifact['table_count']} tables, {len(rows)} columns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
