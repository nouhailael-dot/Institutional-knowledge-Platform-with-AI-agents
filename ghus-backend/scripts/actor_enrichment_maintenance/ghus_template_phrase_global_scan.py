"""Scan all database text columns for old GHUS template/provenance phrases."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.sql.sqltypes import String, Text

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # ghus-backend/
WORKSPACE = Path(r"C:\Users\Ismail\Documents\GHUS")
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.session import engine  # noqa: E402


PATTERNS = (
    "existing ghus",
    "ghus context",
    "hub-linked actor referenced",
    "context used:",
    "linked hub context:",
    "no high-confidence structured api match",
    "enriched from hub context only",
    "existing ghus record",
)


def clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split())


def matched_patterns(value: Any) -> list[str]:
    low = clean(value).lower()
    return [pattern for pattern in PATTERNS if pattern in low]


def text_columns(inspector, schema: str | None):
    for table_name in inspector.get_table_names(schema=schema):
        for column in inspector.get_columns(table_name, schema=schema):
            if isinstance(column["type"], (String, Text)):
                yield schema, table_name, column["name"]


def primary_key_columns(inspector, table_name: str, schema: str | None) -> list[str]:
    pk = inspector.get_pk_constraint(table_name, schema=schema)
    return list(pk.get("constrained_columns") or [])


def q(preparer, name: str) -> str:
    return preparer.quote_identifier(name)


def fqtn(preparer, schema: str | None, table_name: str) -> str:
    if schema:
        return f"{q(preparer, schema)}.{q(preparer, table_name)}"
    return q(preparer, table_name)


def build_sample_query(preparer, schema: str | None, table_name: str, column_name: str, pk_cols: list[str]) -> str:
    table_expr = fqtn(preparer, schema, table_name)
    col_expr = q(preparer, column_name)
    pk_select = ", ".join(q(preparer, pk) for pk in pk_cols)
    if not pk_select:
        pk_select = "ctid::text AS row_ref"
    where = " OR ".join(f"lower({col_expr}::text) LIKE :p{i}" for i, _ in enumerate(PATTERNS))
    return f"SELECT {pk_select}, {col_expr}::text AS value FROM {table_expr} WHERE {where} LIMIT 500"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", default="public")
    parser.add_argument("--report", default=str(WORKSPACE / "ghus_template_phrase_global_hits.csv"))
    parser.add_argument("--sample-limit", type=int, default=5000)
    args = parser.parse_args()

    inspector = inspect(engine)
    preparer = engine.dialect.identifier_preparer
    params = {f"p{i}": f"%{pattern}%" for i, pattern in enumerate(PATTERNS)}
    hits: list[dict[str, str]] = []
    scanned = 0

    with engine.connect() as conn:
        conn.execute(text("set statement_timeout to '10min'"))
        for schema, table_name, column_name in text_columns(inspector, args.schema):
            scanned += 1
            pk_cols = primary_key_columns(inspector, table_name, schema)
            query = build_sample_query(preparer, schema, table_name, column_name, pk_cols)
            try:
                rows = conn.execute(text(query), params).mappings().all()
            except Exception as exc:  # pragma: no cover - operational scan
                hits.append(
                    {
                        "table": table_name,
                        "column": column_name,
                        "row_ref": "<scan-error>",
                        "patterns": type(exc).__name__,
                        "value": str(exc)[:500],
                    }
                )
                continue
            for row in rows:
                if len(hits) >= args.sample_limit:
                    break
                row_ref_parts = []
                for pk in pk_cols:
                    row_ref_parts.append(f"{pk}={row.get(pk)}")
                if not row_ref_parts and row.get("row_ref"):
                    row_ref_parts.append(str(row["row_ref"]))
                value = row.get("value") or ""
                hits.append(
                    {
                        "table": table_name,
                        "column": column_name,
                        "row_ref": "|".join(row_ref_parts),
                        "patterns": "|".join(matched_patterns(value)),
                        "value": clean(value),
                    }
                )
            if len(hits) >= args.sample_limit:
                break

    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["table", "column", "row_ref", "patterns", "value"])
        writer.writeheader()
        writer.writerows(hits)

    print(f"text_columns_scanned={scanned}")
    print(f"hits_sampled={len(hits)}")
    print("by_table=" + str(dict(Counter(hit["table"] for hit in hits))))
    print("by_table_column=" + str(dict(Counter(f"{hit['table']}.{hit['column']}" for hit in hits))))
    print(f"report={report}")
    for hit in hits[:120]:
        print(f"HIT|{hit['table']}|{hit['column']}|{hit['row_ref']}|{hit['patterns']}|{hit['value'][:260]}")


if __name__ == "__main__":
    main()
