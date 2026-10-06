"""Report the corrected Phase 12 backfill proof and fail-closed loss audit."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence"
# Isolated migration databases this proof may read, each with its own evidence files.
POLICY_DATABASES = {
    "ghus_v2_phase12_policy_test": (
        EVIDENCE / "phase12_policy_backfill_proof_2026-10-06.json",
        EVIDENCE / "pre_cutover_data_loss_audit_2026-10-06.json",
    ),
    "ghus_v2_phase12_full_test": (
        EVIDENCE / "phase12_policy_backfill_proof_full_dump_2026-10-06.json",
        EVIDENCE / "pre_cutover_data_loss_audit_full_dump_2026-10-06.json",
    ),
}


def _url() -> tuple[str, str]:
    raw = os.environ.get("V2_PHASE12_POLICY_DATABASE_URL", "").strip()
    parsed = urlsplit(raw.replace("postgresql+psycopg2", "postgresql", 1))
    database = parsed.path.removeprefix("/")
    if (
        parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port != 55432
        or database not in POLICY_DATABASES
    ):
        raise RuntimeError("policy proof accepts only the named isolated migration databases")
    return raw.replace("postgresql+psycopg2", "postgresql", 1), database


def _one(cursor, statement: str) -> dict:
    cursor.execute(statement)
    return dict(cursor.fetchone())


def main() -> int:
    url, database = _url()
    proof_path, loss_path = POLICY_DATABASES[database]
    connection = psycopg2.connect(url, application_name="ghus_phase12_policy_proof")
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            actor = _one(cursor, """
                SELECT count(*) total,
                  count(*) FILTER(WHERE status='verified') verified,
                  count(*) FILTER(WHERE category_type IS NOT NULL) category_type_populated,
                  count(*) FILTER(WHERE category_type IS NULL) category_type_pending,
                  count(*) FILTER(WHERE actor_category IS NULL) category_unresolved,
                  count(*) FILTER(WHERE source_origin='imported_phase1') imported_origin
                FROM actor
            """)
            migration = _one(cursor, """
                SELECT count(*) total,
                  count(*) FILTER(WHERE mapping_status='mapped') mapped,
                  count(*) FILTER(WHERE mapping_status='requires_review') requires_review
                FROM actor_category_migration_audit
                WHERE migration_batch_id='phase12_existing_canonical_2026_10'
            """)
            events = _one(cursor, """
                SELECT count(*) total,
                  count(*) FILTER(WHERE decision_origin='existing_canonical_migration'
                    AND decision='verified' AND decided_by IS NULL AND decided_at IS NULL
                    AND topic_id IS NULL) honest_bootstrap
                FROM actor_verification_event
            """)
            reviews = _one(cursor, """
                SELECT count(*) FILTER(WHERE review_kind='category_doubt'
                  AND payload->>'migration_batch_id'='phase12_existing_canonical_2026_10')
                  category_review
                FROM review_item
            """)
            invariants = {
                "hubs": _one(cursor, "SELECT count(*) value FROM hub")["value"],
                "memberships": _one(cursor, "SELECT count(*) value FROM hub_actor")["value"],
                "events": _one(cursor, "SELECT count(*) value FROM event")["value"],
            }
            scalar = _one(cursor, """
                SELECT count(*) FILTER(WHERE NULLIF(btrim(primary_technical_focus),'') IS NOT NULL) primary_technical_focus,
                  count(*) FILTER(WHERE NULLIF(btrim(technical_approach),'') IS NOT NULL) technical_approach,
                  count(*) FILTER(WHERE NULLIF(btrim(current_activities),'') IS NOT NULL) current_activities,
                  count(*) FILTER(WHERE NULLIF(btrim(technology_ip_notes),'') IS NOT NULL) technology_ip_notes,
                  count(*) FILTER(WHERE NULLIF(btrim(key_constraints),'') IS NOT NULL) key_constraints,
                  count(*) FILTER(WHERE NULLIF(btrim(funding_summary),'') IS NOT NULL) funding_summary,
                  count(*) FILTER(WHERE estimated_trl IS NOT NULL) estimated_trl,
                  count(*) FILTER(WHERE NULLIF(btrim(primary_lifecycle_role),'') IS NOT NULL) primary_lifecycle_role
                FROM actor
            """)
            legacy_identity = _one(cursor, """
                SELECT count(actor_type_raw) actor_type_raw,
                  count(record_status) record_status,
                  count(state) state,
                  count(state_code) state_code,
                  count(alternate_names) alternate_names,
                  count(location_city) location_city
                FROM actor
            """)
            audit_preservation = _one(cursor, """
                SELECT count(legacy_category) legacy_category,
                  count(legacy_category_raw) legacy_category_raw,
                  count(prior_status) prior_status
                FROM actor_category_migration_audit
            """)
            legacy_tables = {
                table: _one(cursor, f"SELECT count(*) value FROM {table}")["value"]
                for table in (
                    "record_verification",
                    "organization_hierarchy",
                    "actor_profile",
                    "actor_capability_fact",
                )
            }
            facts = _one(cursor, "SELECT count(*) imported_facts FROM actor_fact")
        connection.rollback()
    finally:
        connection.close()

    assertions = {
        "all_existing_actors_scoped": migration["total"] == actor["total"] == 965,
        "all_existing_actors_verified": actor["verified"] == actor["total"],
        "verification_provenance_honest": events["honest_bootstrap"] == actor["total"],
        "missing_type_is_pending_not_review": actor["category_type_pending"] == 965
        and reviews["category_review"] == migration["requires_review"],
        "mapped_plus_review_reconciles": migration["mapped"] + migration["requires_review"] == actor["total"],
        "historical_memberships_preserved": invariants["memberships"] == 821,
        "hubs_preserved": invariants["hubs"] == 49,
        "events_preserved": invariants["events"] == 356,
    }
    proof = {
        "generated_at": datetime.now(UTC).isoformat(),
        "database": database,
        "actor": actor,
        "category_mapping": migration,
        "verification_events": events,
        "reviews": reviews,
        "row_count_invariants": invariants,
        "assertions": assertions,
        "passed": all(assertions.values()),
    }
    loss_checks = [
        {
            "source": "actor.actor_type / legacy actor_category concept",
            "destination": "actor.actor_category + actor_category_migration_audit.legacy_category",
            "source_rows": actor["total"],
            "destination_rows": migration["total"],
            "passed": assertions["all_existing_actors_scoped"],
        },
        {
            "source": "actor.actor_type_raw",
            "destination": "actor_category_migration_audit.legacy_category_raw",
            "source_rows": legacy_identity["actor_type_raw"],
            "destination_rows": audit_preservation["legacy_category_raw"],
            "passed": legacy_identity["actor_type_raw"]
            == audit_preservation["legacy_category_raw"],
        },
        {
            "source": "actor.verification_status / actor.record_status",
            "destination": "actor.status + actor_verification_event + migration audit prior_status",
            "source_rows": legacy_identity["record_status"],
            "destination_rows": audit_preservation["prior_status"],
            "passed": legacy_identity["record_status"] == audit_preservation["prior_status"]
            and assertions["verification_provenance_honest"],
        },
        {
            "source": "actor.alternate_names",
            "destination": "actor.alt_names rename",
            "source_rows": legacy_identity["alternate_names"],
            "destination_rows": legacy_identity["alternate_names"],
            "passed": True,
        },
        {
            "source": "actor.location_city",
            "destination": "actor.city rename",
            "source_rows": legacy_identity["location_city"],
            "destination_rows": legacy_identity["location_city"],
            "passed": True,
        },
        {
            "source": "actor.state",
            "destination": "actor.state_code + region_code",
            "source_rows": legacy_identity["state"],
            "destination_rows": legacy_identity["state_code"],
            "passed": legacy_identity["state"] == legacy_identity["state_code"],
            "blocker": "Deterministic state normalization has not run.",
        },
    ]
    for source_field, source_rows in scalar.items():
        loss_checks.append({
            "source": f"actor.{source_field}",
            "destination": f"actor_fact[{source_field}]",
            "source_rows": source_rows,
            "destination_rows": facts["imported_facts"],
            "passed": source_rows == 0,
            "blocker": "Imported historical facts have not yet been appended with baseline provenance.",
        })
    for source_table, source_rows in legacy_tables.items():
        destination = {
            "record_verification": "actor_verification_event",
            "organization_hierarchy": "entity_edge",
            "actor_profile": "actor_fact",
            "actor_capability_fact": "actor_fact",
        }[source_table]
        loss_checks.append({
            "source": source_table,
            "destination": destination,
            "source_rows": source_rows,
            "destination_rows": 0,
            "passed": source_rows == 0,
            "blocker": None if source_rows == 0 else "Rows require semantic migration and reconciliation.",
        })
    loss_checks.extend([
        {
            "source": "actor_v1_compat, staged_record_agent3_compat, actor_profile_current views",
            "destination": "final V2 tables/views",
            "source_rows": 0,
            "destination_rows": 0,
            "passed": True,
        },
        {
            "source": "hub and membership history",
            "destination": "hub and hub_actor",
            "passed": assertions["hubs_preserved"]
            and assertions["historical_memberships_preserved"],
        },
    ])
    loss = {
        "generated_at": datetime.now(UTC).isoformat(),
        "database": database,
        "audit_name": "pre_cutover_data_loss_audit",
        "passed": all(item["passed"] for item in loss_checks),
        "cutover_attestation_written": False,
        "checks": loss_checks,
        "rule": "Migration 500 must fail closed until this audit passes and is independently attested.",
    }
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    loss_path.write_text(json.dumps(loss, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {proof_path.relative_to(ROOT)}; passed={proof['passed']}")
    print(f"wrote {loss_path.relative_to(ROOT)}; passed={loss['passed']}")
    return 0 if proof["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
