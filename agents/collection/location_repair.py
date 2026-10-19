"""Fill actors' missing state, region and coordinates from their own records.

    python -m agents.collection.location_repair            # dry run: report only
    python -m agents.collection.location_repair --live     # write the derivations

Deterministic only (``agents.common.location_derivation``): the state of a city
that is a place in exactly one US state, coordinates of a city in the record's
own state, the region of a state, and a state (and "… at <City>") in the name.
Nothing is read from the web and no model is called; each value says how it
was derived, and only empty fields are filled (``decisions.fill_actor_location_gaps``).

Actors still missing a city after this have nothing in their record to derive
it from: their own pages can say it (Actor updates -> Missing information).

Writes outside a local ``*_test`` database also need
ACTOR_UPDATE_WRITES_ENABLED=true.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]


def targets(session) -> list[dict]:
    """Actors (not merged, not aggregates) missing a state, a region or coordinates."""
    return [dict(r) for r in session.execute(text(
        "SELECT a.actor_id::text AS actor_id, a.name, "
        "COALESCE(NULLIF(to_jsonb(a)->>'location_city',''), NULLIF(to_jsonb(a)->>'city','')) "
        "AS city, COALESCE(NULLIF(to_jsonb(a)->>'state_code',''), NULLIF(to_jsonb(a)->>'state','')) "
        "AS state, NULLIF(to_jsonb(a)->>'region_code','') AS region, a.country, "
        "(a.latitude IS NOT NULL AND a.longitude IS NOT NULL) AS has_coordinates, "
        "COALESCE(NULLIF(to_jsonb(a)->>'status',''), NULLIF(to_jsonb(a)->>'record_status',''),'') "
        "AS status FROM actor a WHERE a.merged_into_actor_id IS NULL "
        "AND COALESCE(NULLIF(to_jsonb(a)->>'actor_category',''), "
        "  NULLIF(to_jsonb(a)->>'actor_type',''), '') <> 'aggregate' "
        "AND (NULLIF(COALESCE(to_jsonb(a)->>'state_code', to_jsonb(a)->>'state'),'') IS NULL "
        "  OR NULLIF(to_jsonb(a)->>'region_code','') IS NULL OR a.latitude IS NULL) "
        "ORDER BY a.name"
    )).mappings()]


def run(session, *, live: bool) -> dict:
    from agents.common.location_derivation import derive
    from agents.enrichment.decisions import fill_actor_location_gaps

    rows, filled = [], 0
    for actor in targets(session):
        derivation = derive(name=actor["name"], city=actor["city"], state=actor["state"],
                            country=actor["country"] or "US",
                            has_coordinates=bool(actor["has_coordinates"]))
        if actor["region"]:
            derivation.region_code = None  # never touch a recorded region
        if not derivation.any and not derivation.region_code:
            rows.append({**actor, "action": "nothing_to_derive"})
            continue
        if not derivation.how and derivation.region_code:
            derivation.how.append(f"region from the state {actor['state']}")
        result = fill_actor_location_gaps(session, actor_id=actor["actor_id"],
                                          derivation=derivation, live=live)
        filled += result["action"] == "filled"
        rows.append({**actor, "derived": result, "action": result["action"],
                     "how": result.get("how", [])})
    if live:
        session.commit()
    return {"live": live, "checked": len(rows), "filled": filled, "rows": rows}


def render(report: dict) -> str:
    done = [r for r in report["rows"] if r["action"] in ("filled", "would_fill")]
    left = [r for r in report["rows"] if r["action"] == "nothing_to_derive"]
    lines = [f"# Location repair - {datetime.now(UTC):%Y-%m-%d %H:%M} UTC "
             f"({'written' if report['live'] else 'dry run, nothing written'})", "",
             f"Checked {report['checked']} actors missing a state, region or coordinates; "
             f"{len(done)} can be filled from their own record, {len(left)} cannot.", "",
             "| Actor | Status | City | State | Filled | How |", "|---|---|---|---|---|---|"]
    for r in done:
        d = r["derived"]
        got = ", ".join(f"{k}={d[k]}" for k in ("city", "state_code", "region_code")
                        if d.get(k)) + (" + coordinates" if d.get("latitude") else "")
        lines.append(f"| {r['name']} | {r['status']} | {r['city'] or '—'} | {r['state'] or '—'} "
                     f"| {got} | {'; '.join(r['how'])} |")
    lines += ["", "## Nothing in the record to derive from", "",
              "Abroad (the gazetteer is US-only), an ambiguous city, or no city, state or "
              "state-bearing name. Their own pages can say it: Actor updates -> Missing "
              "information.", ""]
    lines += [f"- {r['name']} ({r['status']}): city {r['city'] or '—'}, state {r['state'] or '—'}, "
              f"country {r['country'] or '—'}" for r in left]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="write; absent means dry run")
    parser.add_argument("--report-out", default=None)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    from agents.collection.actor_updates import _local_test_database

    if args.live and not _local_test_database() \
            and os.environ.get("ACTOR_UPDATE_WRITES_ENABLED", "").lower() != "true":
        print(json.dumps({"ok": False, "error": "Writing outside a local *_test database needs "
                                                "ACTOR_UPDATE_WRITES_ENABLED=true."}))
        return 0
    from agents.collection.discovery_requests import open_session

    with open_session() as session:
        report = run(session, live=args.live)
    out = Path(args.report_out or ROOT / "agents" / "runs" /
               f"location-repair-{datetime.now(UTC):%Y%m%d-%H%M}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(report), encoding="utf-8")
    print(json.dumps({"ok": True, "live": report["live"], "checked": report["checked"],
                      "filled": report["filled"],
                      "derivable": sum(1 for r in report["rows"]
                                       if r["action"] in ("filled", "would_fill")),
                      "report": str(out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
