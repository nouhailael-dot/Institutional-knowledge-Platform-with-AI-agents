"""Propose the controlled topic list, hub topics and hub centers for GHUS approval.

Read-only. Nothing here is applied: the `topic` table is empty and no
controlled topic list exists yet, so GHUS must approve this proposal before
migration 486 (generated from the CSV) may run. Topics are never inferred
silently from sectors; each proposal row states its basis.

Outputs:
  docs/evidence/phase12_topic_proposal.csv
  docs/evidence/phase12_topic_proposal_summary.json
"""

from __future__ import annotations

import csv
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
from psycopg2.extras import RealDictCursor

from agents.common.geography import distance_miles
from agents.common.hub_centers import (
    HUB_CENTER_METHOD_VERSION,
    CenterMember,
    compute_density_center,
)

ROOT = Path(__file__).resolve().parents[1]
CSV_OUTPUT = ROOT / "docs/evidence/phase12_topic_proposal.csv"
SUMMARY_OUTPUT = ROOT / "docs/evidence/phase12_topic_proposal_summary.json"
EXPECTED_DATABASE = "ghus_v2_phase12_full_test"
RADIUS_MILES = 200.0
# Hubs whose sector tags are empty: the name is the only evidence, so the
# proposal is marked for explicit GHUS review.
NAME_ONLY_TOPICS = {"Mining Hubs": "MINING"}
FIELDS = (
    "record_type", "topic_code", "topic_name", "basis", "needs_ghus_review",
    "hub_id", "hub_name", "primary_sectors", "members", "members_with_coordinates",
    "center_city", "center_state_code", "center_latitude", "center_longitude",
    "core_members_within_50mi", "members_outside_radius", "note",
)


def _url() -> str:
    raw = os.environ.get("V2_PHASE12_FULL_DATABASE_URL", "").strip()
    parsed = urlsplit(raw)
    if (parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 55432
            or parsed.path.removeprefix("/") != EXPECTED_DATABASE):
        raise RuntimeError("topic proposal accepts only the local full-dump copy")
    return raw


def main() -> int:
    connection = psycopg2.connect(_url(), application_name="ghus_phase12_topic_proposal")
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT count(*) n FROM topic")
            existing_topics = cursor.fetchone()["n"]
            cursor.execute("SELECT code, name FROM sector ORDER BY code")
            sectors = cursor.fetchall()
            cursor.execute("""
                SELECT hub_id::text, name, primary_sectors, secondary_sectors
                FROM hub ORDER BY name
            """)
            hubs = cursor.fetchall()
            cursor.execute("""
                SELECT ha.hub_id::text, a.actor_id::text, a.location_city city, a.state_code,
                       a.latitude, a.longitude, a.status, a.actor_category,
                       a.merged_into_actor_id IS NOT NULL merged
                FROM hub_actor ha JOIN actor a USING (actor_id)
            """)
            members: dict[str, list[dict]] = {}
            for row in cursor.fetchall():
                members.setdefault(row["hub_id"], []).append(row)
        connection.rollback()
    finally:
        connection.close()
    if existing_topics:
        raise RuntimeError("topic table is not empty; regenerate the proposal against it")

    used = {}
    rows = []
    for hub in hubs:
        primary = list(hub["primary_sectors"] or [])
        if len(primary) == 1:
            topic, basis, review = primary[0], "single legacy primary sector tag", False
        elif hub["name"] in NAME_ONLY_TOPICS:
            topic, basis, review = NAME_ONLY_TOPICS[hub["name"]], "hub name only (no sector tag)", True
        else:
            topic, basis, review = "", "no deterministic basis", True
        used[topic] = used.get(topic, 0) + 1
        hub_members = members.get(hub["hub_id"], [])
        center = compute_density_center(
            CenterMember(
                actor_id=m["actor_id"], city=m["city"] or "", state_code=m["state_code"] or "",
                latitude=float(m["latitude"]) if m["latitude"] is not None else None,
                longitude=float(m["longitude"]) if m["longitude"] is not None else None,
                record_status=m["status"] or "", actor_category=m["actor_category"],
                merged=m["merged"],
            )
            for m in hub_members
        )
        located = [m for m in hub_members if m["latitude"] is not None]
        outside = 0
        if center is not None:
            outside = sum(
                distance_miles(center.latitude, center.longitude,
                               float(m["latitude"]), float(m["longitude"])) > RADIUS_MILES
                for m in located
            )
        rows.append({
            "record_type": "hub", "topic_code": topic, "basis": basis,
            "needs_ghus_review": review, "hub_id": hub["hub_id"], "hub_name": hub["name"],
            "primary_sectors": ";".join(primary), "members": len(hub_members),
            "members_with_coordinates": len(located),
            "center_city": center.city if center else "",
            "center_state_code": center.state_code if center else "",
            "center_latitude": round(center.latitude, 6) if center else "",
            "center_longitude": round(center.longitude, 6) if center else "",
            "core_members_within_50mi": center.core_member_count if center else "",
            "members_outside_radius": outside if center else "",
            "note": "" if center else "no member with coordinates; center needs GHUS input",
        })
    topic_rows = [{
        "record_type": "topic", "topic_code": sector["code"], "topic_name": sector["name"],
        "basis": "legacy sector of the same code (1:1)",
        "needs_ghus_review": sector["code"] not in used,
        "note": f"{used.get(sector['code'], 0)} hubs" if sector["code"] in used
        else "no hub uses this sector; GHUS decides whether it is a controlled topic",
    } for sector in sectors]

    with CSV_OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(topic_rows + rows)
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "database": EXPECTED_DATABASE,
        "mode": "proposal_only_requires_ghus_approval",
        "existing_controlled_topics": existing_topics,
        "proposed_topics": [row["topic_code"] for row in topic_rows],
        "hubs": len(rows),
        "hubs_with_deterministic_topic": sum(not row["needs_ghus_review"] for row in rows),
        "hubs_needing_review": [row["hub_name"] for row in rows if row["needs_ghus_review"]],
        "hubs_with_center": sum(bool(row["center_city"]) for row in rows),
        "memberships": sum(row["members"] for row in rows),
        "memberships_outside_radius_informational": sum(
            row["members_outside_radius"] or 0 for row in rows
        ),
        "center_method": HUB_CENTER_METHOD_VERSION,
        "actor_topic_policy": (
            "actor_topic stays empty at cutover: hub membership is not topic evidence and "
            "actor_topic requires a source. Memberships carry the hub topic in hub_actor.topic_id."
        ),
    }
    SUMMARY_OUTPUT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "generated_at"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
