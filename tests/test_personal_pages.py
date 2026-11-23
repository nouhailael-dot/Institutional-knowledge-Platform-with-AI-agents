"""Personal pages (GHUS, 23 Nov 2026).

Everything is personal apart from the Ecosystem Directory: each person sees their
own maps, Monitor and Update requests, Data Feed imports, Review Results and
Pending Deletion, plus what was made before accounts (no recorded owner), which
stays shared with everyone. Someone else's item answers "not found"; owners that
cannot be read refuse rather than show everything.

The real route handlers run behind the real sign-in middleware; their storage is
a stand-in. Synthetic users on GHUS_ACCOUNTS_TEST_DATABASE_URL; nothing reaches
Supabase.
"""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app as app_module
from backend import accounts_admin, accounts_routes
from src.accounts import personal
from src.accounts.store import AccountsStore
from src.accounts.supabase_auth import AuthSettings, SupabaseAuth
from src.identity import signed_in_as
from src.review.store import ReviewStore
from tests.test_review import discovery_candidate

DB = os.environ.get("GHUS_ACCOUNTS_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="GHUS_ACCOUNTS_TEST_DATABASE_URL is required")
SITE = "http://testserver"
H = {"Origin": SITE}
PASSWORD = "a long passphrase for compass 7"
PG = (DB or "").replace("postgresql+psycopg://", "postgresql://")


# --- the review store hides someone else's runs everywhere (no database) ------------------------

def _run(store, run_id, n=2):
    items = []
    for i in range(n):
        item = discovery_candidate("actor", f"{run_id}-{i}")
        item.update(source_run_id=run_id, source_key=f"postgres:search_candidate:{run_id}-{i}",
                    source_description=f"Open-web discovery · {run_id}")
        item["payload"] = {**item["payload"], "name": f"Lab {run_id} {i}"}
        items.append(item)
    store.sync_external_candidates(items)


def test_someone_elses_run_is_left_out_of_items_counts_and_groups(tmp_path):
    store = ReviewStore(tmp_path / "review.sqlite3")
    _run(store, "discovery:mine")
    _run(store, "discovery:theirs", n=3)
    _run(store, "discovery:before-accounts")
    assert set(store.source_run_ids()) == {"discovery:mine", "discovery:theirs", "discovery:before-accounts"}
    whole = store.list(status="all")
    assert len(whole["candidates"]) == 7
    shown = store.list(status="all", hidden_runs=frozenset({"discovery:theirs"}))
    assert {c["source_run_id"] for c in shown["candidates"]} == {"discovery:mine", "discovery:before-accounts"}
    assert sum(shown["counts"].values()) == 4
    assert {g["key"] for g in shown["run_groups"]} == {"discovery:mine", "discovery:before-accounts"}
    assert {m["source_run_id"] for m in shown["source_maps"]} == {"discovery:mine", "discovery:before-accounts"}
    any_item = shown["candidates"][0]["candidate_id"]
    assert store.source_run_of(any_item) in {"discovery:mine", "discovery:before-accounts"}
    assert store.source_run_of("no-such-item") is None


# --- routes behind the real sign-in (test database) ---------------------------------------------

class Maps:
    def __init__(self):
        self.made: dict[str, dict] = {}

    def create(self, description=""):
        job = uuid.uuid4().hex
        self.made[job] = {"id": job, "description": description or "Untitled map", "status": "done",
                          "stage": "Complete", "result": None, "error": None, "messages": [],
                          "plan": None, "created": 1.0, "updated": 1.0,
                          "cost": {"calls": [], "estimated_usd": 0}}
        return job

    def recent(self):
        return list(self.made.values())

    def get(self, job):
        return self.made[job]

    def undecided(self, ids):
        return {}


class Requests:
    configured = True

    def __init__(self):
        self.rows: list[dict] = []
        self.changed: list[tuple[str, str]] = []

    def list_requests(self):
        return {"requests": list(self.rows)}

    def list_update_requests(self):
        return {"requests": [], "one_time": []}

    def change(self, sid, action):
        self.changed.append((sid, action))
        return {"subscription_id": sid, "status": action}


@pytest.fixture(scope="module")
def world():
    from tests.accounts_fakes import JWT_SECRET, SERVICE_KEY, FakeGoTrue
    from tests.test_accounts import _reset_schema

    _reset_schema(DB)
    gotrue = FakeGoTrue()
    store = AccountsStore(DB)
    accounts_routes.configure(
        auth=SupabaseAuth(AuthSettings(url="https://auth.example.test", anon_key="anon-test-key",
                                       service_role_key=SERVICE_KEY, jwt_secret=JWT_SECRET),
                          transport=gotrue.transport()),
        store=store)
    app = FastAPI()
    app.include_router(accounts_routes.router)
    app.include_router(accounts_admin.router)
    for method, path, handler in [
        ("POST", "/api/map/session", app_module.map_session),
        ("GET", "/api/maps", app_module.maps_recent),
        ("GET", "/api/map/{job_id}", app_module.map_status),
        ("POST", "/api/map/{job_id}/stop", app_module.map_stop),
        ("GET", "/api/discovery/requests", app_module.discovery_requests),
        ("POST", "/api/discovery/requests/{subscription_id}/{action}", app_module.discovery_change),
        ("GET", "/api/review/deleted", app_module.review_deleted),
    ]:
        app.add_api_route(path, handler, methods=[method])
    app.add_exception_handler(personal.OwnershipUnavailable, app_module._owners_unavailable)
    app.middleware("http")(accounts_routes.require_account)
    yield {"app": app, "gotrue": gotrue, "store": store}
    accounts_routes.configure()


@pytest.fixture
def fakes(world, monkeypatch):
    maps, requests = Maps(), Requests()
    monkeypatch.setattr(app_module, "map_store", lambda: maps)
    monkeypatch.setattr(app_module, "discovery_bridge", lambda: requests)
    monkeypatch.setattr(app_module, "research_availability", lambda: (False, "off in tests"))
    return {"maps": maps, "requests": requests}


def _sql(query, *params):
    with psycopg.connect(PG, autocommit=True) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else None


def _member(world, role="editor", name=None) -> dict:
    email = f"{uuid.uuid4().hex[:10]}@example.test"
    uid = world["gotrue"].add_user(email, PASSWORD)
    _sql("INSERT INTO auth.users (id, email) VALUES (%s, %s)", uid, email)
    _sql("INSERT INTO compass.user_profile (user_id, email, full_name, role_code, status) "
         "VALUES (%s, %s, %s, %s, 'active')", uid, email, name or f"Synthetic {role}", role)
    return {"id": uid, "email": email}


def _client(world, person) -> TestClient:
    client = TestClient(world["app"], base_url=SITE)
    r = client.post("/api/auth/login", json={"email": person["email"], "password": PASSWORD}, headers=H)
    assert r.status_code == 200, r.text
    return client


@needs_db
def test_each_person_sees_their_own_maps_and_the_shared_ones_from_before_accounts(world, fakes):
    ana, bob = _member(world, "editor", "Ana"), _member(world, "admin", "Bob Admin")
    a, b = _client(world, ana), _client(world, bob)
    anas = a.post("/api/map/session", headers=H).json()["job_id"]
    bobs = b.post("/api/map/session", headers=H).json()["job_id"]
    old = fakes["maps"].create("Made with the shared login")          # no owner recorded
    seen = {m["id"]: m for m in a.get("/api/maps").json()["maps"]}
    assert set(seen) == {anas, old} and seen[old].get("shared") is True and not seen[anas].get("shared")
    assert {m["id"] for m in b.get("/api/maps").json()["maps"]} == {bobs, old}   # admins too
    # Someone else's map is not found, whatever the action.
    assert b.get(f"/api/map/{anas}").status_code == 404
    assert b.post(f"/api/map/{anas}/stop", headers=H).status_code == 404
    assert a.get(f"/api/map/{anas}").status_code == 200
    assert a.get(f"/api/map/{old}").status_code == 200


@needs_db
def test_each_person_sees_their_own_monitor_requests_and_cannot_change_others(world, fakes):
    ana, bob = _member(world, "editor", "Ana"), _member(world, "editor", "Bob")
    a, b = _client(world, ana), _client(world, bob)
    sid_a, sid_b, sid_old = (str(uuid.uuid4()) for _ in range(3))
    for sid, person in ((sid_a, ana), (sid_b, bob)):
        _sql("INSERT INTO compass.record_owner (entity_type, entity_id, owner_user_id, origin) "
             "VALUES ('request', %s, %s, 'requested')", sid, person["id"])
    fakes["requests"].rows = [{"subscription_id": s, "title": t} for s, t in
                              ((sid_a, "Ana's"), (sid_b, "Bob's"), (sid_old, "Before accounts"))]
    mine = {r["subscription_id"]: r for r in a.get("/api/discovery/requests").json()["requests"]}
    assert set(mine) == {sid_a, sid_old} and mine[sid_old]["shared"] is True
    assert b.post(f"/api/discovery/requests/{sid_a}/pause", headers=H).status_code == 404
    assert a.post(f"/api/discovery/requests/{sid_a}/pause", headers=H).status_code == 200
    assert fakes["requests"].changed == [(sid_a, "pause")]
    # The cached list itself is never changed by one person's view.
    assert len(fakes["requests"].rows) == 3 and "shared" not in fakes["requests"].rows[2]


@needs_db
def test_pending_deletion_lists_only_my_deletions_admins_included(world, fakes, monkeypatch):
    ana, bob = _member(world, "editor", "Ana"), _member(world, "admin", "Bob Admin")
    rows = [{"deletion_id": str(uuid.uuid4()), "entity_type": "actor", "entity_id": str(uuid.uuid4()),
             "name": n, "reason": None, "deleted_at": None, "purge_after": None, "deleted_by": n,
             "days_remaining": 30, "owner": None, "snapshot": {}, "deleted_by_user_id": who["id"]}
            for n, who in (("Deleted by Ana", ana), ("Deleted by Bob", bob))]
    monkeypatch.setattr(world["store"], "deletions", lambda **kw: rows)
    names = lambda c: [d["name"] for d in c.get("/api/review/deleted").json()["deleted"]]  # noqa: E731
    assert names(_client(world, ana)) == ["Deleted by Ana"]
    assert names(_client(world, bob)) == ["Deleted by Bob"]


@needs_db
def test_owners_that_cannot_be_read_refuse_rather_than_show_everyone(world, fakes, monkeypatch):
    ana = _member(world, "editor", "Ana")
    a = _client(world, ana)
    job = a.post("/api/map/session", headers=H).json()["job_id"]

    def broken(*_args):
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(world["store"], "owner_ids", broken)
    monkeypatch.setattr(world["store"], "owner_of", broken)
    listed = a.get("/api/maps")
    assert listed.status_code == 503 and "could not check" in listed.json()["detail"]
    assert a.get(f"/api/map/{job}").status_code == 503


@needs_db
def test_review_items_belong_to_the_owner_of_their_import_or_request(world, fakes, monkeypatch):
    ana, bob = _member(world, "editor", "Ana"), _member(world, "editor", "Bob")
    run_a, sid_b, check_a = str(uuid.uuid4()), str(uuid.uuid4()), uuid.uuid4().hex
    _sql("INSERT INTO compass.record_owner (entity_type, entity_id, owner_user_id, origin) "
         "VALUES ('import', %s, %s, 'imported'), ('request', %s, %s, 'requested')",
         run_a, ana["id"], sid_b, bob["id"])
    links = {"discovery:bobs-run": {"request": sid_b, "check": None},
             "actor-update:anas-check-run": {"request": None, "check": check_a}}
    monkeypatch.setattr(world["store"], "review_run_links", lambda ids: {k: v for k, v in links.items() if k in ids})
    monkeypatch.setattr(world["store"], "check_owners", lambda: {check_a: ana["id"]})
    runs = [f"datafeed:{run_a}", "discovery:bobs-run", "actor-update:anas-check-run", "discovery:before-accounts"]
    owners = personal.review_run_owners(runs)
    assert owners == {f"datafeed:{run_a}": ana["id"], "discovery:bobs-run": bob["id"],
                      "actor-update:anas-check-run": ana["id"], "discovery:before-accounts": None}
    account = world["store"].account(bob["id"])
    with signed_in_as(account):
        assert personal.hidden_review_runs(runs) == {f"datafeed:{run_a}", "actor-update:anas-check-run"}
    # Without individual accounts (the shared login) nothing is hidden.
    assert personal.hidden_review_runs(runs) == frozenset()
