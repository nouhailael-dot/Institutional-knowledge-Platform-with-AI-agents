"""
Run the Ecosystem Mapping events-sheet translator.

Usage:
    python scripts/run_ecosystem_events.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.session import SessionLocal
from src.etl.translators.ecosystem_events import EcosystemEventsTranslator


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
logger = logging.getLogger("run_ecosystem_events")


def main() -> int:
    logger.info("Starting Ecosystem Events translator")

    with SessionLocal() as session:
        translator = EcosystemEventsTranslator(PROJECT_ROOT, session)
        try:
            stats = translator.run()
        except Exception as err:
            logger.exception("Translator crashed before completion: %s", err)
            session.rollback()
            return 2

    print("\n" + "=" * 60)
    print("Ecosystem events translation complete.")
    print("=" * 60)
    print(stats.summary())
    print("\nAudit logs written to data/interim/")
    return 1 if stats.failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
