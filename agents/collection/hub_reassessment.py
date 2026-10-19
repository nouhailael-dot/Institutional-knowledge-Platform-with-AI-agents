"""Does an actor still fit its hubs - and does a hub now fit an actor with none?

Read-only. Uses the hub contract itself (``agents.common.hub_assignment``:
sector is Test 1, then the hub's radius) on the actor's current record, so the
answer is the one ``promote.py`` would give today. Rules (spec section 10):

* a membership is never removed here. One that no longer fits is reported -
  "outside the radius" or "sector no longer matches" - for a person to look at;
* GHUS and imported memberships (``legacy_membership_preserved``) are marked
  preserved and only ever reported;
* an actor with no hub in a sector stays eligible: when a hub of that sector
  now contains it, the nearest such hub is proposed to Review
  (``decisions.propose_hub_membership``); nothing is assigned directly;
* no hub is ever created here (new hubs come from Phase 7 hub detection).

Hubs without a ``hub_sector`` row (databases before migration 520) take their
sector from their own topic, which mirrors the sector of the same code.
"""

from __future__ import annotations

from sqlalchemy import text


def _has_table(session, table: str) -> bool:
    return bool(session.execute(text("SELECT to_regclass(:t) IS NOT NULL"), {"t": table}).scalar())


def _hubs(session) -> list[dict]:
    if _has_table(session, "hub_sector"):
        sector = ("COALESCE((SELECT s.code FROM hub_sector hs JOIN sector s ON s.sector_id = "
                  "hs.sector_id WHERE hs.hub_id = h.hub_id AND hs.is_primary LIMIT 1), t.code)")
    else:
        sector = "t.code"
    return [dict(r) for r in session.execute(text(
        "SELECT h.hub_id::text AS hub_id, h.name, h.topic_id::text AS topic_id, "
        "h.center_latitude, h.center_longitude, COALESCE(h.radius_miles, 200) AS radius_miles, "
        f"{sector} AS sector_code FROM hub h LEFT JOIN topic t ON t.topic_id = h.topic_id"
    )).mappings()]


def assess(session, actor_id: str, *, sector_codes=None) -> dict:
    """Memberships with their fit today, and hubs the actor is newly eligible for."""
    from agents.collection.actor_updates import actor_topics
    from agents.common.hub_assignment import (
        ASSIGNED,
        ActorHubContext,
        HubCandidate,
        evaluate_hub_candidate,
    )

    row = session.execute(text(
        "SELECT name, CAST(NULLIF(to_jsonb(a)->>'latitude', '') AS double precision) AS lat, "
        "CAST(NULLIF(to_jsonb(a)->>'longitude', '') AS double precision) AS lon "
        "FROM actor a WHERE a.actor_id = CAST(:id AS uuid)"), {"id": actor_id}).mappings().first()
    if row is None:
        return {"ok": False, "error": "No actor with that id."}
    sectors = frozenset(c.upper() for c in (sector_codes or ())) or frozenset(
        t["code"].upper() for t in actor_topics(session, actor_id))
    members = {str(r["hub_id"]): dict(r) for r in session.execute(text(
        "SELECT hub_id::text AS hub_id, relationship_type, assignment_outcome "
        "FROM hub_actor WHERE actor_id = CAST(:id AS uuid)"), {"id": actor_id}).mappings()}
    context = ActorHubContext(actor_id, None, row["lat"], row["lon"], sectors)
    memberships, eligible = [], []
    for hub in _hubs(session):
        candidate = HubCandidate(
            hub_id=hub["hub_id"], name=hub["name"], topic_id=hub["topic_id"],
            center_latitude=hub["center_latitude"], center_longitude=hub["center_longitude"],
            radius_miles=float(hub["radius_miles"]), sector_code=hub["sector_code"])
        evaluation = evaluate_hub_candidate(context, candidate)
        distance = (round(evaluation.distance_miles, 1)
                    if evaluation.distance_miles is not None else None)
        if hub["hub_id"] in members:
            membership = members[hub["hub_id"]]
            preserved = membership["assignment_outcome"] == "legacy_membership_preserved" or \
                membership["relationship_type"] == "member"
            if evaluation.outcome == ASSIGNED:
                fit = "fits"
            elif not evaluation.sector_matched:
                fit = "sector_no_longer_matches"
            elif evaluation.outside_radius:
                fit = "outside_radius"
            else:
                fit = "location_unknown"
            memberships.append({"hub_id": hub["hub_id"], "name": hub["name"],
                                "sector": hub["sector_code"], "fit": fit,
                                "distance_miles": distance, "radius_miles": candidate.radius_miles,
                                "preserved": preserved,
                                "action": "Kept. " + ("" if fit == "fits" else
                                                      "Reported for a person to look at; "
                                                      "never removed automatically.")})
        elif evaluation.outcome == ASSIGNED:
            eligible.append({"hub_id": hub["hub_id"], "name": hub["name"],
                             "sector": hub["sector_code"], "distance_miles": distance,
                             "radius_miles": candidate.radius_miles})
    member_sectors = {m["sector"] for m in memberships}
    proposals = []
    # One proposal per sector the actor has no hub in: the nearest hub that fits.
    for sector in sorted({e["sector"] for e in eligible} - member_sectors):
        nearest = min((e for e in eligible if e["sector"] == sector),
                      key=lambda e: (e["distance_miles"] or 0.0, e["hub_id"]))
        proposals.append({**nearest, "action": "Proposed to Review; assigned only if a person "
                                               "accepts."})
    if row["lat"] is None or row["lon"] is None:
        note = "No coordinates on record, so no hub radius can be checked."
    elif not sectors:
        note = "Not linked to a sector, so no hub can be matched (sector is Test 1)."
    elif not memberships and not proposals:
        note = "In no hub, and no hub of its sector contains it today. It stays eligible."
    else:
        note = None
    return {"ok": True, "memberships": memberships, "proposals": proposals,
            "unassigned": not memberships, "sectors": sorted(sectors), "note": note}
