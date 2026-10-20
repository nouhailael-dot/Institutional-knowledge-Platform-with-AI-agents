"""Export the proven isolated V2 target-expand schema as machine-readable evidence."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "evidence" / "v2_target_schema_manifest_2026-10-06.json"
TABLES = (
    "actor_category_definition", "actor_category_type_definition", "region_definition",
    "region_state", "us_city_coord", "source_origin_definition", "source", "actor",
    "actor_location", "topic", "actor_topic", "actor_verification_event", "actor_fact",
    "actor_category_migration_audit", "architecture_v2_cutover_attestation",
    "actor_fact_current_pointer", "fact_corroboration", "fact_resolution", "actor_ranking",
    "entity_edge_type_definition", "entity_edge", "hub", "hub_actor",
    "hub_assignment_evidence", "hub_center_review", "proposed_hub",
    "proposed_hub_member", "proposed_hub_decision", "hub_detection_run", "review_item",
    "review_item_decision", "collection_request", "collection_run", "fetched_document",
    "canonical_write_audit", "person", "person_topic", "contact_collection_authorization",
    "event", "event_topic", "event_claim",
)


def _url() -> str:
    raw = os.environ.get("V2_TEST_DATABASE_URL", "").strip()
    parsed = urlsplit(raw)
    if (parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 55432
            or parsed.path.removeprefix("/") != "ghus_v2_target_test"):
        raise RuntimeError("manifest export accepts only the isolated target database")
    return raw


def main() -> int:
    connection = psycopg2.connect(_url(), application_name="ghus_v2_manifest_read_only")
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            manifest = {
                "generated_at": datetime.now(UTC).isoformat(),
                "database": "ghus_v2_target_test",
                "checkpoint": "target_final_expand",
                "production_deployed": False,
                "tables": {}, "views": {},
            }
            for table in TABLES:
                cursor.execute("""
                    SELECT column_name,data_type,udt_name,is_nullable,column_default,
                           is_generated,generation_expression
                    FROM information_schema.columns
                    WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position
                """, (table,))
                columns = [dict(row) for row in cursor.fetchall()]
                if not columns:
                    continue
                cursor.execute("""
                    SELECT conname AS name,contype AS type,pg_get_constraintdef(oid,true) AS definition,
                           convalidated AS validated
                    FROM pg_constraint WHERE conrelid=%s::regclass ORDER BY contype,conname
                """, (f"public.{table}",))
                constraints = [dict(row) for row in cursor.fetchall()]
                cursor.execute("SELECT indexname AS name,indexdef AS definition FROM pg_indexes WHERE schemaname='public' AND tablename=%s ORDER BY indexname", (table,))
                indexes = [dict(row) for row in cursor.fetchall()]
                cursor.execute("""
                    SELECT tgname AS name,pg_get_triggerdef(oid,true) AS definition
                    FROM pg_trigger WHERE tgrelid=%s::regclass AND NOT tgisinternal ORDER BY tgname
                """, (f"public.{table}",))
                triggers = [dict(row) for row in cursor.fetchall()]
                cursor.execute("SELECT policyname AS name,cmd,roles,qual,with_check FROM pg_policies WHERE schemaname='public' AND tablename=%s ORDER BY policyname", (table,))
                policies = [dict(row) for row in cursor.fetchall()]
                cursor.execute("SELECT grantee,privilege_type FROM information_schema.role_table_grants WHERE table_schema='public' AND table_name=%s ORDER BY grantee,privilege_type", (table,))
                grants = [dict(row) for row in cursor.fetchall()]
                manifest["tables"][table] = {
                    "columns": columns, "constraints": constraints, "indexes": indexes,
                    "triggers": triggers, "rls_policies": policies, "grants": grants,
                }
            cursor.execute("""
                SELECT viewname AS name,definition FROM pg_views
                WHERE schemaname='public' AND viewname=ANY(%s) ORDER BY viewname
            """, (["actor_fact_current_v2", "actor_fact_history", "actor_descendants",
                     "actor_v1_compat", "staged_record_agent3_compat", "actor_profile_current"],))
            manifest["views"] = {row["name"]: row["definition"] for row in cursor.fetchall()}
        connection.rollback()
    finally:
        connection.close()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} with {len(manifest['tables'])} tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
