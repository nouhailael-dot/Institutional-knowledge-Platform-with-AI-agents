"""Generalized enrichment CLI.

The actor path reuses the existing actor enrichment candidate pipeline. This
module adds entity/field policy, proposal handling, and a stable CLI surface.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import text

from agents.common.run_log import InMemoryRunLog, SQLRunLog
from agents.enrichment.actor_adapter import (
    LEGACY_ACTOR_FIELDS,
    PolicyActorEnrichmentCandidatePipeline,
)
from agents.enrichment.fields import load_field_config, policies_for_entity, resolve_field_set
from agents.enrichment.gaps import sql_gap_condition
from agents.enrichment.specs import ENTITY_SPECS, assert_known_fields, get_entity_spec
from src.ai.client import HAIKU
from src.enrichment.actor_enrichment_candidates import DEFAULT_APPLY_THRESHOLD

logger = logging.getLogger(__name__)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run_enrichment(args, *, session=None, root: Path | None = None) -> dict[str, object]:
    root = root or project_root()
    if args.entity == "actor" and bool(args.live):
        raise RuntimeError(
            "legacy live actor enrichment is retired; use the verified, topic-scoped "
            "Architecture V2 Deep Pull service"
        )
    config = load_field_config(root)
    spec = get_entity_spec(args.entity)
    fields = resolve_field_set(config, args.entity, args.field_set)
    assert_known_fields(spec, fields)
    policies = policies_for_entity(config, args.entity)

    owned_session = False
    if session is None:
        from src.db.session import SessionLocal

        session = SessionLocal()
        owned_session = True

    live = bool(args.live)
    run_log = SQLRunLog(session) if live else InMemoryRunLog()
    run_id = run_log.start_run(
        source_name="enrichment",
        entity_type=args.entity,
        live=live,
        config={
            "entity": args.entity,
            "field_set": args.field_set,
            "fields": fields,
            "limit": args.limit,
            "use_claude": bool(getattr(args, "allow_claude", False)),
        },
    )
    stats: dict[str, object] = {
        "run_id": run_id,
        "entity": args.entity,
        "field_set": args.field_set,
        "fields": list(fields),
        "live": live,
    }

    try:
        status = "succeeded"
        if args.entity == "actor":
            stats.update(_run_actor_enrichment(args, root, session, run_id, fields, policies))
        else:
            stats.update(_scan_sparse_without_adapter(session, spec, fields, args.limit))
            status = "skipped"
            stats["attention_required"] = True
            stats["skipped_reason"] = f"no candidate adapter exists for entity={args.entity}"
            logger.warning(
                "No candidate adapter exists yet for entity=%s; sparse rows were counted, no writes attempted",
                args.entity,
            )

        cost_usd = float(stats.get("cost_usd", 0.0) or 0.0)
        run_log.close_run(run_id, status=status, stats=stats, cost_usd=cost_usd)
        if not live:
            session.rollback()
        return {"status": status, "run_id": run_id, "stats": stats}
    except Exception as exc:
        session.rollback()
        stats["error"] = str(exc)
        stats["failures"] = 1
        run_log.fail_run(run_id, error=str(exc), stats=stats, cost_usd=float(stats.get("cost_usd", 0.0) or 0.0))
        raise
    finally:
        if owned_session:
            session.close()


def _run_actor_enrichment(args, root: Path, session, run_id: str, fields: tuple[str, ...], policies):
    unsupported = [field for field in fields if field not in LEGACY_ACTOR_FIELDS]
    legacy_fields = [field for field in fields if field in LEGACY_ACTOR_FIELDS]
    if unsupported:
        logger.warning(
            "Actor candidate generation currently supports only %s; unsupported fields remain proposal-only: %s",
            ", ".join(LEGACY_ACTOR_FIELDS),
            ", ".join(unsupported),
        )
    if not legacy_fields:
        return {
            "adapter": "actor_legacy",
            "actors_seen": 0,
            "unsupported_fields": unsupported,
            "cost_usd": 0.0,
        }

    pipeline = PolicyActorEnrichmentCandidatePipeline(
        args.audit_root or root,
        session,
        field_policies={field: policies[field] for field in legacy_fields},
        proposal_run_id=run_id,
        limit=args.limit,
        apply=args.live,
        apply_threshold=args.threshold,
        commit_every=args.commit_every,
        model=args.model,
        use_wikidata=args.use_wikidata,
        use_openalex=not args.no_openalex,
        openalex_sleep_seconds=args.openalex_sleep,
        use_web_search=args.use_web_search,
        web_search_sleep_seconds=args.web_search_sleep,
        web_search_result_limit=args.web_search_limit,
        include_unlinked=args.include_unlinked,
        deterministic_only=args.deterministic_only,
        revisit_missing=args.revisit_missing,
        use_claude=args.allow_claude and not args.deterministic_only,
        max_claude_calls=args.max_claude_calls,
        max_claude_cost=args.max_claude_cost,
        min_claude_candidate_score=args.min_claude_candidate_score,
        missing_fields=legacy_fields,
        stop_after_claude_budget=args.stop_after_claude_budget,
    )
    try:
        legacy_stats = pipeline.run()
    finally:
        pipeline.close()

    tracker_summary = pipeline.tracker.summary()
    cost_usd = float(pipeline.tracker.cost_estimate())
    return {
        "adapter": "actor_legacy",
        "unsupported_fields": unsupported,
        "actors_seen": legacy_stats.actors_seen,
        "candidates_found": legacy_stats.candidates_found,
        "decisions_made": legacy_stats.decisions_made,
        "no_candidates": legacy_stats.no_candidates,
        "no_match": legacy_stats.no_match,
        "needs_review": legacy_stats.needs_review,
        "would_apply": legacy_stats.would_apply,
        "applied": legacy_stats.applied,
        "skipped_low_confidence": legacy_stats.skipped_low_confidence,
        "api_failures": legacy_stats.api_failures,
        "ai_failures": legacy_stats.ai_failures,
        "claude_skipped": legacy_stats.claude_skipped,
        "claude_budget_skipped": legacy_stats.claude_budget_skipped,
        "claude_weak_candidate_skipped": legacy_stats.claude_weak_candidate_skipped,
        "stopped_early": legacy_stats.stopped_early,
        "usage": tracker_summary,
        "cost_usd": cost_usd,
    }


def _scan_sparse_without_adapter(session, spec, fields: tuple[str, ...], limit: int | None) -> dict[str, object]:
    conditions = " OR ".join(f"({sql_gap_condition(field)})" for field in fields)
    limit_clause = " LIMIT :limit" if limit else ""
    rows = session.execute(
        text(
            f"SELECT {spec.id_column}::text AS entity_id, {spec.name_column} AS name "
            f"FROM {spec.table_name} WHERE {conditions} "
            f"ORDER BY {spec.name_column}{limit_clause}"
        ),
        {"limit": limit} if limit else {},
    ).mappings().all()
    return {
        "adapter": "none",
        "sparse_rows": len(rows),
        "sample_entity_ids": [row["entity_id"] for row in rows[:10]],
        "cost_usd": 0.0,
    }


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entity", required=True, choices=sorted(ENTITY_SPECS))
    parser.add_argument("--field-set", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--live", action="store_true", help="commit writes; absent means dry-run")
    parser.add_argument("--threshold", type=float, default=DEFAULT_APPLY_THRESHOLD)
    parser.add_argument("--commit-every", type=int, default=50)
    parser.add_argument("--model", default=HAIKU)
    parser.add_argument("--use-wikidata", action="store_true")
    parser.add_argument("--no-openalex", action="store_true")
    parser.add_argument("--openalex-sleep", type=float, default=2.0)
    parser.add_argument("--use-web-search", action="store_true")
    parser.add_argument("--web-search-sleep", type=float, default=0.5)
    parser.add_argument("--web-search-limit", type=int, default=3)
    parser.add_argument("--include-unlinked", action="store_true")
    parser.add_argument("--deterministic-only", action="store_true")
    parser.add_argument("--revisit-missing", action="store_true")
    parser.add_argument("--audit-root", type=Path, default=None)
    parser.add_argument("--allow-claude", action="store_true")
    parser.add_argument("--max-claude-calls", type=int, default=25)
    parser.add_argument("--max-claude-cost", type=float, default=0.50)
    parser.add_argument("--min-claude-candidate-score", type=float, default=0.72)
    parser.add_argument("--stop-after-claude-budget", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s %(message)s")
    args = parse_args(argv)
    result = run_enrichment(args)
    stats = result["stats"]
    print(
        "status={status} run_id={run_id} entity={entity} adapter={adapter} "
        "live={live} cost_usd={cost_usd}".format(
            status=result["status"],
            run_id=result["run_id"],
            entity=args.entity,
            adapter=stats.get("adapter"),
            live=args.live,
            cost_usd=float(stats.get("cost_usd", 0.0) or 0.0),
        )
    )
    if stats.get("usage"):
        print(str(stats["usage"]))
    return 2 if stats.get("ai_failures") else 0


if __name__ == "__main__":
    sys.exit(main())
