"""Read-only compatibility smoke checks for the backend or frontend repository."""

from __future__ import annotations

import argparse

from db_connection import engine, guarded
from sqlalchemy import text


def scalar(connection, sql: str) -> int:
    return int(connection.execute(text(sql)).scalar_one())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", choices=("backend", "frontend"), required=True)
    args = parser.parse_args()
    db_engine = engine(read_only=True, statement_timeout_ms=8000)
    try:
        with db_engine.connect() as connection:
            assert connection.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
            actor_count = scalar(connection, "SELECT count(*) FROM actor")
            assert scalar(connection, "SELECT count(*) FROM actor_v1_compat") == actor_count
            assert scalar(connection, "SELECT count(*) FROM hub") >= 0
            assert scalar(connection, "SELECT count(*) FROM event") >= 0
            if args.repo == "backend":
                category_mismatches = scalar(
                    connection,
                    "SELECT count(*) FROM actor "
                    "WHERE actor_category IS DISTINCT FROM ghus_legacy_actor_category(actor_type)",
                )
                if category_mismatches:
                    raise RuntimeError("legacy actor-category compatibility mismatch")
                status_mismatches = scalar(
                    connection,
                    "SELECT count(*) FROM actor "
                    "WHERE record_status IS DISTINCT FROM "
                    "ghus_legacy_record_status(verification_status)",
                )
                if status_mismatches:
                    raise RuntimeError("legacy actor-status compatibility mismatch")
                forbidden_mappings = scalar(
                    connection,
                    "SELECT count(*) FROM actor "
                    "WHERE record_status IN ('verified','rejected')",
                )
                if forbidden_mappings:
                    raise RuntimeError("legacy status mapping created a verified/rejected state")
                for table in ("actor_fact", "entity_edge", "review_item", "canonical_write_audit"):
                    assert scalar(connection, f"SELECT count(*) FROM {table}") >= 0
            else:
                connection.execute(text("SELECT actor_id,name,actor_type,verification_status FROM actor_v1_compat LIMIT 1"))
                connection.execute(text("SELECT * FROM staged_record_agent3_compat LIMIT 1"))
            print(f"{args.repo} read-only smoke passed; actors={actor_count}")
    finally:
        db_engine.dispose()


if __name__ == "__main__":
    guarded(main)
