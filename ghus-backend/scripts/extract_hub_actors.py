"""
Runner for the hub actor extractor.

Usage:
    python -m scripts.extract_hub_actors
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.session import SessionLocal
from src.etl.translators.hub_actor_extractor import HubActorExtractor


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
logger = logging.getLogger("extract_hub_actors")


def main() -> int:
    logger.info("Starting hub actor extraction")

    with SessionLocal() as session:
        extractor = HubActorExtractor(PROJECT_ROOT, session)
        try:
            stats = extractor.run()
        except Exception as e:
            logger.exception("Extractor crashed: %s", e)
            session.rollback()
            return 2

    print("\n" + "=" * 60)
    print("Hub actor extraction complete.")
    print("=" * 60)
    print(stats.summary())
    print("\nAudit log: data/interim/hub_actor_extraction_audit.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())