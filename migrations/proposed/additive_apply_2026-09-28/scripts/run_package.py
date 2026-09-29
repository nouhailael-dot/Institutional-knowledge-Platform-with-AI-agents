"""Run the reviewed additive package locally or, with safeguards, on shared Postgres."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from db_connection import connection_settings, engine, guarded
from sqlalchemy import text

PACKAGE = Path(__file__).resolve().parents[1]
MANIFEST = PACKAGE / "manifest.json"


def validate_target(args: argparse.Namespace, settings: dict[str, str]) -> None:
    local = settings["host"] in {"127.0.0.1", "localhost"}
    if args.target == "local":
        if not local or settings["port"] != "55432" or not settings["database"].endswith("_test"):
            raise RuntimeError("local mode accepts only localhost:55432/*_test")
        return
    if local:
        raise RuntimeError("shared mode refuses a local target")
    if not args.approval_file or not args.backup_manifest:
        raise RuntimeError("shared mode requires --approval-file and --backup-manifest")
    approval = Path(args.approval_file).read_text(encoding="utf-8")
    if "SCHEMA_OWNER_APPROVED_ADDITIVE_V2" not in approval:
        raise RuntimeError("schema-owner approval marker is missing")
    backup = json.loads(Path(args.backup_manifest).read_text(encoding="utf-8"))
    dump_path = Path(backup["dump_path"])
    actual = hashlib.sha256(dump_path.read_bytes()).hexdigest()
    if actual != backup["sha256"]:
        raise RuntimeError("pre-apply dump checksum does not match its manifest")
    if args.direction == "down" and not args.confirm_rollback:
        raise RuntimeError("shared rollback requires --confirm-rollback")


def load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"v2_additive_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load proposal module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_sql(engine, path: Path) -> None:
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


def run_alembic(engine, path: Path, direction: str) -> None:
    module = load_module(path)
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        getattr(module, "upgrade" if direction == "up" else "downgrade")()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("direction", choices=("up", "down"))
    parser.add_argument("--target", choices=("local", "shared"), required=True)
    parser.add_argument("--approval-file")
    parser.add_argument("--backup-manifest")
    parser.add_argument("--confirm-rollback", action="store_true")
    args = parser.parse_args()
    settings = connection_settings()
    validate_target(args, settings)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))["logical_migrations"]
    steps = manifest if args.direction == "up" else list(reversed(manifest))
    db_engine = engine()
    try:
        with db_engine.connect() as connection:
            version, read_only = connection.execute(
                text("SELECT current_setting('server_version'), current_setting('transaction_read_only')")
            ).one()
            if not str(version).startswith("17."):
                raise RuntimeError(f"expected PostgreSQL 17, got {version}")
            if read_only == "on":
                raise RuntimeError("target connection is read-only; package was not applied")
        for step in steps:
            actions = step["actions"] if args.direction == "up" else list(reversed(step["actions"]))
            for action in actions:
                if action["type"] == "sql":
                    run_sql(db_engine, PACKAGE / action[args.direction])
                else:
                    run_alembic(db_engine, PACKAGE / action["path"], args.direction)
            print(f"{args.direction}: {step['id']} {step['name']}")
    finally:
        db_engine.dispose()


if __name__ == "__main__":
    guarded(main)
