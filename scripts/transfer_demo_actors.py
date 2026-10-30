"""Stage the real organizations made in the local demo database on the shared one.

    python -m scripts.transfer_demo_actors            # check against the shared database
    python -m scripts.transfer_demo_actors --live     # stage them for Review

GHUS, 2026-10-29: the work done in the local demo database moves to the shared
database so the whole team sees it. This step takes the 11 real organizations
created locally (discovered, or added through the Data Feed) - never the test
records - and stages them through the Data Feed exactly as a person would, for
Review. Admitting them (Parked, with a verify_actor item: "needs review") is
the backend's admission command; their facts are replayed by the backend's fact
writer (ghus-backend/scripts/replay_demo_facts.py).

Every value comes from the demo record as it stands. The website is the site's
root; the page it was found on is kept as the Source URL. Reads the demo
database read-only; writes only through the Data Feed's staging writer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.datafeed.bridge import DataFeedBridge  # noqa: E402
from src.datafeed.service import DataFeedService  # noqa: E402

DEMO = "postgresql://ghus_test@127.0.0.1:55432/ghus_v2_demo_test"
IMPORT_NAME = "Transfer from the local demo: 11 organizations (needs review)"
UPLOADER = "Ismail Sabbar"
# Test records made by the test suites; never transferred.
TEST_NAMES = r"^(Phase 8|Agent Verified|Accepted Actor|Topicless|Cross Topic|Overlap Actor|" \
             r"Outside Actor|Mismatch Actor|Functional New|Deep Pull Actor|FX )"

SELECT = """
select a.actor_id::text, a.name, a.website, a.actor_category, a.category_type, a.category_note,
       a.description, a.location_city, a.state_code, a.country, a.alternate_names,
       (select array_agg(s.code order by x.is_primary desc nulls last, s.code)
          from actor_sector x join sector s using (sector_id) where x.actor_id = a.actor_id) sectors,
       (select t.code from actor_fact f join topic t using (topic_id) where f.actor_id = a.actor_id
          group by t.code order by count(*) desc limit 1) main_topic
from actor a
where a.source_origin in ('claude_discovered', 'ghus_manual') and a.merged_into_actor_id is null
order by a.created_at
"""


def shared_url() -> str:
    url = dotenv_values(ROOT / ".env").get("DATABASE_URL", "")
    return url.replace("postgresql+psycopg2://", "postgresql+psycopg://")


def sentences(text: str | None, limit: int) -> str:
    """At most ``limit`` characters, cut at the end of a sentence."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("; "))
    return cut[: end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0]


def records(catalog: dict) -> list[dict]:
    vocab = catalog["vocabularies"]
    categories = {c["code"]: c["label"] for c in vocab["actor_categories"]}
    sectors = {s["code"]: s["label"] for s in vocab["sectors"]}
    with psycopg.connect(DEMO, options="-c default_transaction_read_only=on") as conn:
        rows = conn.execute(SELECT).fetchall()
    out = []
    for (actor_id, name, website, category, type_code, note, description, city, state,
         country, alternate, codes, topic) in rows:
        if re.match(TEST_NAMES, name):
            continue
        types = {t["code"]: t["label"] for t in vocab["category_types"].get(category, [])}
        codes = list(codes or [])
        primary = topic if topic in codes or not codes else codes[0]
        parts = urlsplit(website or "")
        out.append({"_demo_actor_id": actor_id, "record": {
            "name": name,
            "alternate_names": "; ".join(alternate or []),
            "website": f"{parts.scheme}://{parts.netloc}" if parts.netloc else "",
            "actor_category": categories.get(category, category),
            "category_type": types.get(type_code, "") if type_code else "",
            "category_note": sentences(note, 500),
            "description": sentences(description, 1000),
            "primary_sector": sectors.get(primary, primary),
            "additional_sectors": "; ".join(sectors.get(c, c) for c in codes if c != primary),
            "city": city or "",
            "state_code": state or "",
            "country": "United States" if (country or "US") in ("US", "USA", "United States") else country,
            "source_url": website or "",
        }})
    return out


MAP_IMPORT_NAME = "Transfer from the local demo: Explore and Map results (energy optimization)"


def map_records(catalog: dict, store: Path) -> list[dict]:
    """Results Explore and Map sent to Review, held only in the local review store.

    The same fields the Map's own hand-off to the Data Feed sends; the first
    evidence page is the Source URL. Nothing is added that the result did not say.
    """
    import sqlite3

    states = {s["label"].split(" (")[0].casefold(): s["label"]
              for s in catalog["vocabularies"]["states"]}
    db = sqlite3.connect(store)
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT reviewed_payload, evidence FROM review_candidate WHERE "
                      "source_run_id LIKE '05f7f0f8%' AND status = 'pending_review'").fetchall()
    out = []
    for row in rows:
        p = json.loads(row["reviewed_payload"] or "{}")
        evidence = json.loads(row["evidence"] or "[]")
        url = next((e.get("url") for e in evidence if str(e.get("url") or "").startswith("http")), "")
        said = f"{p.get('category_note') or ''} {p.get('description') or ''}"
        # A national lab's formal designation, only where the result states it.
        designation = ("DOE national laboratory" if p.get("actor_category") == "National Laboratory"
                       and re.search(r"\bDOE national lab", said, re.I) else "")
        out.append({"record": {
            "name": p.get("name") or "",
            "actor_category": p.get("actor_category") or "",
            "category_type": p.get("category_type") or "",
            "category_note": sentences(p.get("category_note"), 500),
            "description": sentences(p.get("description"), 1000),
            "primary_sector": "Energy Transition",
            "city": p.get("location_city") or "",
            "state_code": states.get(str(p.get("state") or "").casefold(), p.get("state") or ""),
            "country": p.get("country") or "",
            "source_url": url,
            "funding_signal": sentences(p.get("funding_summary"), 1000),
            # Its current activities carry no date, and a recent activity needs one:
            # left out rather than dated by guess.
            **({"formal_national_designation": designation} if designation else {}),
        }})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="stage them for Review")
    parser.add_argument("--map-results", action="store_true",
                        help="the Explore and Map results instead of the 11 organizations")
    parser.add_argument("--out", type=Path, default=ROOT / ".datafeed" / "transfer_actors.json")
    args = parser.parse_args(argv)
    bridge = DataFeedBridge(project_root=ROOT / "ghus-backend", database_url=shared_url())
    service = DataFeedService(bridge=bridge, preview_dir=ROOT / ".datafeed" / "transfer")
    if args.map_results:
        chosen = map_records(service.catalog(), ROOT / ".demo" / "review-demo.sqlite3")
        preview = service.validate_manual("actor", [c["record"] for c in chosen], method="map")
        print(f"{len(chosen)} map results; preview counts: {preview['counts']}")
        for row in preview["rows"]:
            print(f"  {row['status']:<9} {row['payload'].get('name')}  {row.get('errors') or ''}")
        if not args.live:
            print("check only: nothing staged (add --live)")
            return 0
        outcome = service.confirm(preview["preview_id"], import_name=MAP_IMPORT_NAME,
                                  accept_left_out=True, uploaded_by=UPLOADER, attest_source=True,
                                  admission="review")
        print(json.dumps({k: outcome.get(k) for k in ("status", "run_id", "staged",
                                                       "already_awaiting_review", "left_out")}))
        return 0
    chosen = records(service.catalog())
    preview = service.validate_manual("actor", [c["record"] for c in chosen])
    print(f"{len(chosen)} organizations; preview counts: {preview['counts']}")
    for item, row in zip(chosen, preview["rows"]):
        print(f"  {row['status']:<9} {row['record']['name'] if 'record' in row else row['payload'].get('name')}"
              f"  errors={row.get('errors') or ''}")
    if not args.live:
        print("check only: nothing staged (add --live)")
        return 0
    outcome = service.confirm(preview["preview_id"], import_name=IMPORT_NAME, accept_left_out=False,
                              uploaded_by=UPLOADER, attest_source=True, admission="review")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"outcome": outcome, "chosen": chosen}, indent=1, default=str),
                        encoding="utf-8")
    print(json.dumps({k: outcome.get(k) for k in ("status", "run_id", "staged",
                                                   "already_awaiting_review", "left_out")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
