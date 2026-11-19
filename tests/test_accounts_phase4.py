"""Personal dashboard, notifications, preferences, role-aware pages and late import
ownership (multi-user Compass, Phase 4).

Real handlers behind the real sign-in middleware; storage and backends are
stand-ins. Synthetic users on the isolated local database
GHUS_ACCOUNTS_TEST_DATABASE_URL, which also gets small stand-ins of the
request and run tables. Nothing reaches Supabase; no email is sent.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app as app_module
from backend import accounts_admin, accounts_routes
from src.accounts import email_notifications, notifier
from src.accounts.store import AccountsStore
from src.accounts.supabase_auth import AuthSettings, SupabaseAuth
from tests.accounts_fakes import JWT_SECRET, SERVICE_KEY, FakeGoTrue
from tests.test_accounts import _reset_schema
from tests.test_accounts_phase3 import Bridge, Maps, Requests, ReviewStore

DB = os.environ.get("GHUS_ACCOUNTS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="GHUS_ACCOUNTS_TEST_DATABASE_URL is required")
SITE = "http://testserver"
H = {"Origin": SITE}
PASSWORD = "a long passphrase for compass 7"
PG = (DB or "").replace("postgresql+psycopg://", "postgresql://")
ROOT = Path(__file__).resolve().parents[1]


def _sql(query, *params):
    with psycopg.connect(PG, autocommit=True) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else None


def _run_tables():
    """Small stand-ins of the request and run tables, in the test database only."""
    from tests.accounts_ledgers import create_ledgers
    create_ledgers(PG)


@pytest.fixture(scope="module")
def world():
    _reset_schema(DB)
    _run_tables()
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
        ("POST", "/api/review/candidates/{candidate_id}/decision", app_module.review_candidate_decision),
        ("POST", "/api/browse/{kind}/{record_id}/edit", app_module.directory_edit),
        ("GET", "/api/browse/actors", app_module.browse_actors),
        ("GET", "/api/account/dashboard", app_module.account_dashboard),
        ("GET", "/api/account/notifications", app_module.account_notifications),
        ("POST", "/api/account/notifications/read-all", app_module.account_notifications_read_all),
        ("POST", "/api/account/notifications/{notification_id}/read", app_module.account_notification_read),
        ("GET", "/api/account/preferences", app_module.account_preferences),
        ("PUT", "/api/account/preferences", app_module.account_preferences_update),
        ("GET", "/api/account/record-trail", app_module.account_record_trail),
        ("GET", "/api/review/candidates", lambda: {"candidates": []}),
    ]:
        app.add_api_route(path, handler, methods=[method])
    app.middleware("http")(accounts_routes.require_account)
    yield {"app": app, "gotrue": gotrue, "store": store}
    accounts_routes.configure()


class History:
    """Data Feed history and created records, as the service would answer."""

    def __init__(self):
        self.rows, self.created = [], {}

    def history(self):
        return list(self.rows)

    def created_entities(self, run_id):
        return list(self.created.get(run_id, []))


@pytest.fixture
def fakes(world, monkeypatch):
    maps, reviews, bridge, feed = Maps(), ReviewStore(), Bridge(), History()
    actors = [{"id": str(uuid.uuid4()), "name": "Water Lab", "hubs": ["Arizona Water Hub"], "owner": None}]
    monkeypatch.setattr(app_module, "map_store", lambda: maps)
    monkeypatch.setattr(app_module, "discovery_bridge", lambda: Requests())
    monkeypatch.setattr(app_module, "review_store", lambda: reviews)
    monkeypatch.setattr(app_module, "review_admission_bridge", lambda: bridge)
    monkeypatch.setattr(app_module, "_datafeed", lambda: feed)
    monkeypatch.setattr(app_module, "_actors", lambda: actors)
    monkeypatch.setattr(app_module, "_sectors_by_hub", lambda: {"Arizona Water Hub": ["Water"]})
    monkeypatch.setattr(app_module.browse, "actor_filter_options", lambda rows: {"sectors": ["Water"]})
    for name in ("_hubs", "_events", "_people"):
        monkeypatch.setattr(app_module, name, lambda: [])
    for cached in ("_actors", "_hubs", "_events", "_people"):
        getattr(app_module, cached).cache_clear = lambda: None
    notifier._last_sync.clear()
    return {"maps": maps, "reviews": reviews, "bridge": bridge, "feed": feed}


def _member(world, role="editor", name=None) -> dict:
    email = f"{uuid.uuid4().hex[:10]}@example.test"
    uid = world["gotrue"].add_user(email, PASSWORD)
    _sql("INSERT INTO auth.users (id, email) VALUES (%s, %s)", uid, email)
    name = name or f"Synthetic {role} {email[:4]}"
    _sql("INSERT INTO compass.user_profile (user_id, email, full_name, role_code, status) "
         "VALUES (%s, %s, %s, %s, 'active')", uid, email, name, role)
    return {"id": uid, "email": email, "name": name}


def _client(world, person) -> TestClient:
    client = TestClient(world["app"], base_url=SITE)
    assert client.post("/api/auth/login", json={"email": person["email"], "password": PASSWORD},
                       headers=H).status_code == 200
    return client


def _own(person, kind, entity_id, origin="created", source_ref=None):
    _sql("INSERT INTO compass.record_owner (entity_type, entity_id, owner_user_id, origin, source_ref) "
         "VALUES (%s, %s, %s::uuid, %s, %s)", kind, str(entity_id), person["id"], origin, source_ref)


def _request(person, title, *, runs=(), due_in_hours=None):
    sid = str(uuid.uuid4())
    due = datetime.now(timezone.utc) + timedelta(hours=due_in_hours) if due_in_hours is not None else None
    _sql("INSERT INTO public.actor_update_subscription VALUES (%s, %s, 'active', %s)", sid, title, due)
    _own(person, "request", sid, "requested")
    for status, started_hours_ago, finished in runs:
        rid = str(uuid.uuid4())
        started = datetime.now(timezone.utc) - timedelta(hours=started_hours_ago)
        _sql("INSERT INTO public.collection_run VALUES (%s, %s, %s, %s, %s, 7, 3, 2)", rid, status, started,
             started + timedelta(minutes=5) if finished else None, "search provider down" if status == "failed" else None)
        _sql("INSERT INTO public.actor_update_subscription_run VALUES (%s, %s, false)", sid, rid)
    return sid


def _notes(world, person):
    return world["store"].notifications(person["id"], limit=100)


# --- preferences -----------------------------------------------------------------------------

def test_preferences_have_defaults_save_per_person_and_survive_a_restart(world, fakes):
    ana, bob = _member(world, "viewer"), _member(world)
    a = _client(world, ana)
    start = a.get("/api/account/preferences").json()["preferences"]
    assert start["directory"]["default_view"] == "all" and start["notifications"]["run_finished"] is True
    assert start["notifications"]["email"] is False
    changed = a.put("/api/account/preferences", headers=H, json={"preferences": {
        "sectors": ["Water", "Water", " Mining "], "directory": {"default_view": "mine",
        "saved_filters": [{"name": "Arizona water", "tab": "actors", "values": {"state": "Arizona", "sector": "Water"}}]},
        "dashboard": {"hidden": ["sectors"]}, "notifications": {"schedule": False, "email": True}}})
    assert changed.status_code == 200, changed.text
    saved = AccountsStore(DB).preferences(ana["id"])                    # a new process
    assert saved["sectors"] == ["Water", "Mining"] and saved["directory"]["default_view"] == "mine"
    assert saved["directory"]["saved_filters"][0]["values"] == {"state": "Arizona", "sector": "Water"}
    assert saved["notifications"]["schedule"] is False and saved["notifications"]["run_finished"] is True
    assert _client(world, bob).get("/api/account/preferences").json()["preferences"]["sectors"] == []


@pytest.mark.parametrize("change, words", [
    ({"theme": "dark"}, "Unknown preference"),
    ({"directory": {"default_view": "everyone"}}, "All Records or My Records"),
    ({"sectors": [f"s{i}" for i in range(21)]}, "at most 20"),
    ({"dashboard": {"hidden": ["secret"]}}, "Unknown Dashboard section"),
    ({"notifications": {"email": "yes"}}, "on or off"),
    ({"directory": {"saved_filters": [{"name": "x", "tab": "budgets", "values": {}}]}}, "Directory tab"),
])
def test_invalid_preferences_are_refused(world, fakes, change, words):
    r = _client(world, _member(world)).put("/api/account/preferences", json={"preferences": change}, headers=H)
    assert r.status_code == 422 and words in r.json()["detail"]


def test_preferences_never_change_shared_records(world, fakes):
    person = _member(world)
    before = _sql("SELECT count(*) FROM compass.record_owner")
    _client(world, person).put("/api/account/preferences", headers=H,
                               json={"preferences": {"directory": {"default_view": "mine"}}})
    assert _sql("SELECT count(*) FROM compass.record_owner") == before
    assert fakes["maps"].made == [] and fakes["reviews"].decided == []


# --- notifications ------------------------------------------------------------------------------

def test_runs_maps_imports_and_schedules_notify_their_owner_once(world, fakes):
    owner, other = _member(world, name="Olivia Owner"), _member(world, name="Otto Other")
    _request(owner, "Water reuse", runs=[("succeeded", 2, True), ("failed", 3, True)], due_in_hours=5)
    _request(owner, "Stuck request", runs=[("running", 8, False)])
    _request(other, "Not hers", runs=[("succeeded", 1, True)])
    done_map, failed_map = uuid.uuid4().hex, uuid.uuid4().hex
    fakes["maps"].made += [{"id": done_map, "description": "Solar map", "status": "done"},
                           {"id": failed_map, "description": "Broken map", "status": "error"}]
    _own(owner, "map", done_map)
    _own(owner, "map", failed_map)
    run = str(uuid.uuid4())
    _own(owner, "import", run, "imported", "type:actor")
    fakes["feed"].rows.append({"run_id": run, "import_name": "Kansas labs", "counts": {"pending": 3, "deferred": 1}})
    client = _client(world, owner)
    first = client.get("/api/account/notifications").json()
    titles = sorted(i["title"] for i in first["items"])
    assert titles == sorted([
        "Your request 'Water reuse' finished", "Your request 'Water reuse' failed",
        "Your request 'Stuck request' may have been interrupted", "Your map 'Solar map' is ready",
        "Your map 'Broken map' stopped", "4 record(s) from your import 'Kansas labs' wait in Review",
        "Your request 'Water reuse' runs soon"])
    assert first["unread"] == 7
    notifier._last_sync.clear()
    again = client.get("/api/account/notifications").json()
    assert again["unread"] == 7 and len(again["items"]) == 7            # no duplicates
    assert all("Not hers" not in i["title"] for i in again["items"])
    assert _notes(world, other)["items"] == []                           # nobody else's


def test_read_state_is_kept_and_only_ones_own_can_be_marked(world, fakes):
    me, them = _member(world), _member(world)
    for person in (me, them):
        world["store"].add_notification(user_id=person["id"], kind="decisions", title="Hello", dedupe_key="k1")
    mine = _notes(world, me)["items"][0]["id"]
    theirs = _notes(world, them)["items"][0]["id"]
    client = _client(world, me)
    assert client.post(f"/api/account/notifications/{theirs}/read", headers=H).status_code == 404
    assert _notes(world, them)["unread"] == 1
    assert client.post(f"/api/account/notifications/{mine}/read", headers=H).status_code == 200
    assert client.post(f"/api/account/notifications/{mine}/read", headers=H).status_code == 404
    world["store"].add_notification(user_id=me["id"], kind="decisions", title="Two", dedupe_key="k2")
    world["store"].add_notification(user_id=me["id"], kind="decisions", title="Three", dedupe_key="k3")
    assert client.post("/api/account/notifications/read-all", headers=H).json() == {"marked": 2}
    assert AccountsStore(DB).notifications(me["id"])["unread"] == 0        # kept after a restart


def test_notification_preferences_decide_what_is_created_and_email_waits(world, fakes):
    person = _member(world)
    client = _client(world, person)
    client.put("/api/account/preferences", headers=H,
               json={"preferences": {"notifications": {"run_failed": False, "email": True}}})
    _request(person, "Fails quietly", runs=[("failed", 1, True)])
    _request(person, "Finishes", runs=[("succeeded", 1, True)])
    titles = [i["title"] for i in client.get("/api/account/notifications").json()["items"]]
    assert titles == ["Your request 'Finishes' finished"]
    waiting = [e for e in email_notifications.pending(world["store"]) if e["to"] == person["email"]]
    assert [e["title"] for e in waiting] == ["Your request 'Finishes' finished"]
    message = email_notifications.render(waiting[0], site_url="https://compass.example")
    assert message["subject"].startswith("GHUS Compass:") and "My profile" in message["text"]
    with pytest.raises(email_notifications.EmailNotEnabled):
        email_notifications.deliver(message)


def test_decisions_by_others_notify_the_importer_but_not_oneself(world, fakes):
    importer, reviewer = _member(world, name="Ivy Importer"), _member(world, name="Ray Reviewer")
    run = str(uuid.uuid4())
    _own(importer, "import", run, "imported", "type:actor")
    cid = fakes["reviews"].add(name="Imported Lab", source=f"datafeed:{run}")
    r = _client(world, reviewer).post(f"/api/review/candidates/{cid}/decision", headers=H,
                                      json={"decision_kind": "new", "idempotency_key": "n1", "confirmed": True})
    assert r.status_code == 200
    items = _notes(world, importer)["items"]
    assert [i["title"] for i in items] == ["'Imported Lab' from your import was verified"]
    assert "Ray Reviewer" in items[0]["body"]
    own = fakes["reviews"].add(name="Own decision", source=f"datafeed:{run}")
    _client(world, importer).post(f"/api/review/candidates/{own}/decision", headers=H,
                                  json={"decision_kind": "reject", "idempotency_key": "n2", "confirmed": True,
                                        "rejection_reason": "Not relevant to GHUS sectors"})
    assert len(_notes(world, importer)["items"]) == 1                   # one's own decision: no notice
    record = fakes["bridge"].created[cid]
    _client(world, reviewer).post(f"/api/browse/actors/{record}/edit", headers=H, json={"changes": {"name": "Lab 2"}})
    assert _notes(world, importer)["items"][0]["title"] == "A record you brought in was edited"


# --- owner, reviewer, last editor ------------------------------------------------------------------

def test_the_record_trail_keeps_owner_reviewer_and_last_editor_apart(world, fakes):
    importer, reviewer, editor = _member(world, name="Ivy"), _member(world, name="Ray"), _member(world, name="Eve")
    run = str(uuid.uuid4())
    _own(importer, "import", run, "imported", "type:actor")
    cid = fakes["reviews"].add(source=f"datafeed:{run}")
    _client(world, reviewer).post(f"/api/review/candidates/{cid}/decision", headers=H,
                                  json={"decision_kind": "new", "idempotency_key": "t1", "confirmed": True})
    record = fakes["bridge"].created[cid]
    _client(world, editor).post(f"/api/browse/actors/{record}/edit", headers=H, json={"changes": {"name": "Renamed"}})
    trail = _client(world, _member(world, "viewer")).get(
        f"/api/account/record-trail?entity_type=actor&entity_id={record}").json()
    assert (trail["owner"]["name"], trail["owner"]["origin"]) == ("Ivy", "imported")
    assert (trail["reviewed_by"]["name"], trail["reviewed_by"]["decision"]) == ("Ray", "new")
    assert trail["last_edited_by"]["name"] == "Eve"
    old = _client(world, editor).get(f"/api/account/record-trail?entity_type=actor&entity_id={uuid.uuid4()}").json()
    assert old == {"owner": None, "reviewed_by": None, "last_edited_by": None}


# --- late import records ---------------------------------------------------------------------------

def test_records_an_import_stores_later_inherit_the_importer(world, fakes):
    importer, someone = _member(world, name="Ina"), _member(world)
    run, late, claimed = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    _own(importer, "import", run, "imported", "type:actor")
    _own(someone, "actor", claimed, "discovered")                       # already owned: unchanged
    fakes["feed"].created[run] = [late, claimed]
    old_run, old_record = str(uuid.uuid4()), str(uuid.uuid4())           # an import from before accounts
    fakes["feed"].created[old_run] = [old_record]
    assert notifier.sync_import_ownership(world["store"], fakes["feed"].created_entities, user_id=importer["id"]) == 1
    assert world["store"].owner_of("actor", late) == importer["id"]
    assert world["store"].owner_of("actor", claimed) == someone["id"]
    assert world["store"].owner_of("actor", old_record) is None
    assert _sql("SELECT origin, source_ref FROM compass.record_owner WHERE entity_id=%s", late) == [
        ("imported", f"datafeed:{run}")]
    again = notifier.sync_import_ownership(world["store"], fakes["feed"].created_entities, user_id=importer["id"])
    assert again == 0


def test_only_records_the_import_created_count():
    from src.datafeed.service import DataFeedService

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params):
            class R:
                def fetchall(self):
                    return [(1, "a", "approved", "new", "id-new", False),
                            (2, "b", "approved", "imported_verified", "id-verified", False),
                            (3, "c", "approved", "same_existing", "id-existing", False),
                            (4, "d", "pending", None, None, False)]
            return R()

    service = DataFeedService.__new__(DataFeedService)
    service.connect = lambda: Conn()
    assert service.created_entities(str(uuid.uuid4())) == ["id-new", "id-verified"]
    assert service.created_entities("not-a-run") == []


# --- the dashboard ------------------------------------------------------------------------------------

def test_each_person_gets_their_own_dashboard(world, fakes):
    ana, bob = _member(world, name="Ana Lima"), _member(world, "viewer", name="Bob Viewer")
    a = _client(world, ana)
    a.put("/api/account/preferences", headers=H, json={"preferences": {"sectors": ["Water"]}})
    job = a.post("/api/map/session", headers=H).json()["job_id"]
    fakes["maps"].made[-1]["status"] = "running"
    d = a.get("/api/account/dashboard").json()
    assert d["name"] == "Ana Lima" and d["counts"]["maps"] == 1
    assert [r["id"] for r in d["running"]] == [job]
    assert d["sectors"] == [{"sector": "Water", "organizations": 1}]
    assert any(e["action"] == "map.session" for e in d["activity"])
    b = _client(world, bob).get("/api/account/dashboard").json()
    assert b["name"] == "Bob Viewer" and b["counts"] == {"records": 0, "requests": 0, "maps": 0, "imports": 0}
    assert b["running"] == [] and "review.decide" not in b["permissions"]
    assert TestClient(world["app"], base_url=SITE).get("/api/account/dashboard").status_code == 401


def test_viewers_are_refused_what_their_menu_hides(world, fakes):
    viewer = _client(world, _member(world, "viewer"))
    assert viewer.get("/api/review/candidates").status_code == 403
    assert viewer.post("/api/map/session", headers=H).status_code == 403
    assert viewer.post(f"/api/browse/actors/{uuid.uuid4()}/edit", json={"changes": {}}, headers=H).status_code == 403
    assert viewer.get("/api/account/dashboard").status_code == 200
    assert viewer.get("/api/account/notifications").status_code == 200


# --- role-aware navigation (the page) -------------------------------------------------------------------

def test_the_menu_and_pages_follow_permissions():
    page = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    needs = dict(re.findall(r'(\w+):"([a-z_]+\.[a-z_]+)"', page[page.index("const NAV_NEEDS="):page.index("function applyPermissions")]))
    assert needs == {"dashboard": "dashboard.view", "ask": "ask.use", "map": "maps.view", "browse": "records.view",
                     "discovery": "requests.view", "datafeed": "datafeed.import", "review": "review.view",
                     "mywork": "dashboard.view", "users": "users.manage", "audit": "audit.view_all",
                     "usage": "usage.view_own", "costs": "usage.view_all",
                     "deletions": "records.delete_permanent"}
    for tab in ("dashboard", "ask", "browse", "discovery", "datafeed", "review", "map"):
        assert f'${{allowed("{tab}")&&html`' in page, tab                 # pages mount only when allowed
    for marked in ('class="mactions" data-needs="review.decide"', 'class="start-card" data-needs="maps.create"',
                   'data-needs="maps.create" disabled=${busy||verifying} onClick=${reset}>+ New map',
                   'data-needs="records.edit"', '"records.delete_permanent":"records.remove"', 'data-needs="requests.create"'):
        assert marked in page, marked
    assert "[data-needs~=" in page and "display:none!important" in page


def test_dashboard_buttons_are_whole_elements():
    # 12 Nov 2026: a helper returned "<button ...>" alone and the page closed it in
    # another template; htm cannot join them and the Dashboard failed to draw.
    js = (ROOT / "frontend/accounts.js").read_text(encoding="utf-8")
    assert "${go(" not in js
    assert 'const go = (tab, label) => html`<button class="example" type="button" onClick=${() => onNavigate(tab)}>${label}</button>`;' in js
