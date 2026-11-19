"""End-to-end check of the multi-user platform on a migrated copy of production.

    python -m tests.accounts_integration_check --database ghus_phase7_integration_test

The REAL application (backend.app, GHUS_AUTH_MODE=supabase) with the real backend
writers (admission, Data Feed, Discovery requests) against a local *_test copy of
production with migrations 700 and 710 applied. Only Supabase Auth is the stand-in
(tests/accounts_fakes.py); no paid AI call is made (the key is a dummy).

  1. accounts: the first administrator is bootstrapped and accepts; they invite an
     Editor/Reviewer and a Viewer, who accept and sign in
  2. permissions: every GET route in the policy for every role (allowed -> served,
     not allowed -> 403), and every POST route a role may not use -> 403
  3. flows with attribution from the session: Directory edit, Delete and Restore
     (Pending Deletion), a Review rejection, a Monitor request, a Data Feed check,
     ownership (immutable), My Records / My Requests, Dashboard, notifications,
     preferences, usage, admin reporting and exports, the audit history
  4. two people acting at once: each action is recorded under its own account
  5. role change, deactivation, sign-out take effect on the next request

Refuses anything but a local *_test database. Prints one JSON report; exit 1 on a failed check.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import tempfile
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = "http://testserver"
H = {"Origin": SITE}
PASSWORD = "a long passphrase for compass 7"


def _environment(database: str) -> str:
    if not database.endswith("_test"):
        raise SystemExit("only a local *_test database")
    url = f"postgresql://ghus_test@127.0.0.1:55432/{database}"
    alchemy = url.replace("postgresql://", "postgresql+psycopg://", 1)
    work = Path(tempfile.mkdtemp(prefix="compass-integration-"))
    backend = ROOT / "ghus-backend"
    for leaked in ("REVIEW_SOURCE_POSTGRES_ENV_FILE", "REVIEW_SOURCE_RUN_DB", "SUPABASE_URL",
                   "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_JWT_SECRET"):
        os.environ.pop(leaked, None)
    os.environ.update({
        "DATABASE_URL": url, "BROWSE_DATABASE_URL": url, "REVIEW_SOURCE_DATABASE_URL": url,
        "REVIEW_STORE_DB": str(work / "review.sqlite3"), "MAP_RUN_DB": str(work / "runs.sqlite3"),
        "GHUS_DISCOVERY_PROJECT_ROOT": str(backend), "DISCOVERY_REQUESTS_DATABASE_URL": alchemy,
        "GHUS_DATAFEED_PROJECT_ROOT": str(backend), "DATAFEED_DATABASE_URL": alchemy,
        "GHUS_ADMISSION_PROJECT_ROOT": str(backend), "REVIEW_ADMISSION_DATABASE_URL": alchemy,
        "GHUS_AUTH_MODE": "supabase", "GHUS_SESSION_KEY": secrets.token_urlsafe(48),
        "GHUS_PUBLIC_URL": SITE, "GHUS_PURGE_MODE": "off",
        "ANTHROPIC_API_KEY": "test-not-a-real-key", "GHUS_ACCOUNTS_TEST_DATABASE_URL": alchemy,
    })
    return url


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", required=True)
    args = parser.parse_args(argv)
    url = _environment(args.database)
    sys.path.insert(0, str(ROOT))

    import psycopg
    from fastapi.testclient import TestClient

    from backend import accounts_routes
    from src.accounts.bootstrap import bootstrap_admin
    from src.accounts.permissions import DEFAULT_ROLES, PUBLIC, ROUTE_POLICY, SIGNED_IN
    from src.accounts.store import AccountsStore
    from src.accounts.supabase_auth import AuthSettings, SupabaseAuth
    from tests.accounts_fakes import JWT_SECRET, SERVICE_KEY, FakeGoTrue

    def sql(query, *params):
        with psycopg.connect(url, autocommit=True) as conn:
            cur = conn.execute(query, params)
            return cur.fetchall() if cur.description else None

    gotrue = FakeGoTrue(on_create=lambda uid, email: sql(
        "INSERT INTO auth.users (id, email) VALUES (%s, %s) ON CONFLICT DO NOTHING", uid, email))
    auth = SupabaseAuth(AuthSettings(url="https://auth.example.test", anon_key="anon-test",
                                     service_role_key=SERVICE_KEY, jwt_secret=JWT_SECRET),
                        transport=gotrue.transport())
    store = AccountsStore(url)
    accounts_routes.configure(auth=auth, store=store)
    import backend.app as app_module                 # accounts mode: the sign-in middleware is on

    checks: dict[str, bool] = {}
    notes: dict[str, object] = {}

    def check(name, ok, detail=None):
        checks[name] = bool(ok)
        if detail is not None and not ok:
            notes[name] = detail

    def client():
        return TestClient(app_module.app, base_url=SITE)

    def link(email):
        try:
            return gotrue.last_link(email, "invite")
        except IndexError:
            return "no-invitation-was-sent"

    def sign_in(email):
        c = client()
        r = c.post("/api/auth/login", json={"email": email, "password": PASSWORD}, headers=H)
        check(f"sign_in {email}", r.status_code == 200, r.text[:200])
        return c

    try:
        # -- 1. accounts ---------------------------------------------------------------------
        anonymous = client()
        check("signed_out_is_refused", anonymous.get("/api/browse/actors").status_code == 401)
        result = bootstrap_admin(store, auth, email="ana.admin@example.test", full_name="Ana Admin (synthetic)",
                                 confirm_email="ana.admin@example.test", site_url=SITE, live=True)
        check("bootstrap_sends_one_invitation", result.sent, result.lines)
        r = client().post("/api/auth/accept", headers=H, json={
            "token_hash": link("ana.admin@example.test"), "password": PASSWORD,
            "full_name": "Ana Admin (synthetic)", "kind": "invite"})
        check("admin_accepts", r.status_code == 200, r.text[:200])
        admin = sign_in("ana.admin@example.test")
        check("bootstrap_refuses_a_second_admin", not bootstrap_admin(
            store, auth, email="other@example.test", full_name="Other", confirm_email="other@example.test",
            site_url=SITE, live=True).sent)
        people = {}
        for role, email, name in (("editor", "eli.editor@example.test", "Eli Editor (synthetic)"),
                                  ("viewer", "vic.viewer@example.test", "Vic Viewer (synthetic)")):
            r = admin.post("/api/admin/invitations", headers=H, json={"email": email, "full_name": name, "role": role})
            check(f"invite_{role}", r.status_code == 200, r.text[:200])
            r = client().post("/api/auth/accept", headers=H, json={
                "token_hash": link(email), "password": PASSWORD, "full_name": name,
                "kind": "invite"})
            check(f"{role}_accepts", r.status_code == 200, r.text[:200])
            people[role] = sign_in(email)
        editor, viewer = people["editor"], people["viewer"]
        ids = {r[1]: r[0] for r in sql("SELECT user_id::text, role_code FROM compass.user_profile")}
        check("three_accounts_three_roles", set(ids) == {"admin", "editor", "viewer"})

        # -- 2. permissions ---------------------------------------------------------------------
        sample = {"candidate_id": str(uuid.uuid4()), "job_id": "nonexistent-job", "subscription_id": str(uuid.uuid4()),
                  "run_id": str(uuid.uuid4()), "preview_id": "nonexistent", "actor_id": str(uuid.uuid4()),
                  "check_id": "nonexistent", "user_id": str(uuid.uuid4()), "invitation_id": str(uuid.uuid4()),
                  "notification_id": str(uuid.uuid4()), "deletion_id": str(uuid.uuid4()), "kind": "actors",
                  "record_id": str(uuid.uuid4()), "review_item_id": str(uuid.uuid4()), "record_type": "actor",
                  "extension": "csv", "action": "pause"}
        skip_get = {"/api/ask/stream"}                     # a paid model call
        served, refused_wrong, errors = 0, [], []
        clients = {"admin": admin, "editor": editor, "viewer": viewer}
        for rule in ROUTE_POLICY:
            if rule.permission == PUBLIC:
                continue
            path = re.sub(r"\{([^}]+)\}", lambda m: sample.get(m.group(1), "x"), rule.template)
            for role, c in clients.items():
                allowed = rule.permission == SIGNED_IN or rule.permission in DEFAULT_ROLES[role]
                if rule.method == "GET" and rule.template not in skip_get:
                    status = c.get(path).status_code
                    if allowed and status in (401, 403):
                        refused_wrong.append(f"{role} GET {rule.template} -> {status}")
                    elif not allowed and status != 403:
                        refused_wrong.append(f"{role} GET {rule.template} -> {status} (expected 403)")
                    elif allowed and status >= 500:
                        errors.append(f"{role} GET {rule.template} -> {status}")
                    else:
                        served += 1
                elif rule.method != "GET" and not allowed:
                    status = c.request(rule.method, path, json={}, headers=H).status_code
                    if status != 403:
                        refused_wrong.append(f"{role} {rule.method} {rule.template} -> {status} (expected 403)")
                    else:
                        served += 1
        notes["permission_probes"] = served
        check("every_role_gets_exactly_its_permissions", not refused_wrong, refused_wrong)
        check("no_allowed_page_errors", not errors, errors)
        check("pages_mount_per_role", all(
            c.get("/api/auth/me").json()["account"]["role"] == role for role, c in clients.items()))

        # -- 3. flows ---------------------------------------------------------------------------
        actors = editor.get("/api/browse/actors").json()["actors"]
        notes["directory_organizations"] = len(actors)
        check("directory_lists_production_copy", len(actors) > 500)
        target = next(a for a in actors if a.get("website"))
        r = editor.post(f"/api/browse/actors/{target['id']}/edit", headers=H,
                        json={"changes": {}, "ghus_notes": "Integration check note (synthetic)."})
        check("directory_edit_saved_by_backend_writer", r.status_code == 200, r.text[:300])
        trail = editor.get(f"/api/account/record-trail?entity_type=actor&entity_id={target['id']}").json()
        check("record_trail_names_the_editor", (trail.get("last_edited_by") or {}).get("name") == "Eli Editor (synthetic)",
              trail)

        victim = next(a for a in actors if a["id"] != target["id"] and a.get("website"))
        check("viewer_cannot_delete", viewer.post(f"/api/browse/actors/{victim['id']}/delete", headers=H,
                                                  json={"confirm": True}).status_code == 403)
        check("delete_needs_confirmation", editor.post(f"/api/browse/actors/{victim['id']}/delete", headers=H,
                                                       json={"confirm": False}).status_code == 400)
        r = editor.post(f"/api/browse/actors/{victim['id']}/delete", headers=H,
                        json={"confirm": True, "reason": "Integration check (synthetic)"})
        check("delete_through_backend_writer", r.status_code == 200, r.text[:300])
        deletion_id = (r.json() if r.status_code == 200 else {}).get("deletion_id")
        check("deleted_hidden_from_directory", victim["id"] not in {a["id"] for a in editor.get("/api/browse/actors").json()["actors"]})
        check("deleted_hidden_from_actor_read", sql("SELECT count(*) FROM actor_read WHERE actor_id = %s", victim["id"])[0][0] == 0)
        check("deleted_profile_404", editor.get(f"/api/browse/actors/{victim['id']}/profile").status_code == 404)
        pending = admin.get("/api/review/deleted").json()["deleted"]
        check("pending_deletion_lists_it_with_who_and_deadline",
              any(d["deletion_id"] == deletion_id and d["deleted_by"] == "Eli Editor (synthetic)"
                  and d["days_remaining"] == 30 for d in pending), pending)
        check("viewer_cannot_see_pending_deletion", viewer.get("/api/review/deleted").status_code == 403)
        check("database_records_deleter_account", sql(
            "SELECT deleted_by::text FROM compass.deleted_record WHERE deletion_id = %s", deletion_id)[0][0] == ids["editor"])
        r = admin.post(f"/api/review/deleted/{deletion_id}/restore", headers=H, json={"confirm": True})
        check("restore_through_backend_writer", r.status_code == 200, r.text[:300])
        check("restored_back_in_directory", victim["id"] in {a["id"] for a in editor.get("/api/browse/actors").json()["actors"]})
        check("database_records_restorer_account", sql(
            "SELECT restored_by::text FROM compass.deleted_record WHERE deletion_id = %s", deletion_id)[0][0] == ids["admin"])
        check("second_restore_refused", admin.post(f"/api/review/deleted/{deletion_id}/restore", headers=H,
                                                   json={"confirm": True}).status_code == 422)
        check("cleanup_has_nothing_due", sql(
            "SELECT count(*) FROM compass.deleted_record WHERE purge_after <= now() AND purged_at IS NULL")[0][0] == 0)

        # Review: a rejection is recorded under the signed-in reviewer.
        review = editor.get("/api/review/candidates?status=pending_review")
        candidates = review.json().get("candidates", []) if review.status_code == 200 else []
        notes["review_pending"] = len(candidates)
        if candidates:
            cid = candidates[0]["candidate_id"]
            r = editor.post(f"/api/review/candidates/{cid}/reject", headers=H, json={
                "rejection_reason": "Integration check (synthetic)", "idempotency_key": f"it-{uuid.uuid4()}",
                "confirmed": True, "reviewer": "Somebody Else"})
            check("review_reject_accepted", r.status_code == 200, r.text[:300])
            audit = sql("SELECT user_id::text FROM compass.audit_event WHERE action LIKE 'review.%%' "
                        "AND entity_id = %s ORDER BY audit_id DESC LIMIT 1", cid)
            check("review_decision_attributed_to_session_not_typed_name", audit and audit[0][0] == ids["editor"], audit)
        else:
            check("review_has_pending_items_to_test", False, review.text[:200])

        # Monitor: a request belongs to the account that created it.
        r = editor.post("/api/discovery/requests", headers=H, json={
            "title": "Integration check request (synthetic)", "sector_codes": ["AGRI"], "end_date": "2027-06-30",
            "cadence": "monthly", "requested_by": "someone.else@example.test"})
        check("monitor_request_created", r.status_code == 200, r.text[:300])
        mine = editor.get("/api/account/mine").json()
        check("my_requests_lists_it", any("Integration check request" in (x.get("name") or "") for x in mine.get("requests", [])),
              mine.get("requests"))
        check("viewer_sees_no_monitor", viewer.get("/api/discovery/requests").status_code == 403)

        # Data Feed: checking a manual record is read-only and allowed for editors.
        r = editor.post("/api/datafeed/validate-manual", headers=H, json={
            "record_type": "actor", "records": [{"name": "Integration Check Lab (synthetic)", "website": "https://example.test"}]})
        check("datafeed_check_runs", r.status_code == 200, r.text[:300])

        # Ownership is immutable.
        owned = sql("SELECT entity_type, entity_id FROM compass.record_owner LIMIT 1")
        if owned:
            try:
                sql("UPDATE compass.record_owner SET owner_user_id = %s WHERE entity_type = %s AND entity_id = %s",
                    ids["viewer"], owned[0][0], owned[0][1])
                check("ownership_immutable", False)
            except psycopg.Error:
                check("ownership_immutable", True)
        notes["owned_records"] = sql("SELECT count(*) FROM compass.record_owner")[0][0]

        # Dashboard, notifications, preferences, usage, admin reporting, audit.
        dash = editor.get("/api/account/dashboard")
        check("dashboard_personal", dash.status_code == 200 and dash.json()["name"] == "Eli Editor (synthetic)")
        prefs = editor.put("/api/account/preferences", headers=H, json={"preferences": {"directory": {"default_view": "mine"}}})
        check("preferences_saved", prefs.status_code == 200, prefs.text[:200])
        check("preferences_are_per_user", viewer.get("/api/account/preferences").json()["preferences"].get(
            "directory", {}).get("default_view") != "mine")
        check("usage_own", editor.get("/api/account/usage").status_code == 200)
        check("viewer_no_admin_usage", viewer.get("/api/admin/usage").status_code == 403)
        usage = admin.get("/api/admin/usage")
        check("admin_usage_report", usage.status_code == 200, usage.text[:200])
        for fmt in ("csv", "xlsx"):
            r = admin.get(f"/api/admin/usage/export?format={fmt}")
            check(f"admin_export_{fmt}", r.status_code == 200 and len(r.content) > 50, r.status_code)
        audit = admin.get("/api/admin/audit").json()
        actions = {e["action"] for e in audit.get("events", audit.get("entries", []))} if isinstance(audit, dict) else set()
        notes["audit_actions"] = sorted(actions)[:40]
        check("audit_records_the_session_actions", {"browse.delete", "review.deleted_restore"} <= actions, sorted(actions))

        # -- 4. two people at once ------------------------------------------------------------------
        second = admin.post("/api/admin/invitations", headers=H, json={
            "email": "eda.editor@example.test", "full_name": "Eda Editor (synthetic)", "role": "editor"})
        client().post("/api/auth/accept", headers=H, json={"token_hash": link("eda.editor@example.test"),
                                                           "password": PASSWORD, "full_name": "Eda Editor (synthetic)", "kind": "invite"})
        eda = sign_in("eda.editor@example.test")
        edits = [a for a in actors if a["id"] not in (target["id"], victim["id"])][:6]
        barrier = threading.Barrier(2)

        def burst(c, rows, tag):
            barrier.wait()
            for a in rows:
                c.post(f"/api/browse/actors/{a['id']}/edit", headers=H, json={"changes": {}, "ghus_notes": f"{tag} (synthetic)"})

        threads = [threading.Thread(target=burst, args=(editor, edits[:3], "Eli")),
                   threading.Thread(target=burst, args=(eda, edits[3:], "Eda"))]
        [t.start() for t in threads]
        [t.join() for t in threads]
        eda_id = sql("SELECT user_id::text FROM compass.user_profile WHERE email = 'eda.editor@example.test'")[0][0]
        rows = sql("SELECT entity_id, user_id::text FROM compass.audit_event WHERE action = 'browse.edit' AND entity_id = ANY(%s)",
                   [a["id"] for a in edits])
        expected = {a["id"]: ids["editor"] for a in edits[:3]} | {a["id"]: eda_id for a in edits[3:]}
        check("simultaneous_users_attributed_correctly", rows and all(expected[e] == u for e, u in rows), rows)

        # -- 5. role change, deactivation, sign-out ------------------------------------------------
        r = admin.post(f"/api/admin/users/{eda_id}/role", headers=H, json={"role": "viewer"})
        check("role_change", r.status_code == 200, r.text[:200])
        check("role_change_applies_next_request", eda.post(f"/api/browse/actors/{edits[3]['id']}/delete", headers=H,
                                                           json={"confirm": True}).status_code == 403)
        r = admin.post(f"/api/admin/users/{eda_id}/deactivate", headers=H, json={"reason": "Integration check"})
        check("deactivate", r.status_code == 200, r.text[:200])
        check("deactivated_session_refused", eda.get("/api/browse/actors").status_code in (401, 403))
        check("deactivated_cannot_sign_in", client().post("/api/auth/login", headers=H, json={
            "email": "eda.editor@example.test", "password": PASSWORD}).status_code in (401, 403))
        viewer.post("/api/auth/logout", headers=H)
        check("signed_out_session_refused", viewer.get("/api/browse/actors").status_code == 401)
        check("admin_cannot_remove_last_admin", admin.post(f"/api/admin/users/{ids['admin']}/deactivate", headers=H,
                                                           json={"reason": "x"}).status_code in (400, 409))

    except Exception:  # noqa: BLE001 - the report says where it stopped
        import traceback
        checks["completed_without_crash"] = False
        notes["crash"] = traceback.format_exc()[-1500:]

    report = {"database": args.database, "checks": checks, "notes": notes, "ok": all(checks.values()),
              "passed": sum(checks.values()), "total": len(checks)}
    json.dump(report, sys.stdout, indent=2, sort_keys=True, default=str)
    sys.stdout.write("\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
