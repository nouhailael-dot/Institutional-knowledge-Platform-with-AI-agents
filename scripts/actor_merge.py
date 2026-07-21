"""
actor_merge.py — reversible actor merge execution for GHUS entity resolution.

Merges a "loser" actor into a "winner" actor, moving every reference, and keeps
enough state to undo it. Built against the real GHUS schema (initial_v1_schema +
organization_hierarchy migration).

Three reference shapes are handled, each with its own hazard:

  (1) SCALAR FKs — plain columns pointing at actor.actor_id. HAZARD: composite
      PKs / unique constraints mean the loser's row can COLLIDE with a row the
      winner already has (e.g. hub_actor PK is (hub_id, actor_id) and duplicate
      actors usually share a hub). Colliding loser rows are captured, then
      deleted, then the survivors are repointed.

  (2) organization_hierarchy — TWO actor columns with composite PK
      (parent_actor_id, child_actor_id). Same collision hazard, plus repointing
      can create a self-edge (parent == child).

  (3) hub_sector_strength.top_actor_ids — a uuid[] ARRAY. A scalar UPDATE does
      nothing to it; needs array_replace, then de-duplication in case the winner
      was already present in the same array.

Reversibility: pre_merge_state stores the loser row, the identity of every row
that was repointed, the FULL rows that were deleted as collisions, and the
complete before-state of hierarchy edges and arrays for BOTH actors. revert_merge
restores from that, so it moves back only the rows that actually came from the
loser and re-inserts what was deleted.

Usage:
    from src.db.session import SessionLocal
    from src.ml.entity_resolution.actor_merge import merge_actors, revert_merge

    merge_id = merge_actors(SessionLocal, winner_id, loser_id,
                            score=0.97, method="auto", decided_by="er_pipeline")
    revert_merge(SessionLocal, merge_id)      # if it was wrong
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

ACTOR_TABLE = "actor"
ACTOR_PK = "actor_id"
MERGED_INTO_COL = "merged_into_actor_id"

# (table, actor_column, identity_cols, collision_cols)
#   identity_cols  : columns that identify the row apart from the actor column,
#                    so revert moves back ONLY the loser's original rows.
#   collision_cols : columns that must be unique per actor. [] means the table is
#                    unique on the actor column alone. None means no constraint.
SCALAR_FKS = [
    ("hub_actor",           "actor_id",      ["hub_id"],                  ["hub_id"]),
    ("actor_person",        "actor_id",      ["person_id", "role"],       ["person_id", "role"]),
    ("actor_sector",        "actor_id",      ["sector_id"],               ["sector_id"]),
    ("actor_relevance",     "actor_id",      ["actor_relevance_id"],      ["challenge_id"]),
    ("partnership_profile", "actor_id",      ["partnership_profile_id"],  []),
    ("event",               "host_actor_id", ["event_id"],                None),
]

HIERARCHY_TABLE = "organization_hierarchy"
HIERARCHY_COLS = ["parent_actor_id", "child_actor_id"]
ARRAY_FKS = [("hub_sector_strength", ["hub_id", "sector_id"], "top_actor_ids")]

# GAP 3 — field-level inheritance. When a scraped duplicate is merged into the
# canonical actor, the winner should KEEP its own values but gain anything it was
# missing. Only fields the winner has left empty are filled. Identity/provenance
# columns (name, slug, source_id, confidence, timestamps) are deliberately excluded.
INHERITABLE_FIELDS = [
    "actor_type", "actor_type_raw", "description", "website", "location_city",
    "state", "country", "primary_technical_focus", "technical_approach",
    "current_activities", "technology_ip_notes", "key_constraints",
    "estimated_trl", "primary_lifecycle_role",
]
# Anything inherited is AI/scraper-sourced until a human confirms it, per the
# project's provenance rule.
FLAG_INHERITED_AS_NEEDS_REVIEW = True


def _now():
    return datetime.now(timezone.utc)


def _recompute_hub_sector_strength(conn, actor_id):
    """GAP 2 — refresh denormalized counts for the hubs this actor belongs to.

    A merge changes hub/sector membership, so hub_sector_strength.actor_count
    goes stale. Merged-away actors (merged_into_actor_id NOT NULL) are excluded.

    NOTE: strength_score is NOT recomputed — its formula lives in your scoring
    code, not here. Re-run that job after a batch of merges.
    """
    conn.execute(text("""
        UPDATE hub_sector_strength h
        SET actor_count = sub.cnt, last_computed = now()
        FROM (
            SELECT ha.hub_id, asec.sector_id, COUNT(DISTINCT ha.actor_id) AS cnt
            FROM hub_actor ha
            JOIN actor_sector asec ON asec.actor_id = ha.actor_id
            JOIN actor a ON a.actor_id = ha.actor_id
            WHERE a.merged_into_actor_id IS NULL
            GROUP BY ha.hub_id, asec.sector_id
        ) sub
        WHERE h.hub_id = sub.hub_id AND h.sector_id = sub.sector_id
          AND h.hub_id IN (SELECT hub_id FROM hub_actor WHERE actor_id = :a)
    """), {"a": actor_id})


def _rows(result):
    return [dict(r) for r in result.mappings().all()]


def _jsonable(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if v is None or isinstance(v, (int, float, bool, str)):
            out[k] = v
        elif isinstance(v, (list, tuple)):
            out[k] = [str(x) for x in v]
        else:
            out[k] = str(v)
    return out


# --------------------------------------------------------------------- snapshot
def _snapshot(conn, winner_id, loser_id) -> dict:
    loser_row = conn.execute(
        text(f"SELECT * FROM {ACTOR_TABLE} WHERE {ACTOR_PK} = :id"), {"id": loser_id}
    ).mappings().first()
    if loser_row is None:
        raise ValueError(f"loser actor {loser_id} not found")
    if conn.execute(text(f"SELECT 1 FROM {ACTOR_TABLE} WHERE {ACTOR_PK} = :id"),
                    {"id": winner_id}).first() is None:
        raise ValueError(f"winner actor {winner_id} not found")

    snap = {"loser_row": _jsonable(dict(loser_row)),
            "scalar_identity": {}, "hierarchy_before": {}, "arrays_before": [],
            "captured_at": _now().isoformat()}

    # NOTE: scalar_identity is filled during merge_actors, AFTER collision rows are
    # removed, so it lists only rows that were actually repointed. Capturing it here
    # would also include collision-deleted rows, and revert would then move a row
    # that belongs to the winner.

    # full hierarchy edges touching EITHER actor, so revert can restore exactly
    snap["hierarchy_before"] = [
        _jsonable(r) for r in _rows(conn.execute(
            text(f"SELECT * FROM {HIERARCHY_TABLE} WHERE parent_actor_id IN (:w,:l) "
                 f"OR child_actor_id IN (:w,:l)"), {"w": winner_id, "l": loser_id}))]

    # full array rows containing EITHER actor (arrays kept as real lists)
    for tbl, pk_cols, arr_col in ARRAY_FKS:
        sel = ", ".join(pk_cols + [arr_col])
        got = _rows(conn.execute(
            text(f"SELECT {sel} FROM {tbl} WHERE :w = ANY({arr_col}) OR :l = ANY({arr_col})"),
            {"w": winner_id, "l": loser_id}))
        for r in got:
            snap["arrays_before"].append({
                "table": tbl,
                "pk": {c: str(r[c]) for c in pk_cols},
                "value": [str(x) for x in (r[arr_col] or [])],
            })
    return snap


# ------------------------------------------------------------------------ merge
def merge_actors(SessionLocal, winner_id, loser_id, *, score, method, decided_by,
                 inherit_fields: bool = True, recompute_aggregates: bool = True):
    """Merge loser INTO winner, reversibly. Returns merge_id. All-or-nothing.

    inherit_fields      — winner gains any INHERITABLE_FIELDS it left empty (this
                          is what makes ingest-time dedup useful: the scraped
                          duplicate's new facts land on the canonical actor).
    recompute_aggregates— refresh hub_sector_strength.actor_count afterwards.
    """
    if str(winner_id) == str(loser_id):
        raise ValueError("winner and loser are the same actor")

    session = SessionLocal()
    try:
        conn = session.connection()
        pre = _snapshot(conn, winner_id, loser_id)
        deleted = {"scalar": {}, "hierarchy": []}

        # (1) scalar FKs: resolve collisions, then repoint
        for tbl, acol, ident, collision in SCALAR_FKS:
            if collision is not None:
                if collision == []:          # unique on the actor column alone
                    sql = (f"DELETE FROM {tbl} WHERE {acol} = :l "
                           f"AND EXISTS (SELECT 1 FROM {tbl} w WHERE w.{acol} = :w) RETURNING *")
                else:
                    match = " AND ".join(f"w.{c} = lo.{c}" for c in collision)
                    sql = (f"DELETE FROM {tbl} lo WHERE lo.{acol} = :l "
                           f"AND EXISTS (SELECT 1 FROM {tbl} w WHERE w.{acol} = :w AND {match}) "
                           f"RETURNING *")
                gone = _rows(conn.execute(text(sql), {"l": loser_id, "w": winner_id}))
                if gone:
                    deleted["scalar"][tbl] = [_jsonable(r) for r in gone]
            # identity of the rows that SURVIVE and will be repointed. Taken after
            # collision removal so revert never touches a winner-owned row.
            cols = ", ".join(ident)
            surviving = _rows(conn.execute(
                text(f"SELECT {cols} FROM {tbl} WHERE {acol} = :l"), {"l": loser_id}))
            pre["scalar_identity"][tbl] = [_jsonable(r) for r in surviving]
            conn.execute(text(f"UPDATE {tbl} SET {acol} = :w WHERE {acol} = :l"),
                         {"w": winner_id, "l": loser_id})

        # (2) hierarchy: drop would-be duplicates and self-edges, then repoint
        for col, other in (("parent_actor_id", "child_actor_id"),
                           ("child_actor_id", "parent_actor_id")):
            gone = _rows(conn.execute(text(
                f"DELETE FROM {HIERARCHY_TABLE} lo WHERE lo.{col} = :l AND EXISTS ("
                f"  SELECT 1 FROM {HIERARCHY_TABLE} wi WHERE wi.{col} = :w "
                f"  AND wi.{other} = lo.{other}) RETURNING *"),
                {"l": loser_id, "w": winner_id}))
            deleted["hierarchy"] += [_jsonable(r) for r in gone]
        gone = _rows(conn.execute(text(
            f"DELETE FROM {HIERARCHY_TABLE} "
            f"WHERE (parent_actor_id = :l AND child_actor_id = :w) "
            f"   OR (parent_actor_id = :w AND child_actor_id = :l) RETURNING *"),
            {"l": loser_id, "w": winner_id}))
        deleted["hierarchy"] += [_jsonable(r) for r in gone]
        for col in HIERARCHY_COLS:
            conn.execute(text(f"UPDATE {HIERARCHY_TABLE} SET {col} = :w WHERE {col} = :l"),
                         {"w": winner_id, "l": loser_id})
        conn.execute(text(f"DELETE FROM {HIERARCHY_TABLE} "
                          f"WHERE parent_actor_id = child_actor_id"))

        # (3) arrays: replace loser id with winner id, then de-duplicate
        for tbl, pk_cols, arr_col in ARRAY_FKS:
            conn.execute(text(
                f"UPDATE {tbl} SET {arr_col} = array_replace({arr_col}, :l, :w) "
                f"WHERE :l = ANY({arr_col})"), {"l": loser_id, "w": winner_id})
            conn.execute(text(
                f"UPDATE {tbl} SET {arr_col} = sub.deduped FROM ("
                f"  SELECT {', '.join(pk_cols)}, ARRAY(SELECT DISTINCT unnest({arr_col})) AS deduped"
                f"  FROM {tbl} WHERE :w = ANY({arr_col})) sub "
                f"WHERE " + " AND ".join(f"{tbl}.{c} = sub.{c}" for c in pk_cols)),
                {"w": winner_id})

        # (4) soft-delete the loser
        conn.execute(text(f"UPDATE {ACTOR_TABLE} SET {MERGED_INTO_COL} = :w "
                          f"WHERE {ACTOR_PK} = :l"), {"w": winner_id, "l": loser_id})

        # (4b) GAP 3 — field-level inheritance (fills only what the winner lacks)
        inherited, prev_status = {}, None
        if inherit_fields:
            w_row = conn.execute(text(f"SELECT * FROM {ACTOR_TABLE} WHERE {ACTOR_PK} = :w"),
                                 {"w": winner_id}).mappings().first()
            l_row = pre["loser_row"]
            for f in INHERITABLE_FIELDS:
                wv, lv = w_row.get(f), l_row.get(f)
                if (wv is None or str(wv).strip() == "") and lv is not None and str(lv).strip() != "":
                    inherited[f] = lv
            if inherited:
                prev_status = w_row.get("verification_status")
                sets = ", ".join(f"{f} = :{f}" for f in inherited)
                extra = ", verification_status = 'needs_review'" if FLAG_INHERITED_AS_NEEDS_REVIEW else ""
                params = dict(inherited); params["w"] = winner_id
                conn.execute(text(f"UPDATE {ACTOR_TABLE} SET {sets}{extra}, "
                                  f"updated_at = now() WHERE {ACTOR_PK} = :w"), params)
        pre["inherited"] = {"fields": list(inherited),
                            "prev_verification_status": prev_status}

        # (4c) GAP 2 — refresh denormalized aggregates
        if recompute_aggregates:
            _recompute_hub_sector_strength(conn, winner_id)

        # (5) log
        pre["deleted"] = deleted
        merge_id = uuid.uuid4()
        conn.execute(text(
            """INSERT INTO actor_merge_log
               (merge_id, winner_actor_id, loser_actor_id, score, method, decided_by,
                decided_at, pre_merge_state, status)
               VALUES (:mid, :w, :l, :s, :m, :by, :at, :pre, 'applied')"""),
            {"mid": merge_id, "w": winner_id, "l": loser_id, "s": float(score),
             "m": method, "by": decided_by, "at": _now(), "pre": json.dumps(pre)})

        session.commit()
        return merge_id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ----------------------------------------------------------------------- revert
def revert_merge(SessionLocal, merge_id):
    """Undo a merge using its snapshot.

    Revert newest-first if a winner absorbed several actors: undoing an older
    merge before a newer one can move the newer actor's rows to the wrong place.
    """
    session = SessionLocal()
    try:
        conn = session.connection()
        log = conn.execute(text("SELECT * FROM actor_merge_log WHERE merge_id = :id"),
                           {"id": merge_id}).mappings().first()
        if log is None:
            raise ValueError(f"merge {merge_id} not found")
        if log["status"] == "reverted":
            raise ValueError(f"merge {merge_id} already reverted")

        # GAP 1 — chained merges must be reverted newest-first. If this winner
        # absorbed other actors AFTER this merge, undoing this one now would move
        # those newer actors' rows to the wrong place. Refuse and say which.
        later = conn.execute(text(
            "SELECT merge_id FROM actor_merge_log "
            "WHERE winner_actor_id = :w AND status = 'applied' AND decided_at > :at "
            "ORDER BY decided_at DESC"),
            {"w": log["winner_actor_id"], "at": log["decided_at"]}).mappings().all()
        if later:
            ids = ", ".join(str(r["merge_id"]) for r in later)
            raise ValueError(
                f"cannot revert {merge_id}: winner {log['winner_actor_id']} absorbed "
                f"other actors later. Revert these first (newest first): {ids}")

        winner_id, loser_id = log["winner_actor_id"], log["loser_actor_id"]
        pre = log["pre_merge_state"]
        if isinstance(pre, str):
            pre = json.loads(pre)

        # (1) scalar: move back ONLY the rows that came from the loser
        for tbl, acol, ident, _ in SCALAR_FKS:
            for row in pre.get("scalar_identity", {}).get(tbl, []):
                where = " AND ".join(f"{c} = :{c}" for c in ident)
                params = {c: row[c] for c in ident}
                params.update({"w": winner_id, "l": loser_id})
                conn.execute(text(f"UPDATE {tbl} SET {acol} = :l "
                                  f"WHERE {acol} = :w AND {where}"), params)

        # (2) re-insert rows deleted as collisions
        for tbl, rows in pre.get("deleted", {}).get("scalar", {}).items():
            for row in rows:
                cols = list(row.keys())
                conn.execute(text(
                    f"INSERT INTO {tbl} ({', '.join(cols)}) "
                    f"VALUES ({', '.join(':' + c for c in cols)}) ON CONFLICT DO NOTHING"), row)

        # (3) hierarchy: rebuild exactly from the before-state
        conn.execute(text(f"DELETE FROM {HIERARCHY_TABLE} "
                          f"WHERE parent_actor_id IN (:w,:l) OR child_actor_id IN (:w,:l)"),
                     {"w": winner_id, "l": loser_id})
        for row in pre.get("hierarchy_before", []):
            cols = list(row.keys())
            conn.execute(text(
                f"INSERT INTO {HIERARCHY_TABLE} ({', '.join(cols)}) "
                f"VALUES ({', '.join(':' + c for c in cols)}) ON CONFLICT DO NOTHING"), row)

        # (4) arrays: restore the exact before-state
        for entry in pre.get("arrays_before", []):
            tbl = entry["table"]
            where = " AND ".join(f"{c} = :{c}" for c in entry["pk"])
            params = dict(entry["pk"]); params["val"] = entry["value"]
            arr_col = next(a for t, _p, a in ARRAY_FKS if t == tbl)
            conn.execute(text(f"UPDATE {tbl} SET {arr_col} = CAST(:val AS uuid[]) "
                              f"WHERE {where}"), params)

        # (5) undo field inheritance (those fields were empty before the merge)
        inh = pre.get("inherited") or {}
        if inh.get("fields"):
            sets = ", ".join(f"{f} = NULL" for f in inh["fields"])
            conn.execute(text(f"UPDATE {ACTOR_TABLE} SET {sets}, "
                              f"verification_status = :st, updated_at = now() "
                              f"WHERE {ACTOR_PK} = :w"),
                         {"st": inh.get("prev_verification_status"), "w": winner_id})

        # (6) un-soft-delete
        conn.execute(text(f"UPDATE {ACTOR_TABLE} SET {MERGED_INTO_COL} = NULL "
                          f"WHERE {ACTOR_PK} = :l"), {"l": loser_id})
        _recompute_hub_sector_strength(conn, winner_id)
        _recompute_hub_sector_strength(conn, loser_id)
        conn.execute(text("UPDATE actor_merge_log SET status='reverted', reverted_at=:at "
                          "WHERE merge_id=:id"), {"at": _now(), "id": merge_id})
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def verify_fks_query() -> str:
    return f"""
SELECT tc.table_name, kcu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
WHERE tc.constraint_type='FOREIGN KEY'
  AND ccu.table_name='{ACTOR_TABLE}' AND ccu.column_name='{ACTOR_PK}'
ORDER BY tc.table_name;
-- array columns are never declared FKs; hub_sector_strength.top_actor_ids is handled separately
"""


if __name__ == "__main__":
    print("Verify the actor_id foreign keys against your live DB:\n")
    print(verify_fks_query())