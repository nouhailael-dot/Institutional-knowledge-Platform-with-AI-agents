"""Serve the platform on a Linux host (Render) against the team's shared database.

    python -m scripts.run_hosted_server

The hosted twin of ``scripts.run_shared_server`` (GHUS, 9 Nov 2026, 10-day team
trial). The same pages, the same backend commands and the same database; only
where things live differs:

* every setting comes from the environment (the host's secret store), never
  from a ``.env`` file in the image;
* everything that must outlive a redeploy sits on the persistent disk at
  ``GHUS_DATA_DIR`` (default ``/var/data``): the Review store (the only record
  of a rejected candidate, see docs/REVIEW_STORE_PERSISTENCE.md), uploaded
  Data Feed files, Build the Map jobs, and the agents' run logs and caches;
* it listens on ``0.0.0.0:$PORT`` behind the host's HTTPS proxy, with a login
  required (``GHUS_ACCESS_USERS``; see backend.access).

It refuses to start when the disk is not mounted, so a missing disk never
quietly puts Review decisions somewhere a redeploy wipes, and when a login's
password is shorter than 12 characters. Nothing is printed that holds a secret.

Moving a Review store in (10 Nov 2026): upload it next to the store as
``review-shared.sqlite3.incoming`` and restart the service. Before the app
opens anything, the launcher checks the upload is an intact Review store, keeps
the store it replaces under ``review-store/replaced/``, and puts the upload in
its place. A store is never overwritten while the app has it open.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "ghus-backend"


def _driver_urls(url: str) -> tuple[str, str]:
    """(SQLAlchemy psycopg URL, plain libpq URL) from any postgres URL form."""
    plain = url
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://", "postgres://"):
        if plain.startswith(prefix):
            plain = "postgresql://" + plain[len(prefix):]
    return plain.replace("postgresql://", "postgresql+psycopg://", 1), plain


def _on_disk(link: Path, target: Path) -> None:
    """Make ``link`` (inside the image) point at ``target`` on the disk."""
    target.mkdir(parents=True, exist_ok=True)
    if link.is_symlink():
        if link.resolve() == target.resolve():
            return
        link.unlink()
    elif link.exists():
        # Shipped in the image by mistake: keep its files, then link.
        for item in link.iterdir():
            if not (target / item.name).exists():
                shutil.move(str(item), str(target / item.name))
        shutil.rmtree(link)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)


def take_incoming_store(store: Path) -> str | None:
    """Put an uploaded ``<store>.incoming`` in place of the store; say what happened."""
    incoming = store.with_name(store.name + ".incoming")
    if not incoming.is_file():
        return None
    db = None
    try:
        db = sqlite3.connect(f"file:{incoming}?mode=ro", uri=True)
        intact = db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.DatabaseError:
        intact, tables = False, set()
    finally:
        if db is not None:
            db.close()
    if not intact or not {"review_candidate", "review_decision"} <= tables:
        rejected = incoming.with_name(incoming.name + ".rejected")
        incoming.replace(rejected)
        return f"the uploaded store is not an intact Review store; kept as {rejected.name}, not used"
    kept = store.parent / "replaced" / time.strftime("%Y%m%d-%H%M%S")
    kept.mkdir(parents=True, exist_ok=True)
    for part in (store, store.with_name(store.name + "-wal"), store.with_name(store.name + "-shm"),
                 store.with_name(store.name + "-journal")):
        if part.exists():
            part.replace(kept / part.name)
    incoming.replace(store)
    return f"the uploaded store is now the Review store; the one it replaced is in {kept}"


def prepare(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Check the host and return the settings the app runs with."""
    env = os.environ if environ is None else environ
    data = Path(env.get("GHUS_DATA_DIR") or "/var/data")
    if not data.is_dir():
        raise SystemExit(
            f"GHUS_DATA_DIR ({data}) is not a mounted directory. Refusing to start: "
            "Review decisions written anywhere else are lost at the next deploy.")
    probe = data / ".write-check"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise SystemExit(f"GHUS_DATA_DIR ({data}) is not writable: {exc}") from exc

    url = (env.get("DATABASE_URL") or "").strip()
    if not url:
        raise SystemExit("DATABASE_URL is not set in the host's environment.")
    if not (env.get("GHUS_ACCESS_USERS") or "").strip():
        raise SystemExit("GHUS_ACCESS_USERS is not set: the hosted app never runs without a login.")
    from backend.access import MIN_PASSWORD_LENGTH, accounts, weak_accounts

    known = accounts(env.get("GHUS_ACCESS_USERS"))
    if not known:
        raise SystemExit("GHUS_ACCESS_USERS has no valid name:password entry.")
    if weak := weak_accounts(known):
        raise SystemExit(f"Password shorter than {MIN_PASSWORD_LENGTH} characters for: "
                         f"{', '.join(weak)}. Refusing to start.")
    driver_url, plain_url = _driver_urls(url)

    store = data / "review-store" / "review-shared.sqlite3"
    store.parent.mkdir(parents=True, exist_ok=True)
    if moved := take_incoming_store(store):
        print(f"review store  : {moved}")
    (data / "map-runs").mkdir(parents=True, exist_ok=True)
    return {
        "REVIEW_SOURCE_DATABASE_URL": plain_url,
        "BROWSE_DATABASE_URL": plain_url,
        "REVIEW_STORE_DB": str(store),
        "GHUS_DISCOVERY_PROJECT_ROOT": str(BACKEND),
        "DISCOVERY_REQUESTS_DATABASE_URL": driver_url,
        "GHUS_DATAFEED_PROJECT_ROOT": str(BACKEND),
        "DATAFEED_DATABASE_URL": driver_url,
        "GHUS_ADMISSION_PROJECT_ROOT": str(BACKEND),
        "REVIEW_ADMISSION_DATABASE_URL": driver_url,
        "GHUS_DATAFEED_ORIGINALS": str(data / "datafeed-originals"),
        "MAP_RUN_DB": str(data / "map-runs" / "runs.sqlite3"),
        "GHUS_REQUIRE_LOGIN": "1",
    }


def main() -> int:
    settings = prepare()
    os.environ.update(settings)
    for demo_only in ("GHUS_DEMO_MODE", "REVIEW_DEMO_MODE", "REVIEW_SOURCE_RUN_DB"):
        os.environ.pop(demo_only, None)
    data = Path(os.environ.get("GHUS_DATA_DIR") or "/var/data")
    # The agents' run logs, blocked-site list, search and answer caches, and the
    # pages they read: kept across deploys so a repeat run does not pay again.
    _on_disk(BACKEND / "agents" / "runs", data / "agent-runs")
    _on_disk(BACKEND / "agents" / "raw_documents", data / "raw-documents")

    port = int(os.environ.get("PORT") or 10000)
    print("database      : shared (from the host's environment)")
    print(f"review store  : {settings['REVIEW_STORE_DB']}")
    print(f"backend       : {BACKEND}")
    print(f"listening on  : 0.0.0.0:{port}")

    sys.path.insert(0, str(ROOT))
    import uvicorn

    os.environ.setdefault("GHUS_REVIEW_WARM_START", "1")
    # One worker: Review's store, the request lists and "Run now" tracking are
    # held in this process.
    uvicorn.run("backend.app:app", host="0.0.0.0", port=port, log_level="info",
                proxy_headers=True, forwarded_allow_ips="*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
