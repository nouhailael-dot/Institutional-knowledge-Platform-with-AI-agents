"""Individual accounts, roles and permissions (multi-user Compass, Phase 1).

Synthetic accounts only, on an isolated local database
(GHUS_ACCOUNTS_TEST_DATABASE_URL, a local database whose name ends in _test),
with a stand-in for Supabase Auth (tests/accounts_fakes.py). Nothing reaches
Supabase.
"""

from __future__ import annotations

import os
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend import accounts_routes
from src.accounts import permissions
from src.accounts.permissions import DEFAULT_ROLES, PERMISSIONS, PUBLIC, SIGNED_IN, permission_for
from src.accounts.store import AccountsStore
from src.accounts.supabase_auth import AuthSettings, SupabaseAuth
from src.accounts.tokens import InvalidToken, make_access_token, sign, verify_access_token
from src.identity import NO_SIGN_IN_YET, current_user, current_user_id
from tests.accounts_fakes import JWT_SECRET, FakeGoTrue

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "ghus-backend/migrations/proposed/deferred/700_compass_accounts.sql"
DB = os.environ.get("GHUS_ACCOUNTS_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="GHUS_ACCOUNTS_TEST_DATABASE_URL is required")
PASSWORD = "correct horse battery staple"
SITE = "http://testserver"


# --- the permission catalogue and route policy (no database) -----------------------

def _seeded_matrix() -> tuple[set[str], dict[str, set[str]]]:
    sql = MIGRATION.read_text(encoding="utf-8")
    perms = set(re.findall(r"\('([a-z_]+\.[a-z_]+)',\s*'", sql))
    roles = {"admin": set(perms), "editor": set(), "viewer": set()}
    for role, perm in re.findall(r"\('(editor|viewer)', '([a-z_]+\.[a-z_]+)'\)", sql):
        roles[role].add(perm)
    return perms, roles


def test_the_code_and_the_migration_agree_on_permissions_and_roles():
    perms, roles = _seeded_matrix()
    assert perms == set(PERMISSIONS)
    assert {k: set(v) for k, v in DEFAULT_ROLES.items()} == roles


def test_the_three_roles_follow_the_brief():
    admin, editor, viewer = DEFAULT_ROLES["admin"], DEFAULT_ROLES["editor"], DEFAULT_ROLES["viewer"]
    assert {"users.manage", "settings.admin", "usage.view_all", "audit.view_all"} <= admin
    assert not editor & {"users.manage", "settings.admin", "usage.view_all", "audit.view_all"}
    assert {"requests.create", "datafeed.import", "records.edit", "notes.write", "review.decide",
            "records.delete_permanent", "usage.view_own"} <= editor
    assert viewer == {"records.view", "ask.use", "maps.view", "dashboard.view", "usage.view_own"}
    paid = {"maps.create", "requests.create"}
    assert not viewer & paid


def test_every_route_of_the_app_has_a_policy():
    # A new route without a policy would be refused for everyone; this names it.
    import backend.app as app_module
    from fastapi.routing import APIRoute

    missing = []
    for route in app_module.app.routes:
        if isinstance(route, APIRoute):
            sample = re.sub(r"\{[^}]+\}", "x", route.path)
            for method in route.methods:
                if permission_for(method, sample) is None:
                    missing.append(f"{method} {route.path}")
    assert missing == []


@pytest.mark.parametrize("method, path, expected", [
    ("GET", "/api/health", PUBLIC),
    ("POST", "/api/auth/login", PUBLIC),
    ("GET", "/", SIGNED_IN),
    ("GET", "/review.js", SIGNED_IN),
    ("HEAD", "/api/browse/actors", "records.view"),
    ("POST", "/api/browse/actors/abc/remove", "records.remove"),
    ("POST", "/api/browse/events/abc/edit", "records.edit"),
    ("POST", "/api/discovery/requests/abc/run", "requests.create"),
    ("POST", "/api/map", "maps.create"),
    ("POST", "/api/map/abc/save", "review.decide"),
    ("PATCH", "/api/review/candidates/abc", "review.decide"),
    ("GET", "/api/datafeed/templates/actor.xlsx", "datafeed.import"),
    ("GET", "/api/not-a-route", None),
    ("DELETE", "/api/browse/actors", None),
    ("GET", "/../etc/passwd", None),
])
def test_route_policy(method, path, expected):
    assert permission_for(method, path) == expected


# --- tokens -----------------------------------------------------------------------

def _claims(**extra):
    return {"sub": "u1", "aud": "authenticated", "exp": time.time() + 600, **extra}


def test_a_valid_token_is_accepted():
    assert verify_access_token(make_access_token(_claims(), JWT_SECRET), JWT_SECRET)["sub"] == "u1"


@pytest.mark.parametrize("token, words", [
    (lambda: make_access_token(_claims(exp=time.time() - 120), JWT_SECRET), "expired"),
    (lambda: make_access_token(_claims(), "another-secret"), "bad signature"),
    (lambda: make_access_token(_claims(aud="anon"), JWT_SECRET), "audience"),
    (lambda: make_access_token({"aud": "authenticated", "exp": time.time() + 60}, JWT_SECRET), "subject"),
    (lambda: "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ1MSJ9.", "algorithm"),
    (lambda: "not-a-token", "malformed"),
])
def test_forged_or_stale_tokens_are_refused(token, words):
    with pytest.raises(InvalidToken, match=words):
        verify_access_token(token(), JWT_SECRET)


# --- the sign-in middleware, end to end -------------------------------------------------

def _reset_schema(conninfo: str) -> None:
    parts = urlsplit(conninfo.replace("postgresql+psycopg://", "postgresql://"))
    assert parts.hostname in {"127.0.0.1", "localhost"} and parts.path.rstrip("/").endswith("_test"), \
        "the accounts tests only ever reset a local *_test database"
    with psycopg.connect(conninfo.replace("postgresql+psycopg://", "postgresql://"), autocommit=True) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS auth")
        conn.execute("CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY, email text)")
        conn.execute("DROP SCHEMA IF EXISTS compass CASCADE")
        conn.execute(MIGRATION.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def world():
    if not DB:
        pytest.skip("GHUS_ACCOUNTS_TEST_DATABASE_URL is required")
    _reset_schema(DB)
    gotrue = FakeGoTrue()
    store = AccountsStore(DB)
    auth = SupabaseAuth(AuthSettings(url="https://auth.example.test", anon_key="anon-test-key",
                                     service_role_key="", jwt_secret=JWT_SECRET),
                        transport=gotrue.transport())
    accounts_routes.configure(auth=auth, store=store)

    app = FastAPI()
    app.include_router(accounts_routes.router)

    @app.get("/")
    def home():
        return {"page": "workspace"}

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/browse/actors")
    def browse():
        return {"who": current_user(), "id": current_user_id()}

    @app.post("/api/browse/{kind}/{record_id}/edit")
    async def edit(kind: str, record_id: str, request: Request):
        sent = await request.json()       # a "reviewer" or "user_id" sent here is ignored
        return {"who": current_user(), "id": current_user_id(), "sent": sent}

    @app.post("/api/discovery/requests")
    def create_request():
        return {"who": current_user()}

    @app.get("/api/review/candidates")
    def review():
        return {"who": current_user()}

    @app.get("/api/not-in-the-policy")
    def unlisted():
        return {"leak": True}

    app.middleware("http")(accounts_routes.require_account)
    yield {"app": app, "gotrue": gotrue, "store": store}
    accounts_routes.configure()


def _account(world, *, role: str | None, status: str = "active", name: str | None = None) -> dict:
    email = f"{uuid.uuid4().hex[:10]}@example.test"
    user_id = world["gotrue"].add_user(email, PASSWORD)
    name = name or f"Test {role or 'none'} {email[:4]}"
    with psycopg.connect(DB.replace("postgresql+psycopg://", "postgresql://"), autocommit=True) as conn:
        conn.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s)", (user_id, email))
        conn.execute(
            "INSERT INTO compass.user_profile (user_id, email, full_name, role_code, status, deactivated_at) "
            "VALUES (%s, %s, %s, %s, %s, CASE WHEN %s = 'deactivated' THEN now() END)",
            (user_id, email, name, role, status, status))
    return {"id": user_id, "email": email, "name": name}


def _client(world) -> TestClient:
    return TestClient(world["app"], base_url=SITE)


def _signed_in(world, person) -> TestClient:
    client = _client(world)
    response = client.post("/api/auth/login", json={"email": person["email"], "password": PASSWORD},
                           headers={"Origin": SITE})
    assert response.status_code == 200, response.text
    return client


def _sql(query, *params):
    with psycopg.connect(DB.replace("postgresql+psycopg://", "postgresql://")) as conn:
        return conn.execute(query, params).fetchall()


@needs_db
def test_sign_in_sets_http_only_cookies_and_acts_as_that_person(world):
    editor = _account(world, role="editor", name="Amina Editor")
    client = _client(world)
    response = client.post("/api/auth/login", json={"email": editor["email"].upper(), "password": PASSWORD},
                           headers={"Origin": SITE})
    assert response.status_code == 200
    cookies = response.headers.get_list("set-cookie")
    assert all("httponly" in c.lower() and "samesite=lax" in c.lower() for c in cookies)
    assert {c.split("=")[0] for c in cookies} == {"compass_at", "compass_rt", "compass_since"}
    assert "access_token" not in response.text and "refresh" not in response.text
    me = client.get("/api/auth/me").json()["account"]
    assert (me["full_name"], me["role"]) == ("Amina Editor", "editor")
    assert "review.decide" in me["permissions"] and "users.manage" not in me["permissions"]
    assert client.get("/api/browse/actors").json() == {"who": "Amina Editor", "id": editor["id"]}
    assert _sql("SELECT last_login_at IS NOT NULL FROM compass.user_profile WHERE user_id=%s::uuid",
                editor["id"]) == [(True,)]
    assert _sql("SELECT action FROM compass.audit_event WHERE user_id=%s::uuid", editor["id"]) \
        == [("auth.login",)]


@needs_db
def test_each_role_gets_exactly_its_permissions(world):
    viewer = _signed_in(world, _account(world, role="viewer"))
    editor = _signed_in(world, _account(world, role="editor"))
    admin = _signed_in(world, _account(world, role="admin"))
    checks = [("get", "/api/browse/actors", {}), ("post", "/api/browse/actors/x/edit", {"json": {}}),
              ("post", "/api/discovery/requests", {}), ("get", "/api/review/candidates", {})]
    expected = {"viewer": [200, 403, 403, 403], "editor": [200, 200, 200, 200], "admin": [200, 200, 200, 200]}
    for name, client in (("viewer", viewer), ("editor", editor), ("admin", admin)):
        got = [getattr(client, m)(p, headers={"Origin": SITE}, **kw).status_code for m, p, kw in checks]
        assert got == expected[name], name
    assert viewer.post("/api/browse/actors/x/edit", json={}, headers={"Origin": SITE}).json()["detail"] \
        == "Your role does not allow this."


@needs_db
@pytest.mark.parametrize("role, status", [(None, "active"), ("editor", "invited"), ("admin", "deactivated")])
def test_no_role_an_unaccepted_invitation_or_a_deactivated_account_cannot_sign_in(world, role, status):
    person = _account(world, role=role, status=status)
    response = _client(world).post("/api/auth/login", json={"email": person["email"], "password": PASSWORD},
                                   headers={"Origin": SITE})
    assert response.status_code == 403 and "not active" in response.json()["detail"]
    assert "set-cookie" not in response.headers
    assert _sql("SELECT action FROM compass.audit_event WHERE user_id=%s::uuid", person["id"]) \
        == [("auth.login_refused",)]


@needs_db
def test_deactivating_someone_ends_their_access_at_once(world):
    person = _account(world, role="editor")
    client = _signed_in(world, person)
    assert client.get("/api/browse/actors").status_code == 200
    _sql("UPDATE compass.user_profile SET status='deactivated', deactivated_at=now() "
         "WHERE user_id=%s::uuid RETURNING 1", person["id"])
    world["store"].forget(person["id"])
    response = client.get("/api/browse/actors")
    assert response.status_code == 403 and "not active" in response.json()["detail"]


@needs_db
def test_requests_without_a_session_are_refused_and_pages_go_to_sign_in(world):
    client = _client(world)
    assert client.get("/api/health").json() == {"ok": True}
    assert client.get("/api/browse/actors").status_code == 401
    page = client.get("/?tab=review", follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"] == "/login?next=%2F%3Ftab%3Dreview"
    signed = _signed_in(world, _account(world, role="admin"))
    assert signed.get("/api/not-in-the-policy").status_code == 403      # fail closed, even for admins


@needs_db
def test_wrong_passwords_are_limited(world):
    person = _account(world, role="editor")
    client = _client(world)
    for attempt in range(5):
        r = client.post("/api/auth/login", json={"email": person["email"], "password": f"wrong-{attempt}"},
                        headers={"Origin": SITE})
        assert r.status_code == 401 and r.json()["detail"] == "Wrong email or password."
    locked = client.post("/api/auth/login", json={"email": person["email"], "password": PASSWORD},
                         headers={"Origin": SITE})
    assert locked.status_code == 429 and "Retry-After" in locked.headers
    assert _sql("SELECT count(*) FROM compass.audit_event WHERE action='auth.login_failed' "
                "AND user_label=%s", person["email"]) == [(5,)]


@needs_db
def test_an_expired_access_token_is_renewed_quietly_and_sign_out_ends_the_session(world):
    person = _account(world, role="editor")
    world["gotrue"].ttl = -120               # the first token is already expired
    client = _signed_in(world, person)
    world["gotrue"].ttl = 3600
    old = client.cookies.get("compass_at")
    response = client.get("/api/browse/actors")
    assert response.status_code == 200 and response.json()["id"] == person["id"]
    assert client.cookies.get("compass_at") != old            # renewed in place
    stolen = dict(client.cookies)
    assert client.post("/api/auth/logout", headers={"Origin": SITE}).status_code == 200
    assert client.get("/api/browse/actors").status_code == 401
    replay = _client(world)                                    # cookies copied before sign-out
    for key, value in stolen.items():
        replay.cookies.set(key, value)
    refused = replay.get("/api/browse/actors")                # the access token was still fresh
    assert refused.status_code == 401 and "signed out" in refused.json()["detail"]
    actions = [a for (a,) in _sql("SELECT action FROM compass.audit_event WHERE user_id=%s::uuid "
                                  "ORDER BY audit_id", person["id"])]
    assert actions == ["auth.login", "auth.logout"]
    world["gotrue"].ttl = 3600


@needs_db
def test_a_revoked_refresh_token_cannot_bring_a_session_back(world):
    person = _account(world, role="editor")
    world["gotrue"].ttl = -120
    client = _signed_in(world, person)
    world["gotrue"].ttl = 3600
    world["gotrue"].refresh_tokens.clear()                    # signed out elsewhere
    response = client.get("/api/browse/actors")
    assert response.status_code == 401 and "ended" in response.json()["detail"]
    assert client.cookies.get("compass_at") is None            # cookies cleared


@needs_db
def test_a_session_ends_after_its_maximum_age_and_its_start_cannot_be_forged(world, monkeypatch):
    client = _signed_in(world, _account(world, role="editor"))
    monkeypatch.setenv("GHUS_SESSION_MAX_HOURS", "1")
    old = str(int(time.time()) - 2 * 3600)
    client.cookies.set("compass_since", sign(old, accounts_routes.session_key()))
    assert client.get("/api/browse/actors").status_code == 401
    forged = _signed_in(world, _account(world, role="editor"))
    forged.cookies.set("compass_since", f"{int(time.time())}.forged")
    assert forged.get("/api/browse/actors").status_code == 401


@needs_db
def test_changes_from_another_site_are_refused(world):
    person = _account(world, role="admin")
    client = _signed_in(world, person)
    evil = {"Origin": "https://evil.example"}
    assert client.post("/api/browse/actors/x/edit", json={}, headers=evil).status_code == 403
    assert _client(world).post("/api/auth/login", json={"email": person["email"], "password": PASSWORD},
                               headers=evil).status_code == 403


@needs_db
def test_nobody_can_act_as_someone_else_through_the_request(world):
    me, other = _account(world, role="editor", name="Me Myself"), _account(world, role="admin")
    client = _signed_in(world, me)
    body = {"reviewer": "Someone Else", "user_id": other["id"], "decided_by": other["email"]}
    answer = client.post("/api/browse/actors/x/edit", json=body,
                         headers={"Origin": SITE, "X-User-Id": other["id"]}).json()
    assert (answer["who"], answer["id"]) == ("Me Myself", me["id"])
    # A token minted with another secret, claiming the admin's id, is refused.
    forged = _client(world)
    forged.cookies.set("compass_at", make_access_token(
        {"sub": other["id"], "aud": "authenticated", "exp": time.time() + 600}, "not-the-secret"))
    forged.cookies.set("compass_rt", "nothing")
    forged.cookies.set("compass_since", sign(str(int(time.time())), accounts_routes.session_key()))
    assert forged.get("/api/browse/actors").status_code == 401


@needs_db
def test_two_people_working_at_the_same_time_each_act_as_themselves(world):
    people = [_account(world, role="editor", name=f"Worker {i}") for i in range(2)]
    clients = [_signed_in(world, p) for p in people]
    seen: list[tuple[str, str]] = []
    lock = threading.Lock()

    def work(i):
        for _ in range(15):
            who = clients[i].get("/api/browse/actors").json()["who"]
            with lock:
                seen.append((people[i]["name"], who))

    threads = [threading.Thread(target=work, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(seen) == 30 and all(expected == got for expected, got in seen)


def test_outside_a_request_nobody_is_signed_in():
    assert (current_user(), current_user_id()) == (NO_SIGN_IN_YET, None)


def test_the_shared_login_stays_the_default():
    # Without GHUS_AUTH_MODE=supabase the deployed behaviour is unchanged.
    import backend.app as app_module

    assert os.environ.get("GHUS_AUTH_MODE", "") != "supabase"
    assert not accounts_routes.accounts_enabled()
    source = (ROOT / "backend/app.py").read_text(encoding="utf-8")
    assert "app.middleware(\"http\")(require_login)" in source
    assert not any(getattr(r, "path", "") == "/api/auth/login" for r in app_module.app.routes)
