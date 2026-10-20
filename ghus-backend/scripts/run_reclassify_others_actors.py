"""
Run Task 4: Reclassify 'other' actors using Claude Haiku 4.5.

Usage:
    # Test on 10 actors first (recommended):
    python -m scripts.run_reclassify_others --limit 10

    # Full run (all 'other' actors):
    python -m scripts.run_reclassify_others
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.session import SessionLocal
from src.enrichment.reclassify_others_actors import OtherReclassifier


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
logger = logging.getLogger("run_reclassify_others")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit to N actors for testing. Omit for full run.")
    args = parser.parse_args()

    logger.info("Starting Task 4: reclassify 'other' actors")
    if args.limit:
        logger.info("TEST MODE: limited to %d actors", args.limit)

    with SessionLocal() as session:
        reclassifier = OtherReclassifier(PROJECT_ROOT, session, limit=args.limit)
        try:
            stats = reclassifier.run()
        except Exception as e:
            logger.exception("Reclassifier crashed: %s", e)
            session.rollback()
            return 2

    print("\n" + "=" * 60)
    print("Task 4 reclassification complete.")
    print("=" * 60)
    print(stats.summary())
    print("\nUsage:")
    print(reclassifier.tracker.summary())
    print("\nAudit log: data/interim/ai_reclassification_audit.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())