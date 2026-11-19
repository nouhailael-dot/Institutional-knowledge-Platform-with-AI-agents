"""Usage, AI costs and reporting (multi-user Compass, Phase 5).

Costs come from stand-ins of the existing ledgers (collection_run, scrape_run, a
real map store file) and Ask's token usage; the report attributes them and must
add up to each ledger exactly. Synthetic users on the isolated local database
GHUS_ACCOUNTS_TEST_DATABASE_URL. Nothing reaches Supabase.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.app as app_module
from backend import accounts_admin, accounts_routes
from src.accounts import usage
from src.accounts.store import AccountsStore
from src.accounts.supabase_auth import AuthSettings, SupabaseAuth
from src.identity import signed_in_as
from src.map_agent.run_store import RunStore
from tests.accounts_fakes import JWT_SECRET, SERVICE_KEY, FakeGoTrue
from tests.accounts_ledgers import create_ledgers
from tests.test_accounts import _reset_schema

DB = os.environ.get("GHUS_ACCOUNTS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="GHUS_ACCOUNTS_TEST_DATABASE_URL is required")
SITE = "http://testserver"
H = {"Origin": SITE}
PASSWORD = "a long passphrase for compass 7"
PG = (DB or "").replace("postgresql+psycopg://", "postgresql://")
NOW = datetime.now(timezone.utc)


def _sql(query, *params):
    with psycopg.connect(PG, autocommit=True) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else None


class Bridge:
    configured = True

    def run_now(self, subscription_id, user=None):
        return {"started": True}


@pytest.fixture
def world(tmp_path, monkeypatch):
    _reset_schema(DB)
    create_ledgers(PG)
    gotrue = FakeGoTrue()
    store = AccountsStore(DB)
    accounts_routes.configure(
        auth=SupabaseAuth(AuthSettings(url="https://auth.example.test", anon_key="anon-test-key",
                                       service_role_key=SERVICE_KEY, jwt_secret=JWT_SECRET),
                          transport=gotrue.transport()),
        store=store)
    maps = RunStore(tmp_path / "runs.sqlite3")
    monkeypatch.setattr(app_module, "map_store", lambda: maps)
    monkeypatch.setattr(app_module, "discovery_bridge", lambda: Bridge())
    checks = {}

    def fake_check(actor_id, mode, payload):
        check_id = uuid.uuid4().hex
        checks[check_id] = actor_id
        return {"ok": True, "check_id": check_id, "cost_usd": 0.42, "actor_name": "Water Lab"}

    monkeypatch.setattr(app_module, "_actor_update_call", fake_check)
    app = FastAPI()
    app.include_router(accounts_routes.router)
    app.include_router(accounts_admin.router)
    for method, path, handler in [
        ("POST", "/api/discovery/requests/{subscription_id}/run", app_module.discovery_run_now),
        ("POST", "/api/discovery/actors/{actor_id}/check", app_module.discovery_actor_check),
        ("GET", "/api/account/usage", app_module.account_usage),
        ("GET", "/api/admin/usage", app_module.admin_usage),
        ("GET", "/api/admin/usage/export", app_module.admin_usage_export),
    ]:
        app.add_api_route(path, handler, methods=[method])
    app.middleware("http")(accounts_routes.require_account)
    yield {"app": app, "gotrue": gotrue, "store": store, "maps": maps, "checks": checks}
    accounts_routes.configure()


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


def _own(person, kind, entity_id, origin="requested"):
    _sql("INSERT INTO compass.record_owner (entity_type, entity_id, owner_user_id, origin) "
         "VALUES (%s, %s, %s::uuid, %s)", kind, str(entity_id), person["id"], origin)


def _request(owner=None, title="Water reuse"):
    sid = str(uuid.uuid4())
    _sql("INSERT INTO public.actor_update_subscription VALUES (%s, %s, 'active', NULL)", sid, title)
    if owner:
        _own(owner, "request", sid)
    return sid


def _run(*, sid=None, job="discovery_request", status="succeeded", cost=1.0, started=None, check_id=None,
         trigger="subscription"):
    rid = str(uuid.uuid4())
    started = started or NOW - timedelta(hours=1)
    _sql("INSERT INTO public.collection_run (collection_run_id, status, started_at, finished_at, job_name, "
         "trigger_type, spent_usd, config_snapshot) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
         rid, status, started, None if status == "running" else started + timedelta(minutes=4), job, trigger,
         cost, json.dumps({"check_id": check_id} if check_id else {}))
    if sid:
        _sql("INSERT INTO public.actor_update_subscription_run VALUES (%s, %s, false)", sid, rid)
    return rid


def _map(world, owner=None, *, calls=(), status="done", parent=None, starter=None):
    job = uuid.uuid4().hex
    with world["maps"].connect() as db:
        db.execute("INSERT INTO runs (id, description, status, stage, budget, created, updated) "
                   "VALUES (?, 'A map', ?, 'done', 2000000, ?, ?)", (job, status, NOW.timestamp(), NOW.timestamp()))
        for cost, reserved, finished in calls:
            db.execute("INSERT INTO calls (id, run_id, stage, model, status, reserved, cost, pricing, started, finished) "
                       "VALUES (?, ?, 'search', 'claude-sonnet-5', 'done', ?, ?, '{}', ?, ?)",
                       (uuid.uuid4().hex, job, reserved, cost, NOW.timestamp(), NOW.timestamp() if finished else None))
        if parent:
            db.execute("INSERT INTO people_tasks (run_id, parent_id, actor_key, request_key) VALUES (?, ?, 'a', ?)",
                       (job, parent, uuid.uuid4().hex))
    if owner:
        _own(owner, "map", job, "created")
    if starter:
        with signed_in_as(AccountsStore(DB).account(starter["id"])):
            from src.accounts import activity
            activity.record_usage("people_search", job, detail={"map_id": parent})
    return job


def _ops(world):
    with world["maps"].connect() as db:
        return usage.operations(world["store"], db)


def _op(ops, reference):
    return next(o for o in ops if o["reference"] == reference)


# --- attribution ----------------------------------------------------------------------------------

def test_scheduled_runs_go_to_the_request_owner_and_run_now_to_whoever_pressed_it(world):
    owner, presser = _member(world, name="Olga Owner"), _member(world, name="Pat Presser")
    sid = _request(owner)
    scheduled = _run(sid=sid, cost=1.25, started=NOW - timedelta(days=2))
    r = _client(world, presser).post(f"/api/discovery/requests/{sid}/run", headers=H)
    assert r.status_code == 200
    now = datetime.now(timezone.utc)        # when Run now was pressed (NOW is when the module loaded)
    pressed = _run(sid=sid, cost=0.75, started=now + timedelta(seconds=20))
    later = _run(sid=sid, cost=0.5, started=now + timedelta(hours=3))        # outside the window
    ops = _ops(world)
    assert (_op(ops, scheduled)["user"], _op(ops, scheduled)["trigger"]) == ("Olga Owner", "scheduled")
    assert (_op(ops, pressed)["user"], _op(ops, pressed)["trigger"]) == ("Pat Presser", "run_now")
    assert (_op(ops, later)["user"], _op(ops, later)["trigger"]) == ("Olga Owner", "scheduled")
    assert _op(ops, pressed)["feature"] == "Discovery requests"


def test_a_check_is_charged_once_whether_or_not_it_was_applied(world):
    checker = _member(world, name="Chen Checker")
    client = _client(world, checker)
    first = client.post("/api/discovery/actors/a1/check", json={}, headers=H).json()["check_id"]
    second = client.post("/api/discovery/actors/a2/check", json={}, headers=H).json()["check_id"]
    applied_run = _run(job="actor_update", trigger="manual", cost=0.40, check_id=second)
    ops = _ops(world)
    unapplied = _op(ops, first)
    assert (unapplied["source"], unapplied["cost_usd"], unapplied["user"]) == ("check_result", 0.42, "Chen Checker")
    assert unapplied["basis"] == "recorded by the check"
    assert not any(o["reference"] == second for o in ops)                  # the ledger run replaces it
    run = _op(ops, applied_run)
    assert (run["cost_usd"], run["user"], run["feature"]) == (0.40, "Chen Checker", "Organization checks and Deep Pull")


def test_data_feed_costs_go_to_who_started_the_completion_else_the_importer(world):
    importer, completer = _member(world, name="Ivy"), _member(world, name="Cam")
    plain, completed, old = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    for run, cost in ((plain, 0.3), (completed, 1.1), (old, 0.9)):
        _sql("INSERT INTO public.scrape_run VALUES (%s, 'ghus_data_feed', 'succeeded', %s, %s, %s)",
             run, NOW, NOW, cost)
    _own(importer, "import", plain, "imported")
    _own(importer, "import", completed, "imported")
    with signed_in_as(world["store"].account(completer["id"])):
        from src.accounts import activity
        activity.record_usage("datafeed_completion", completed)
    ops = _ops(world)
    assert _op(ops, plain)["user"] == "Ivy" and _op(ops, completed)["user"] == "Cam"
    assert _op(ops, old)["user"] == usage.NOT_RECORDED and _op(ops, old)["user_id"] is None


def test_map_costs_go_to_the_owner_and_people_searches_to_their_starter_without_double_counting(world):
    owner, starter = _member(world, name="Mia Mapper"), _member(world, name="Sam Searcher")
    parent = _map(world, owner, calls=[(500_000, 600_000, True), (250_000, 300_000, True)])
    child = _map(world, None, calls=[(100_000, 120_000, True)], parent=parent, starter=starter)
    ops = _ops(world)
    assert (_op(ops, parent)["cost_usd"], _op(ops, parent)["user"]) == (0.75, "Mia Mapper")
    assert (_op(ops, child)["cost_usd"], _op(ops, child)["user"], _op(ops, child)["feature"]) == \
        (0.10, "Sam Searcher", "People search")
    assert round(sum(o["cost_usd"] for o in ops if o["source"] == "map_calls"), 6) == 0.85


def test_failed_interrupted_and_unfinished_costs_are_kept_and_labelled(world):
    owner = _member(world)
    sid = _request(owner)
    failed = _run(sid=sid, status="failed", cost=0.33)
    running = _run(sid=sid, status="running", cost=0.12)
    stopped = _map(world, owner, calls=[(200_000, 250_000, True)], status="interrupted")
    open_call = _map(world, owner, calls=[(None, 300_000, False)], status="running")
    ops = _ops(world)
    assert (_op(ops, failed)["cost_usd"], _op(ops, failed)["basis"]) == (0.33, "partial run")
    assert (_op(ops, running)["cost_usd"], _op(ops, running)["basis"]) == (0.12, "in progress")
    assert (_op(ops, stopped)["cost_usd"], _op(ops, stopped)["basis"]) == (0.2, "partial run")
    assert (_op(ops, open_call)["cost_usd"], _op(ops, open_call)["basis"]) == (0.3, "estimate (calls still running)")
    totals = usage.summary(ops)["total"]
    assert totals["not_final_usd"] == round(0.33 + 0.12 + 0.2 + 0.3, 6)


def test_historical_runs_without_an_owner_are_not_recorded(world):
    _member(world)
    orphan_request = _request(None)
    run = _run(sid=orphan_request, cost=2.0, started=NOW - timedelta(days=60))
    manual = _run(job="actor_update", trigger="manual", cost=0.2, check_id="unknowncheck")
    old_map = _map(world, None, calls=[(400_000, 400_000, True)])
    ops = _ops(world)
    for ref in (run, manual, old_map):
        assert _op(ops, ref)["user"] == usage.NOT_RECORDED and _op(ops, ref)["attributed_because"] is None
    assert usage.summary(usage.filtered(ops, unattributed=True))["total"]["cost_usd"] == 2.6


def test_ask_answers_record_tokens_and_a_cost_only_when_the_model_has_a_price(world, monkeypatch):
    asker = _member(world, name="Ada Asker")
    account = world["store"].account(asker["id"])

    def fake_stream(question, hits, on_usage=None):
        yield "An answer."
        on_usage(model, SimpleNamespace(input_tokens=1200, output_tokens=300))

    monkeypatch.setattr(app_module, "stream_answer", fake_stream)
    monkeypatch.setattr(app_module, "plan", lambda q: ("semantic", None))
    monkeypatch.setattr(app_module, "retrieve", lambda q, **kw: [{"name": "x"}])
    monkeypatch.setattr(app_module, "_parked_hits", lambda q, hits: [])
    monkeypatch.setattr(app_module, "_sources", lambda hits: [])

    async def drain(response):
        return [chunk async for chunk in response.body_iterator]

    for model in ("claude-sonnet-5", "claude-opus-4-8"):
        with signed_in_as(account):
            response = app_module.ask_stream(question="Who works on water?", doc_id=None, history=None)
        asyncio.run(drain(response))
    asks = sorted((o for o in _ops(world) if o["source"] == "ask_usage"), key=lambda o: o["cost_usd"], reverse=True)
    priced, unpriced = asks
    assert (priced["user"], priced["tokens"], priced["basis"]) == ("Ada Asker", 1500, "priced from tokens")
    assert priced["cost_usd"] == round((1200 * 2 + 300 * 10) / 1_000_000, 6)
    assert (unpriced["cost_usd"], unpriced["basis"]) == (0, "unknown (no price)")


def test_people_running_agents_at_the_same_time_are_each_charged_their_own(world):
    people = [_member(world, name=f"Runner {i}") for i in range(3)]
    requests = [_request(None, f"Request {i}") for i in range(3)]
    clients = [_client(world, p) for p in people]
    barrier = threading.Barrier(3)

    def press(i):
        barrier.wait()
        assert clients[i].post(f"/api/discovery/requests/{requests[i]}/run", headers=H).status_code == 200

    threads = [threading.Thread(target=press, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    runs = [_run(sid=requests[i], cost=0.1 * (i + 1), started=datetime.now(timezone.utc) + timedelta(seconds=5))
            for i in range(3)]
    ops = _ops(world)
    assert [_op(ops, runs[i])["user"] for i in range(3)] == ["Runner 0", "Runner 1", "Runner 2"]


# --- reports, permissions, exports ------------------------------------------------------------------

def _seed_report(world):
    ana, bob = _member(world, name="Ana"), _member(world, name="Bob")
    sid = _request(ana)
    _run(sid=sid, cost=1.0, started=NOW - timedelta(days=40))
    _run(sid=sid, cost=2.0)
    _run(sid=_request(None), cost=0.5)
    _map(world, bob, calls=[(300_000, 300_000, True)])
    return ana, bob


def test_totals_reconcile_with_every_ledger(world):
    _seed_report(world)
    _sql("INSERT INTO public.scrape_run VALUES (%s, 'ghus_data_feed', 'succeeded', %s, %s, 0.7)",
         str(uuid.uuid4()), NOW, NOW)
    ops = _ops(world)
    with world["maps"].connect() as db:
        rows = usage.reconcile(world["store"], ops, db)
    assert {r["ledger"]: r["difference_usd"] for r in rows} == {
        "Discovery, Update and check runs": 0, "Data Feed runs": 0, "Map and people-search calls": 0}
    runs = next(r for r in rows if r["ledger"].startswith("Discovery"))
    assert (runs["ledger_total_usd"], runs["attributed_usd"], runs["not_recorded_usd"]) == (3.5, 3.0, 0.5)
    ledger_sum = float(_sql("SELECT sum(spent_usd) FROM public.collection_run")[0][0])
    assert round(sum(o["cost_usd"] for o in ops if o["source"] == "collection_run"), 6) == ledger_sum


def test_people_see_only_their_own_usage_and_only_admins_see_everyones(world):
    ana, bob = _seed_report(world)
    viewer = _member(world, "viewer", name="Vic")
    mine = _client(world, ana).get("/api/account/usage").json()
    assert mine["this_month"]["cost_usd"] == 2.0
    assert sum(h["cost_usd"] for h in mine["history"]) == 3.0
    assert all(o["user"] == "Ana" for o in mine["recent"])
    assert _client(world, viewer).get("/api/account/usage").json()["this_month"]["cost_usd"] == 0
    for person in (ana, viewer):
        assert _client(world, person).get("/api/admin/usage").status_code == 403
        assert _client(world, person).get("/api/admin/usage/export").status_code == 403
    admin = _client(world, _member(world, "admin"))
    report = admin.get("/api/admin/usage").json()
    assert report["summary"]["total"]["cost_usd"] == 3.8
    assert report["not_recorded"]["cost_usd"] == 0.5
    assert set(report["summary"]["by_user"]) == {"Ana", "Bob", usage.NOT_RECORDED}
    only_bob = admin.get(f"/api/admin/usage?user_id={bob['id']}").json()
    assert only_bob["summary"]["total"]["cost_usd"] == 0.3
    month = NOW.strftime("%Y-%m")
    this_month = admin.get(f"/api/admin/usage?since={month}&until={month}").json()
    assert this_month["summary"]["total"]["cost_usd"] == 2.8
    assert admin.get("/api/admin/usage?since=2026-13").status_code == 422


def test_exports_in_csv_and_excel(world):
    _seed_report(world)
    admin = _client(world, _member(world, "admin"))
    csv_r = admin.get("/api/admin/usage/export?format=csv")
    assert csv_r.status_code == 200 and "attachment" in csv_r.headers["content-disposition"]
    lines = csv_r.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0].startswith("month,started_at,feature,user") and len(lines) == 5
    xlsx = admin.get("/api/admin/usage/export?format=xlsx")
    from openpyxl import load_workbook
    book = load_workbook(io.BytesIO(xlsx.content))
    assert book.sheetnames == ["Operations", "By person and month", "By feature"]
    assert book["Operations"].max_row == 5


def test_usage_survives_a_restart(world):
    ana, _ = _seed_report(world)
    with world["maps"].connect() as db:
        before = usage.summary(usage.operations(world["store"], db))
        after = usage.summary(usage.operations(AccountsStore(DB), db))           # a new process
    assert before == after and before["by_user"]["Ana"]["cost_usd"] == 3.0
