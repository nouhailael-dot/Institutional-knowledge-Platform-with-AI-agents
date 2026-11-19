"""Validate Compass accounts against a REAL Supabase Auth (a separate test project).

    set GHUS_AUTH_TEST_URL=https://<test-ref>.supabase.co
    set GHUS_AUTH_TEST_ANON_KEY=...
    set GHUS_AUTH_TEST_SERVICE_ROLE_KEY=...
    set GHUS_AUTH_TEST_JWT_SECRET=...        (optional: empty on asymmetric signing keys)
    python -m tests.supabase_auth_live_check --database ghus_accounts_test --confirm-test-project <test-ref>

The real platform (accounts routes, middleware, admin pages) talks to the real
Supabase Auth of the test project. The only change: invitation and recovery
emails are not sent - the Admin API's generate_link issues the same single-use
link, so synthetic addresses can be used. Everything else (verifying the link,
setting the password, signing in, renewing, signing out, bans) is Supabase's own.

Refuses: the production project (SUPABASE_URL / DATABASE_URL), a project ref that
does not match --confirm-test-project, a non-local or non-*_test accounts database.
Creates synthetic users only and deletes them at the end. Prints one JSON report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://compass-check.example"           # requests carry x-forwarded-proto: https
H = {"Origin": SITE, "x-forwarded-proto": "https"}


def _ref(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host.split(".")[0] if host.endswith(".supabase.co") else ""


def _production_refs() -> set[str]:
    refs = {_ref(os.environ.get("SUPABASE_URL", ""))}
    match = re.search(r"postgres\.([a-z0-9]{20})", os.environ.get("DATABASE_URL", ""))
    if match:
        refs.add(match.group(1))
    return {r for r in refs if r}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", required=True, help="local *_test accounts database (reset)")
    parser.add_argument("--confirm-test-project", required=True)
    args = parser.parse_args(argv)
    url = os.environ.get("GHUS_AUTH_TEST_URL", "").rstrip("/")
    ref = _ref(url)
    if not ref or ref != args.confirm_test_project:
        parser.error("GHUS_AUTH_TEST_URL must be https://<ref>.supabase.co with <ref> = --confirm-test-project")
    if ref in _production_refs():
        parser.error("that is the production project: refused")
    if not args.database.endswith("_test"):
        parser.error("only a local *_test accounts database")
    dsn = f"postgresql://ghus_test@127.0.0.1:55432/{args.database}"
    os.environ.update({"GHUS_SESSION_KEY": secrets.token_urlsafe(48), "GHUS_PUBLIC_URL": SITE})
    sys.path.insert(0, str(ROOT))

    import httpx
    import psycopg
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend import accounts_admin, accounts_routes
    from src.accounts.bootstrap import bootstrap_admin
    from src.accounts.store import AccountsStore
    from src.accounts.supabase_auth import AuthSettings, SupabaseAuth
    from tests.test_accounts import _reset_schema

    service = os.environ["GHUS_AUTH_TEST_SERVICE_ROLE_KEY"]
    admin_api = httpx.Client(base_url=f"{url}/auth/v1", timeout=20,
                             headers={"apikey": service, "Authorization": f"Bearer {service}"})
    _reset_schema(dsn)
    auth = SupabaseAuth(AuthSettings(url=url, anon_key=os.environ["GHUS_AUTH_TEST_ANON_KEY"],
                                     service_role_key=service,
                                     jwt_secret=os.environ.get("GHUS_AUTH_TEST_JWT_SECRET", "")))
    created: list[str] = []
    links: dict[tuple[str, str], str] = {}

    def generate(kind: str, email: str, full_name: str | None = None) -> str:
        body = {"type": kind, "email": email}
        if full_name:
            body["data"] = {"full_name": full_name}
        r = admin_api.post("/admin/generate_link", json=body)
        r.raise_for_status()
        data = r.json()
        user_id = str(data.get("id") or (data.get("user") or {}).get("id"))
        links[(email, kind)] = data.get("hashed_token") or (data.get("properties") or {}).get("hashed_token")
        with psycopg.connect(dsn, autocommit=True) as conn:       # the stand-in for auth.users locally
            conn.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                         (user_id, email))
        if user_id not in created:
            created.append(user_id)
        return user_id

    # No email: the same single-use links, issued by the Admin API.
    auth.invite = lambda email, *, full_name, redirect_to=None: generate("invite", email, full_name)
    auth.send_recovery = lambda email, *, redirect_to=None: generate("recovery", email)
    store = AccountsStore(dsn)
    accounts_routes.configure(auth=auth, store=store)
    app = FastAPI()
    app.include_router(accounts_routes.router)
    app.include_router(accounts_admin.router)

    @app.get("/api/browse/actors")
    def probe():
        from src.identity import current_user
        return {"who": current_user()}

    app.middleware("http")(accounts_routes.require_account)
    checks: dict[str, bool] = {}
    notes: dict[str, object] = {}

    def check(name, ok, detail=None):
        checks[name] = bool(ok)
        if detail is not None and not ok:
            notes[name] = detail

    tag = secrets.token_hex(4)
    email = {role: f"compass-check-{role}-{tag}@example.com" for role in ("admin", "editor", "viewer")}
    pw = {role: f"Synthetic passphrase {tag} {role} 7" for role in email}

    def client():
        return TestClient(app, base_url=SITE)

    def sign_in(role, password=None):
        c = client()
        r = c.post("/api/auth/login", json={"email": email[role], "password": password or pw[role]}, headers=H)
        return c, r

    try:
        result = bootstrap_admin(store, auth, email=email["admin"], full_name="Check Admin (synthetic)",
                                 confirm_email=email["admin"], site_url=SITE, live=True)
        check("invitation_issued_by_supabase", result.sent, result.lines)
        r = client().post("/api/auth/accept", headers=H, json={"token_hash": links[(email["admin"], "invite")],
                                                               "password": pw["admin"], "full_name": "Check Admin (synthetic)"})
        check("invitation_link_verified_and_password_set", r.status_code == 200, r.text[:200])
        r = client().post("/api/auth/accept", headers=H, json={"token_hash": links[(email["admin"], "invite")],
                                                               "password": pw["admin"]})
        check("invitation_link_single_use", r.status_code == 400, r.text[:200])
        admin, r = sign_in("admin")
        check("login", r.status_code == 200, r.text[:200])
        cookies = [v for k, v in r.headers.multi_items() if k.lower() == "set-cookie"]
        check("cookies_httponly_secure_lax", cookies and all(
            "httponly" in c.lower() and "secure" in c.lower() and "samesite=lax" in c.lower() for c in cookies), cookies)
        check("wrong_password_refused", sign_in("admin", "not the password at all")[1].status_code == 401)

        for role in ("editor", "viewer"):
            r = admin.post("/api/admin/invitations", headers=H,
                           json={"email": email[role], "full_name": f"Check {role} (synthetic)", "role": role})
            check(f"admin_invites_{role}", r.status_code == 200, r.text[:200])
            r = client().post("/api/auth/accept", headers=H, json={"token_hash": links[(email[role], "invite")],
                                                                   "password": pw[role]})
            check(f"{role}_accepts", r.status_code == 200, r.text[:200])
        editor, _ = sign_in("editor")
        viewer, _ = sign_in("viewer")

        check("backend_authorization_viewer_refused", viewer.get("/api/admin/users").status_code == 403)
        check("backend_authorization_admin_served", admin.get("/api/admin/users").status_code == 200)

        # Renewal: an access token Supabase no longer accepts is renewed from the refresh token.
        editor.cookies.set(accounts_routes.ACCESS_COOKIE, "eyJhbGciOiJIUzI1NiJ9.e30.invalid", domain=urlsplit(SITE).hostname)
        r = editor.get("/api/browse/actors")
        check("session_renewed_with_refresh_token", r.status_code == 200 and any(
            k.lower() == "set-cookie" and accounts_routes.ACCESS_COOKIE in v for k, v in r.headers.multi_items()), r.status_code)

        # Several people at once: each request is its own account.
        seen, lock = [], threading.Lock()

        def hit(c, expected):
            for _ in range(5):
                who = c.get("/api/browse/actors").json().get("who")
                with lock:
                    seen.append(who == expected)

        threads = [threading.Thread(target=hit, args=(c, n)) for c, n in
                   ((admin, "Check Admin (synthetic)"), (editor, "Check editor (synthetic)"),
                    (viewer, "Check viewer (synthetic)"))]
        [t.start() for t in threads]
        [t.join() for t in threads]
        check("simultaneous_users_isolated", all(seen) and len(seen) == 15)

        # Password reset (account recovery): the old password stops working.
        r = client().post("/api/auth/recover", headers=H, json={"email": email["viewer"]})
        check("recovery_requested", r.status_code == 200, r.text[:200])
        new = pw["viewer"] + " renewed"
        r = client().post("/api/auth/reset", headers=H, json={"token_hash": links[(email["viewer"], "recovery")],
                                                              "password": new})
        check("password_reset", r.status_code == 200, r.text[:200])
        check("old_password_refused", sign_in("viewer")[1].status_code == 401)
        viewer, r = sign_in("viewer", new)
        check("new_password_works", r.status_code == 200)

        # Role change and deactivation (also blocked in Supabase Auth itself).
        editor_id = next(u for u in created if admin_api.get(f"/admin/users/{u}").json().get("email") == email["editor"])
        r = admin.post(f"/api/admin/users/{editor_id}/role", headers=H, json={"role": "viewer"})
        check("role_change", r.status_code == 200, r.text[:200])
        check("role_change_takes_effect", editor.get("/api/auth/me").json()["account"]["role"] == "viewer")
        r = admin.post(f"/api/admin/users/{editor_id}/deactivate", headers=H, json={"reason": "live check"})
        check("deactivate", r.status_code == 200, r.text[:200])
        check("deactivated_session_refused", editor.get("/api/browse/actors").status_code in (401, 403))
        banned = admin_api.get(f"/admin/users/{editor_id}").json().get("banned_until")
        check("deactivated_blocked_in_supabase_auth", bool(banned), banned)
        check("deactivated_cannot_sign_in", sign_in("editor")[1].status_code in (401, 403))

        # Sign-out revokes the session.
        viewer.post("/api/auth/logout", headers=H)
        check("signed_out_refused", viewer.get("/api/browse/actors").status_code == 401)
    except Exception:  # noqa: BLE001 - the report says where it stopped
        import traceback
        checks["completed_without_crash"] = False
        notes["crash"] = traceback.format_exc()[-1500:]
    finally:
        for user_id in created:                      # synthetic users only; removed again
            admin_api.delete(f"/admin/users/{user_id}")
        notes["synthetic_users_removed"] = len(created)
    report = {"project": ref, "checks": checks, "notes": notes, "ok": all(checks.values()),
              "passed": sum(checks.values()), "total": len(checks)}
    json.dump(report, sys.stdout, indent=2, sort_keys=True, default=str)
    sys.stdout.write("\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
