"""Capture public-schema row counts and object signatures using a read-only session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from db_connection import engine, guarded
from sqlalchemy import text

OBJECT_SQL = {
    "tables": "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1",
    "views": "SELECT table_name FROM information_schema.views WHERE table_schema='public' ORDER BY 1",
    "columns": "SELECT table_name||'.'||column_name FROM information_schema.columns WHERE table_schema='public' ORDER BY 1",
    "indexes": "SELECT indexname FROM pg_indexes WHERE schemaname='public' ORDER BY 1",
    "functions": "SELECT p.proname||'('||pg_get_function_identity_arguments(p.oid)||')' FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' ORDER BY 1",
    "triggers": "SELECT event_object_table||'.'||trigger_name FROM information_schema.triggers WHERE trigger_schema='public' ORDER BY 1",
    "policies": "SELECT tablename||'.'||policyname FROM pg_policies WHERE schemaname='public' ORDER BY 1",
}


def snapshot() -> dict[str, object]:
    db_engine = engine(read_only=True, statement_timeout_ms=30000)
    try:
        with db_engine.connect() as connection:
            read_only = connection.execute(text("SHOW transaction_read_only")).scalar_one()
            if read_only != "on":
                raise RuntimeError("state capture connection is not read-only")
            tables = [row[0] for row in connection.execute(text(OBJECT_SQL["tables"]))]
            counts = {
                table: connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
                for table in tables
            }
            objects = {
                kind: [row[0] for row in connection.execute(text(sql))]
                for kind, sql in OBJECT_SQL.items()
            }
            version = connection.execute(text("SHOW server_version")).scalar_one()
            return {"server_version": version, "row_counts": counts, "objects": objects}
    finally:
        db_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    guarded(main)
