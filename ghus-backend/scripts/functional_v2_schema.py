"""Apply the cumulative minimum schema to a local Architecture V2 test DB.

This runner never reads DATABASE_URL and refuses every target except
localhost:55432 and a database name ending in ``_test``. Historical migration
files are consumed as-is; this module only selects the subset needed by a
functional checkpoint.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "migrations" / "proposed" / "functional_v2_isolated_manifest.json"


def _url() -> str:
    raw = os.environ.get("V2_TEST_DATABASE_URL", "").strip()
    if not raw:
        raise RuntimeError("V2_TEST_DATABASE_URL is required")
    parsed = urlsplit(raw.replace("postgresql+psycopg2", "postgresql", 1))
    if (
        parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port != 55432
        or not parsed.path.removeprefix("/").endswith("_test")
    ):
        raise RuntimeError("refusing every target except localhost:55432/*_test")
    return raw


def _module(path: Path):
    spec = importlib.util.spec_from_file_location(f"functional_v2_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load proposal {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_sql(engine, path: Path) -> None:
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cursor:
            cursor.execute(path.read_text(encoding="utf-8"))
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def _run_alembic(engine, path: Path) -> None:
    module = _module(path)
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()


def _run_alembic_down(engine, path: Path) -> None:
    module = _module(path)
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.downgrade()


def _rollback_path(step: dict) -> Path | None:
    path = Path(step["path"])
    candidates = []
    if path.parts[:2] == ("agents", "sql"):
        candidates.append(ROOT / "agents" / "sql" / "rollback" / path.name)
    if "additive_apply_2026-09-28" in path.parts and "sql" in path.parts:
        candidates.append(ROOT / path.parent.parent / "rollback" / path.name)
    if "deferred" in path.parts:
        candidates.append(ROOT / path.parent / "rollback" / path.name)
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _remove_ledger(engine, migration_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(text(
            "DELETE FROM architecture_v2_migration_ledger WHERE migration_id=:id"
        ), {"id": migration_id})


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_ledger(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS architecture_v2_migration_ledger ("
            "migration_id text PRIMARY KEY,source_path text NOT NULL,"
            "source_sha256 text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())"
        ))


def _already_applied(engine, step: dict, path: Path) -> bool:
    checksum = _checksum(path)
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT source_sha256 FROM architecture_v2_migration_ledger "
            "WHERE migration_id=:migration_id"
        ), {"migration_id": step["id"]}).scalar_one_or_none()
    if row is None:
        return False
    if row != checksum:
        raise RuntimeError(f"migration checksum changed for {step['id']}")
    return True


def _record_applied(engine, step: dict, path: Path) -> None:
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO architecture_v2_migration_ledger"
            "(migration_id,source_path,source_sha256) VALUES(:id,:path,:checksum)"
        ), {"id": step["id"], "path": step["path"], "checksum": _checksum(path)})


def _steps(manifest: dict, checkpoint: str) -> list[dict]:
    configured = manifest["checkpoints"][checkpoint]
    if isinstance(configured, list):
        return configured
    inherited = _steps(manifest, configured["inherits"])
    return [*inherited, *configured["steps"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    parser.add_argument("checkpoint", choices=tuple(manifest["checkpoints"]))
    parser.add_argument(
        "--after",
        choices=tuple(manifest["checkpoints"]),
        help="apply only steps added after an already-installed inherited checkpoint",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="roll back the selected range in reverse order where a rollback is supplied",
    )
    args = parser.parse_args()
    engine = create_engine(_url(), future=True)
    try:
        with engine.connect() as connection:
            version, database = connection.execute(
                text("SELECT current_setting('server_version'), current_database()")
            ).one()
            if not str(version).startswith("17.") or not str(database).endswith("_test"):
                raise RuntimeError("unexpected isolated database identity")
        _ensure_ledger(engine)
        steps = _steps(manifest, args.checkpoint)
        if args.after:
            installed = _steps(manifest, args.after)
            if steps[:len(installed)] != installed:
                raise RuntimeError("--after must be an inherited prefix of checkpoint")
            steps = steps[len(installed):]
        if args.rollback:
            for step in reversed(steps):
                path = ROOT / step["path"]
                if not _already_applied(engine, step, path):
                    continue
                if step["action"] == "alembic":
                    _run_alembic_down(engine, path)
                else:
                    rollback = _rollback_path(step)
                    if rollback is None:
                        print(f"retained {step['id']}: no supported rollback")
                        continue
                    _run_sql(engine, rollback)
                _remove_ledger(engine, step["id"])
                print(f"rolled back {step['id']}")
            return 0
        for step in steps:
            path = ROOT / step["path"]
            if _already_applied(engine, step, path):
                print(f"skipped {step['id']}: checksum already applied")
                continue
            if step["action"] == "sql":
                _run_sql(engine, path)
            else:
                _run_alembic(engine, path)
            _record_applied(engine, step, path)
            print(f"applied {step['id']}: {step['reason']}")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
