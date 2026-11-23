"""Invitations, password setup and reset, profiles, user management, first
administrator (multi-user Compass, Phase 2).

Synthetic users only, on the isolated local database
GHUS_ACCOUNTS_TEST_DATABASE_URL, with the Supabase Auth stand-in. Nothing
reaches Supabase; no email is sent anywhere (the stand-in keeps an outbox).
"""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import accounts_admin, accounts_routes
from src.accounts.bootstrap import bootstrap_admin
from src.accounts.store import AccountsStore
from src.accounts.supabase_auth import AuthSettings, SupabaseAuth
from src.identity import current_user
from tests.accounts_fakes import JWT_SECRET, SERVICE_KEY, FakeGoTrue
from tests.test_accounts import _reset_schema

DB = os.environ.get("GHUS_ACCOUNTS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="GHUS_ACCOUNTS_TEST_DATABASE_URL is required")
SITE = "http://testserver"
H = {"Origin": SITE}
STRONG = "a long passphrase for compass 7"
PG = (DB or "").replace("postgresql+psycopg://", "postgresql://")


def _sql(query, *params):
    with psycopg.connect(PG, autocommit=True) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else None


@pytest.fixture(scope="module")
def world():
    _reset_schema(DB)
    gotrue = FakeGoTrue(on_create=lambda uid, email: _sql(
        "INSERT INTO auth.users (id, email) VALUES (%s, %s)", uid, email))
    store = AccountsStore(DB)
    auth = SupabaseAuth(AuthSettings(url="https://auth.example.test", anon_key="anon-test-key",
                                     service_role_key=SERVICE_KEY, jwt_secret=JWT_SECRET),
                        transport=gotrue.transport())
    accounts_routes.configure(auth=auth, store=store)
    app = FastAPI()
    app.include_router(accounts_routes.router)
    app.include_router(accounts_admin.router)

    @app.get("/api/browse/actors")
    def browse():
        return {"who": current_user()}

    @app.get("/api/review/candidates")
    def review():
        return {"who": current_user()}

    app.middleware("http")(accounts_routes.require_account)
    yield {"app": app, "gotrue": gotrue, "store": store, "auth": auth}
    accounts_routes.configure()


@pytest.fixture(autouse=True)
def fresh_limits():
    for limiter in (accounts_admin.RECOVERY_PER_EMAIL, accounts_admin.RECOVERY_PER_CLIENT,
                    accounts_admin.LINK_ATTEMPTS, accounts_admin.INVITES_PER_ADMIN):
        limiter._seen.clear()
    from backend.access import FAILURES
    FAILURES._seen.clear()


def _email() -> str:
    return f"{uuid.uuid4().hex[:10]}@example.test"


def _member(world, role="admin", name=None, status="active") -> dict:
    email = _email()
    uid = world["gotrue"].add_user(email, STRONG)
    _sql("INSERT INTO auth.users (id, email) VALUES (%s, %s)", uid, email)
    _sql("INSERT INTO compass.user_profile (user_id, email, full_name, role_code, status, deactivated_at) "
         "VALUES (%s, %s, %s, %s, %s, CASE WHEN %s = 'deactivated' THEN now() END)",
         uid, email, name or f"Synthetic {role}", role, status, status)
    return {"id": uid, "email": email, "name": name or f"Synthetic {role}"}


def _client(world) -> TestClient:
    return TestClient(world["app"], base_url=SITE)


def _signed_in(world, person, password=STRONG) -> TestClient:
    client = _client(world)
    r = client.post("/api/auth/login", json={"email": person["email"], "password": password}, headers=H)
    assert r.status_code == 200, r.text
    return client


def _invite(admin_client, email, role="editor", name="Invited Person"):
    return admin_client.post("/api/admin/invitations", json={"email": email, "full_name": name, "role": role},
                             headers=H)


def _actions(user_id):
    return [a for (a,) in _sql("SELECT action FROM compass.audit_event WHERE entity_id=%s "
                               "OR user_id::text=%s ORDER BY audit_id", user_id, user_id)]


# --- invitations ---------------------------------------------------------------------

def test_an_admin_invites_and_the_person_accepts_with_their_own_password(world):
    admin = _signed_in(world, _member(world, "admin", "Ana Admin"))
    email = _email()
    r = _invite(admin, email, "editor", "Bilal Editor")
    assert r.status_code == 200, r.text
    user_id = r.json()["user"]["user_id"]
    assert r.json()["user"]["status"] == "invited" and r.json()["user"]["invitation"]["state"] == "open"
    mail = world["gotrue"].outbox[-1]
    assert (mail["to"], mail["type"], mail["redirect_to"]) == (email, "invite", f"{SITE}/accept")
    # Not usable before acceptance.
    assert _client(world).post("/api/auth/login", json={"email": email, "password": STRONG},
                               headers=H).status_code == 401
    person = _client(world)
    weak = person.post("/api/auth/accept", json={"token_hash": mail["token_hash"], "password": "short",
                                             "email": email}, headers=H)
    assert weak.status_code == 422                       # refused before the single-use link is spent
    done = person.post("/api/auth/accept", json={"token_hash": mail["token_hash"], "password": STRONG,
                                                 "email": email.upper(), "full_name": "Bilal B. Editor"},
                       headers=H)
    assert done.status_code == 200, done.text
    assert done.json()["account"]["role"] == "editor"
    assert person.get("/api/review/candidates").json() == {"who": "Bilal B. Editor"}
    again = _client(world).post("/api/auth/accept", json={"token_hash": mail["token_hash"], "password": STRONG,
                                                      "email": email},
                                headers=H)
    assert again.status_code == 400 and "already used" in again.json()["detail"]
    assert _client(world).post("/api/auth/login", json={"email": email, "password": STRONG},
                               headers=H).status_code == 200
    assert {"invitation.created", "invitation.accepted"} <= set(_actions(user_id))


def test_the_invitation_page_asks_for_the_invited_email(world):
    """23 Nov 2026: the page asks for the email instead of the name, and it must match."""
    admin = _signed_in(world, _member(world, "admin"))
    email = _email()
    assert _invite(admin, email, "viewer").status_code == 200
    link = world["gotrue"].last_link(email, "invite")
    missing = _client(world).post("/api/auth/accept", json={"token_hash": link, "password": STRONG}, headers=H)
    assert missing.status_code == 422 and "email" in missing.json()["detail"]   # the link is not spent
    other = _client(world).post("/api/auth/accept", json={"token_hash": link, "password": STRONG,
                                                          "email": _email()}, headers=H)
    assert other.status_code == 422 and "different email" in other.json()["detail"]
    # Refused before the password was set: the invitation stays open and nobody can sign in.
    assert world["gotrue"].users[email]["password"] is None
    row = next(u for u in admin.get("/api/admin/users").json()["users"] if u["email"] == email)
    assert row["status"] == "invited"
    page = _client(world).get("/accept").text
    assert 'id="accept-email" type="email"' in page and "accept-name" not in page


def test_duplicate_and_invalid_invitations_are_refused_before_any_email(world):
    admin = _signed_in(world, _member(world, "admin"))
    existing = _member(world, "viewer")
    sent = len(world["gotrue"].outbox)
    assert _invite(admin, existing["email"]).status_code == 409
    email = _email()
    assert _invite(admin, email).status_code == 200
    second = _invite(admin, email.upper())
    assert second.status_code == 409 and "still open" in second.json()["detail"]
    assert _invite(admin, "not-an-email").status_code == 422
    assert _invite(admin, _email(), role="pirate").status_code == 400
    assert len(world["gotrue"].outbox) == sent + 1


def test_an_expired_invitation_cannot_be_accepted_but_can_be_resent(world):
    admin = _signed_in(world, _member(world, "admin"))
    email = _email()
    r = _invite(admin, email, "viewer")
    user_id, invitation_id = r.json()["user"]["user_id"], r.json()["invitation"]["invitation_id"]
    link = world["gotrue"].last_link(email, "invite")
    _sql("UPDATE compass.invitation SET created_at = now() - interval '9 days', "
         "expires_at = now() - interval '2 days' WHERE invitation_id = %s", invitation_id)
    late = _client(world).post("/api/auth/accept", json={"token_hash": link, "password": STRONG, "email": email},
                               headers=H)
    assert late.status_code == 403 and "expired" in late.json()["detail"]
    row = next(u for u in admin.get("/api/admin/users").json()["users"] if u["user_id"] == user_id)
    assert row["status_label"] == "invitation expired"
    resent = admin.post(f"/api/admin/invitations/{invitation_id}/resend", headers=H)
    assert resent.status_code == 200, resent.text
    # The first link was opened, so Supabase Auth will not re-invite: a recovery link completes it.
    mail = world["gotrue"].outbox[-1]
    assert mail["to"] == email and mail["type"] == "recovery"
    done = _client(world).post("/api/auth/reset", json={"token_hash": mail["token_hash"], "password": STRONG},
                               headers=H)
    assert done.status_code == 200, done.text and done.json()["account"]["role"] == "viewer"
    assert {"invitation.refused", "invitation.resent", "invitation.accepted"} <= set(_actions(user_id))


def test_a_revoked_invitation_cannot_be_accepted(world):
    admin = _signed_in(world, _member(world, "admin"))
    email = _email()
    r = _invite(admin, email)
    link = world["gotrue"].last_link(email, "invite")
    assert admin.post(f"/api/admin/invitations/{r.json()['invitation']['invitation_id']}/revoke",
                      headers=H).status_code == 200
    refused = _client(world).post("/api/auth/accept", json={"token_hash": link, "password": STRONG, "email": email},
                                  headers=H)
    assert refused.status_code == 403 and "withdrawn" in refused.json()["detail"]
    # The invitation is checked before the password is set, so none was: sign-in fails.
    assert _client(world).post("/api/auth/login", json={"email": email, "password": STRONG},
                               headers=H).status_code == 401
    assert world["gotrue"].users[email]["password"] is None


def test_a_failed_record_leaves_no_orphan_identity(world, monkeypatch):
    admin = _signed_in(world, _member(world, "admin"))
    email = _email()

    def broken(**kwargs):
        raise psycopg.errors.UniqueViolation("simulated race")

    monkeypatch.setattr(world["store"], "record_invitation", broken)
    r = _invite(admin, email)
    assert r.status_code == 409
    assert email not in world["gotrue"].users                       # the auth user was removed


# --- who may manage users ------------------------------------------------------------------

def test_only_user_managers_reach_the_admin_pages(world):
    target = _member(world, "viewer")
    for role in ("viewer", "editor"):
        client = _signed_in(world, _member(world, role))
        assert client.get("/api/admin/users").status_code == 403
        assert _invite(client, _email()).status_code == 403
        assert client.post(f"/api/admin/users/{target['id']}/role", json={"role": "admin"},
                           headers=H).status_code == 403
    anonymous = _client(world)
    assert anonymous.get("/api/admin/users").status_code == 401
    assert anonymous.post("/api/admin/invitations", json={}, headers=H).status_code == 401


def test_nobody_grants_more_than_they_hold(world):
    # Roles are configurable: a "coordinator" who may manage users but holds little else.
    _sql("INSERT INTO compass.role (code, label) VALUES ('coordinator', 'Coordinator') ON CONFLICT DO NOTHING")
    _sql("INSERT INTO compass.role_permission VALUES ('coordinator','users.manage'), ('coordinator','records.view'), "
         "('coordinator','ask.use'), ('coordinator','maps.view'), ('coordinator','dashboard.view'), "
         "('coordinator','usage.view_own') ON CONFLICT DO NOTHING")
    coordinator = _signed_in(world, _member(world, "coordinator"))
    assert _invite(coordinator, _email(), role="admin").status_code == 403
    assert _invite(coordinator, _email(), role="editor").status_code == 403
    assert _invite(coordinator, _email(), role="viewer").status_code == 200
    someone = _member(world, "viewer")
    assert coordinator.post(f"/api/admin/users/{someone['id']}/role", json={"role": "admin"},
                            headers=H).status_code == 403
    an_admin = _member(world, "admin")
    assert coordinator.post(f"/api/admin/users/{an_admin['id']}/role", json={"role": "viewer"},
                            headers=H).status_code == 403             # nor demote someone above them


def test_a_role_change_applies_at_once(world):
    admin = _signed_in(world, _member(world, "admin"))
    person = _member(world, "editor")
    client = _signed_in(world, person)
    assert client.get("/api/review/candidates").status_code == 200
    r = admin.post(f"/api/admin/users/{person['id']}/role", json={"role": "viewer"}, headers=H)
    assert r.status_code == 200 and r.json()["user"]["role"] == "viewer"
    assert client.get("/api/review/candidates").status_code == 403
    assert client.get("/api/browse/actors").status_code == 200
    assert "user.role_changed" in _actions(person["id"])


def test_compass_always_keeps_an_active_administrator(world):
    _sql("UPDATE compass.user_profile SET status='deactivated', deactivated_at=now() "
         "WHERE role_code IN ('admin','coordinator') AND status='active'")
    world["store"].forget()
    only = _member(world, "admin", "Only Admin")
    client = _signed_in(world, only)
    demote = client.post(f"/api/admin/users/{only['id']}/role", json={"role": "editor"}, headers=H)
    assert demote.status_code == 409 and "at least one active administrator" in demote.json()["detail"]
    assert client.post(f"/api/admin/users/{only['id']}/deactivate", json={}, headers=H).status_code == 409
    second = _member(world, "admin")
    assert client.post(f"/api/admin/users/{only['id']}/role", json={"role": "editor"},
                       headers=H).status_code == 200                  # another admin exists now
    _sql("UPDATE compass.user_profile SET role_code='admin' WHERE user_id=%s", only["id"])
    world["store"].forget()
    assert second


# --- deactivation ---------------------------------------------------------------------------

def test_deactivation_cuts_access_blocks_sign_in_and_recovery_and_can_be_undone(world):
    admin = _signed_in(world, _member(world, "admin"))
    person = _member(world, "editor")
    client = _signed_in(world, person)
    r = admin.post(f"/api/admin/users/{person['id']}/deactivate", json={"reason": "left the team"}, headers=H)
    assert r.status_code == 200 and r.json()["blocked_in_supabase_auth"] is True
    assert client.get("/api/browse/actors").status_code in (401, 403)
    login = _client(world).post("/api/auth/login", json={"email": person["email"], "password": STRONG}, headers=H)
    assert login.status_code == 403 and "not active" in login.json()["detail"]
    sent = len(world["gotrue"].outbox)
    forgot = _client(world).post("/api/auth/recover", json={"email": person["email"]}, headers=H)
    assert forgot.status_code == 200 and len(world["gotrue"].outbox) == sent   # same answer, no email
    assert admin.post(f"/api/admin/users/{person['id']}/activate", headers=H).status_code == 200
    assert _client(world).post("/api/auth/login", json={"email": person["email"], "password": STRONG},
                               headers=H).status_code == 200
    assert {"user.deactivated", "user.activated"} <= set(_actions(person["id"]))


# --- password reset and recovery ---------------------------------------------------------------

def test_password_reset_works_once_and_ends_other_sessions(world):
    person = _member(world, "editor")
    world["gotrue"].shift = -30                      # an older session, on another device
    elsewhere = _signed_in(world, person)
    world["gotrue"].shift = 0
    assert elsewhere.get("/api/browse/actors").status_code == 200
    r = _client(world).post("/api/auth/recover", json={"email": person["email"]}, headers=H)
    assert r.status_code == 200 and "If that address" in r.json()["message"]
    link = world["gotrue"].last_link(person["email"], "recovery")
    assert world["gotrue"].outbox[-1]["redirect_to"] == f"{SITE}/reset"
    fresh = _client(world)
    weak = fresh.post("/api/auth/reset", json={"token_hash": link, "password": "tiny"}, headers=H)
    assert weak.status_code == 422                   # the link is still usable
    new = "another long passphrase 2026"
    done = fresh.post("/api/auth/reset", json={"token_hash": link, "password": new}, headers=H)
    assert done.status_code == 200, done.text
    assert fresh.get("/api/browse/actors").status_code == 200
    ended = elsewhere.get("/api/browse/actors")
    assert ended.status_code == 401 and "ended" in ended.json()["detail"]
    reuse = _client(world).post("/api/auth/reset", json={"token_hash": link, "password": new}, headers=H)
    assert reuse.status_code == 400
    assert _client(world).post("/api/auth/login", json={"email": person["email"], "password": STRONG},
                               headers=H).status_code == 401          # the old password no longer works
    assert "auth.password_reset" in _actions(person["id"])


def test_recovery_never_says_whether_an_account_exists_and_is_limited(world):
    unknown, person = _email(), _member(world, "viewer")
    a = _client(world).post("/api/auth/recover", json={"email": unknown}, headers=H)
    b = _client(world).post("/api/auth/recover", json={"email": person["email"]}, headers=H)
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert not [m for m in world["gotrue"].outbox if m["to"] == unknown]
    for _ in range(5):
        _client(world).post("/api/auth/recover", json={"email": person["email"]}, headers=H)
    mails = [m for m in world["gotrue"].outbox if m["to"] == person["email"] and m["type"] == "recovery"]
    assert len(mails) == 3                           # 3 an hour per address, then silently none


def test_links_and_account_forms_refuse_other_sites(world):
    evil = {"Origin": "https://evil.example"}
    client = _client(world)
    assert client.post("/api/auth/recover", json={"email": _email()}, headers=evil).status_code == 403
    assert client.post("/api/auth/accept", json={"token_hash": "x" * 20, "password": STRONG},
                       headers=evil).status_code == 403
    assert client.post("/api/auth/reset", json={"token_hash": "x" * 20, "password": STRONG},
                       headers=evil).status_code == 403
    for page in ("/accept", "/reset", "/forgot", "/login"):
        r = client.get(page)
        assert r.status_code == 200 and "COMPASS" in r.text and r.headers["cache-control"] == "no-store"


# --- one's own profile --------------------------------------------------------------------------

def test_people_edit_their_own_name_and_change_their_password(world):
    person = _member(world, "viewer", "Old Name")
    client = _signed_in(world, person)
    me = client.get("/api/account/profile").json()
    assert me["profile"]["full_name"] == "Old Name" and "users.manage" not in me["permissions"]
    assert client.patch("/api/account/profile", json={"full_name": "  New   Name "},
                        headers=H).json()["profile"]["full_name"] == "New Name"
    assert client.get("/api/browse/actors").json() == {"who": "New Name"}
    wrong = client.post("/api/account/password", json={"current_password": "nope nope nope",
                                                       "new_password": "a brand new passphrase 9"}, headers=H)
    assert wrong.status_code == 403
    weak = client.post("/api/account/password", json={"current_password": STRONG,
                                                      "new_password": person["email"] + "123"}, headers=H)
    assert weak.status_code == 422
    ok = client.post("/api/account/password", json={"current_password": STRONG,
                                                    "new_password": "a brand new passphrase 9"}, headers=H)
    assert ok.status_code == 200, ok.text
    assert client.get("/api/browse/actors").status_code == 200          # this device stays signed in
    assert _client(world).post("/api/auth/login", json={"email": person["email"], "password": STRONG},
                               headers=H).status_code == 401
    assert {"profile.updated", "auth.password_changed"} <= set(_actions(person["id"]))


# --- the first administrator ------------------------------------------------------------------------

def test_the_first_administrator_bootstrap(world):
    _sql("UPDATE compass.user_profile SET status='deactivated', deactivated_at=now() "
         "WHERE status='active' AND role_code IN ('admin','coordinator')")
    _sql("UPDATE compass.invitation SET revoked_at=now() WHERE bootstrap AND accepted_at IS NULL")
    world["store"].forget()
    store, auth, email = world["store"], world["auth"], _email()
    sent = len(world["gotrue"].outbox)
    dry = bootstrap_admin(store, auth, email=email, full_name="First Admin", confirm_email=None,
                          site_url=SITE)
    assert dry.ready and not dry.sent and len(world["gotrue"].outbox) == sent
    unconfirmed = bootstrap_admin(store, auth, email=email, full_name="First Admin",
                                  confirm_email="someone@else.test", site_url=SITE, live=True)
    assert not unconfirmed.ready and len(world["gotrue"].outbox) == sent
    live = bootstrap_admin(store, auth, email=email, full_name="First Admin", confirm_email=email,
                           site_url=SITE, live=True)
    assert live.sent, live.lines
    assert _sql("SELECT bootstrap, invited_by IS NULL, role_code FROM compass.invitation WHERE email=%s",
                email) == [(True, True, "admin")]
    twice = bootstrap_admin(store, auth, email=_email(), full_name="Second", confirm_email=None, site_url=SITE)
    assert not twice.ready and "still open" in twice.lines[-1]
    link = world["gotrue"].last_link(email, "invite")
    accepted = _client(world).post("/api/auth/accept", json={"token_hash": link, "password": STRONG, "email": email},
                                   headers=H)
    assert accepted.status_code == 200 and accepted.json()["account"]["role"] == "admin"
    after = bootstrap_admin(store, auth, email=_email(), full_name="Third", confirm_email=None, site_url=SITE)
    assert not after.ready and "already has an administrator" in after.lines[-1]


# --- configuration and secrets ------------------------------------------------------------------------

def test_keys_never_appear_in_a_settings_repr():
    settings = AuthSettings(url="https://p.supabase.co", anon_key="ANON-SECRET",
                            service_role_key="SERVICE-SECRET", jwt_secret="JWT-SECRET")
    text = repr(settings)
    assert "SECRET" not in text and "p.supabase.co" in text


def test_the_configuration_check_names_what_is_missing_and_checks_the_templates():
    from scripts.check_accounts_config import checks

    missing = dict(checks({}))
    assert not any(ok for ok, _ in checks({}) if "template" not in _ and "JWT_SECRET" not in _)
    assert any(ok and "Supabase Auth confirms each token" in t for ok, t in checks({}))   # optional
    assert all(ok for ok, text in checks({}) if "template" in text)        # templates are right
    good = {"SUPABASE_URL": "https://abcd.supabase.co", "SUPABASE_ANON_KEY": "a" * 40,
            "SUPABASE_SERVICE_ROLE_KEY": "s" * 40, "SUPABASE_JWT_SECRET": "j" * 40,
            "GHUS_SESSION_KEY": "k" * 48, "GHUS_PUBLIC_URL": "https://ghus-compass.onrender.com"}
    assert all(ok for ok, _ in checks(good))
    assert missing is not None
