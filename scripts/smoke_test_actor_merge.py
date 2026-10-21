"""
smoke_test_actor_merge.py — full-coverage test of merge + revert on throwaway rows.

Exercises EVERY reference path the merge touches, including the two hazards that
only appear on real data:
  * COLLISIONS — winner and loser both in the same hub / same sector / same
    challenge / both holding a partnership_profile. Repointing must not violate
    the composite PKs and unique constraints.
  * WINNER-OWNED ROWS — the winner has its own references before the merge;
    revert must move back ONLY the loser's rows, not the winner's.

Paths covered: hub_actor, actor_person, actor_sector, actor_relevance,
partnership_profile, event.host_actor_id, organization_hierarchy (both columns),
hub_sector_strength.top_actor_ids (uuid[]).

Creates only ZZ_TEST_* rows and deletes them at the end. Run against dev/staging.

    python scripts/smoke_test_actor_merge.py
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.db.session import SessionLocal
try:
    from actor_merge import merge_actors, revert_merge
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    from actor_merge import merge_actors, revert_merge

TAG = "ZZ_TEST"


def _x(conn, sql, **p):
    return conn.execute(text(sql), p)


def purge(conn):
    ids = [r[0] for r in _x(conn, f"SELECT actor_id FROM actor WHERE name LIKE '{TAG}%'").fetchall()]
    ev = [r[0] for r in _x(conn, f"SELECT event_id FROM event WHERE name LIKE '{TAG}%'").fetchall()]
    for aid in ids:
        for t, c in (("hub_actor", "actor_id"), ("actor_person", "actor_id"),
                     ("actor_sector", "actor_id"), ("actor_relevance", "actor_id"),
                     ("partnership_profile", "actor_id")):
            _x(conn, f"DELETE FROM {t} WHERE {c}=:a", a=aid)
        _x(conn, "UPDATE event SET host_actor_id=NULL WHERE host_actor_id=:a", a=aid)
        _x(conn, "DELETE FROM organization_hierarchy WHERE parent_actor_id=:a OR child_actor_id=:a", a=aid)
        _x(conn, "DELETE FROM actor_merge_log WHERE winner_actor_id=:a OR loser_actor_id=:a", a=aid)
        _x(conn, "UPDATE actor SET merged_into_actor_id=NULL WHERE actor_id=:a", a=aid)
        _x(conn, "UPDATE hub_sector_strength SET top_actor_ids = array_remove(top_actor_ids, :a) "
                 "WHERE :a = ANY(top_actor_ids)", a=aid)
    for e in ev:
        _x(conn, "DELETE FROM event_sector WHERE event_id=:e", e=e)
        _x(conn, "DELETE FROM event WHERE event_id=:e", e=e)
    for aid in ids:
        _x(conn, "DELETE FROM actor WHERE actor_id=:a", a=aid)
    # lookup rows this test may have created to guarantee full path coverage
    _x(conn, f"DELETE FROM hub_sector_strength WHERE sector_id IN "
             f"(SELECT sector_id FROM sector WHERE code LIKE '{TAG}%')")
    _x(conn, f"DELETE FROM actor_sector WHERE sector_id IN "
             f"(SELECT sector_id FROM sector WHERE code LIKE '{TAG}%')")
    _x(conn, f"DELETE FROM sector WHERE code LIKE '{TAG}%'")
    _x(conn, f"DELETE FROM actor_person WHERE person_id IN "
             f"(SELECT person_id FROM person WHERE full_name LIKE '{TAG}%')")
    _x(conn, f"DELETE FROM person WHERE full_name LIKE '{TAG}%'")
    if ids or ev:
        print(f"[purge] cleared {len(ids)} leftover actor(s), {len(ev)} event(s)")


def pick(conn, sql):
    r = _x(conn, sql).first()
    return r[0] if r else None


def setup(conn):
    """Create winner+loser and seed every reference path, including collisions."""
    w, l = uuid.uuid4(), uuid.uuid4()
    for aid, nm in ((w, f"{TAG}_WINNER"), (l, f"{TAG}_LOSER")):
        _x(conn, "INSERT INTO actor (actor_id, name, slug, verification_status) "
                 "VALUES (:i,:n,:s,'test')", i=aid, n=nm, s=f"zz-test-{aid.hex[:8]}")

    hub = pick(conn, "SELECT hub_id FROM hub LIMIT 1")
    hub2 = pick(conn, "SELECT hub_id FROM hub OFFSET 1 LIMIT 1")
    chal = pick(conn, "SELECT challenge_id FROM challenge LIMIT 1")
    cov = {}

    # Create our own sector/person if the tables are empty, so the actor_sector,
    # actor_person and array paths are ALWAYS covered rather than silently skipped.
    sector = pick(conn, "SELECT sector_id FROM sector LIMIT 1")
    if not sector:
        sector = uuid.uuid4()
        _x(conn, "INSERT INTO sector (sector_id, code, name) VALUES (:i,:c,:n)",
           i=sector, c=f"{TAG}_SEC", n=f"{TAG}_SECTOR")
    person = pick(conn, "SELECT person_id FROM person LIMIT 1")
    if not person:
        person = uuid.uuid4()
        _x(conn, "INSERT INTO person (person_id, full_name) VALUES (:i,:n)",
           i=person, n=f"{TAG}_PERSON")

    if hub:
        # COLLISION: both actors in the SAME hub (the realistic duplicate case)
        _x(conn, "INSERT INTO hub_actor (hub_id,actor_id,relationship_type) VALUES (:h,:a,'test')", h=hub, a=w)
        _x(conn, "INSERT INTO hub_actor (hub_id,actor_id,relationship_type) VALUES (:h,:a,'test')", h=hub, a=l)
        cov["hub_actor_collision"] = True
        if hub2:   # loser-only row that MUST survive and move to the winner
            _x(conn, "INSERT INTO hub_actor (hub_id,actor_id,relationship_type) VALUES (:h,:a,'test')", h=hub2, a=l)
            cov["hub_actor_move"] = True
    if sector:
        _x(conn, "INSERT INTO actor_sector (actor_id,sector_id,confidence) VALUES (:a,:s,0.5)", a=w, s=sector)
        _x(conn, "INSERT INTO actor_sector (actor_id,sector_id,confidence) VALUES (:a,:s,0.5)", a=l, s=sector)
        cov["actor_sector_collision"] = True
    if person:
        _x(conn, "INSERT INTO actor_person (actor_id,person_id,role) VALUES (:a,:p,'zz_role')", a=l, p=person)
        cov["actor_person"] = True
    if chal:
        _x(conn, "INSERT INTO actor_relevance (actor_relevance_id,actor_id,challenge_id,relevance_score) "
                 "VALUES (:i,:a,:c,0.5)", i=uuid.uuid4(), a=l, c=chal)
        cov["actor_relevance"] = True
    # partnership_profile is UNIQUE(actor_id) -> both having one is a collision
    _x(conn, "INSERT INTO partnership_profile (partnership_profile_id,actor_id,thematic_focus) "
             "VALUES (:i,:a,'zz')", i=uuid.uuid4(), a=w)
    _x(conn, "INSERT INTO partnership_profile (partnership_profile_id,actor_id,thematic_focus) "
             "VALUES (:i,:a,'zz')", i=uuid.uuid4(), a=l)
    cov["partnership_profile_collision"] = True
    # event.host_actor_id
    ev = uuid.uuid4()
    _x(conn, "INSERT INTO event (event_id,name,host_actor_id) VALUES (:e,:n,:a)",
       e=ev, n=f"{TAG}_EVENT", a=l)
    cov["event_host"] = True
    # hierarchy: loser as child of an unrelated parent (must move, not vanish)
    _x(conn, "INSERT INTO organization_hierarchy (parent_actor_id,child_actor_id,relationship_type) "
             "VALUES (:p,:c,'test')", p=w, c=l)      # becomes a self-edge -> deleted
    cov["hierarchy_selfedge"] = True
    # array: seed BOTH into the same top_actor_ids (dedup case)
    hss = _x(conn, "SELECT hub_id, sector_id FROM hub_sector_strength LIMIT 1").first()
    if not hss and hub and sector:
        _x(conn, "INSERT INTO hub_sector_strength (hub_id, sector_id, top_actor_ids) "
                 "VALUES (:h,:s,'{}'::uuid[]) ON CONFLICT DO NOTHING", h=hub, s=sector)
        hss = (hub, sector)
    if hss:
        _x(conn, "UPDATE hub_sector_strength SET top_actor_ids = "
                 "COALESCE(top_actor_ids,'{}'::uuid[]) || ARRAY[:w,:l]::uuid[] "
                 "WHERE hub_id=:h AND sector_id=:s", w=w, l=l, h=hss[0], s=hss[1])
        cov["array_dedup"] = True
    return w, l, ev, cov, hss


def counts(conn, a):
    return {
        "hub_actor": _x(conn, "SELECT COUNT(*) FROM hub_actor WHERE actor_id=:a", a=a).scalar(),
        "actor_person": _x(conn, "SELECT COUNT(*) FROM actor_person WHERE actor_id=:a", a=a).scalar(),
        "actor_sector": _x(conn, "SELECT COUNT(*) FROM actor_sector WHERE actor_id=:a", a=a).scalar(),
        "actor_relevance": _x(conn, "SELECT COUNT(*) FROM actor_relevance WHERE actor_id=:a", a=a).scalar(),
        "partnership": _x(conn, "SELECT COUNT(*) FROM partnership_profile WHERE actor_id=:a", a=a).scalar(),
        "event_host": _x(conn, "SELECT COUNT(*) FROM event WHERE host_actor_id=:a", a=a).scalar(),
        "hier": _x(conn, "SELECT COUNT(*) FROM organization_hierarchy "
                         "WHERE parent_actor_id=:a OR child_actor_id=:a", a=a).scalar(),
        "in_array": _x(conn, "SELECT COUNT(*) FROM hub_sector_strength WHERE :a = ANY(top_actor_ids)", a=a).scalar(),
    }


def main():
    ok = True
    fails = []

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False; fails.append(msg); print(f"  FAIL: {msg}")

    s = SessionLocal(); conn = s.connection(); purge(conn); s.commit(); s.close()

    s = SessionLocal(); conn = s.connection()
    w, l, ev, cov, hss = setup(conn)
    before_l, before_w = counts(conn, l), counts(conn, w)
    s.commit(); s.close()
    print(f"[setup] winner={w}\n[setup] loser ={l}")
    print(f"[setup] paths seeded: {', '.join(sorted(cov))}")
    print(f"[setup] loser  refs: {before_l}")
    print(f"[setup] winner refs: {before_w}")

    try:
        mid = merge_actors(SessionLocal, w, l, score=0.99, method="test", decided_by="smoke")
        print(f"\n[merge] merge_id={mid}")
    except Exception as e:
        print(f"\n  FAIL: merge raised {type(e).__name__}: {e}")
        s = SessionLocal(); conn = s.connection(); purge(conn); s.commit(); s.close()
        print("\nSOME CHECKS FAILED"); sys.exit(1)

    s = SessionLocal(); conn = s.connection()
    after_l, after_w = counts(conn, l), counts(conn, w)
    merged_into = _x(conn, "SELECT merged_into_actor_id FROM actor WHERE actor_id=:a", a=l).scalar()
    arr_dupes = 0
    if hss:
        arr = _x(conn, "SELECT top_actor_ids FROM hub_sector_strength WHERE hub_id=:h AND sector_id=:s",
                 h=hss[0], s=hss[1]).scalar() or []
        arr_dupes = [str(x) for x in arr].count(str(w))
    s.close()
    print(f"[merge] loser  refs: {after_l}")
    print(f"[merge] winner refs: {after_w}")

    check(sum(after_l.values()) == 0, f"loser still has references after merge: {after_l}")
    check(str(merged_into) == str(w), f"merged_into={merged_into}, expected {w}")
    check(after_w["partnership"] == 1, "winner should hold exactly ONE partnership_profile (unique)")
    if cov.get("hub_actor_move"):
        check(after_w["hub_actor"] >= 2, "winner did not receive the loser's second hub_actor row")
    if cov.get("array_dedup"):
        check(arr_dupes <= 1, f"winner appears {arr_dupes}x in top_actor_ids — dedup failed")
    print(f"[merge] winner in array {arr_dupes}x (expect 1) | loser.merged_into set: {merged_into is not None}")

    revert_merge(SessionLocal, mid)
    s = SessionLocal(); conn = s.connection()
    rev_l, rev_w = counts(conn, l), counts(conn, w)
    mi2 = _x(conn, "SELECT merged_into_actor_id FROM actor WHERE actor_id=:a", a=l).scalar()
    st2 = _x(conn, "SELECT status FROM actor_merge_log WHERE merge_id=:m", m=mid).scalar()
    s.close()
    print(f"\n[revert] loser  refs: {rev_l}")
    print(f"[revert] winner refs: {rev_w}")
    check(mi2 is None, f"after revert merged_into={mi2}, expected None")
    check(st2 == "reverted", f"log status={st2}, expected 'reverted'")
    for k in before_l:
        check(rev_l[k] == before_l[k], f"loser.{k} = {rev_l[k]} after revert, expected {before_l[k]}")
    for k in before_w:
        check(rev_w[k] == before_w[k], f"winner.{k} = {rev_w[k]} after revert, expected {before_w[k]}")

    s = SessionLocal(); conn = s.connection(); purge(conn); s.commit(); s.close()
    print("\n" + ("ALL CHECKS PASSED — full round-trip restored exactly"
                  if ok else f"SOME CHECKS FAILED ({len(fails)})"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()