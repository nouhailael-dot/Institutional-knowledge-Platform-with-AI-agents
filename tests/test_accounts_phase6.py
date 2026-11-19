"""Record deletion with 30-day retention and recovery (multi-user Compass, Phase 6).

The platform side: who may delete and restore, the confirmation, hiding a deleted
record from every active view at once, the Pending Deletion listing (Dashboard
card and page; separate from Review's Rejected), the deadline, refusal after it, two
people acting at once, the audit and ownership trail, and the scheduled cleanup.

The deletion table is migration 710's own compass section, applied to the
isolated local database GHUS_ACCOUNTS_TEST_DATABASE_URL. The backend's approved
writer is replaced by a stand-in with the same rules (the real writer, the purge
and the guards are tested in ghus-backend/tests/agent/test_record_deletion.py).
Expiry is simulated by back-dating a deletion. Nothing reaches Supabase.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app as app_module
from backend import accounts_admin, accounts_routes
from backend.purge_scheduler import PurgeScheduler, purge_mode
from src.accounts.permissions import DEFAULT_ROLES, permission_for
from src.accounts.store import AccountsStore
from src.accounts.supabase_auth import AuthSettings, SupabaseAuth
from src.review import AdmissionBridgeError
from tests.accounts_fakes import JWT_SECRET, SERVICE_KEY, FakeGoTrue
from tests.test_accounts import _reset_schema

DB = os.environ.get("GHUS_ACCOUNTS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="GHUS_ACCOUNTS_TEST_DATABASE_URL is required")
SITE = "http://testserver"
H = {"Origin": SITE}
PASSWORD = "a long passphrase for compass 7"
PG = (DB or "").replace("postgresql+psycopg://", "postgresql://")
MIGRATION_710 = (Path(__file__).resolve().parents[1] / "ghus-backend" / "migrations" / "proposed"
                 / "deferred" / "710_record_deletion_retention.sql")


def _sql(query, *params):
    with psycopg.connect(PG, autocommit=True) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else None


def _apply_710_compass_part() -> None:
    """Migration 710's compass section (table, indexes, guard), exactly as written. Its
    public part (the Architecture V2 guards, actor_read) needs the live-like schema
    and is tested on the backend's demo database."""
    body = MIGRATION_710.read_text(encoding="utf-8")
    start = body.index("CREATE TABLE compass.deleted_record")
    end = body.index("CREATE OR REPLACE FUNCTION public.ghus_guard_no_delete")
    with psycopg.connect(PG, autocommit=True) as conn:
        conn.execute(body[start:end])


class DeletionWriter:
    """Stand-in for decisions.delete_record / restore_record behind the admission bridge:
    the same table, the same rules, the account id the platform sends."""

    configured = True

    def __init__(self, names: dict[str, str]):
        self.names = names
        self.calls: list[dict] = []

    def apply(self, decision: dict) -> dict:
        self.calls.append(decision)
        user_id = str(uuid.UUID(decision["user_id"]))
        with psycopg.connect(PG, autocommit=True) as conn:
            if decision["decision_kind"] == "delete_record":
                entity_id = decision["entity_id"]
                try:
                    row = conn.execute("""
                        INSERT INTO compass.deleted_record (entity_type, entity_id, name, snapshot, reason,
                                                            deleted_by, purge_after)
                        VALUES (%s, %s::uuid, %s, %s::jsonb, %s, %s::uuid, now() + interval '30 days')
                        RETURNING deletion_id::text, deleted_at, purge_after
                    """, (decision["entity_type"], entity_id, self.names.get(entity_id, "Record"),
                          json.dumps({"row": {"country": "United States", "website": "https://lab.example.test"},
                                      "links": {"actor_fact.actor_id": 4, "hub_actor.actor_id": 1}}),
                          decision.get("reason") or None, user_id)).fetchone()
                except psycopg.errors.UniqueViolation as exc:
                    raise AdmissionBridgeError("GHUS rejected the decision; no local final decision was recorded. "
                                               "Already deleted; it can be restored from Review Results.") from exc
                return {"decision_kind": "delete_record", "status": "applied", "written": True,
                        "deletion_id": row[0], "name": self.names.get(entity_id, "Record"),
                        "deleted_at": str(row[1]), "purge_after": str(row[2])}
            row = conn.execute("""
                UPDATE compass.deleted_record SET restored_at = now(), restored_by = %s::uuid
                 WHERE deletion_id = %s::uuid AND restored_at IS NULL AND purged_at IS NULL
                   AND purge_after > now()
             RETURNING entity_type, entity_id::text, name
            """, (user_id, decision["deletion_id"])).fetchone()
            if row is None:
                raise AdmissionBridgeError("GHUS rejected the decision; no local final decision was recorded. "
                                           "The 30 days are over (or it was already restored).")
            return {"decision_kind": "restore_record", "status": "applied", "written": True,
                    "deletion_id": decision["deletion_id"], "entity_type": row[0], "entity_id": row[1],
                    "name": row[2]}


@pytest.fixture
def world(monkeypatch):
    _reset_schema(DB)
    _apply_710_compass_part()
    gotrue = FakeGoTrue()
    store = AccountsStore(DB)
    accounts_routes.configure(
        auth=SupabaseAuth(AuthSettings(url="https://auth.example.test", anon_key="anon-test-key",
                                       service_role_key=SERVICE_KEY, jwt_secret=JWT_SECRET),
                          transport=gotrue.transport()),
        store=store)
    ids = {name: str(uuid.uuid4()) for name in ("Water Lab", "Delta Summit", "Ada Byron", "Desert Hub")}
    names = {v: k for k, v in ids.items()}
    writer = DeletionWriter(names)
    monkeypatch.setattr(app_module, "review_admission_bridge", lambda: writer)
    monkeypatch.setattr(app_module.browse, "load_actors", lambda: [
        {"id": ids["Water Lab"], "name": "Water Lab", "hubs": [], "status": "verified"}])
    monkeypatch.setattr(app_module.browse, "load_events", lambda: [
        {"id": ids["Delta Summit"], "name": "Delta Summit", "event_type": "conference"}])
    monkeypatch.setattr(app_module.browse, "load_people", lambda: [
        {"id": ids["Ada Byron"], "name": "Ada Byron", "topics": [], "states": [], "organizations": []}])
    monkeypatch.setattr(app_module.browse, "load_hubs", lambda: [{"hub_id": ids["Desert Hub"], "name": "Desert Hub"}])
    monkeypatch.setattr(app_module.browse, "hub_columns", lambda: ["hub_id", "name"])
    monkeypatch.setattr(app_module.browse, "actor_filter_options", lambda rows: {})
    monkeypatch.setattr(app_module.browse, "people_filter_options", lambda rows: {})
    monkeypatch.setattr(app_module, "_sectors_by_hub", lambda: {})
    for cached in (app_module._actors, app_module._events, app_module._people, app_module._hubs):
        cached.cache_clear()
    app = FastAPI()
    app.include_router(accounts_routes.router)
    app.include_router(accounts_admin.router)
    for method, path, handler in [
        ("POST", "/api/browse/{kind}/{record_id}/delete", app_module.directory_delete),
        ("GET", "/api/review/deleted", app_module.review_deleted),
        ("POST", "/api/review/deleted/{deletion_id}/restore", app_module.review_restore_deleted),
        ("GET", "/api/browse/actors", app_module.browse_actors),
        ("GET", "/api/browse/actors/{actor_id}/profile", app_module.browse_actor_profile),
        ("GET", "/api/browse/events", app_module.browse_events),
        ("GET", "/api/browse/people", app_module.browse_people),
        ("GET", "/api/browse/hubs", app_module.browse_hubs),
    ]:
        app.add_api_route(path, handler, methods=[method])
    app.middleware("http")(accounts_routes.require_account)
    yield SimpleNamespace(app=app, gotrue=gotrue, store=store, ids=ids, writer=writer)
    accounts_routes.configure()
    for cached in (app_module._actors, app_module._events, app_module._people, app_module._hubs):
        cached.cache_clear()


def _member(world, role="editor", name=None) -> dict:
    email = f"{uuid.uuid4().hex[:10]}@example.test"
    uid = world.gotrue.add_user(email, PASSWORD)
    _sql("INSERT INTO auth.users (id, email) VALUES (%s, %s)", uid, email)
    name = name or f"Synthetic {role} {email[:4]}"
    _sql("INSERT INTO compass.user_profile (user_id, email, full_name, role_code, status) "
         "VALUES (%s, %s, %s, %s, 'active')", uid, email, name, role)
    return {"id": uid, "email": email, "name": name}


def _client(world, person) -> TestClient:
    client = TestClient(world.app, base_url=SITE)
    assert client.post("/api/auth/login", json={"email": person["email"], "password": PASSWORD},
                       headers=H).status_code == 200
    return client


def _delete(client, kind, record_id, reason="", confirm=True):
    return client.post(f"/api/browse/{kind}/{record_id}/delete", json={"reason": reason, "confirm": confirm},
                       headers=H)


def _restore(client, deletion_id, confirm=True):
    return client.post(f"/api/review/deleted/{deletion_id}/restore", json={"confirm": confirm}, headers=H)


# ------------------------------------------------------------------ permissions
def test_admins_and_editors_may_delete_and_restore_viewers_may_not(world):
    assert "records.delete_permanent" in DEFAULT_ROLES["admin"]
    assert "records.delete_permanent" in DEFAULT_ROLES["editor"]
    assert "records.delete_permanent" not in DEFAULT_ROLES["viewer"]
    assert permission_for("POST", "/api/browse/people/x/delete") == "records.delete_permanent"
    assert permission_for("POST", "/api/review/deleted/x/restore") == "records.delete_permanent"
    assert permission_for("GET", "/api/review/deleted") == "records.delete_permanent"

    viewer = _client(world, _member(world, "viewer"))
    refused = _delete(viewer, "events", world.ids["Delta Summit"])
    assert refused.status_code == 403
    assert viewer.get("/api/review/deleted").status_code == 403
    assert world.writer.calls == []                         # never reached the writer
    denied = _sql("SELECT detail->>'needed' FROM compass.audit_event WHERE action = 'access.denied'")
    assert ("records.delete_permanent",) in denied

    admin = _client(world, _member(world, "admin"))
    assert _delete(admin, "events", world.ids["Delta Summit"]).status_code == 200
    deletion_id = admin.get("/api/review/deleted").json()["deleted"][0]["deletion_id"]
    assert _restore(viewer, deletion_id).status_code == 403
    editor = _client(world, _member(world, "editor"))
    assert _restore(editor, deletion_id).status_code == 200


def test_pending_deletion_is_for_deleters_only_not_for_every_reviewer(world):
    """Pending Deletion is not part of Review: a role that may open Review Results but may not
    delete does not see the list (roles are configurable, 700)."""
    _sql("INSERT INTO compass.role (code, label) VALUES ('review_reader', 'Review reader')")
    _sql("INSERT INTO compass.role_permission (role_code, permission_code) VALUES "
         "('review_reader', 'review.view'), ('review_reader', 'records.view'), ('review_reader', 'dashboard.view')")
    reader = _client(world, _member(world, "review_reader"))
    assert reader.get("/api/review/deleted").status_code == 403
    editor = _client(world, _member(world))
    assert editor.get("/api/review/deleted").json() == {"deleted": [], "retention_days": 30}


def test_delete_and_restore_need_explicit_confirmation(world):
    editor = _client(world, _member(world))
    answer = _delete(editor, "actors", world.ids["Water Lab"], confirm=False)
    assert answer.status_code == 400 and "Confirm" in answer.json()["detail"]
    assert world.writer.calls == []
    assert _delete(editor, "actors", world.ids["Water Lab"]).status_code == 200
    deletion_id = editor.get("/api/review/deleted").json()["deleted"][0]["deletion_id"]
    assert _restore(editor, deletion_id, confirm=False).status_code == 400
    assert _delete(editor, "planets", world.ids["Water Lab"]).status_code in {403, 404}


# ------------------------------------------------------------------ hiding
def test_a_deleted_record_disappears_from_every_active_view_at_once(world):
    editor = _client(world, _member(world))
    for kind, path, key, name in [("actors", "actors", "id", "Water Lab"),
                                  ("events", "events", "id", "Delta Summit"),
                                  ("people", "people", "id", "Ada Byron"),
                                  ("hubs", "hubs", "hub_id", "Desert Hub")]:
        rows = lambda: editor.get(f"/api/browse/{path}").json()[path]   # noqa: E731
        assert [r[key] for r in rows()] == [world.ids[name]]
        assert _delete(editor, kind, world.ids[name]).status_code == 200
        assert rows() == [], f"{name} is still listed"                 # immediately, no cache wait
    assert editor.get(f"/api/browse/actors/{world.ids['Water Lab']}/profile").status_code == 404

    # Ask: answers never cite a deleted record.
    hits = [{"entity_type": "actor", "entity_id": world.ids["Water Lab"], "text": "Water Lab"},
            {"entity_type": "event", "entity_id": world.ids["Delta Summit"], "text": "Delta Summit"},
            {"entity_type": "actor", "entity_id": str(uuid.uuid4()), "text": "Another lab"}]
    accounts_on = accounts_routes.accounts_enabled
    try:
        accounts_routes.accounts_enabled = lambda: True
        assert [h["text"] for h in app_module._ask_visible(hits)] == ["Another lab"]
    finally:
        accounts_routes.accounts_enabled = accounts_on


def test_deleted_records_wait_under_rejected_with_who_when_why_and_deadline(world):
    owner = _member(world, "editor", name="Owner Olu")
    _sql("INSERT INTO compass.record_owner (entity_type, entity_id, owner_user_id, origin) "
         "VALUES ('actor', %s, %s::uuid, 'imported')", world.ids["Water Lab"], owner["id"])
    deleter = _member(world, "editor", name="Deleter Dana")
    client = _client(world, deleter)
    answer = _delete(client, "actors", world.ids["Water Lab"], reason="  Duplicate of   an older record ")
    assert answer.status_code == 200
    # the writer got the signed-in account, never a typed name or id
    call = world.writer.calls[-1]
    assert call["user_id"] == deleter["id"] and call["entity_type"] == "actor"

    listed = client.get("/api/review/deleted").json()
    assert listed["retention_days"] == 30
    [row] = listed["deleted"]
    assert row["name"] == "Water Lab" and row["entity_type"] == "actor"
    assert row["deleted_by"] == "Deleter Dana" and row["owner"] == "Owner Olu"
    assert row["reason"] == "Duplicate of an older record"
    assert row["days_remaining"] == 30
    assert row["details"]["country"] == "United States"
    assert row["links"] == {"actor_fact.actor_id": 4, "hub_actor.actor_id": 1}
    deadline = _sql("SELECT purge_after - deleted_at FROM compass.deleted_record")[0][0]
    assert deadline.days == 30

    # the owner hears about it; ownership itself is untouched
    note = _sql("SELECT title, body, link FROM compass.notification WHERE user_id = %s::uuid", owner["id"])
    assert note and "deleted" in note[0][0] and "30 days" in note[0][1]
    assert "Pending Deletion" in note[0][1] and note[0][2] == "deletions"      # opens the page, not Review
    assert _sql("SELECT owner_user_id::text FROM compass.record_owner WHERE entity_id = %s",
                world.ids["Water Lab"]) == [(owner["id"],)]


def test_restore_brings_it_back_with_owner_and_trail_and_is_recorded(world):
    owner = _member(world, "editor", name="Owner Olu")
    _sql("INSERT INTO compass.record_owner (entity_type, entity_id, owner_user_id, origin) "
         "VALUES ('event', %s, %s::uuid, 'created')", world.ids["Delta Summit"], owner["id"])
    restorer = _member(world, "admin", name="Admin Ama")
    client = _client(world, _member(world))
    assert _delete(client, "events", world.ids["Delta Summit"]).status_code == 200
    deletion_id = client.get("/api/review/deleted").json()["deleted"][0]["deletion_id"]

    admin = _client(world, restorer)
    answer = _restore(admin, deletion_id)
    assert answer.status_code == 200 and answer.json()["entity_id"] == world.ids["Delta Summit"]
    assert [e["id"] for e in admin.get("/api/browse/events").json()["events"]] == [world.ids["Delta Summit"]]
    assert admin.get("/api/review/deleted").json()["deleted"] == []
    who = _sql("SELECT p.full_name, d.restored_at IS NOT NULL FROM compass.deleted_record d "
               "JOIN compass.user_profile p ON p.user_id = d.restored_by")
    assert who == [("Admin Ama", True)]
    assert _sql("SELECT owner_user_id::text FROM compass.record_owner WHERE entity_id = %s",
                world.ids["Delta Summit"]) == [(owner["id"],)]
    actions = [r[0] for r in _sql("SELECT action FROM compass.audit_event WHERE entity_id IN (%s, %s) "
                                  "ORDER BY audit_id", world.ids["Delta Summit"], deletion_id)]
    assert actions == ["browse.delete", "review.deleted_restore"]
    # a second restore of the same deletion is refused, not repeated
    assert _restore(admin, deletion_id).status_code == 422


def test_restore_is_refused_once_the_30_days_are_over(world):
    deleter = _member(world)
    deletion_id = _sql("""
        INSERT INTO compass.deleted_record (entity_type, entity_id, name, snapshot, deleted_by, deleted_at, purge_after)
        VALUES ('actor', %s::uuid, 'Water Lab', '{}'::jsonb, %s::uuid, now() - interval '31 days',
                now() - interval '1 day') RETURNING deletion_id::text
    """, world.ids["Water Lab"], deleter["id"])[0][0]          # simulated time: deleted 31 days ago
    client = _client(world, _member(world, "admin"))
    [row] = client.get("/api/review/deleted").json()["deleted"]
    assert row["days_remaining"] == 0
    answer = _restore(client, deletion_id)
    assert answer.status_code == 422 and "30 days" in answer.json()["detail"]
    assert client.get("/api/browse/actors").json()["actors"] == []      # still hidden until purged


def test_the_database_refuses_a_restore_after_the_deadline_and_any_rewrite(world):
    deleter = _member(world)
    deletion_id = _sql("""
        INSERT INTO compass.deleted_record (entity_type, entity_id, name, snapshot, deleted_by, deleted_at, purge_after)
        VALUES ('event', %s::uuid, 'Delta Summit', '{}'::jsonb, %s::uuid, now() - interval '40 days',
                now() - interval '10 days') RETURNING deletion_id::text
    """, world.ids["Delta Summit"], deleter["id"])[0][0]
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql("UPDATE compass.deleted_record SET restored_at = now(), restored_by = %s::uuid WHERE deletion_id = %s",
             deleter["id"], deletion_id)
    with pytest.raises(psycopg.errors.RaiseException):
        _sql("UPDATE compass.deleted_record SET purge_after = now() + interval '60 days' WHERE deletion_id = %s",
             deletion_id)
    with pytest.raises(psycopg.errors.RaiseException):
        _sql("DELETE FROM compass.deleted_record WHERE deletion_id = %s", deletion_id)
    with pytest.raises(psycopg.errors.CheckViolation):           # a deadline shorter than 30 days
        _sql("INSERT INTO compass.deleted_record (entity_type, entity_id, name, snapshot, deleted_by, purge_after) "
             "VALUES ('hub', %s::uuid, 'Desert Hub', '{}'::jsonb, %s::uuid, now() + interval '5 days')",
             world.ids["Desert Hub"], deleter["id"])


# ------------------------------------------------------------------ concurrency
def test_two_people_deleting_or_restoring_at_once_make_one_change(world):
    a = _client(world, _member(world, "editor"))
    b = _client(world, _member(world, "admin"))
    barrier = threading.Barrier(2)
    answers = []

    def run(fn):
        barrier.wait()
        answers.append(fn())

    threads = [threading.Thread(target=run, args=(lambda c=c: _delete(c, "people", world.ids["Ada Byron"]),))
               for c in (a, b)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(r.status_code for r in answers) == [200, 422]
    assert _sql("SELECT count(*) FROM compass.deleted_record")[0][0] == 1

    deletion_id = a.get("/api/review/deleted").json()["deleted"][0]["deletion_id"]
    answers.clear()
    threads = [threading.Thread(target=run, args=(lambda c=c: _restore(c, deletion_id),)) for c in (a, b)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(r.status_code for r in answers) == [200, 422]
    assert _sql("SELECT count(*) FROM compass.deleted_record WHERE restored_at IS NOT NULL")[0][0] == 1

    # deleted again after the restore: a new deletion, not a duplicate of the old one
    assert _delete(a, "people", world.ids["Ada Byron"]).status_code == 200
    assert _sql("SELECT count(*) FROM compass.deleted_record")[0][0] == 2


def test_a_person_name_stays_out_of_the_permanent_audit_history(world):
    client = _client(world, _member(world))
    assert _delete(client, "people", world.ids["Ada Byron"], reason="Asked to be removed").status_code == 200
    [(detail, entity_type, entity_id)] = _sql(
        "SELECT detail, entity_type, entity_id FROM compass.audit_event WHERE action = 'browse.delete'")
    assert entity_type == "person" and entity_id == world.ids["Ada Byron"]
    assert "Ada Byron" not in json.dumps(detail) and detail["deletion_id"]


def test_without_a_configured_writer_nothing_is_deleted(world, monkeypatch):
    class Off:
        configured = False
    monkeypatch.setattr(app_module, "review_admission_bridge", lambda: Off())
    client = _client(world, _member(world))
    answer = _delete(client, "actors", world.ids["Water Lab"])
    assert answer.status_code == 503
    assert _sql("SELECT count(*) FROM compass.deleted_record")[0][0] == 0


# ------------------------------------------------------------------ scheduled cleanup
class FakeBackend:
    def __init__(self, configured=True):
        self.configured = configured
        self.database_url = "postgresql://ghus_test@127.0.0.1:55432/ghus_v2_demo_test"
        self.project_root = Path("ghus-backend")
        self.python_executable = "python"


def _runner(report, calls):
    def run(command, **kwargs):
        calls.append({"command": command, "env": kwargs["env"]})
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(report), stderr="")
    return run


def test_cleanup_is_off_by_default_and_runs_dry_unless_live(world, monkeypatch):
    monkeypatch.delenv("GHUS_PURGE_MODE", raising=False)
    assert purge_mode() == "off"
    monkeypatch.setenv("GHUS_PURGE_MODE", "sometimes")
    assert purge_mode() == "off"                                   # unknown values never purge
    assert app_module._start_purge_scheduler() is None              # never started when off

    calls = []
    off = PurgeScheduler(bridge=FakeBackend(), store=world.store, mode="off", run_command=_runner({}, calls))
    assert off.run_once() == {"skipped": "GHUS_PURGE_MODE is off"} and calls == [] and off.start() is False

    monkeypatch.setenv("REVIEW_ADMISSION_WRITES_ENABLED", "true")  # a dry run must not inherit it
    report = {"live": False, "due": 1, "outcomes": {"would_purge": 1},
              "results": [{"deletion_id": "d1", "entity_type": "actor", "entity_id": "a1", "outcome": "would_purge",
                           "rows": {"actor": 1}}]}
    dry = PurgeScheduler(bridge=FakeBackend(), store=world.store, mode="dry-run", run_command=_runner(report, calls))
    assert dry.run_once()["outcomes"] == {"would_purge": 1}
    assert calls[-1]["command"][-1] == "agents.review.purge"
    assert "REVIEW_ADMISSION_WRITES_ENABLED" not in calls[-1]["env"]

    live = PurgeScheduler(bridge=FakeBackend(), store=world.store, mode="live",
                          run_command=_runner({**report, "live": True, "outcomes": {"purged": 1}}, calls))
    live.run_once()
    assert calls[-1]["command"][-1] == "--live" and calls[-1]["env"]["REVIEW_ADMISSION_WRITES_ENABLED"] == "true"
    audits = _sql("SELECT user_label, detail->>'mode', detail->'outcomes' FROM compass.audit_event "
                  "WHERE action = 'cleanup.purge' ORDER BY audit_id")
    assert audits == [("Scheduled cleanup", "dry-run", {"would_purge": 1}),
                      ("Scheduled cleanup", "live", {"purged": 1})]


def test_cleanup_failures_are_recorded_and_never_raise(world):
    def broken(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="Traceback...\nOperationalError: timeout")
    scheduler = PurgeScheduler(bridge=FakeBackend(), store=world.store, mode="live", run_command=broken)
    assert "OperationalError" in scheduler.run_once()["error"]

    def missing(command, **kwargs):
        raise FileNotFoundError("python")
    assert "FileNotFoundError" in PurgeScheduler(bridge=FakeBackend(), store=world.store, mode="live",
                                                 run_command=missing).run_once()["error"]
    assert "not configured" in PurgeScheduler(bridge=FakeBackend(configured=False), store=world.store,
                                              mode="live").run_once()["error"]
    errors = _sql("SELECT detail->>'error' FROM compass.audit_event WHERE action = 'cleanup.purge'")
    assert len(errors) == 3 and all(e[0] for e in errors)


def test_the_cleanup_timer_runs_on_the_server_not_in_a_browser(world):
    ran = threading.Event()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        ran.set()
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"live": False, "due": 0,
                                                                          "outcomes": {}, "results": []}), stderr="")
    scheduler = PurgeScheduler(bridge=FakeBackend(), store=world.store, mode="dry-run", run_command=run,
                               interval_hours=24, first_delay_minutes=0)
    assert scheduler.start() is True and scheduler.start() is False      # one timer per server
    assert ran.wait(5)
    scheduler.stop()
    scheduler._thread.join(5)                                         # its audit entry is written
    assert not scheduler._thread.is_alive()
    assert len(calls) == 1


# ------------------------------------------------------------------ isolation
def test_these_tests_never_touch_production(world):
    assert re.search(r"@(127\.0\.0\.1|localhost):\d+/\w+_test$", PG), "local *_test database only"
    assert "supabase" not in PG.lower()
    assert isinstance(world.writer, DeletionWriter)
