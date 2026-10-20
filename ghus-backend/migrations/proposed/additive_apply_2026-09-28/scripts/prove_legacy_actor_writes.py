"""Prove additive actor compatibility through the legacy insert/update column shape."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from db_connection import engine, guarded
from sqlalchemy import text

UNKNOWN_TYPE = "__ghus_unknown_legacy_actor_type__"


def expected_category(connection, actor_type: str | None) -> str | None:
    return connection.execute(
        text("SELECT ghus_legacy_actor_category(:actor_type)"),
        {"actor_type": actor_type},
    ).scalar_one()


def expected_status(connection, verification_status: str | None) -> str | None:
    return connection.execute(
        text("SELECT ghus_legacy_record_status(:verification_status)"),
        {"verification_status": verification_status},
    ).scalar_one()


def assert_compatible(
    connection,
    *,
    actor_type: str | None,
    actor_category: str | None,
    verification_status: str | None,
    record_status: str | None,
) -> None:
    expected = expected_category(connection, actor_type)
    if actor_category != expected:
        raise AssertionError(
            f"actor_type compatibility mismatch for {actor_type!r}: "
            f"expected {expected!r}, received {actor_category!r}"
        )
    expected_record_status = expected_status(connection, verification_status)
    if record_status != expected_record_status:
        raise AssertionError(
            f"legacy verification status mapping mismatch for {verification_status!r}: "
            f"expected {expected_record_status!r}, received {record_status!r}"
        )
    if record_status in {"verified", "rejected"}:
        raise AssertionError("legacy status mapping must never yield verified/rejected")


def prove() -> dict[str, object]:
    db_engine = engine()
    try:
        with db_engine.connect() as connection:
            transaction = connection.begin()
            before = connection.execute(text("SELECT count(*) FROM actor")).scalar_one()
            existing_types = [
                row[0]
                for row in connection.execute(
                    text("SELECT DISTINCT actor_type FROM actor ORDER BY actor_type NULLS FIRST")
                )
            ]
            test_types = existing_types + [UNKNOWN_TYPE]
            existing_statuses = [
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT DISTINCT verification_status FROM actor "
                        "ORDER BY verification_status NULLS FIRST"
                    )
                )
            ]
            test_statuses = existing_statuses + ["verified", "rejected", "__unknown_status__"]
            insert_results: list[dict[str, object]] = []
            for position, actor_type in enumerate(test_types):
                actor_id = str(uuid.uuid4())
                status = test_statuses[position % len(test_statuses)]
                row = connection.execute(
                    text(
                        "INSERT INTO actor "
                        "(actor_id,name,actor_type,verification_status) "
                        "VALUES (CAST(:actor_id AS uuid),:name,:actor_type,:verification_status) "
                        "RETURNING actor_type,actor_category,verification_status,record_status"
                    ),
                    {
                        "actor_id": actor_id,
                        "name": f"V2 additive legacy insert probe {position}",
                        "actor_type": actor_type,
                        "verification_status": status,
                    },
                ).one()
                assert_compatible(
                    connection,
                    actor_type=row.actor_type,
                    actor_category=row.actor_category,
                    verification_status=row.verification_status,
                    record_status=row.record_status,
                )
                insert_results.append(
                    {
                        "actor_type": actor_type,
                        "actor_category": row.actor_category,
                        "verification_status": row.verification_status,
                        "record_status": row.record_status,
                    }
                )

            update_actor_id = str(uuid.uuid4())
            connection.execute(
                text(
                    "INSERT INTO actor (actor_id,name,actor_type,verification_status) "
                    "VALUES (CAST(:actor_id AS uuid),:name,NULL,'needs_review')"
                ),
                {"actor_id": update_actor_id, "name": "V2 additive legacy update probe"},
            )
            update_results: list[dict[str, object]] = []
            for position, actor_type in enumerate(test_types):
                status = test_statuses[position % len(test_statuses)]
                row = connection.execute(
                    text(
                        "UPDATE actor SET actor_type=:actor_type, verification_status=:status "
                        "WHERE actor_id=CAST(:actor_id AS uuid) "
                        "RETURNING actor_type,actor_category,verification_status,record_status"
                    ),
                    {"actor_id": update_actor_id, "actor_type": actor_type, "status": status},
                ).one()
                assert_compatible(
                    connection,
                    actor_type=row.actor_type,
                    actor_category=row.actor_category,
                    verification_status=row.verification_status,
                    record_status=row.record_status,
                )
                update_results.append(
                    {
                        "actor_type": actor_type,
                        "actor_category": row.actor_category,
                        "verification_status": row.verification_status,
                        "record_status": row.record_status,
                    }
                )

            unknown_insert = insert_results[-1]
            unknown_update = update_results[-1]
            if unknown_insert["actor_category"] is not None or unknown_update["actor_category"] is not None:
                raise AssertionError("an unmapped legacy actor_type must leave actor_category NULL")
            transaction.rollback()

        with db_engine.connect() as connection:
            after = connection.execute(text("SELECT count(*) FROM actor")).scalar_one()
        if before != after:
            raise AssertionError("legacy compatibility proof did not roll back cleanly")
        return {
            "existing_actor_type_count": len(existing_types),
            "tested_actor_types": test_types,
            "existing_verification_statuses": existing_statuses,
            "tested_verification_statuses": test_statuses,
            "insert_results": insert_results,
            "update_results": update_results,
            "unknown_category_is_null": True,
            "verified_or_rejected_mapping_count": 0,
            "actor_count_before": before,
            "actor_count_after": after,
            "transaction_rolled_back": True,
        }
    finally:
        db_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(prove(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    guarded(main)
