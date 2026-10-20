"""
Run the NutriCrops translator.

Usage (from project root, with .venv active):
    python -m scripts.run_nutricrops
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.session import SessionLocal
from src.etl.translators.nutricrops import NutriCropsTranslator


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
logger = logging.getLogger("run_nutricrops")


def main() -> int:
    logger.info("Starting NutriCrops translator")

    with SessionLocal() as session:
        translator = NutriCropsTranslator(PROJECT_ROOT, session)
        try:
            stats = translator.run()
        except Exception as e:
            logger.exception("Translator crashed: %s", e)
            session.rollback()
            return 2

    print("\n" + "=" * 60)
    print("NutriCrops translation complete.")
    print("=" * 60)
    print(stats.summary())
    print("\nAudit log: data/interim/nutricrops_audit.csv")
    print("Quarantine log: data/interim/nutricrops_quarantine.csv")
    print("Failure log: data/interim/nutricrops_failures.csv")
    return 1 if stats.rows_failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())