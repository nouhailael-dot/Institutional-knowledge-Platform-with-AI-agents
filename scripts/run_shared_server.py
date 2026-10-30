"""Serve the platform against the team's shared database.

    python -m scripts.run_shared_server [--port 8030]

GHUS, 2026-10-29: the shared Supabase database is the team's one database, and
the local demo database is retired. Every page reads it, and every write goes
where it always goes - through the GHUS backend's own commands (Discovery
requests, the Data Feed's staging writer, Review admission), which this
instance points at the same database.

The connection string comes from the repository's .env (DATABASE_URL) and is
never printed. Review decisions are kept in a durable store outside the
repository (``C:\\Users\\Ismail\\GHUS-data\\review-store``), so a deployment or
a fresh checkout never loses them.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "ghus-backend"
STORE = Path(r"C:\Users\Ismail\GHUS-data\review-store\review-shared.sqlite3")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8030)
    parser.add_argument("--store", type=Path, default=STORE)
    args = parser.parse_args(argv)

    url = (dotenv_values(ROOT / ".env").get("DATABASE_URL") or "").strip()
    if not url:
        raise SystemExit("DATABASE_URL is missing from .env")
    driver_url = url.replace("postgresql://", "postgresql+psycopg://", 1).replace(
        "postgresql+psycopg2://", "postgresql+psycopg://", 1)
    plain_url = driver_url.replace("postgresql+psycopg://", "postgresql://", 1)
    args.store.parent.mkdir(parents=True, exist_ok=True)

    os.environ.update({
        "REVIEW_SOURCE_DATABASE_URL": plain_url,
        "BROWSE_DATABASE_URL": plain_url,
        "REVIEW_STORE_DB": str(args.store),
        "GHUS_DISCOVERY_PROJECT_ROOT": str(BACKEND),
        "DISCOVERY_REQUESTS_DATABASE_URL": driver_url,
        "GHUS_DATAFEED_PROJECT_ROOT": str(BACKEND),
        "DATAFEED_DATABASE_URL": driver_url,
        "GHUS_ADMISSION_PROJECT_ROOT": str(BACKEND),
        "REVIEW_ADMISSION_DATABASE_URL": driver_url,
    })
    # No demo banner and no local test canonical: this is the real queue.
    for demo_only in ("GHUS_DEMO_MODE", "REVIEW_DEMO_MODE", "REVIEW_SOURCE_RUN_DB"):
        os.environ.pop(demo_only, None)

    print("database      : shared (from .env)")
    print(f"review store  : {args.store}")
    print(f"backend       : {BACKEND}")
    print(f"listening on  : http://localhost:{args.port}")

    sys.path.insert(0, str(ROOT))
    import uvicorn

    uvicorn.run("backend.app:app", host="127.0.0.1", port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
