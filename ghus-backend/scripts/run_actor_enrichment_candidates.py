"""
Run actor enrichment candidate generation.

Default mode is dry-run: it searches local/context/API evidence, writes an
audit CSV, and rolls back DB changes. Claude validation is disabled unless
--allow-claude is passed, and even then call/cost gates apply. Use --apply only
after reviewing a small sample.

Usage:
    python scripts/run_actor_enrichment_candidates.py --limit 10
    python scripts/run_actor_enrichment_candidates.py --limit 10 --apply
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.ai.client import HAIKU  # noqa: E402
from src.db.session import SessionLocal  # noqa: E402
from src.enrichment.actor_enrichment_candidates import (  # noqa: E402
    DEFAULT_APPLY_THRESHOLD,
    ActorEnrichmentCandidatePipeline,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
logger = logging.getLogger("run_actor_enrichment_candidates")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N sparse actors.")
    parser.add_argument("--apply", action="store_true",
                        help="Apply high-confidence non-review updates to actor rows.")
    parser.add_argument("--threshold", type=float, default=DEFAULT_APPLY_THRESHOLD,
                        help="Minimum confidence required for --apply.")
    parser.add_argument("--commit-every", type=int, default=50,
                        help="When applying, commit after every N actors. Use 0 to commit only at the end.")
    parser.add_argument("--model", default=HAIKU, help="Anthropic model id.")
    parser.add_argument("--use-wikidata", action="store_true",
                        help="Also query Wikidata. Disabled by default because some environments return 403.")
    parser.add_argument("--no-openalex", action="store_true",
                        help="Skip OpenAlex lookups. Useful when OpenAlex is rate-limiting long runs.")
    parser.add_argument("--openalex-sleep", type=float, default=2.0,
                        help="Seconds to sleep after each OpenAlex request.")
    parser.add_argument("--use-web-search", action="store_true",
                        help="Add no-key DuckDuckGo HTML result candidates for Claude validation.")
    parser.add_argument("--web-search-sleep", type=float, default=0.5,
                        help="Seconds to sleep after each DuckDuckGo HTML request.")
    parser.add_argument("--web-search-limit", type=int, default=3,
                        help="Maximum DuckDuckGo result candidates per actor.")
    parser.add_argument("--include-unlinked", action="store_true",
                        help="Also process sparse actors without hub links. These only apply trusted API matches.")
    parser.add_argument("--deterministic-only", action="store_true",
                        help="Use only local deterministic matches; do not call external APIs or Claude.")
    parser.add_argument("--revisit-missing", action="store_true",
                        help="Revisit already-processed actors that still have missing target fields.")
    parser.add_argument("--audit-root", type=Path, default=PROJECT_ROOT,
                        help="Root folder where data/interim/actor_enrichment_candidates.csv is written.")
    parser.add_argument("--allow-claude", action="store_true",
                        help="Permit Claude validation after deterministic and API-only shortcuts fail.")
    parser.add_argument("--max-claude-calls", type=int, default=25,
                        help="Maximum Claude calls when --allow-claude is set. Use -1 for no call limit.")
    parser.add_argument("--max-claude-cost", type=float, default=0.50,
                        help="Approximate dollar ceiling when --allow-claude is set. Use -1 for no cost limit.")
    parser.add_argument("--min-claude-candidate-score", type=float, default=0.72,
                        help="Minimum candidate/actor name score required before spending a Claude call.")
    parser.add_argument("--missing-field", action="append",
                        choices=("any", "description", "website", "city", "location_city", "state", "country"),
                        help="Only select actors where this field is empty. Repeat for multiple fields.")
    parser.add_argument("--stop-after-claude-budget", action="store_true",
                        help="Stop the run as soon as the Claude call/cost budget is exhausted.")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    logger.info("Starting actor enrichment candidate pipeline [%s]", mode)

    with SessionLocal() as session:
        pipeline = ActorEnrichmentCandidatePipeline(
            args.audit_root,
            session,
            limit=args.limit,
            apply=args.apply,
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
            missing_fields=args.missing_field,
            stop_after_claude_budget=args.stop_after_claude_budget,
        )
        try:
            stats = pipeline.run()
        except Exception as err:
            session.rollback()
            pipeline.close()
            logger.exception("Actor enrichment candidate pipeline crashed: %s", err)
            return 2

    print("\n" + "=" * 60)
    print("Actor enrichment candidate pipeline complete.")
    print("=" * 60)
    print(stats.summary())
    print("\nUsage:")
    print(pipeline.tracker.summary())
    print("\nAudit log: data/interim/actor_enrichment_candidates.csv")
    if not args.apply:
        print("\nDry-run only - no database changes were committed.")
    return 2 if stats.ai_failures else 0


if __name__ == "__main__":
    sys.exit(main())
