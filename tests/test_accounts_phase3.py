"""Ownership, activity and Review attribution (multi-user Compass, Phase 3).

The real route handlers (maps, requests, Review decisions, Directory, My work)
run behind the real sign-in middleware; only their storage and backend calls
are stand-ins. Synthetic users on the isolated local database
GHUS_ACCOUNTS_TEST_DATABASE_URL; nothing reaches Supabase.
"""

from __future__ import annotations

import os
import threading
import uuid

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app as app_module
from backend import accounts_admin, accounts_routes
from src.accounts import activity
from src.accounts.store import AccountsStore
from src.accounts.supabase_auth import AuthSettings, SupabaseAuth
from src.identity import signed_in_as
from tests.accounts_fakes import JWT_SECRET, SERVICE_KEY, FakeGoTrue
from tests.test_accounts import _reset_schema

DB = os.environ.get("GHUS_ACCOUNTS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="GHUS_ACCOUNTS_TEST_DATABASE_URL is required")
SITE = "http://testserver"
H = {"Origin": SITE}
PASSWORD = "a long passphrase for compass 7"
PG = (DB or "").replace("postgresql+psycopg://", "postgresql://")


def _sql(query, *params):
    with psycopg.connect(PG, autocommit=True) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else None


# --- stand-ins for what the handlers call --------------------------------------------------
class Maps:
    def __init__(self):
        self.made = []

    def create(self, description=""):
        job = uuid.uuid4().hex
        self.made.append({"id": job, "description": description or "Untitled map"})
        return job

    def recent(self):
        return list(self.made)


class Requests:
    configured = True

    def __init__(self):
        self.sent = []

    def create(self, body):
        self.sent.append(body)
        return {"request": {"subscription_id": str(uuid.uuid4()), "title": body.get("title")}}

    def list_requests(self):
        return {"requests": []}

    def list_update_requests(self):
        return {"requests": []}


class ReviewStore:
    """A Review item per id: entity type, name and where it came from."""

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.decided: list[tuple[str, str]] = []

    def add(self, *, kind="actor", name="Prairie Water Lab", source="disc-run-1") -> str:
        cid = str(uuid.uuid4())
        self.items[cid] = {"candidate_id": cid, "entity_type": kind, "display_name": name,
                           "source_run_id": source}
        return cid

    def get(self, cid):
        return self.items[cid]

    def admission_request(self, cid, **kw):
        return {"decision_kind": kw["decision_kind"], "candidate_id": cid}

    def record_admission_success(self, cid, *, reviewer, decision_kind, **kw):
        self.decided.append((cid, reviewer))
        return {"candidate_id": cid, "status": "decided"}

    def record_admission_failure(self, *a, **kw):
        pass


class Bridge:
    configured = True

    def __init__(self):
        self.created: dict[str, str] = {}
        self.fail = False

    def apply(self, decision):
        if self.fail:
            raise app_module.AdmissionBridgeError("refused by the backend")
        if decision["decision_kind"] == "edit_directory_record":
            return {"status": "applied", "changed": sorted(decision["changes"])}
        if decision["decision_kind"] == "new":
            new = self.created.setdefault(decision["candidate_id"], str(uuid.uuid4()))
            return {"status": "applied", "canonical_entity_id": new}
        return {"status": "applied"}


@pytest.fixture(scope="module")
def world():
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
        ("POST", "/api/discovery/requests", app_module.discovery_create),
        ("POST", "/api/review/candidates/{candidate_id}/decision", app_module.review_candidate_decision),
        ("POST", "/api/browse/{kind}/{record_id}/edit", app_module.directory_edit),
        ("GET", "/api/browse/actors", app_module.browse_actors),
        ("GET", "/api/account/mine", app_module.account_mine),
        ("GET", "/api/account/review-history", app_module.account_review_history),
    ]:
        app.add_api_route(path, handler, methods=[method])
    app.middleware("http")(accounts_routes.require_account)
    yield {"app": app, "gotrue": gotrue, "store": store}
    accounts_routes.configure()


@pytest.fixture
def fakes(world, monkeypatch):
    maps, requests, reviews, bridge = Maps(), Requests(), ReviewStore(), Bridge()
    actors = [{"id": str(uuid.uuid4()), "name": "Historic Lab (before accounts)", "hubs": [],
               "owner": None}]
    monkeypatch.setattr(app_module, "map_store", lambda: maps)
    monkeypatch.setattr(app_module, "discovery_bridge", lambda: requests)
    monkeypatch.setattr(app_module, "review_store", lambda: reviews)
    monkeypatch.setattr(app_module, "review_admission_bridge", lambda: bridge)
    monkeypatch.setattr(app_module, "_actors", lambda: actors)
    monkeypatch.setattr(app_module, "_sectors_by_hub", lambda: {})
    monkeypatch.setattr(app_module.browse, "actor_filter_options", lambda rows: {})
    for name in ("_hubs", "_events", "_people"):
        monkeypatch.setattr(app_module, name, lambda: [])
    for cached in ("_actors", "_hubs", "_events", "_people"):
        getattr(app_module, cached).cache_clear = lambda: None
    return {"maps": maps, "requests": requests, "reviews": reviews, "bridge": bridge, "actors": actors}


def _member(world, role="editor", name=None) -> dict:
    email = f"{uuid.uuid4().hex[:10]}@example.test"
    uid = world["gotrue"].add_user(email, PASSWORD)
    _sql("INSERT INTO auth.users (id, email) VALUES (%s, %s)", uid, email)
    _sql("INSERT INTO compass.user_profile (user_id, email, full_name, role_code, status) "
         "VALUES (%s, %s, %s, %s, 'active')", uid, email, name or f"Synthetic {role} {email[:4]}", role)
    return {"id": uid, "email": email, "name": name or f"Synthetic {role} {email[:4]}"}


def _client(world, person) -> TestClient:
    client = TestClient(world["app"], base_url=SITE)
    r = client.post("/api/auth/login", json={"email": person["email"], "password": PASSWORD}, headers=H)
    assert r.status_code == 200, r.text
    return client


def _decide(client, cid, kind="new", **extra):
    return client.post(f"/api/review/candidates/{cid}/decision",
                       json={"decision_kind": kind, "idempotency_key": uuid.uuid4().hex,
                             "confirmed": True, **extra}, headers=H)


def _owner(kind, entity_id):
    rows = _sql("SELECT owner_user_id::text, origin, source_ref FROM compass.record_owner "
                "WHERE entity_type=%s AND entity_id=%s", kind, str(entity_id))
    return rows[0] if rows else None


def _audit(user_id, action=None):
    rows = _sql("SELECT action, entity_type, entity_id, detail FROM compass.audit_event "
                "WHERE user_id=%s::uuid AND action NOT LIKE 'auth.%%' ORDER BY audit_id", user_id)
    return [r for r in rows if action is None or r[0] == action]


# --- ownership ---------------------------------------------------------------------------------

def test_a_new_map_and_a_new_request_belong_to_whoever_made_them(world, fakes):
    ana, bob = _member(world, name="Ana"), _member(world, name="Bob")
    a = _client(world, ana)
    job = a.post("/api/map/session", headers=H).json()["job_id"]
    assert _owner("map", job)[:2] == (ana["id"], "created")
    created = a.post("/api/discovery/requests", json={"title": "Water reuse", "end_date": "2027-01-01",
                                                      "cadence": "weekly"}, headers=H).json()
    sid = created["request"]["subscription_id"]
    assert _owner("request", sid)[:2] == (ana["id"], "requested")
    assert fakes["requests"].sent[-1]["requested_by"] == ana["email"]      # the session's address
    mine = a.get("/api/account/mine").json()
    assert [m["entity_id"] for m in mine["maps"]] == [job]
    assert [r["entity_id"] for r in mine["requests"]] == [sid]
    other = _client(world, bob).get("/api/account/mine").json()
    assert other["maps"] == [] and other["requests"] == []


def test_verifying_a_new_record_makes_the_verifier_its_owner_and_audits_the_decision(world, fakes):
    rita = _member(world, name="Rita Reviewer")
    cid = fakes["reviews"].add(name="Desert Solar Institute")
    r = _decide(_client(world, rita), cid)
    assert r.status_code == 200, r.text
    created = fakes["bridge"].created[cid]
    assert _owner("actor", created) == (rita["id"], "discovered", f"review:{cid}")
    (action, etype, eid, detail), = _audit(rita["id"])
    assert (action, etype, eid) == ("review.candidates_decision", "review_candidate", cid)
    assert detail["decision"] == "new" and detail["canonical_entity_id"] == created
    assert detail["record_name"] == "Desert Solar Institute"
    assert fakes["reviews"].decided == [(cid, "Rita Reviewer")]       # Review's own log: the name


def test_a_record_from_an_import_belongs_to_the_importer_not_the_reviewer(world, fakes):
    importer, reviewer = _member(world, name="Ivy Importer"), _member(world, name="Ray Reviewer")
    run = str(uuid.uuid4())
    with signed_in_as(world["store"].account(importer["id"])):
        token = activity.begin()
        activity.claim("import", run, "imported")
        activity.end(token)
    cid = fakes["reviews"].add(name="Imported Lab", source=f"datafeed:{run}")
    assert _decide(_client(world, reviewer), cid).status_code == 200
    owner = _owner("actor", fakes["bridge"].created[cid])
    assert owner == (importer["id"], "imported", f"review:{cid}")
    assert _audit(reviewer["id"])[0][3]["decision"] == "new"            # the reviewer decided


def test_data_feed_owns_the_import_and_only_the_records_it_created(world, fakes):
    from src.datafeed.service import DataFeedService

    person = _member(world)
    run, new_id, existing_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with signed_in_as(world["store"].account(person["id"])):
        token = activity.begin()
        DataFeedService._claim_ownership(
            {"record_type": "actor", "method": "file"}, run,
            [{"outcome": "stored", "entity_id": new_id}, {"outcome": "matched_existing", "entity_id": existing_id},
             {"outcome": "awaiting_review"}])
        notes = activity.end(token)
    assert _owner("import", run)[:2] == (person["id"], "imported")
    assert _owner("actor", new_id) == (person["id"], "imported", f"datafeed:{run}")
    assert _owner("actor", existing_id) is None                       # an existing record keeps its owner
    assert len(notes["owned"]) == 2
    with signed_in_as(world["store"].account(person["id"])):
        DataFeedService._claim_ownership({"record_type": "actor", "method": "map"}, str(uuid.uuid4()), [])
    assert _sql("SELECT origin FROM compass.record_owner WHERE owner_user_id=%s::uuid AND entity_type='import' "
                "ORDER BY recorded_at DESC LIMIT 1", person["id"]) == [("mapped",)]


def test_the_original_owner_never_changes(world, fakes):
    first, second = _member(world, name="First"), _member(world, name="Second")
    cid = fakes["reviews"].add()
    _decide(_client(world, first), cid)
    record = fakes["bridge"].created[cid]
    editor = _client(world, second)
    edit = editor.post(f"/api/browse/actors/{record}/edit", json={"changes": {"name": "Renamed Lab"}}, headers=H)
    assert edit.status_code == 200, edit.text
    assert _owner("actor", record)[0] == first["id"]
    with signed_in_as(world["store"].account(second["id"])):
        assert activity.claim("actor", record, "created") is False      # first claim wins
    assert _owner("actor", record)[0] == first["id"]
    with pytest.raises(psycopg.errors.RaiseException, match="never changes"):
        _sql("UPDATE compass.record_owner SET owner_user_id=%s::uuid WHERE entity_id=%s", second["id"], record)
    (action, etype, eid, detail), = _audit(second["id"], "browse.edit")
    assert (etype, eid, detail["changed"]) == ("actor", record, ["name"])


# --- what each list shows --------------------------------------------------------------------------

def test_lists_show_the_owner_or_not_recorded_and_my_records_are_mine_only(world, fakes):
    owner = _member(world, name="Olga Owner")
    cid = fakes["reviews"].add(name="Owned Lab")
    _decide(_client(world, owner), cid)
    owned_id = fakes["bridge"].created[cid]
    fakes["actors"].append({"id": owned_id, "name": "Owned Lab", "hubs": [], "owner": None})
    before = _sql("SELECT count(*) FROM compass.record_owner")
    rows = {r["name"]: r for r in _client(world, _member(world, "viewer")).get("/api/browse/actors").json()["actors"]}
    assert (rows["Owned Lab"]["owner"], rows["Owned Lab"]["owner_user_id"]) == ("Olga Owner", owner["id"])
    assert rows["Historic Lab (before accounts)"]["owner"] is None     # shown as Not recorded
    assert "owner_user_id" not in rows["Historic Lab (before accounts)"]
    assert _sql("SELECT count(*) FROM compass.record_owner") == before  # reading never assigns owners
    mine = _client(world, owner).get("/api/account/mine").json()["records"]
    assert [(m["entity_id"], m["name"]) for m in mine] == [(owned_id, "Owned Lab")]
    assert fakes["actors"][0]["owner"] is None                         # the shared rows are not changed


def test_my_review_history_lists_only_my_decisions(world, fakes):
    me, other = _member(world, name="Me"), _member(world, name="Other")
    mine, theirs = fakes["reviews"].add(name="Mine"), fakes["reviews"].add(name="Theirs")
    _decide(_client(world, me), mine, "reject", rejection_reason="Not relevant to GHUS sectors")
    _decide(_client(world, other), theirs, "defer")
    history = _client(world, me).get("/api/account/review-history").json()["history"]
    assert [(h["entity_id"], h["detail"]["decision"]) for h in history] == [(mine, "reject")]


# --- identity and access --------------------------------------------------------------------------

def test_names_and_ids_sent_by_the_browser_are_ignored(world, fakes):
    real, impostor_target = _member(world, name="Real Person"), _member(world, "admin", name="Someone Else")
    cid = fakes["reviews"].add()
    r = _client(world, real).post(f"/api/review/candidates/{cid}/decision", headers={**H, "X-User-Id": impostor_target["id"]},
                                  json={"decision_kind": "new", "idempotency_key": "x1", "confirmed": True,
                                        "reviewer": "Someone Else", "user_id": impostor_target["id"]})
    assert r.status_code == 200
    assert fakes["reviews"].decided[-1] == (cid, "Real Person")
    assert _owner("actor", fakes["bridge"].created[cid])[0] == real["id"]
    assert _audit(impostor_target["id"]) == []


def test_refused_actions_are_audited_and_change_nothing(world, fakes):
    viewer = _member(world, "viewer", name="Vera Viewer")
    cid = fakes["reviews"].add()
    refused = _decide(_client(world, viewer), cid)
    assert refused.status_code == 403
    assert fakes["reviews"].decided == [] and fakes["bridge"].created == {}
    (action, _, eid, detail), = _audit(viewer["id"])
    assert (action, eid, detail["needed"]) == ("access.denied", cid, "review.decide")
    fakes["bridge"].fail = True
    editor = _member(world)
    failed = _decide(_client(world, editor), fakes["reviews"].add())
    assert failed.status_code >= 400
    assert _audit(editor["id"]) == []                                  # a failure is not recorded as done


def test_the_full_audit_history_is_for_its_permission_only(world, fakes):
    editor, admin = _member(world), _member(world, "admin")
    cid = fakes["reviews"].add()
    _decide(_client(world, editor), cid)
    assert _client(world, editor).get("/api/admin/audit").status_code == 403
    a = _client(world, admin)
    entries = a.get(f"/api/admin/audit?user_id={editor['id']}&action=review.").json()["entries"]
    assert [e["entity_id"] for e in entries] == [cid]
    assert a.get("/api/admin/audit?user_id=not-a-uuid").status_code == 422
    assert a.get("/api/admin/audit?action=review';drop").status_code == 422


def test_the_audit_history_cannot_be_edited_or_deleted(world, fakes):
    person = _member(world)
    _client(world, person).post("/api/map/session", headers=H)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        _sql("UPDATE compass.audit_event SET user_label='someone' WHERE user_id=%s::uuid", person["id"])
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        _sql("DELETE FROM compass.audit_event WHERE user_id=%s::uuid", person["id"])


# --- several people, restarts ------------------------------------------------------------------------

def test_people_working_at_the_same_time_each_own_their_own_work(world, fakes):
    people = [_member(world, name=f"Parallel {i}") for i in range(3)]
    clients = [_client(world, p) for p in people]
    made: dict[int, list[str]] = {i: [] for i in range(3)}

    def work(i):
        for _ in range(4):
            made[i].append(clients[i].post("/api/map/session", headers=H).json()["job_id"])

    threads = [threading.Thread(target=work, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for i, person in enumerate(people):
        assert all(_owner("map", job)[0] == person["id"] for job in made[i])
        assert {m["entity_id"] for m in clients[i].get("/api/account/mine").json()["maps"]} == set(made[i])


def test_two_claims_on_the_same_record_at_once_leave_exactly_one_owner(world):
    a, b = _member(world), _member(world)
    record, wins = str(uuid.uuid4()), []
    barrier = threading.Barrier(2)

    def claim(person):
        barrier.wait()
        wins.append(world["store"].claim_owner(entity_type="actor", entity_id=record,
                                               owner_user_id=person["id"], origin="created"))

    threads = [threading.Thread(target=claim, args=(p,)) for p in (a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(wins) == [False, True]
    assert _sql("SELECT count(*) FROM compass.record_owner WHERE entity_id=%s", record) == [(1,)]


def test_ownership_and_history_survive_a_restart(world, fakes):
    person = _member(world, name="Persistent")
    job = _client(world, person).post("/api/map/session", headers=H).json()["job_id"]
    restarted = AccountsStore(DB)                                       # a new process, same database
    assert restarted.owner_of("map", job) == person["id"]
    assert any(e["entity_id"] == job for e in restarted.audit_entries(user_id=person["id"]))


def test_without_individual_accounts_nothing_is_recorded():
    rows = [{"id": "1", "name": "x", "owner": None}]
    assert activity.claim("map", "job", "created") is False
    assert activity.with_owners(rows, "actor") is rows
    activity.note(anything="ignored")
