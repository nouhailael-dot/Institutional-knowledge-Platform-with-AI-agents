"""Incremental search_doc refresh with an empty-result guard."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass, replace
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
    from_index_dirty: bool = False


@dataclass(frozen=True)
class SearchRefreshStats:
    candidates: int = 0
    upserts: int = 0
    deletes: int = 0
    skipped: int = 0
    updated_at_candidates: int = 0
    index_dirty_candidates: int = 0
    dirty_cleared: int = 0


@dataclass(frozen=True)
class CandidateSelection:
    candidates: list[SearchDocCandidate]
    updated_at_candidates: int = 0
    index_dirty_candidates: int = 0


def refresh_search_doc(
    session,
    *,
    entity_types: Iterable[str] = ("actor", "hub", "person", "event"),
    limit: Optional[int] = None,
    live: bool = False,
    candidates: Optional[Iterable[SearchDocCandidate]] = None,
) -> SearchRefreshStats:
    if candidates is not None:
        selected = list(candidates)
        index_dirty_candidates = sum(1 for candidate in selected if candidate.from_index_dirty)
        updated_at_candidates = len(selected) - index_dirty_candidates
    else:
        selection = load_incremental_candidate_selection(session, entity_types=entity_types, limit=limit)
        selected = selection.candidates
        updated_at_candidates = selection.updated_at_candidates
        index_dirty_candidates = selection.index_dirty_candidates

    logger.info(
        "search_doc candidate counts updated_at=%s index_dirty=%s total=%s",
        updated_at_candidates,
        index_dirty_candidates,
        len(selected),
    )
    if not selected:
        logger.warning("search_doc incremental refresh found zero candidates; no-op with zero deletes")
        return SearchRefreshStats(
            candidates=0,
            upserts=0,
            deletes=0,
            skipped=0,
            updated_at_candidates=updated_at_candidates,
            index_dirty_candidates=index_dirty_candidates,
            dirty_cleared=0,
        )

    upserts = 0
    dirty_cleared = 0
    try:
        for candidate in selected:
            if not str(candidate.entity_type or "").strip() or not str(candidate.entity_id or "").strip():
                raise RuntimeError("search_doc candidate missing entity_type or entity_id")
            if not candidate.doc_text.strip():
                logger.warning(
                    "skipping blank search_doc text for %s %s",
                    candidate.entity_type,
                    candidate.entity_id,
                )
                continue
            _upsert_search_doc(session, candidate)
            if candidate.from_index_dirty:
                _clear_index_dirty(session, candidate)
                dirty_cleared += 1
            upserts += 1
    except Exception:
        session.rollback()
        raise

    if live:
        session.commit()
    else:
        session.rollback()
    return SearchRefreshStats(
        candidates=len(selected),
        upserts=upserts,
        deletes=0,
        skipped=len(selected) - upserts,
        updated_at_candidates=updated_at_candidates,
        index_dirty_candidates=index_dirty_candidates,
        dirty_cleared=dirty_cleared,
    )


def load_incremental_candidates(
    session,
    *,
    entity_types: Iterable[str],
    limit: Optional[int] = None,
) -> list[SearchDocCandidate]:
    return load_incremental_candidate_selection(session, entity_types=entity_types, limit=limit).candidates


def load_incremental_candidate_selection(
    session,
    *,
    entity_types: Iterable[str],
    limit: Optional[int] = None,
) -> CandidateSelection:
    search_doc_columns = _table_columns(session, "search_doc")
    timestamp_column = _search_doc_timestamp_column(search_doc_columns)
    if timestamp_column is None:
        logger.warning(
            "search_doc has no updated_at/indexed_at column visible; selecting only canonical rows with no search_doc entry"
        )
    updated_candidates: list[SearchDocCandidate] = []
    dirty_candidates: list[SearchDocCandidate] = []
    remaining = limit
    for entity_type in entity_types:
        spec = get_entity_spec(entity_type)
        rows = []
        if remaining is None or remaining > 0:
            rows = _load_entity_rows(
                session,
                spec,
                timestamp_column=timestamp_column,
                limit=remaining,
            )
            for row in rows:
                updated_candidates.append(_candidate_from_row(spec, row, from_index_dirty=False))
            if remaining is not None:
                remaining -= len(rows)
        dirty_rows = _load_index_dirty_rows(session, spec)
        for row in dirty_rows:
            dirty_candidates.append(_candidate_from_row(spec, row, from_index_dirty=True))

    combined: dict[tuple[str, str], SearchDocCandidate] = {}
    for candidate in updated_candidates:
        combined[(candidate.entity_type, candidate.entity_id)] = candidate
    for candidate in dirty_candidates:
        key = (candidate.entity_type, candidate.entity_id)
        if key in combined:
            combined[key] = replace(combined[key], from_index_dirty=True)
        else:
            combined[key] = candidate

    return CandidateSelection(
        candidates=list(combined.values()),
        updated_at_candidates=len(updated_candidates),
        index_dirty_candidates=len(dirty_candidates),
    )


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
        (
            "search_doc_refresh candidates={candidates} updated_at_candidates={updated_at_candidates} "
            "index_dirty_candidates={index_dirty_candidates} upserts={upserts} "
            "dirty_cleared={dirty_cleared} deletes={deletes} skipped={skipped} live={live}"
        ).format(
            candidates=stats.candidates,
            updated_at_candidates=stats.updated_at_candidates,
            index_dirty_candidates=stats.index_dirty_candidates,
            upserts=stats.upserts,
            dirty_cleared=stats.dirty_cleared,
            deletes=stats.deletes,
            skipped=stats.skipped,
            live=args.live,
        )
    )
    return 0


def _load_entity_rows(session, spec: EntitySpec, *, timestamp_column: Optional[str], limit: Optional[int]):
    for identifier in (spec.table_name, spec.id_column, spec.name_column):
        _assert_identifier(identifier)
    select_columns = _select_columns(spec)
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


def _load_index_dirty_rows(session, spec: EntitySpec):
    for identifier in (spec.table_name, spec.id_column, spec.name_column):
        _assert_identifier(identifier)
    select_columns = _select_columns(spec)
    updated_expr = _canonical_updated_expression(spec)
    select_columns.append(f"{updated_expr} AS source_updated_at")
    rows = session.execute(
        text(
            f"SELECT {', '.join(select_columns)} "
            f"FROM index_dirty id "
            f"JOIN {spec.table_name} e ON e.{spec.id_column} = id.entity_id "
            f"WHERE id.entity_type = :entity_type "
            f"ORDER BY id.marked_at, e.{spec.name_column}"
        ),
        {"entity_type": spec.entity_type},
    ).mappings().all()
    return rows


def _candidate_from_row(spec: EntitySpec, row, *, from_index_dirty: bool) -> SearchDocCandidate:
    values = dict(row)
    builder = spec.doc_builder
    doc_text = builder(values) if builder else ""
    return SearchDocCandidate(
        entity_type=spec.entity_type,
        entity_id=str(values["entity_id"]),
        name=str(values.get("name") or ""),
        doc_text=doc_text,
        source_updated_at=values.get("source_updated_at"),
        from_index_dirty=from_index_dirty,
    )


# Legacy actor names and their Architecture V2 replacements: read whichever exists,
# so the index builds on the schema before and after migration 500.
_ACTOR_FALLBACKS = {
    "actor_type": ("actor_category",),
    "location_city": ("city",),
    "state": ("state_code",),
}
# Narrative fields become imported baseline facts at the cutover.
_ACTOR_BASELINE_FACTS = frozenset({
    "primary_technical_focus", "technical_approach", "current_activities",
    "technology_ip_notes", "key_constraints", "funding_summary", "estimated_trl",
    "primary_lifecycle_role",
})


def _select_columns(spec: EntitySpec) -> list[str]:
    select_columns = [f"e.{spec.id_column}::text AS entity_id", f"e.{spec.name_column} AS name"]
    for field in spec.fields:
        _assert_identifier(field)
        if field in {spec.id_column, spec.name_column}:
            continue
        options = [f"to_jsonb(e)->>'{field}'"]
        if spec.entity_type == "actor":
            options += [f"to_jsonb(e)->>'{name}'" for name in _ACTOR_FALLBACKS.get(field, ())]
            if field in _ACTOR_BASELINE_FACTS:
                options.append(
                    "(SELECT f.fact_value #>> '{}' FROM actor_fact f "
                    f"WHERE f.actor_id = e.actor_id AND f.fact_type = 'legacy_baseline' "
                    f"AND f.fact_key = '{field}' LIMIT 1)"
                )
        expression = options[0] if len(options) == 1 else f"COALESCE({', '.join(options)})"
        select_columns.append(f"{expression} AS {field}")
    return select_columns


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


def _clear_index_dirty(session, candidate: SearchDocCandidate) -> None:
    session.execute(
        text(
            "DELETE FROM index_dirty "
            "WHERE entity_type = :entity_type AND entity_id = CAST(:entity_id AS uuid)"
        ),
        {"entity_type": candidate.entity_type, "entity_id": candidate.entity_id},
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
