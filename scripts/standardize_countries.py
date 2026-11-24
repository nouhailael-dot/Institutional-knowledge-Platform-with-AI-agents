"""One form for the country (GHUS, 24 Nov 2026): every stored US spelling becomes "USA".

A one-time correction, run by hand in the Render shell (or locally):

    python -m scripts.standardize_countries          # dry run: lists what would change
    python -m scripts.standardize_countries --live   # writes

Organizations, their locations and hubs saved "United States", "US" or "U.S.A."
read "USA". A value that is not a US spelling (a city typed into a hub's country)
is listed, never rewritten. The write is the approved writer's
(agents.enrichment.decisions standardize_countries); this only prepares its
database address the way the hosted server does for every backend command.
"""

from __future__ import annotations

import os
import subprocess
import sys

from scripts.run_hosted_server import BACKEND, _driver_urls


def main(argv: list[str] | None = None, *, run=subprocess.run) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args not in ([], ["--live"]):
        print("usage: python -m scripts.standardize_countries [--live]", file=sys.stderr)
        return 2
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 2
    driver_url, _ = _driver_urls(url)
    env = {**os.environ, "DATABASE_URL": driver_url, "NO_COLOR": "1", "PYTHON_COLORS": "0"}
    done = run([sys.executable, "-m", "agents.enrichment.standardize_countries", *args],
               cwd=BACKEND, env=env, check=False)
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(main())
