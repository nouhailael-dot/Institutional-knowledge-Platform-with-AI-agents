"""Serve the platform against the ISOLATED demonstration database.

A second instance, on its own port, with its own review store, reading a local
`_test` database. Every Review response it serves carries the
"EXAMPLE / TEST DATA" banner, so a demo can never be mistaken for the real
queue.

    python -m scripts.run_demo_server [--port 8030] [--database ghus_v2_demo_test]

It refuses any target that is not a local `*_test` database, so this script
cannot be pointed at production even by accident.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]

# Local only, and only a database whose name ends in _test. Both conditions, not
# either: a local host with a production-shaped name is still refused.
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
ALLOWED_PORT = 55432


def _guarded_url(database: str, user: str) -> str:
    url = f"postgresql://{user}@127.0.0.1:{ALLOWED_PORT}/{database}"
    parsed = urlsplit(url)
    name = (parsed.path or "").removeprefix("/")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise SystemExit(f"demo server refuses a non-local host: {parsed.hostname}")
    if parsed.port != ALLOWED_PORT:
        raise SystemExit(f"demo server refuses port {parsed.port}; expected {ALLOWED_PORT}")
    if not name.endswith("_test"):
        raise SystemExit(f"demo server refuses database {name!r}: the name must end in _test")
    return url


def _backend_root(explicit: str | None) -> Path | None:
    """The GHUS backend checkout that owns discovery requests.

    Explicit argument, then environment, then this repository's own
    `ghus-backend/`. The separate GHUS-Platform checkout is no longer searched:
    the backend lives in this repository, and an old sibling copy must never
    be run by accident.
    """
    candidates = [explicit, os.environ.get("GHUS_DISCOVERY_PROJECT_ROOT"),
                  os.environ.get("GHUS_ADMISSION_PROJECT_ROOT"), str(ROOT / "ghus-backend")]
    for candidate in candidates:
        if candidate and (Path(candidate) / "agents" / "collection"
                          / "discovery_requests.py").is_file():
            return Path(candidate)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8030)
    parser.add_argument("--database", default="ghus_v2_demo_test")
    parser.add_argument("--user", default="ghus_test")
    parser.add_argument("--backend-root", default=None,
                        help="GHUS backend checkout, for Discovery requests")
    args = parser.parse_args(argv)

    url = _guarded_url(args.database, args.user)

    store = ROOT / ".demo" / "review-demo.sqlite3"
    store.parent.mkdir(parents=True, exist_ok=True)

    env = {
        "REVIEW_SOURCE_DATABASE_URL": url,
        # Browse reads the database this instance writes to (it read DATABASE_URL
        # from .env - the shared database - before).
        "BROWSE_DATABASE_URL": url,
        # Its own store, so demo decisions never land in the real review store.
        "REVIEW_STORE_DB": str(store),
        "GHUS_DEMO_MODE": "1",
    }
    backend = _backend_root(args.backend_root)
    if backend is not None:
        # Discovery requests are written to the same isolated _test database,
        # through the backend's own command - never by this app.
        env["GHUS_DISCOVERY_PROJECT_ROOT"] = str(backend)
        env["DISCOVERY_REQUESTS_DATABASE_URL"] = url.replace(
            "postgresql://", "postgresql+psycopg://", 1)
        # Data Feed stages records for Review in the same isolated database.
        env["GHUS_DATAFEED_PROJECT_ROOT"] = str(backend)
        env["DATAFEED_DATABASE_URL"] = env["DISCOVERY_REQUESTS_DATABASE_URL"]
    os.environ.update(env)
    # Whatever .env says, this instance must not reach a canonical database.
    for leaked in ("DATABASE_URL", "REVIEW_ADMISSION_DATABASE_URL",
                   "REVIEW_SOURCE_POSTGRES_ENV_FILE", "REVIEW_SOURCE_RUN_DB"):
        os.environ.pop(leaked, None)
    if backend is not None:
        # Review decisions (verify, park, reject, add a sector) are applied by
        # the GHUS backend's admission command - to this SAME isolated _test
        # database, which _guarded_url has already confirmed. Never anywhere else.
        os.environ["GHUS_ADMISSION_PROJECT_ROOT"] = str(backend)
        os.environ["REVIEW_ADMISSION_DATABASE_URL"] = url.replace(
            "postgresql://", "postgresql+psycopg://", 1)

    print(f"demo database : {args.database} (127.0.0.1:{ALLOWED_PORT})")
    print(f"review store  : {store}")
    print(f"demo banner   : on")
    print(f"discovery     : {backend or 'not configured (backend checkout not found)'}")
    print(f"admission     : {'on, to ' + args.database if backend else 'off'}")
    print(f"listening on  : http://localhost:{args.port}")

    sys.path.insert(0, str(ROOT))
    import uvicorn

    uvicorn.run("backend.app:app", host="127.0.0.1", port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
