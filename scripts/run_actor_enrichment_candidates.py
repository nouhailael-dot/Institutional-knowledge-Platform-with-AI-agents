"""
Run actor enrichment candidate generation.

Default mode is dry-run: it searches APIs, calls Claude for validation, writes
an audit CSV, and rolls back DB changes. Use --apply only after reviewing a
small sample.

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

from src.ai.client import SONNET  # noqa: E402
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
    parser.add_argument("--model", default=SONNET, help="Anthropic model id.")
    parser.add_argument("--use-wikidata", action="store_true",
                        help="Also query Wikidata. Disabled by default because some environments return 403.")
    parser.add_argument("--no-openalex", action="store_true",
                        help="Skip OpenAlex lookups. Useful when OpenAlex is rate-limiting long runs.")
    parser.add_argument("--openalex-sleep", type=float, default=2.0,
                        help="Seconds to sleep after each OpenAlex request.")
    parser.add_argument("--include-unlinked", action="store_true",
                        help="Also process sparse actors without hub links. These only apply trusted API matches.")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    logger.info("Starting actor enrichment candidate pipeline [%s]", mode)

    with SessionLocal() as session:
        pipeline = ActorEnrichmentCandidatePipeline(
            PROJECT_ROOT,
            session,
            limit=args.limit,
            apply=args.apply,
            apply_threshold=args.threshold,
            commit_every=args.commit_every,
            model=args.model,
            use_wikidata=args.use_wikidata,
            use_openalex=not args.no_openalex,
            openalex_sleep_seconds=args.openalex_sleep,
            include_unlinked=args.include_unlinked,
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
