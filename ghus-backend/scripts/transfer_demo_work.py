"""Bring the real work of the local demo database to the shared one, through the approved writers.

    python -m scripts.transfer_demo_work admit --run RUN_ID [--live]
    python -m scripts.transfer_demo_work facts --mapping FILE [--live]

GHUS, 2026-10-29. The platform's ``scripts/transfer_demo_actors.py`` stages the
11 real organizations made locally through the Data Feed. Then:

``admit``  applies the Review decision "new" to each staged organization of
           that import (``agents.review.admission.apply_review_decision``):
           promotion creates it Parked with a ``verify_actor`` item - it needs
           review, and appears in everyone's Review. A record entity
           resolution matches stays in Review, and the result says so.
``facts``  replays each organization's found Light Pull facts from the demo
           database through ``agents.enrichment.decisions.append_actor_fact``,
           with the page each was read on and the date it was read. Facts
           promotion writes itself (identity, description, location, website,
           category, sector, hub, parent) are not replayed; a Deep Pull fact is
           not either, since it needs GHUS verification first.

DATABASE_URL is the target. The demo database is read read-only. Dry run by
default: everything runs and is rolled back.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEMO = "postgresql://ghus_test@127.0.0.1:55432/ghus_v2_demo_test"
REVIEWER = "Ismail Sabbar"
NOTE = ("Transferred from the local demo database on 2026-10-29: admitted for review "
        "(Parked, needs verification).")
CREATED_BY = "transfer:demo_2026-10-29"
# Written by promotion at admission, or not yet allowed (Deep Pull).
NOT_REPLAYED = {"actor_category_type", "description", "hub_assignment", "location",
                "official_identity", "parent_connection", "sector_topic", "website"}


def topic_map(demo, target) -> dict[str, str]:
    """Demo topic id -> target topic id, by topic code (the demo database made its own)."""
    theirs = {code: str(tid) for code, tid in target.execute("select code, topic_id from topic")}
    return {str(tid): theirs[code] for code, tid in demo.execute("select code, topic_id from topic")
            if code in theirs}


def translate(value, ids: dict[str, str]):
    """Replace every demo id ``ids`` knows, in a column, a list or JSON."""
    if isinstance(value, str):
        for old, new in ids.items():
            if old in value:
                value = value.replace(old, new)
        return value
    if hasattr(value, "hex") and str(value) in ids:            # uuid.UUID
        return ids[str(value)]
    if isinstance(value, list):
        return [translate(v, ids) for v in value]
    if isinstance(value, dict):
        return {k: translate(v, ids) for k, v in value.items()}
    return value


def target_engine():
    import os

    url = os.environ.get("DATABASE_URL", "").replace("postgresql://", "postgresql+psycopg://", 1)
    if not url:
        raise SystemExit("DATABASE_URL (the target database) is required")
    return create_engine(url)


def admit(run_id: str, *, live: bool) -> list[dict]:
    from agents.review.admission import AdmissionConflict, apply_review_decision

    engine = target_engine()
    out = []
    with Session(engine) as session:
        rows = session.execute(text(
            "SELECT candidate_id::text, record_preview->>'name' FROM search_candidate "
            "WHERE run_id = CAST(:run AS uuid) AND review_status = 'pending' ORDER BY 2"),
            {"run": run_id}).all()
    for candidate_id, name in rows:
        decision = {"entity_type": "actor", "decision_kind": "new",
                    "source_ref": {"table": "search_candidate", "id": candidate_id},
                    "reviewer": REVIEWER, "notes": NOTE,
                    "idempotency_key": f"demo-transfer-2026-10-29:{candidate_id}"}
        with Session(engine) as session:
            try:
                result = apply_review_decision(session, decision) if live else _dry(session, decision)
                out.append({"name": name, "candidate_id": candidate_id,
                            "actor_id": result.get("canonical_entity_id"),
                            "action": result.get("promotion_action") or result.get("status")})
            except AdmissionConflict as exc:
                out.append({"name": name, "candidate_id": candidate_id, "action": "stays_in_review",
                            "reason": str(exc)})
    return out


def _dry(session, decision):
    """The same admission, rolled back: what it would create."""
    from agents.review import admission

    original = session.begin
    # Admission opens and commits its own transaction; here that is a savepoint
    # inside one outer transaction, which is rolled back.
    session.begin = lambda nested=False: original(nested=True)
    try:
        return admission.apply_review_decision(session, decision)
    finally:
        session.begin = original
        session.rollback()


CURRENT_FOUND = (
    "SELECT f.actor_id::text, f.topic_id::text, f.fact_type, f.fact_key, f.layer, f.fact_value, "
    "f.confidence, f.retrieved_at, s.url, f.collection_state, NULL::text "
    "FROM actor_fact_current_pointer p JOIN actor_fact f USING (actor_fact_id) "
    "JOIN source s ON s.source_id = f.source_id "
    "WHERE f.actor_id = ANY(%s::uuid[]) AND f.collection_state = 'found' "
    "AND f.fact_type = 'light_pull' ORDER BY f.actor_id, f.fact_key")
# What each copied update run wrote, in the order it wrote it, with its request.
BY_REQUEST = (
    "SELECT f.actor_id::text, f.topic_id::text, f.fact_type, f.fact_key, f.layer, f.fact_value, "
    "f.confidence, f.retrieved_at, s.url, f.collection_state, f.request_id::text "
    "FROM actor_fact f JOIN source s ON s.source_id = f.source_id "
    "WHERE f.request_id = ANY(%s::uuid[]) AND f.actor_id = ANY(%s::uuid[]) "
    "AND f.fact_type = 'light_pull' ORDER BY f.created_at, f.actor_fact_id")


def facts(mapping: dict[str, str], *, live: bool, requests: list[str] | None = None) -> list[dict]:
    """Replay demo facts onto the target actors, through the approved fact writer.

    Without ``requests``: each actor's current found facts. With them: every
    fact those update runs wrote, in order, carrying their request.
    """
    import os

    from agents.common.facts import ActorFactWrite
    from agents.enrichment.decisions import append_actor_fact

    target = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(DEMO, options="-c default_transaction_read_only=on") as demo, \
            psycopg.connect(target, options="-c default_transaction_read_only=on") as tgt:
        topics = topic_map(demo, tgt)
        rows = demo.execute(BY_REQUEST, (requests, list(mapping))) if requests else \
            demo.execute(CURRENT_FOUND, (list(mapping),))
        rows = rows.fetchall()
    engine = target_engine()
    out = []
    with Session(engine) as session:
        for (demo_id, topic_id, fact_type, key, layer, value, confidence, read_at, url,
             state, request_id) in rows:
            if key in NOT_REPLAYED or (key == "um6p_ocp_connection" and isinstance(value, dict)
                                       and value.get("state")):
                continue
            if topic_id not in topics:
                out.append({"actor_id": demo_id, "field": key, "error": "topic not in target"})
                continue
            savepoint = session.begin_nested()
            try:
                fact_id = append_actor_fact(session, ActorFactWrite(
                    actor_id=mapping[demo_id], topic_id=topics[topic_id], field_key=key,
                    fact_type=fact_type, layer=int(layer),
                    value=translate(value, {**topics, **mapping}) if state == "found" else None,
                    collection_state=state, source_url=url, source_origin="newly_found",
                    date_read=read_at, confidence=confidence or "medium", created_by=CREATED_BY,
                    request_id=request_id), live=True)
                savepoint.commit()
                out.append({"actor_id": mapping[demo_id], "field": key, "fact_id": fact_id})
            except Exception as exc:  # noqa: BLE001 - one fact must not stop the others
                savepoint.rollback()
                out.append({"actor_id": mapping[demo_id], "field": key,
                            "error": f"{type(exc).__name__}: {exc}"[:200]})
        if live:
            session.commit()
        else:
            session.rollback()
    return out


# Staging and ledger rows, parents first. Nothing canonical: these are what a
# discovery run, the Data Feed or a request runner writes before Review.
STAGING_ORDER = ("actor_update_subscription", "collection_request", "collection_run",
                 "actor_update_subscription_run", "scrape_run", "raw_document", "source",
                 "staged_record",
                 "search_candidate", "event_review_queue", "person_review_queue")
KEYS = {"actor_update_subscription": "actor_update_subscription_id",
        "collection_request": "collection_request_id", "collection_run": "collection_run_id",
        "actor_update_subscription_run": "collection_run_id", "scrape_run": "run_id",
        "raw_document": "raw_document_id",
        "source": "source_id", "staged_record": "staged_record_id",
        "search_candidate": "candidate_id", "event_review_queue": "event_review_id",
        "person_review_queue": "person_review_id"}


def staging(selection: dict[str, list[str]], *, live: bool,
            actor_ids: dict[str, str] | None = None) -> dict:
    """Copy the selected staging and ledger rows, keeping their own ids.

    Topic ids are translated to the target's (by code), and the demo ids of
    organizations already admitted to the target to their new ids. A row
    already in the target is left alone (ON CONFLICT DO NOTHING). A reference
    to an event or person the target does not have is cleared, so a queue item
    still waits in Review without pointing at nothing.
    """
    from psycopg.types.json import Jsonb

    import os
    target = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    out = {}
    with psycopg.connect(DEMO, options="-c default_transaction_read_only=on") as demo, \
            psycopg.connect(target) as tgt:
        ids = {**topic_map(demo, tgt), **(actor_ids or {})}
        for table in STAGING_ORDER:
            wanted = selection.get(table) or []
            if not wanted:
                continue
            key = KEYS[table]
            json_cols = {r[0] for r in tgt.execute(
                "select column_name from information_schema.columns where table_schema='public' "
                "and table_name=%s and data_type in ('json','jsonb')", (table,))}
            target_cols = {r[0] for r in tgt.execute(
                "select column_name from information_schema.columns where table_schema='public' "
                "and table_name=%s", (table,))}
            cur = demo.execute(f"select * from {table} where {key} = any(%s::uuid[])", (wanted,))
            cols = [d.name for d in cur.description if d.name in target_cols]
            rows = [{name: translate(value, ids) for name, value in
                     zip([d.name for d in cur.description], r)} for r in cur.fetchall()]
            for row in rows:
                for ref, parent in (("candidate_event_id", "event"), ("candidate_person_id", "person")):
                    if row.get(ref) and not tgt.execute(
                            f"select 1 from {parent} where {parent}_id = %s", (row[ref],)).fetchone():
                        row[ref] = None
            placeholders = ", ".join(["%s"] * len(cols))
            sql = (f"insert into {table} ({', '.join(cols)}) values ({placeholders}) "
                   f"on conflict do nothing")
            inserted = 0
            for row in rows:
                values = [Jsonb(row[c]) if c in json_cols and row[c] is not None else row[c]
                          for c in cols]
                inserted += tgt.execute(sql, values).rowcount
            out[table] = {"selected": len(wanted), "found_in_demo": len(rows), "inserted": inserted}
        if live:
            tgt.commit()
        else:
            tgt.rollback()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("admit")
    one.add_argument("--run", required=True)
    one.add_argument("--live", action="store_true")
    two = sub.add_parser("facts")
    two.add_argument("--mapping", required=True, type=Path,
                     help="JSON {demo actor id: target actor id}")
    two.add_argument("--live", action="store_true")
    two.add_argument("--selection", type=Path,
                     help="replay what these copied update runs wrote (their collection_request ids)")
    three = sub.add_parser("staging")
    three.add_argument("--selection", required=True, type=Path,
                       help="JSON {table: [ids]} of staging and ledger rows to copy")
    three.add_argument("--mapping", type=Path, help="JSON {demo actor id: target actor id}")
    three.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "admit":
        result = admit(args.run, live=args.live)
    elif args.command == "staging":
        mapping = json.loads(args.mapping.read_text(encoding="utf-8")) if args.mapping else {}
        result = staging(json.loads(args.selection.read_text(encoding="utf-8")), live=args.live,
                         actor_ids=mapping)
    else:
        requests = (json.loads(args.selection.read_text(encoding="utf-8"))["collection_request"]
                    if args.selection else None)
        result = facts(json.loads(args.mapping.read_text(encoding="utf-8")), live=args.live,
                       requests=requests)
    print(json.dumps({"live": args.live, "results": result}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
