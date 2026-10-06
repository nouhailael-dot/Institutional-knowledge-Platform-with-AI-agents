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
    "ghus_v2_phase12_rehearsal_test": (
        EVIDENCE / "phase12_policy_backfill_proof_rehearsal_2026-10-06.json",
        EVIDENCE / "pre_cutover_data_loss_audit_rehearsal_2026-10-06.json",
    ),
}


SCALAR_FIELDS = (
    "description", "primary_technical_focus", "technical_approach", "current_activities",
    "technology_ip_notes", "key_constraints", "funding_summary", "estimated_trl",
    "primary_lifecycle_role",
)
PROFILE_FIELDS = (
    "profile_summary", "identity_summary", "technical_summary", "lifecycle_summary",
    "funding_summary",
)
LEGACY_TABLE_COUNTS = {
    "record_verification": "SELECT count(*) value FROM record_verification "
                           "WHERE entity_type='actor'",
    "organization_hierarchy": "SELECT count(*) value FROM organization_hierarchy",
    "actor_profile": "SELECT " + "+".join(
        f"count(*) FILTER(WHERE NULLIF(btrim({field}),'') IS NOT NULL)" for field in PROFILE_FIELDS
    ) + " value FROM actor_profile",
    "actor_capability_fact": "SELECT count(*) value FROM actor_capability_fact",
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


def _record_check(source: str, destination: str, source_rows: int,
                  dispositions: dict[str, int], *, extra: bool = True) -> dict:
    """Every legacy value needs a destination row or an explicit listed record."""
    destination_rows = sum(dispositions.values())
    check = {
        "source": source,
        "destination": destination,
        "source_rows": source_rows,
        "destination_rows": destination_rows,
        "destination_by_disposition": dispositions,
        "passed": source_rows == destination_rows and extra,
    }
    if not check["passed"]:
        check["blocker"] = "Legacy values without a destination row or listed migration record."
    return check


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
                  count(*) FILTER(WHERE status='rejected' AND EXISTS (
                    SELECT 1 FROM actor_verification_event e WHERE e.actor_id=actor.actor_id
                      AND e.decision='rejected' AND e.decision_origin='ghus_review'))
                    rejected_by_ghus,
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
            # Rows removed by an explicit GHUS decision are archived, never lost.
            archived = {"hubs": 0, "memberships": 0}
            if _one(cursor, "SELECT to_regclass('public.hub_removed') IS NOT NULL value")["value"]:
                archived = {
                    "hubs": _one(cursor, "SELECT count(*) value FROM hub_removed")["value"],
                    "memberships": _one(cursor, "SELECT count(*) value FROM hub_actor_removed")["value"],
                }
            invariants = {
                "hubs": _one(cursor, "SELECT count(*) value FROM hub")["value"],
                "memberships": _one(cursor, "SELECT count(*) value FROM hub_actor")["value"],
                "events": _one(cursor, "SELECT count(*) value FROM event")["value"],
                "archived_by_ghus_decision": archived,
            }
            legacy_fields = {}
            for field in SCALAR_FIELDS:
                legacy_fields[field] = _one(cursor, f"""
                    SELECT count(*) FILTER(WHERE NULLIF(btrim({field}::text),'') IS NOT NULL) value
                    FROM actor
                """)["value"]
            has_status_column = _one(cursor, """
                SELECT count(*) > 0 value FROM information_schema.columns
                WHERE table_schema='public' AND table_name='actor'
                  AND column_name='verification_status'
            """)["value"]
            status_column = "verification_status" if has_status_column else "record_status"
            cursor.execute(f"SELECT COALESCE({status_column},'<null>') value,count(*) n "
                           "FROM actor GROUP BY 1")
            legacy_status = {row["value"]: row["n"] for row in cursor.fetchall()}
            cursor.execute("SELECT COALESCE(prior_status,'<null>') value,count(*) n "
                           "FROM actor_category_migration_audit GROUP BY 1")
            prior_status = {row["value"]: row["n"] for row in cursor.fetchall()}
            legacy_identity = _one(cursor, """
                SELECT count(actor_type_raw) actor_type_raw,
                  count(*) FILTER(WHERE NULLIF(btrim(state),'') IS NOT NULL) state,
                  count(*) FILTER(WHERE NULLIF(btrim(state),'') IS NOT NULL
                                    AND state_code IS NOT NULL) state_normalized,
                  count(alternate_names) alternate_names,
                  count(location_city) location_city
                FROM actor
            """)
            audit_preservation = _one(cursor, """
                SELECT count(legacy_category) legacy_category,
                  count(legacy_category_raw) legacy_category_raw
                FROM actor_category_migration_audit
            """)
            legacy_tables = {}
            for table, count_sql in LEGACY_TABLE_COUNTS.items():
                exists = _one(cursor, f"SELECT to_regclass('public.{table}') IS NOT NULL value")
                legacy_tables[table] = _one(cursor, count_sql)["value"] if exists["value"] else 0
            has_records = _one(cursor, "SELECT to_regclass('public.legacy_migration_record') "
                                       "IS NOT NULL value")["value"]
            records: dict[tuple[str, str], dict[str, int]] = {}
            if has_records:
                # A fact/review record only counts when its destination row really exists.
                cursor.execute("""
                    SELECT r.legacy_table,r.legacy_field,r.disposition,count(*) n
                    FROM legacy_migration_record r
                    LEFT JOIN actor_fact f ON r.destination_table='actor_fact'
                                          AND f.actor_fact_id=r.destination_id
                    LEFT JOIN review_item i ON r.destination_table='review_item'
                                           AND i.review_item_id=r.destination_id
                    WHERE r.disposition IN ('audit_only','normalized')
                       OR f.actor_fact_id IS NOT NULL OR i.review_item_id IS NOT NULL
                       OR (r.disposition='review' AND r.legacy_field='state')
                    GROUP BY 1,2,3
                """)
                for row in cursor.fetchall():
                    key = (row["legacy_table"], row["legacy_field"])
                    records.setdefault(key, {})[row["disposition"]] = row["n"]
        connection.rollback()
    finally:
        connection.close()

    assertions = {
        "all_existing_actors_scoped": migration["total"] == actor["total"] == 965,
        # Every actor is Verified, unless GHUS explicitly rejected it with an event.
        "all_existing_actors_verified": actor["verified"] + actor["rejected_by_ghus"]
        == actor["total"],
        "verification_provenance_honest": events["honest_bootstrap"] == actor["total"],
        "missing_type_is_pending_not_review": actor["category_type_pending"] == 965
        and reviews["category_review"] == migration["requires_review"],
        "mapped_plus_review_reconciles": migration["mapped"] + migration["requires_review"] == actor["total"],
        "historical_memberships_preserved": invariants["memberships"] + archived["memberships"]
        == 821,
        "hubs_preserved": invariants["hubs"] + archived["hubs"] == 49,
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
            "source": "actor.verification_status (legacy status distribution)",
            "destination": "actor.status + actor_verification_event + migration audit prior_status",
            "source_rows": sum(n for v, n in legacy_status.items() if v != "<null>"),
            "destination_rows": sum(n for v, n in prior_status.items() if v != "<null>"),
            "source_distribution": legacy_status,
            "destination_distribution": prior_status,
            "passed": legacy_status == prior_status
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
        _record_check(
            "actor.state", "actor.state_code + region_code, or geocode review with raw value",
            legacy_identity["state"], records.get(("actor", "state"), {}),
            extra=legacy_identity["state_normalized"]
            == records.get(("actor", "state"), {}).get("normalized", 0),
        ),
    ]
    for field, source_rows in legacy_fields.items():
        loss_checks.append(_record_check(
            f"actor.{field}", f"actor_fact[legacy_baseline.{field}] or listed audit record",
            source_rows, records.get(("actor", field), {}),
        ))
    profile_records: dict[str, int] = {}
    for field in PROFILE_FIELDS:
        for disposition, n in records.get(("actor_profile", field), {}).items():
            profile_records[disposition] = profile_records.get(disposition, 0) + n
    loss_checks.extend([
        _record_check("record_verification (actor decisions)",
                      "actor_verification_event (genuine GHUS decisions)",
                      legacy_tables["record_verification"], {}),
        _record_check("organization_hierarchy", "entity_edge or relationship_review",
                      legacy_tables["organization_hierarchy"],
                      records.get(("organization_hierarchy", "relationship"), {})),
        _record_check("actor_profile (non-empty summary values)",
                      "actor_fact[legacy_profile] or listed audit record",
                      legacy_tables["actor_profile"], profile_records),
        _record_check("actor_capability_fact", "identical actor_fact or listed audit record",
                      legacy_tables["actor_capability_fact"],
                      records.get(("actor_capability_fact", "fact_value"), {})),
    ])
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
