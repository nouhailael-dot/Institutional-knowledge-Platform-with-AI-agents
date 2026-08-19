"""Incremental search_doc refresh with an empty-result guard."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import text

from agents.enrichment.specs import ENTITY_SPECS, EntitySpec, get_entity_spec

logger = logging.getLogger(__name__)
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True)
class SearchDocCandidate:
    entity_type: str
    entity_id: str
    name: str
    doc_text: str
    source_updated_at: object = None


@dataclass(frozen=True)
class SearchRefreshStats:
    candidates: int = 0
    upserts: int = 0
    deletes: int = 0
    skipped: int = 0


def refresh_search_doc(
    session,
    *,
    entity_types: Iterable[str] = ("actor", "hub", "person", "event"),
    limit: Optional[int] = None,
    live: bool = False,
    candidates: Optional[Iterable[SearchDocCandidate]] = None,
) -> SearchRefreshStats:
    selected = list(candidates) if candidates is not None else list(
        load_incremental_candidates(session, entity_types=entity_types, limit=limit)
    )
    if not selected:
        logger.warning("search_doc incremental refresh found zero candidates; no-op with zero deletes")
        return SearchRefreshStats(candidates=0, upserts=0, deletes=0, skipped=0)

    upserts = 0
    for candidate in selected:
        if not candidate.doc_text.strip():
            logger.warning(
                "skipping blank search_doc text for %s %s",
                candidate.entity_type,
                candidate.entity_id,
            )
            continue
        if live:
            _upsert_search_doc(session, candidate)
        upserts += 1

    if live:
        session.commit()
    else:
        session.rollback()
    return SearchRefreshStats(candidates=len(selected), upserts=upserts, deletes=0, skipped=len(selected) - upserts)


def load_incremental_candidates(
    session,
    *,
    entity_types: Iterable[str],
    limit: Optional[int] = None,
) -> list[SearchDocCandidate]:
    search_doc_columns = _table_columns(session, "search_doc")
    timestamp_column = _search_doc_timestamp_column(search_doc_columns)
    if timestamp_column is None:
        logger.warning(
            "search_doc has no updated_at/indexed_at column visible; selecting only canonical rows with no search_doc entry"
        )
    candidates: list[SearchDocCandidate] = []
    remaining = limit
    for entity_type in entity_types:
        spec = get_entity_spec(entity_type)
        rows = _load_entity_rows(
            session,
            spec,
            timestamp_column=timestamp_column,
            limit=remaining,
        )
        for row in rows:
            values = dict(row)
            builder = spec.doc_builder
            doc_text = builder(values) if builder else ""
            candidates.append(
                SearchDocCandidate(
                    entity_type=spec.entity_type,
                    entity_id=str(values["entity_id"]),
                    name=str(values.get("name") or ""),
                    doc_text=doc_text,
                    source_updated_at=values.get("source_updated_at"),
                )
            )
        if remaining is not None:
            remaining -= len(rows)
            if remaining <= 0:
                break
    return candidates


def parse_args(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entity", default="all", help="one entity type or all")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--live", action="store_true", help="commit writes; absent means dry-run")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s %(message)s")
    args = parse_args(argv)
    if args.entity == "all":
        entity_types = tuple(ENTITY_SPECS)
    else:
        entity_types = (get_entity_spec(args.entity).entity_type,)

    from src.db.session import SessionLocal

    with SessionLocal() as session:
        stats = refresh_search_doc(session, entity_types=entity_types, limit=args.limit, live=args.live)
    print(
        "search_doc_refresh candidates={candidates} upserts={upserts} deletes={deletes} skipped={skipped} live={live}".format(
            candidates=stats.candidates,
            upserts=stats.upserts,
            deletes=stats.deletes,
            skipped=stats.skipped,
            live=args.live,
        )
    )
    return 0


def _load_entity_rows(session, spec: EntitySpec, *, timestamp_column: Optional[str], limit: Optional[int]):
    for identifier in (spec.table_name, spec.id_column, spec.name_column):
        _assert_identifier(identifier)
    select_columns = [f"e.{spec.id_column}::text AS entity_id", f"e.{spec.name_column} AS name"]
    for field in spec.fields:
        _assert_identifier(field)
        if field in {spec.id_column, spec.name_column}:
            continue
        select_columns.append(f"e.{field} AS {field}")
    updated_expr = _canonical_updated_expression(spec)
    select_columns.append(f"{updated_expr} AS source_updated_at")

    if timestamp_column:
        _assert_identifier(timestamp_column)
        stale_clause = f"OR {updated_expr} > sd.{timestamp_column}"
    else:
        stale_clause = ""
    limit_clause = " LIMIT :limit" if limit else ""
    rows = session.execute(
        text(
            f"SELECT {', '.join(select_columns)} "
            f"FROM {spec.table_name} e "
            f"LEFT JOIN search_doc sd ON sd.entity_id = e.{spec.id_column} "
            f"AND sd.entity_type = :entity_type "
            f"WHERE sd.entity_id IS NULL {stale_clause} "
            f"ORDER BY e.{spec.name_column}{limit_clause}"
        ),
        {"entity_type": spec.entity_type, "limit": limit} if limit else {"entity_type": spec.entity_type},
    ).mappings().all()
    return rows


def _upsert_search_doc(session, candidate: SearchDocCandidate) -> None:
    session.execute(
        text(
            "INSERT INTO search_doc (entity_id, entity_type, name, doc_text) "
            "VALUES (CAST(:entity_id AS uuid), :entity_type, :name, :doc_text) "
            "ON CONFLICT (entity_id) DO UPDATE SET "
            "entity_type = EXCLUDED.entity_type, "
            "name = EXCLUDED.name, "
            "doc_text = EXCLUDED.doc_text"
        ),
        {
            "entity_id": candidate.entity_id,
            "entity_type": candidate.entity_type,
            "name": candidate.name,
            "doc_text": candidate.doc_text,
        },
    )


def _table_columns(session, table_name: str) -> set[str]:
    rows = session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :table_name"
        ),
        {"table_name": table_name},
    ).all()
    return {str(row[0]) for row in rows}


def _search_doc_timestamp_column(columns: set[str]) -> Optional[str]:
    if "updated_at" in columns:
        return "updated_at"
    if "indexed_at" in columns:
        return "indexed_at"
    return None


def _canonical_updated_expression(spec: EntitySpec) -> str:
    if spec.updated_at_column:
        _assert_identifier(spec.updated_at_column)
        return f"e.{spec.updated_at_column}"
    return "e.created_at"


def _assert_identifier(value: str) -> None:
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(f"unsafe SQL identifier: {value!r}")


if __name__ == "__main__":
    sys.exit(main())
