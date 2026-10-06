"""Generate the report-only Architecture V2 Phase 12 baseline analysis.

The command is deliberately restricted to the isolated local copy and starts a
read-only transaction before reading any application table.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "evidence" / "phase12_dry_run_2026-10-06.json"
EXPECTED_DATABASE = "ghus_v2_phase12_report_test"
LEGACY_CATEGORY_CASE = """CASE lower(btrim(actor_category))
 WHEN 'university' THEN 'university_academic'
 WHEN 'university_academic' THEN 'university_academic'
 WHEN 'university_lab' THEN 'research_center'
 WHEN 'research_organization' THEN 'research_center'
 WHEN 'national_research_center' THEN 'research_center'
 WHEN 'research_center' THEN 'research_center'
 WHEN 'national_research_lab' THEN 'national_laboratory'
 WHEN 'federal_research_system' THEN 'national_laboratory'
 WHEN 'national_laboratory' THEN 'national_laboratory'
 WHEN 'applied_facility' THEN 'applied_facility'
 WHEN 'hospital_clinical' THEN 'hospital_clinical'
 WHEN 'company' THEN 'company'
 WHEN 'corporate_rd_lab' THEN 'company'
 WHEN 'industrial_partner' THEN 'company'
 WHEN 'project_developer' THEN 'company'
 WHEN 'startup' THEN 'startup'
 WHEN 'accelerator' THEN 'innovation_platform'
 WHEN 'innovation_platform' THEN 'innovation_platform'
 WHEN 'venture_capital' THEN 'investor'
 WHEN 'investor' THEN 'investor'
 WHEN 'government' THEN 'government'
 WHEN 'government agency' THEN 'government'
 WHEN 'government_agency' THEN 'government'
 WHEN 'federal_agency' THEN 'government'
 WHEN 'state_agency' THEN 'government'
 WHEN 'foundation_nonprofit' THEN 'foundation_nonprofit'
 WHEN 'nonprofit' THEN 'foundation_nonprofit'
 WHEN 'association_network' THEN 'association_network'
 WHEN 'consortium' THEN 'association_network'
 WHEN 'industry_association' THEN 'association_network'
 WHEN 'intergovernmental_organization' THEN 'association_network'
 WHEN 'un_agency' THEN 'association_network'
 WHEN 'un_committee' THEN 'association_network'
 WHEN 'un_programme' THEN 'association_network'
 WHEN 'un_secretariat' THEN 'association_network'
 ELSE NULL END"""


def _url() -> str:
    raw = os.environ.get("V2_PHASE12_REPORT_DATABASE_URL", "").strip()
    parsed = urlsplit(raw)
    if (parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 55432
            or parsed.path.removeprefix("/") != EXPECTED_DATABASE):
        raise RuntimeError("Phase 12 report accepts only the named local isolated copy")
    return raw


def _one(cursor, sql: str) -> dict:
    cursor.execute(sql)
    return dict(cursor.fetchone())


def _counts(cursor, table: str, field: str) -> dict[str, int]:
    cursor.execute(
        f"SELECT COALESCE({field}::text,'<null>') value,count(*) count "
        f"FROM {table} GROUP BY {field} ORDER BY count(*) DESC,value"
    )
    return {row["value"]: row["count"] for row in cursor.fetchall()}


def main() -> int:
    connection = psycopg2.connect(_url(), application_name="ghus_phase12_report_only")
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SHOW transaction_read_only")
            if cursor.fetchone()["transaction_read_only"] != "on":
                raise RuntimeError("database refused report-only transaction")
            actors = _one(cursor, """
                SELECT count(*) total,
                  count(*) FILTER(WHERE actor_category IS NULL) missing_category,
                  count(*) FILTER(WHERE category_type IS NULL) missing_category_type,
                  count(*) FILTER(WHERE category_needs_review) existing_doubts,
                  count(*) FILTER(WHERE category_type='other') existing_other,
                  count(*) FILTER(WHERE latitude IS NOT NULL AND longitude IS NOT NULL) geocoded,
                  count(*) FILTER(WHERE latitude IS NULL OR longitude IS NULL) missing_coordinates,
                  count(*) FILTER(WHERE NULLIF(btrim(location_city),'') IS NULL) missing_city,
                  count(*) FILTER(WHERE NULLIF(btrim(state_code),'') IS NULL) missing_state_code,
                  count(*) FILTER(WHERE NULLIF(btrim(region_code),'') IS NULL) missing_region,
                  count(*) FILTER(WHERE NULLIF(btrim(country),'') IS NULL) missing_country,
                  count(*) FILTER(WHERE source_id IS NOT NULL) source_ids_present,
                  count(DISTINCT source_id) distinct_source_ids,
                  count(*) FILTER(WHERE NULLIF(btrim(website),'') IS NOT NULL) websites
                FROM actor
            """)
            category_migration = _one(cursor, f"""
                SELECT count(*) FILTER(WHERE mapped IS NOT NULL) mapped,
                       count(*) FILTER(WHERE mapped IS NULL) unmappable
                FROM (SELECT {LEGACY_CATEGORY_CASE} mapped FROM actor) migration
            """)
            cursor.execute(f"""
                SELECT COALESCE(actor_category,'<null>') legacy_category,count(*) count
                FROM actor WHERE ({LEGACY_CATEGORY_CASE}) IS NULL
                GROUP BY actor_category ORDER BY count(*) DESC,legacy_category
            """)
            unmappable_categories = {
                row["legacy_category"]: row["count"] for row in cursor.fetchall()
            }
            topics = _one(cursor, """
                SELECT count(*) actor_topic_rows,count(DISTINCT actor_id) actors_with_topic
                FROM actor_topic
            """)
            cursor.execute("SELECT actor_category,name FROM actor WHERE actor_category='aggregate'")
            aggregate_rows = cursor.fetchall()
            network_words = ("consortium", "association", "network", "alliance", "coalition", "council", "cluster")
            mistag_words = ("university", "laborator", "company", "corporation", "agency", "institute", "ministry", "department")
            likely_network = sorted(row["name"] for row in aggregate_rows
                                    if any(word in row["name"].casefold() for word in network_words))
            likely_mistagged = sorted(row["name"] for row in aggregate_rows
                                      if any(word in row["name"].casefold() for word in mistag_words))
            relationships = _one(cursor, """
                SELECT count(*) hierarchy_rows,
                  count(*) FILTER(WHERE parent_actor_id=child_actor_id) self_cycles,
                  count(DISTINCT parent_actor_id) parents,count(DISTINCT child_actor_id) children
                FROM organization_hierarchy
            """)
            relationships["typed_edge_rows"] = _one(cursor, "SELECT count(*) value FROM entity_edge")["value"]
            hubs = _one(cursor, """
                SELECT count(*) total,count(*) FILTER(WHERE topic_id IS NOT NULL) with_topic,
                  count(*) FILTER(WHERE center_latitude IS NOT NULL AND center_longitude IS NOT NULL) with_center,
                  count(*) FILTER(WHERE radius_miles IS NOT NULL) with_radius,
                  count(*) FILTER(WHERE center_frozen) frozen
                FROM hub
            """)
            memberships = _one(cursor, """
                SELECT count(*) total,count(*) FILTER(WHERE topic_id IS NOT NULL) with_topic,
                  count(*) FILTER(WHERE distance_miles IS NOT NULL) with_distance,
                  count(*) FILTER(WHERE outside_radius) known_outside_radius,
                  count(*) FILTER(WHERE is_primary) primary_members
                FROM hub_actor
            """)
            events = _one(cursor, """
                SELECT count(*) total,count(*) FILTER(WHERE host_actor_id IS NULL) null_host,
                  count(*) FILTER(WHERE record_status IS NULL) missing_status,
                  count(*) FILTER(WHERE source_origin IS NULL) missing_origin
                FROM event
            """)
            facts = _one(cursor, """
                SELECT count(*) actor_fact_rows,count(DISTINCT actor_id) actors_with_facts,
                  count(*) FILTER(WHERE source_id IS NULL) fact_rows_missing_source
                FROM actor_fact
            """)
            facts.update(_one(cursor, """
                SELECT count(*) actor_profile_rows,
                  count(*) FILTER(WHERE source_id IS NULL) actor_profiles_missing_source
                FROM actor_profile
            """))
            facts.update(_one(cursor, """
                SELECT count(*) capability_fact_rows,
                  count(*) FILTER(WHERE source_id IS NULL) capability_facts_missing_source,
                  count(*) FILTER(WHERE NULLIF(btrim(evidence_url),'') IS NULL) capability_facts_missing_url
                FROM actor_capability_fact
            """))
            facts["source_rows"] = _one(cursor, "SELECT count(*) value FROM source")["value"]
            scalar_fields = _one(cursor, """
                SELECT count(*) FILTER(WHERE NULLIF(btrim(description),'') IS NOT NULL) description,
                  count(*) FILTER(WHERE NULLIF(btrim(primary_technical_focus),'') IS NOT NULL) primary_technical_focus,
                  count(*) FILTER(WHERE NULLIF(btrim(technical_approach),'') IS NOT NULL) technical_approach,
                  count(*) FILTER(WHERE NULLIF(btrim(current_activities),'') IS NOT NULL) current_activities,
                  count(*) FILTER(WHERE NULLIF(btrim(technology_ip_notes),'') IS NOT NULL) technology_ip_notes,
                  count(*) FILTER(WHERE NULLIF(btrim(key_constraints),'') IS NOT NULL) key_constraints,
                  count(*) FILTER(WHERE NULLIF(btrim(funding_summary),'') IS NOT NULL) funding_summary,
                  count(*) FILTER(WHERE estimated_trl IS NOT NULL) estimated_trl
                FROM actor
            """)

            report = {
                "generated_at": datetime.now(UTC).isoformat(),
                "mode": "report_only",
                "database": EXPECTED_DATABASE,
                "database_mutated": False,
                "actors": {
                    **actors,
                    **topics,
                    "legacy_status_counts": _counts(cursor, "actor", "record_status"),
                    "legacy_category_counts": _counts(cursor, "actor", "actor_category"),
                    "category_type_counts": _counts(cursor, "actor", "category_type"),
                    "source_origin_counts": _counts(cursor, "actor", "source_origin"),
                    "proposed_status": {"verified": actors["total"]},
                    "proposed_source_origin": {"imported_phase1": actors["total"]},
                    "category_migration": {
                        **category_migration,
                        "unmappable_values": unmappable_categories,
                    },
                    "final_constraint_blockers": {
                        "actor_category": category_migration["unmappable"],
                        "coordinates": actors["missing_coordinates"],
                        "controlled_topic": actors["total"] - topics["actors_with_topic"],
                    },
                    "category_type_pending_enrichment": actors["missing_category_type"],
                },
                "aggregates": {
                    "total": len(aggregate_rows),
                    "likely_network_or_consortium_count": len(likely_network),
                    "likely_network_or_consortium_names": likely_network,
                    "likely_mistagged_count": len(likely_mistagged),
                    "likely_mistagged_names": likely_mistagged,
                    "unresolved_count": len(aggregate_rows) - len(set(likely_network) | set(likely_mistagged)),
                    "method": "name-token triage only; never an automatic reclassification",
                },
                "relationships": relationships,
                "hubs": hubs,
                "memberships": memberships,
                "events": {**events, "status_counts": _counts(cursor, "event", "record_status")},
                "facts": {**facts, "legacy_scalar_field_counts": scalar_fields,
                          "unrecoverable_provenance": actors["source_ids_present"] if facts["source_rows"] == 0 else 0},
                "reviews": {
                    "verify_actor": 0,
                    "category_doubt": category_migration["unmappable"],
                    "geocode_failed_insufficient_location": actors["missing_city"],
                    "hub_needs_review": hubs["total"],
                    "total_without_double_counting_payload_issues": (
                        category_migration["unmappable"] + actors["missing_city"] + hubs["total"]
                    ),
                },
                "invariants": {
                    "all_49_hubs_preserved": hubs["total"] == 49,
                    "all_821_memberships_preserved": memberships["total"] == 821,
                    "all_356_events_preserved": events["total"] == 356,
                    "existing_canonical_verified_by_explicit_policy": actors["total"],
                    "named_human_verifier_invented": False,
                    "missing_category_type_creates_review": False,
                    "history_invented": False,
                },
            }
        connection.rollback()
    finally:
        connection.close()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
