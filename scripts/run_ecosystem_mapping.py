"""
Run the Ecosystem Mapping translator.

Usage (from project root, with .venv active):
    python -m scripts.run_ecosystem_mapping

Or directly:
    python scripts/run_ecosystem_mapping.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.session import SessionLocal
from src.etl.translators.ecosystem_mapping import EcosystemMappingTranslator


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
logger = logging.getLogger("run_ecosystem_mapping")


def main() -> int:
    logger.info("Starting Ecosystem Mapping translator")

    with SessionLocal() as session:
        translator = EcosystemMappingTranslator(PROJECT_ROOT, session)
        try:
            stats = translator.run()
        except Exception as e:
            logger.exception("Translator crashed before completion: %s", e)
            session.rollback()
            return 2

    print("\n" + "=" * 60)
    print("Ecosystem Mapping translation complete.")
    print("=" * 60)
    print(stats.summary())
    print("\nAudit logs written to data/interim/")

    # Non-zero exit if any rows failed
    return 1 if stats.failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())