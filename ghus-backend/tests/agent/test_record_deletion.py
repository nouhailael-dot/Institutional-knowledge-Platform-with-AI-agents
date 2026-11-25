"""Record deletion with 30-day retention, restore and permanent purge (GHUS policy,
17 Nov 2026; migration 710).

Runs on an isolated copy of production (V2_TEST_DATABASE_URL, a local *_test
database restored from a Supabase backup, e.g. ghus_phase7_prodcopy_test) inside
ONE transaction that is always rolled back: migrations 700 and 710 are applied
inside it, so the database is left exactly as it was. 710 refuses a database
whose guards or actor_read differ from production; on such a database (the old
demo copy) these tests are skipped and say so. Expiry is simulated by deletions
dated 31 days ago.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from agents.enrichment.decisions import (DeletionError, delete_record, pending_deletion, purge_record,
                                         restore_record)
from agents.review import purge as purge_job

DB = os.environ.get("V2_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="V2_TEST_DATABASE_URL is required")
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations/proposed/deferred"


def _sql_body(name: str) -> str:
    body = (MIGRATIONS / name).read_text(encoding="utf-8")
    return re.sub(r"^\s*(BEGIN|COMMIT);\s*$", "", body, flags=re.MULTILINE)


@pytest.fixture
def conn():
    parts = urlsplit(DB.replace("postgresql+psycopg://", "postgresql://"))
    assert parts.hostname in {"127.0.0.1", "localhost"} and parts.path.rstrip("/").endswith("_test")
    engine = create_engine(DB)
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS auth")
            connection.exec_driver_sql("CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY, email text)")
            raw = connection.connection.driver_connection     # SQL run as written (no placeholders)
            if not connection.execute(text("SELECT to_regclass('compass.user_profile')")).scalar():
                raw.execute(_sql_body("700_compass_accounts.sql"))
            # A copy restored from a recent backup already has 710: test it as it is.
            if not connection.execute(text("SELECT to_regclass('compass.deleted_record')")).scalar():
                savepoint = connection.begin_nested()
                try:
                    raw.execute(_sql_body("710_record_deletion_retention.sql"))
                except Exception as exc:  # noqa: BLE001
                    savepoint.rollback()
                    if "from production as reviewed" in str(exc):
                        pytest.skip("710 targets production's schema: set V2_TEST_DATABASE_URL to a restored "
                                    "copy of the latest Supabase backup (e.g. ghus_phase7_prodcopy_test)")
                    raise
            yield connection
        finally:
            outer.rollback()
    engine.dispose()


def _person(conn, name="Del Eter") -> str:
    uid = str(uuid.uuid4())
    conn.execute(text("INSERT INTO auth.users (id, email) VALUES (:id, :e)"), {"id": uid, "e": f"{uid[:8]}@example.test"})
    conn.execute(text("INSERT INTO compass.user_profile (user_id, email, full_name, role_code, status) "
                      "VALUES (:id, :e, :n, 'editor', 'active')"),
                 {"id": uid, "e": f"{uid[:8]}@example.test", "n": name})
    return uid


def _busy_actor(conn) -> str:
    """A real organization with history: facts and verification decisions."""
    return conn.execute(text("""
        SELECT a.actor_id::text FROM actor_read a
         WHERE a.merged_into_actor_id IS NULL
           AND NOT EXISTS (SELECT 1 FROM actor m WHERE m.merged_into_actor_id = a.actor_id)
         ORDER BY (SELECT count(*) FROM actor_fact f WHERE f.actor_id = a.actor_id) DESC LIMIT 1""")).scalar()


def _expire(conn, deletion_id: str) -> None:
    """Simulated time: re-date the deletion 31 days back (a fresh row, as if made then)."""
    row = conn.execute(text("SELECT * FROM compass.deleted_record WHERE deletion_id = :id"),
                       {"id": deletion_id}).mappings().one()
    conn.exec_driver_sql("ALTER TABLE compass.deleted_record DISABLE TRIGGER deleted_record_guard")
    conn.execute(text("UPDATE compass.deleted_record SET deleted_at = now() - interval '31 days', "
                      "purge_after = now() - interval '1 day' WHERE deletion_id = :id"), {"id": deletion_id})
    conn.exec_driver_sql("ALTER TABLE compass.deleted_record ENABLE TRIGGER deleted_record_guard")
    assert row["entity_id"]


def _count(conn, sql: str, **params) -> int:
    return conn.execute(text(sql), params).scalar()


# --- delete and restore -------------------------------------------------------------------------

def test_delete_hides_at_once_keeps_everything_and_sets_a_30_day_deadline(conn):
    actor, by = _busy_actor(conn), _person(conn)
    facts = _count(conn, "SELECT count(*) FROM actor_fact WHERE actor_id = CAST(:a AS uuid)", a=actor)
    decisions = _count(conn, "SELECT count(*) FROM actor_verification_event WHERE actor_id = CAST(:a AS uuid)", a=actor)
    status = conn.execute(text("SELECT status FROM actor WHERE actor_id = CAST(:a AS uuid)"), {"a": actor}).scalar()
    out = delete_record(conn, entity_type="actor", entity_id=actor, deleted_by=by, reason="Duplicate", live=True)
    assert out["written"] and (out["purge_after"] - out["deleted_at"]).days == 30
    assert _count(conn, "SELECT count(*) FROM actor_read WHERE actor_id = CAST(:a AS uuid)", a=actor) == 0
    assert _count(conn, "SELECT count(*) FROM actor WHERE actor_id = CAST(:a AS uuid)", a=actor) == 1
    assert _count(conn, "SELECT count(*) FROM actor_fact WHERE actor_id = CAST(:a AS uuid)", a=actor) == facts
    assert _count(conn, "SELECT count(*) FROM actor_verification_event WHERE actor_id = CAST(:a AS uuid)",
                  a=actor) == decisions                                  # history unchanged
    assert conn.execute(text("SELECT status FROM actor WHERE actor_id = CAST(:a AS uuid)"), {"a": actor}).scalar() == status
    snap = conn.execute(text("SELECT snapshot FROM compass.deleted_record WHERE deletion_id = :d"),
                        {"d": out["deletion_id"]}).scalar()
    assert snap["row"]["actor_id"] == actor and snap["links"].get("actor_fact.actor_id") == facts
    with pytest.raises(DeletionError, match="Already deleted"):
        delete_record(conn, entity_type="actor", entity_id=actor, deleted_by=by, live=True)


def test_restore_within_30_days_brings_it_back_unchanged(conn):
    actor, by, restorer = _busy_actor(conn), _person(conn), _person(conn, "Re Storer")
    deletion = delete_record(conn, entity_type="actor", entity_id=actor, deleted_by=by, live=True)["deletion_id"]
    restored = restore_record(conn, deletion_id=deletion, restored_by=restorer, live=True)
    assert restored["written"] and restored["entity_id"] == actor
    assert _count(conn, "SELECT count(*) FROM actor_read WHERE actor_id = CAST(:a AS uuid)", a=actor) == 1
    row = conn.execute(text("SELECT restored_by::text, restored_at IS NOT NULL FROM compass.deleted_record "
                            "WHERE deletion_id = :d"), {"d": deletion}).one()
    assert tuple(row) == (restorer, True)
    with pytest.raises(DeletionError, match="already restored"):
        restore_record(conn, deletion_id=deletion, restored_by=restorer, live=True)
    again = delete_record(conn, entity_type="actor", entity_id=actor, deleted_by=by, live=True)
    assert again["deletion_id"] != deletion                              # deletable again, new record


def test_restore_after_30_days_is_refused(conn):
    actor, by = _busy_actor(conn), _person(conn)
    deletion = delete_record(conn, entity_type="actor", entity_id=actor, deleted_by=by, live=True)["deletion_id"]
    _expire(conn, deletion)
    with pytest.raises(DeletionError, match="30 days ended"):
        restore_record(conn, deletion_id=deletion, restored_by=by, live=True)


def test_a_merged_duplicate_cannot_be_deleted_and_one_deletion_at_a_time(conn):
    by = _person(conn)
    merged = conn.execute(text("SELECT actor_id::text FROM actor WHERE merged_into_actor_id IS NOT NULL LIMIT 1")).scalar()
    if merged:
        with pytest.raises(DeletionError, match="merged into another"):
            delete_record(conn, entity_type="actor", entity_id=merged, deleted_by=by, live=True)
    actor = _busy_actor(conn)
    delete_record(conn, entity_type="actor", entity_id=actor, deleted_by=by, live=True)
    with pytest.raises(DBAPIError, match="deleted_record_pending_key"):
        with conn.begin_nested():
            conn.execute(text("INSERT INTO compass.deleted_record (entity_type, entity_id, name, snapshot, deleted_by, "
                              "purge_after) VALUES ('actor', CAST(:a AS uuid), 'x', '{}', CAST(:b AS uuid), "
                              "now() + interval '30 days')"), {"a": actor, "b": by})


# --- the guards ------------------------------------------------------------------------------------

def test_the_guards_still_refuse_every_other_delete_and_every_update(conn):
    actor, by = _busy_actor(conn), _person(conn)
    deletion = delete_record(conn, entity_type="actor", entity_id=actor, deleted_by=by, live=True)["deletion_id"]
    with pytest.raises(DBAPIError, match="never deleted"):
        with conn.begin_nested():
            conn.execute(text("DELETE FROM actor WHERE actor_id = CAST(:a AS uuid)"), {"a": actor})
    with pytest.raises(DBAPIError, match="never deleted"):                # declared, but not due yet
        with conn.begin_nested():
            conn.execute(text("SELECT set_config('ghus.permanent_delete', :d, true)"), {"d": deletion})
            conn.execute(text("DELETE FROM actor WHERE actor_id = CAST(:a AS uuid)"), {"a": actor})
    _expire(conn, deletion)
    with pytest.raises(DBAPIError, match="append-only"):                  # the door is DELETE only
        with conn.begin_nested():
            conn.execute(text("SELECT set_config('ghus.permanent_delete', :d, true)"), {"d": deletion})
            conn.execute(text("UPDATE actor_fact SET confidence = 'high' WHERE actor_id = CAST(:a AS uuid)"),
                         {"a": actor})
    with pytest.raises(DBAPIError, match="kept permanently"):
        with conn.begin_nested():
            conn.execute(text("DELETE FROM compass.deleted_record WHERE deletion_id = :d"), {"d": deletion})


# --- the purge ----------------------------------------------------------------------------------------

def test_purge_waits_30_days_then_removes_the_record_and_only_its_own_rows(conn):
    actor, by = _busy_actor(conn), _person(conn)
    others_before = _count(conn, "SELECT count(*) FROM actor WHERE actor_id <> CAST(:a AS uuid)", a=actor)
    other_facts = _count(conn, "SELECT count(*) FROM actor_fact WHERE actor_id <> CAST(:a AS uuid)", a=actor)
    request = conn.execute(text("SELECT collection_request_id::text FROM collection_request LIMIT 1")).scalar()
    if request:
        conn.execute(text("UPDATE collection_request SET actor_id = CAST(:a AS uuid) WHERE collection_request_id = "
                          "CAST(:r AS uuid)"), {"a": actor, "r": request})
    deletion = delete_record(conn, entity_type="actor", entity_id=actor, deleted_by=by, live=True)["deletion_id"]
    assert purge_record(conn, deletion_id=deletion, live=True)["outcome"] == "not_due"
    _expire(conn, deletion)
    plan = purge_record(conn, deletion_id=deletion, live=False)
    assert plan["outcome"] == "would_purge" and plan["rows"]["actor"] == 1
    assert _count(conn, "SELECT count(*) FROM actor WHERE actor_id = CAST(:a AS uuid)", a=actor) == 1   # dry run
    done = purge_record(conn, deletion_id=deletion, live=True)
    assert done["outcome"] == "purged" and done["rows"] == plan["rows"]
    assert _count(conn, "SELECT count(*) FROM actor WHERE actor_id = CAST(:a AS uuid)", a=actor) == 0
    assert _count(conn, "SELECT count(*) FROM actor_fact WHERE actor_id = CAST(:a AS uuid)", a=actor) == 0
    assert _count(conn, "SELECT count(*) FROM actor_verification_event WHERE actor_id = CAST(:a AS uuid)", a=actor) == 0
    assert _count(conn, "SELECT count(*) FROM actor WHERE actor_id <> CAST(:a AS uuid)", a=actor) == others_before
    assert _count(conn, "SELECT count(*) FROM actor_fact WHERE actor_id <> CAST(:a AS uuid)", a=actor) == other_facts
    if request:                                                           # the run ledger stays, detached
        assert _count(conn, "SELECT count(*) FROM collection_request WHERE collection_request_id = CAST(:r AS uuid) "
                            "AND actor_id IS NULL", r=request) == 1
    tomb = conn.execute(text("SELECT purged_at IS NOT NULL, snapshot, purge_report FROM compass.deleted_record "
                             "WHERE deletion_id = :d"), {"d": deletion}).one()
    assert tomb[0] and "row" not in tomb[1] and tomb[2] == done["rows"]   # the minimum kept
    assert purge_record(conn, deletion_id=deletion, live=True)["outcome"] == "already_purged"
    with pytest.raises(DeletionError, match="permanently deleted"):
        restore_record(conn, deletion_id=deletion, restored_by=by, live=True)
    with pytest.raises(DBAPIError, match="never deleted"):                # the door closed again
        with conn.begin_nested():
            conn.execute(text("DELETE FROM actor WHERE actor_id = (SELECT actor_id FROM actor LIMIT 1)"))


def test_a_purged_person_leaves_no_personal_data(conn):
    person = conn.execute(text("SELECT person_id::text FROM person LIMIT 1")).scalar()
    if person is None:
        person = str(uuid.uuid4())
        conn.execute(text("INSERT INTO person (person_id, full_name) VALUES (CAST(:p AS uuid), 'Ana Example')"),
                     {"p": person})
    by = _person(conn)
    deletion = delete_record(conn, entity_type="person", entity_id=person, deleted_by=by, live=True)["deletion_id"]
    _expire(conn, deletion)
    assert purge_record(conn, deletion_id=deletion, live=True)["outcome"] == "purged"
    name, snap = conn.execute(text("SELECT name, snapshot FROM compass.deleted_record WHERE deletion_id = :d"),
                              {"d": deletion}).one()
    assert name == "Deleted person" and "full_name" not in json.dumps(snap)


def test_an_unplanned_link_blocks_the_purge_instead_of_guessing(conn):
    actor, by = _busy_actor(conn), _person(conn)
    # Between 720 and 800, actor was a stand-in view over organization: keys point at the table.
    is_table = conn.execute(text("SELECT relkind = 'r' FROM pg_class WHERE oid = to_regclass('public.actor')")).scalar()
    target = "actor(actor_id)" if is_table else "organization(organization_id)"
    conn.exec_driver_sql(f"CREATE TABLE public.tmp_new_link (actor_id uuid REFERENCES {target})")
    deletion = delete_record(conn, entity_type="actor", entity_id=actor, deleted_by=by, live=True)["deletion_id"]
    _expire(conn, deletion)
    out = purge_record(conn, deletion_id=deletion, live=True)
    assert out["outcome"] == "blocked" and "tmp_new_link.actor_id" in out["reason"]
    assert _count(conn, "SELECT count(*) FROM actor WHERE actor_id = CAST(:a AS uuid)", a=actor) == 1


def test_nothing_attaches_to_a_record_awaiting_deletion(conn):
    actor, by = _busy_actor(conn), _person(conn)
    delete_record(conn, entity_type="actor", entity_id=actor, deleted_by=by, live=True)
    pending = pending_deletion(conn, "actor", actor)
    assert pending and pending["purge_after"] > pending["deleted_at"]
    from agents.common.deletions import pending_deletion_ids
    assert actor in pending_deletion_ids(conn, "actor")


def test_the_cleanup_job_is_dry_by_default_retry_safe_and_one_at_a_time(conn):
    by = _person(conn)
    actors = conn.execute(text("""
        SELECT a.actor_id::text FROM actor a WHERE a.merged_into_actor_id IS NULL
           AND NOT EXISTS (SELECT 1 FROM actor m WHERE m.merged_into_actor_id = a.actor_id) LIMIT 2""")).scalars().all()
    ids = []
    for actor in actors:
        d = delete_record(conn, entity_type="actor", entity_id=actor, deleted_by=by, live=True)["deletion_id"]
        _expire(conn, d)
        ids.append(d)
    factory = sessionmaker(bind=conn, join_transaction_mode="create_savepoint")
    dry = purge_job.run(factory, live=False)
    assert dry["outcomes"] == {"would_purge": len(ids)}
    assert all(_count(conn, "SELECT count(*) FROM actor WHERE actor_id = CAST(:a AS uuid)", a=a) == 1 for a in actors)
    live = purge_job.run(factory, live=True)
    assert live["outcomes"] == {"purged": len(ids)}
    again = purge_job.run(factory, live=True)
    assert again["due"] == 0                                             # nothing left: safe to retry
    assert purge_job.due_deletions(conn, 10) == []


def test_the_purge_policy_covers_every_link_in_this_database(conn):
    """Every foreign key into an organization, person, event or hub (and into the rows
    removed with it) is in the policy, so no purge here would block or surprise."""
    from sqlalchemy.orm import Session

    from agents.enrichment.decisions import DELETABLE, _unplanned_links

    session = Session(bind=conn)
    assert {kind: _unplanned_links(session, kind) for kind in DELETABLE} == \
        {kind: [] for kind in DELETABLE}
