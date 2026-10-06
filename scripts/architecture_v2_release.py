"""Build, verify and apply the Architecture V2 cutover release, one stage at a time.

    python -m scripts.architecture_v2_release build
    python -m scripts.architecture_v2_release plan
    python -m scripts.architecture_v2_release apply STAGE --database-url-env NAME [...]

`plan` is the default and touches no database. `apply` reads the target URL from
the named environment variable (never DATABASE_URL, never printed) and runs one
stage. A target other than a local *_test database on port 55432 is refused unless
--owner-approval names a JSON file in which the schema owner approved this exact
release manifest for that host. The migration ledger skips any step already
applied with the same checksum, so every stage can be re-run safely.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "migrations/proposed/functional_v2_isolated_manifest.json"
RELEASE_DIR = ROOT / "migrations/release/architecture_v2_cutover"
RELEASE_MANIFEST = RELEASE_DIR / "release_manifest.json"
TOPIC_CSV = ROOT / "docs/evidence/phase12_topic_proposal.csv"
GAZETTEER_MIN_ROWS = 30_000

STAGES = ("baseline", "expand", "gazetteer", "backfill", "validate", "decisions", "topic",
          "contract", "cutover")
STAGE_OF = {
    **{step: "backfill" for step in ("480", "482", "484", "485", "488", "489")},
    "490": "validate",
    "491": "decisions",
    "486": "topic",
    **{step: "contract" for step in ("405", "410", "495")},
    "500": "cutover",
}
NOTES = {
    "review-kinds": "widens the review_item kind CHECK; superseded by 430/440/482",
    "484": "model category proposals land with category_needs_review=true",
    "486": "requires GHUS approval of docs/evidence/phase12_topic_proposal.csv",
    "491": "GHUS decisions of 2026-10-06 (categories, collections, empty hub)",
    "495": "fails until every category_doubt review is resolved by GHUS",
    "405": "fails until every hub has a topic and center (incl. the empty 'Mining Hubs')",
    "500": "fails without a passed attestation and a passing live audit",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _steps(manifest: dict, checkpoint: str) -> list[dict]:
    configured = manifest["checkpoints"][checkpoint]
    if isinstance(configured, list):
        return configured
    return [*_steps(manifest, configured["inherits"]), *configured["steps"]]


def build() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    steps = []
    for order, step in enumerate(_steps(manifest, "final_cutover"), start=1):
        path = ROOT / step["path"]
        steps.append({
            "order": order, "id": step["id"], "stage": STAGE_OF.get(step["id"], "expand"),
            "action": step["action"], "path": step["path"], "sha256": _sha256(path),
            "kind": step.get("kind"), "note": NOTES.get(step["id"], ""),
        })
    release = {
        "release": "architecture_v2_cutover",
        "source_manifest": MANIFEST.relative_to(ROOT).as_posix(),
        "stages": list(STAGES),
        "non_sql_stages": {
            "baseline": "record row counts before anything changes",
            "gazetteer": "load the vendored Census Places table (checksum-verified)",
        },
        "steps": steps,
    }
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    RELEASE_MANIFEST.write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8",
                                newline="\n")
    return release


def verify() -> dict:
    release = json.loads(RELEASE_MANIFEST.read_text(encoding="utf-8"))
    mismatched = [step["path"] for step in release["steps"]
                  if _sha256(ROOT / step["path"]) != step["sha256"]]
    if mismatched:
        raise RuntimeError("release files changed since the manifest was built: "
                           + ", ".join(mismatched))
    return release


def _target(env_name: str, owner_approval: Path | None) -> str:
    raw = os.environ.get(env_name, "").strip()
    if not raw or env_name == "DATABASE_URL":
        raise RuntimeError("pass --database-url-env naming a dedicated variable (not DATABASE_URL)")
    parsed = urlsplit(raw.replace("postgresql+psycopg2", "postgresql", 1))
    local_test = (parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == 55432
                  and parsed.path.removeprefix("/").endswith("_test"))
    if not local_test:
        if owner_approval is None or not owner_approval.is_file():
            raise RuntimeError("non-test target refused: --owner-approval is required")
        approval = json.loads(owner_approval.read_text(encoding="utf-8"))
        expected = _sha256(RELEASE_MANIFEST)
        if (approval.get("release_manifest_sha256") != expected
                or approval.get("target_host") != parsed.hostname
                or not str(approval.get("approved_by") or "").strip()):
            raise RuntimeError("owner approval does not match this release and target host")
    return raw


def _engine(url: str):
    from sqlalchemy import create_engine
    return create_engine(url.replace("postgresql://", "postgresql+psycopg2://", 1)
                         if url.startswith("postgresql://") else url, future=True)


def apply(stage: str, url: str, *, topic_approval: Path | None) -> list[str]:
    from sqlalchemy import text

    from scripts import functional_v2_schema as runner

    release = verify()
    engine = _engine(url)
    log: list[str] = []
    try:
        with engine.begin() as connection:
            if stage == "baseline":
                connection.execute(text(
                    "CREATE TABLE IF NOT EXISTS architecture_v2_cutover_baseline ("
                    "table_name text PRIMARY KEY, row_count bigint NOT NULL, "
                    "recorded_at timestamptz NOT NULL DEFAULT now())"))
                for table in ("actor", "hub", "hub_actor", "event"):
                    connection.execute(text(
                        "INSERT INTO architecture_v2_cutover_baseline(table_name,row_count) "
                        f"SELECT '{table}', count(*) FROM {table} ON CONFLICT DO NOTHING"))
                return ["recorded baseline row counts"]
            if stage == "gazetteer":
                from psycopg2.extras import execute_values

                from agents.common.geography import (
                    GAZETTEER_SHA256,
                    GAZETTEER_URL,
                    GAZETTEER_YEAR,
                    CensusPlacesGazetteer,
                )
                places = CensusPlacesGazetteer.from_zip().places
                rows = [(p.geoid, p.state_code, p.place_name, p.normalized_city, p.latitude,
                         p.longitude, p.lsad, p.function_status, GAZETTEER_YEAR,
                         GAZETTEER_URL, GAZETTEER_SHA256) for p in places]
                # Multi-row inserts: one round trip per 1,000 places, not per place.
                with connection.connection.cursor() as cursor:
                    execute_values(cursor, (
                        "INSERT INTO us_city_coord (geoid,state_code,place_name,normalized_city,"
                        "latitude,longitude,lsad,function_status,gazetteer_year,source_url,"
                        "source_sha256) VALUES %s ON CONFLICT (geoid) DO NOTHING"
                    ), rows, page_size=1000)
                return [f"loaded {len(rows)} gazetteer places"]
            if stage == "backfill":
                places = connection.execute(text("SELECT count(*) FROM us_city_coord")).scalar_one()
                if places < GAZETTEER_MIN_ROWS:
                    raise RuntimeError("load the gazetteer stage before backfill")
            if stage == "topic":
                if topic_approval is None or not topic_approval.is_file():
                    raise RuntimeError("topic stage needs --topic-approval (GHUS-signed JSON)")
                approval = json.loads(topic_approval.read_text(encoding="utf-8"))
                if approval.get("topic_proposal_sha256") != _sha256(TOPIC_CSV):
                    raise RuntimeError("topic approval does not match the topic proposal CSV")
        runner._ensure_ledger(engine)
        for step in release["steps"]:
            if step["stage"] != stage:
                continue
            path = ROOT / step["path"]
            if runner._already_applied(engine, step, path):
                log.append(f"skipped {step['id']}: checksum already applied")
                continue
            if step["action"] == "sql":
                runner._run_sql(engine, path)
            else:
                runner._run_alembic(engine, path)
            runner._record_applied(engine, step, path)
            log.append(f"applied {step['id']}")
    finally:
        engine.dispose()
    return log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="plan", choices=("build", "plan", "apply"))
    parser.add_argument("stage", nargs="?", choices=STAGES)
    parser.add_argument("--database-url-env")
    parser.add_argument("--owner-approval", type=Path)
    parser.add_argument("--topic-approval", type=Path)
    args = parser.parse_args(argv)
    if args.command == "build":
        release = build()
        print(f"wrote {RELEASE_MANIFEST.relative_to(ROOT)} ({len(release['steps'])} steps)")
        return 0
    if args.command == "plan":
        release = verify()
        for stage in STAGES:
            ids = [s["id"] for s in release["steps"] if s["stage"] == stage]
            print(f"{stage:9} {', '.join(ids) or release['non_sql_stages'].get(stage, '')}")
        return 0
    if not args.stage or not args.database_url_env:
        parser.error("apply needs a STAGE and --database-url-env")
    url = _target(args.database_url_env, args.owner_approval)
    for line in apply(args.stage, url, topic_approval=args.topic_approval):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
