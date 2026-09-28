"""Read-only compatibility smoke checks for the backend or frontend repository."""

from __future__ import annotations

import argparse
import os

from sqlalchemy import create_engine, text


def scalar(connection, sql: str) -> int:
    return int(connection.execute(text(sql)).scalar_one())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", choices=("backend", "frontend"), required=True)
    args = parser.parse_args()
    raw_url = os.environ.get("V2_ADDITIVE_DATABASE_URL", "").strip()
    if not raw_url:
        raise RuntimeError("V2_ADDITIVE_DATABASE_URL is required")
    engine = create_engine(
        raw_url,
        connect_args={"options": "-c default_transaction_read_only=on -c statement_timeout=8000"},
    )
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
            actor_count = scalar(connection, "SELECT count(*) FROM actor")
            assert scalar(connection, "SELECT count(*) FROM actor_v1_compat") == actor_count
            assert scalar(connection, "SELECT count(*) FROM hub") >= 0
            assert scalar(connection, "SELECT count(*) FROM event") >= 0
            if args.repo == "backend":
                assert scalar(connection, "SELECT count(*) FROM actor WHERE actor_category IS DISTINCT FROM actor_type") == 0
                assert scalar(connection, "SELECT count(*) FROM actor WHERE record_status IS DISTINCT FROM verification_status") == 0
                for table in ("actor_fact", "entity_edge", "review_item", "canonical_write_audit"):
                    assert scalar(connection, f"SELECT count(*) FROM {table}") >= 0
            else:
                connection.execute(text("SELECT actor_id,name,actor_type,verification_status FROM actor_v1_compat LIMIT 1"))
                connection.execute(text("SELECT * FROM staged_record_agent3_compat LIMIT 1"))
            print(f"{args.repo} read-only smoke passed; actors={actor_count}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
