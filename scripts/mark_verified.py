"""People and events a GHUS person verified, still shown Parked: made Verified (13 Nov 2026).

A one-time correction, run by hand in the Render shell (or locally):

    python -m scripts.mark_verified          # dry run: lists what would change
    python -m scripts.mark_verified --live   # writes

Until 13 Nov 2026 the backend created every person and event as "parked" -
the state of a record an agent found and nobody has checked - even when a GHUS
person had just verified it in Review or stored it from the Data Feed. The
write is the approved writer's (agents.enrichment.decisions
mark_reviewed_records_verified); this only prepares its database address the
way the hosted server does for every backend command.
"""

from __future__ import annotations

import os
import subprocess
import sys

from scripts.run_hosted_server import BACKEND, _driver_urls


def main(argv: list[str] | None = None, *, run=subprocess.run) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args not in ([], ["--live"]):
        print("usage: python -m scripts.mark_verified [--live]", file=sys.stderr)
        return 2
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 2
    driver_url, _ = _driver_urls(url)
    env = {**os.environ, "DATABASE_URL": driver_url, "NO_COLOR": "1", "PYTHON_COLORS": "0"}
    done = run([sys.executable, "-m", "agents.enrichment.decisions", *args],
               cwd=BACKEND, env=env, check=False)
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(main())
