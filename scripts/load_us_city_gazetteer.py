"""Load the vendored Census Places gazetteer into an isolated V2 database.

The job is dry-run by default and refuses non-local/non-test databases. Database
passwords must be supplied through PGPASSFILE; URLs containing passwords are
rejected and connection strings are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from agents.common.geography import (
    DEFAULT_GAZETTEER_PATH,
    GAZETTEER_SHA256,
    GAZETTEER_URL,
    GAZETTEER_YEAR,
    CensusPlacesGazetteer,
)

INSERT_SQL = text(
    "INSERT INTO us_city_coord (geoid,state_code,place_name,normalized_city,latitude,"
    "longitude,lsad,function_status,gazetteer_year,source_url,source_sha256) VALUES ("
    ":geoid,:state_code,:place_name,:normalized_city,:latitude,:longitude,:lsad,"
    ":function_status,:gazetteer_year,:source_url,:source_sha256) "
    "ON CONFLICT (geoid) DO UPDATE SET state_code=EXCLUDED.state_code,"
    "place_name=EXCLUDED.place_name,normalized_city=EXCLUDED.normalized_city,"
    "latitude=EXCLUDED.latitude,longitude=EXCLUDED.longitude,lsad=EXCLUDED.lsad,"
    "function_status=EXCLUDED.function_status,gazetteer_year=EXCLUDED.gazetteer_year,"
    "source_url=EXCLUDED.source_url,source_sha256=EXCLUDED.source_sha256"
)


def load_rows(session, gazetteer: CensusPlacesGazetteer) -> int:
    rows = [
        {
            "geoid": place.geoid,
            "state_code": place.state_code,
            "place_name": place.place_name,
            "normalized_city": place.normalized_city,
            "latitude": place.latitude,
            "longitude": place.longitude,
            "lsad": place.lsad,
            "function_status": place.function_status,
            "gazetteer_year": GAZETTEER_YEAR,
            "source_url": GAZETTEER_URL,
            "source_sha256": GAZETTEER_SHA256,
        }
        for place in gazetteer.places
    ]
    for offset in range(0, len(rows), 1_000):
        session.execute(INSERT_SQL, rows[offset : offset + 1_000])
    return len(rows)


def _safe_local_url():
    raw = os.environ.get("V2_TEST_DATABASE_URL", "").strip()
    if not raw:
        raise RuntimeError("V2_TEST_DATABASE_URL is required")
    url = make_url(raw)
    if url.password:
        raise RuntimeError("database passwords in URLs are forbidden; use PGPASSFILE")
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost"}
        or url.port != 55432
        or not (url.database or "").endswith("_test")
    ):
        raise RuntimeError("refusing any database except local PostgreSQL :55432/*_test")
    return url


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=DEFAULT_GAZETTEER_PATH)
    parser.add_argument("--live", action="store_true", help="commit to the isolated test database")
    args = parser.parse_args()

    gazetteer = CensusPlacesGazetteer.from_zip(args.archive)
    engine = create_engine(_safe_local_url())
    session = sessionmaker(bind=engine)()
    transaction = session.begin()
    try:
        count = load_rows(session, gazetteer)
        if args.live:
            transaction.commit()
        else:
            transaction.rollback()
    except Exception as exc:
        transaction.rollback()
        raise RuntimeError(f"{type(exc).__name__}: gazetteer load failed") from None
    finally:
        session.close()
        engine.dispose()

    print(json.dumps({"dry_run": not args.live, "rows": count}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
