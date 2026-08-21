"""
Run the UM6P events final version translator.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.session import SessionLocal
from src.etl.translators.um6p_un_events import Um6pEventsTranslator


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
logger = logging.getLogger("run_um6p_un_events")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="commit changes; without this the run is a dry run")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    logger.info("Starting UM6P events vf translator [%s]", mode)

    with SessionLocal() as session:
        translator = Um6pEventsTranslator(PROJECT_ROOT, session, apply=args.apply)
        try:
            stats = translator.run()
        except Exception as e:
            logger.exception("Translator crashed: %s", e)
            session.rollback()
            return 2

    print("\n" + "=" * 60)
    print("UM6P events vf translation complete.")
    print("=" * 60)
    print(stats.summary())
    print("\nAudit log: data/interim/um6p_dashboard_audit.csv")
    print("Failure log: data/interim/um6p_dashboard_failures.csv")
    return 1 if stats.rows_failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())