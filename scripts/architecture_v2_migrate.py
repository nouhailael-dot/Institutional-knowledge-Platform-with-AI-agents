"""Apply detached Architecture V2 proposals to the isolated local test DB only.

This tool refuses non-local hosts, non-55432 ports, and database names that do
not end in ``_test``. It never reads ``DATABASE_URL`` and is not application
code. Canonical proposals stay outside Alembic's configured version directory.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "migrations" / "proposed" / "manifest.json"


def _test_url() -> str:
    raw = os.environ.get("V2_TEST_DATABASE_URL", "").strip()
    if not raw:
        raise RuntimeError("V2_TEST_DATABASE_URL is required")
    url = make_url(raw)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost"}
        or url.port != 55432
        or not (url.database or "").endswith("_test")
    ):
        raise RuntimeError("refusing any database except local PostgreSQL :55432/*_test")
    return raw


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"v2_proposal_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load proposal module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_sql(engine, path: Path) -> None:
    script = path.read_text(encoding="utf-8")
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cursor:
            cursor.execute(script)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def _run_alembic(engine, path: Path, direction: str) -> None:
    module = _load_module(path)
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        getattr(module, "upgrade" if direction == "up" else "downgrade")()


def migrate(direction: str) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))["logical_migrations"]
    steps = manifest if direction == "up" else list(reversed(manifest))
    engine = create_engine(_test_url())
    try:
        for step in steps:
            actions = step["actions"] if direction == "up" else list(reversed(step["actions"]))
            for action in actions:
                if action["type"] == "sql":
                    _run_sql(engine, ROOT / action[direction])
                else:
                    _run_alembic(engine, ROOT / action["path"], direction)
            print(f"{direction}: {step['id']} {step['name']}")
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("direction", choices=("up", "down", "up-down-up"))
    args = parser.parse_args()
    if args.direction == "up-down-up":
        migrate("up")
        migrate("down")
        migrate("up")
    else:
        migrate(args.direction)


if __name__ == "__main__":
    main()
