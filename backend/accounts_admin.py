"""Invitations, passwords, profiles and user management (accounts Phase 2).

Only with GHUS_AUTH_MODE=supabase (registered next to backend/accounts_routes).

* Invitation-only: an administrator invites an address with a role. Supabase
  Auth sends the email; its link opens /accept, where the person sets a
  password. The invitation (compass.invitation) decides: it must be open, not
  revoked and not expired, whatever Supabase Auth's own link allows.
* Password reset: /forgot asks for an email (the answer never says whether an
  account exists); Supabase Auth's link opens /reset. Only an active account
  can reset; the reset ends every other session.
* Profile: each person reads and edits their own name, and changes their
  password (the current one is checked first).
* Administration (permission users.manage): list users and invitations,
  invite, revoke, resend, change a role, deactivate, activate. Nobody grants
  a role with a permission they do not hold, nobody deactivates themselves,
  and Compass always keeps at least one active administrator.

Every action is in the audit history. Who acts comes from the session only.
"""

from __future__ import annotations

import logging
import os
import time
import uuid

import psycopg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from backend.access import same_origin
from backend.accounts_routes import (ACCESS_COOKIE, LOGIN_PAGE, SIGNED_OUT, _account_view, _client,
                                     _secured, _set_session, accounts_store, auth_service,
                                     max_session_seconds)
from src.accounts.policy import Limiter, clean_email, clean_name, password_problem
from src.accounts.store import Account, AccountError
from src.accounts.supabase_auth import AuthError

logger = logging.getLogger(__name__)
router = APIRouter()

RECOVERY_PER_EMAIL = Limiter(3, 3600)
RECOVERY_PER_CLIENT = Limiter(20, 3600)
LINK_ATTEMPTS = Limiter(20, 15 * 60)
INVITES_PER_ADMIN = Limiter(50, 3600)


def invitation_days() -> float:
    try:
        return max(1 / 24, min(float(os.environ.get("GHUS_INVITATION_DAYS") or 7), 30))
    except ValueError:
        return 7.0


def site_url(request: Request) -> str:
    """Where email links point. GHUS_PUBLIC_URL on the host; this request's site otherwise."""
    configured = (os.environ.get("GHUS_PUBLIC_URL") or "").strip().rstrip("/")
    return configured or str(request.base_url).rstrip("/")


def _fail(status: int, message: str):
    raise HTTPException(status_code=status, detail=message)


def _same_site(request: Request) -> None:
    if not same_origin(request):
        _fail(403, "This was sent from another site and was refused.")


def _audit(**kwargs) -> None:
    try:
        accounts_store().audit(**kwargs)
    except Exception:
        logger.exception("Could not write an audit entry (%s)", kwargs.get("action"))


def _me(request: Request) -> Account:
    return request.state.account


def _keep_only(session) -> None:
    """End every other session of this person: older ones are refused from now on
    (compass sessions_valid_after) and Supabase Auth revokes their refresh tokens."""
    claims = auth_service().verify(session.access_token)
    accounts_store().end_sessions(session.user_id, before=float(claims.get("iat") or time.time()))
    auth_service().sign_out(session.access_token, others_only=True)


# -- pages ---------------------------------------------------------------------------
@router.get("/forgot", include_in_schema=False)
@router.get("/accept", include_in_schema=False)
@router.get("/reset", include_in_schema=False)
def account_pages():
    return _secured(FileResponse(LOGIN_PAGE, media_type="text/html"))


# -- public: accept an invitation, recover a password ----------------------------------
class AcceptInvitation(BaseModel):
    token_hash: str = Field(min_length=8, max_length=512)
    password: str = Field(min_length=1, max_length=512)
    full_name: str = Field(default="", max_length=200)
    # The address the invitation was sent to (23 Nov 2026). The page asks for it
    # instead of the name, which the administrator already gave; it must match.
    email: str = Field(default="", max_length=254)
    kind: str = Field(default="invite", pattern="^(invite|recovery)$")


class Recover(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetPassword(BaseModel):
    token_hash: str = Field(min_length=8, max_length=512)
    password: str = Field(min_length=1, max_length=512)


def _signed_in_response(request: Request, session, account: Account, body: dict | None = None):
    response = JSONResponse({"account": _account_view(account), **(body or {})})
    _set_session(response, request, session, int(time.time()))
    return _secured(response)


def _accept(request: Request, session, *, password: str, full_name: str, kind: str,
            email: str | None = None):
    store = accounts_store()
    profile = store.user(session.user_id)
    if profile is None or profile["status"] != "invited":
        auth_service().sign_out(session.access_token)
        _audit(action="invitation.refused", account=None, label=session.email, client=_client(request),
               entity_type="user", entity_id=session.user_id,
               detail={"reason": "no open invitation", "link": kind})
        _fail(409 if profile else 403, "This invitation was already used or is not valid. Sign in instead."
              if profile else "This invitation is not valid.")
    if email is not None and email != clean_email(profile["email"]):
        # Checked before the password is set, so the invitation stays open.
        auth_service().sign_out(session.access_token)
        _audit(action="invitation.refused", account=None, label=profile["email"], client=_client(request),
               entity_type="user", entity_id=session.user_id,
               detail={"reason": "email does not match the invitation", "link": kind})
        _fail(422, "This invitation was sent to a different email address. Ask a Compass "
                   "administrator to send you a new invitation.")
    problem = password_problem(password, email=profile["email"], name=full_name or profile["full_name"])
    if problem:
        _fail(422, problem)
    try:
        # The invitation decides first; the password is set only for a valid one.
        store.check_invitation_open(session.user_id)
        auth_service().set_password(session.access_token, password)
        account = store.accept_invitation(session.user_id, full_name=clean_name(full_name))
    except AccountError as exc:
        auth_service().sign_out(session.access_token)
        _audit(action="invitation.refused", account=None, label=profile["email"], client=_client(request),
               entity_type="user", entity_id=session.user_id, detail={"reason": exc.message, "link": kind})
        _fail(exc.status, exc.message)
    _audit(action="invitation.accepted", account=account, client=_client(request),
           entity_type="user", entity_id=account.user_id, detail={"role": account.role_code})
    store.mark_login(account.user_id)
    return _signed_in_response(request, session, account)


@router.post("/api/auth/accept")
def accept_invitation(payload: AcceptInvitation, request: Request):
    _same_site(request)
    if not LINK_ATTEMPTS.allow(f"client:{_client(request)}"):
        _fail(429, "Too many attempts. Wait a few minutes and try again.")
    if payload.full_name and clean_name(payload.full_name) is None:
        _fail(422, "Enter your name (at most 120 characters).")
    email = clean_email(payload.email)       # before the single-use link is spent
    if email is None:
        _fail(422, "Enter the email address this invitation was sent to.")
    if len(payload.password) < 12:          # before the single-use link is spent
        _fail(422, password_problem(payload.password) or "Choose a longer password.")
    try:
        session = auth_service().verify_link(payload.token_hash, payload.kind)
    except AuthError as exc:
        _fail(exc.status, exc.message)
    return _accept(request, session, password=payload.password, full_name=payload.full_name,
                   kind=payload.kind, email=email)


@router.post("/api/auth/recover")
def recover(payload: Recover, request: Request):
    """Always the same answer, so it never tells whether an address has an account."""
    _same_site(request)
    answer = {"message": "If that address has an active Compass account, an email with a link "
                         "is on its way. The link works once and expires."}
    email, client = clean_email(payload.email), _client(request)
    if email is None:
        _fail(422, "Enter a valid email address.")
    if not RECOVERY_PER_CLIENT.allow(f"client:{client}") or not RECOVERY_PER_EMAIL.allow(f"email:{email}"):
        _audit(action="auth.recovery_limited", account=None, label=email, client=client)
        return _secured(JSONResponse(answer))
    profile = accounts_store().user_by_email(email)
    sent = bool(profile and profile["status"] == "active")
    if sent:
        try:
            auth_service().send_recovery(email, redirect_to=f"{site_url(request)}/reset")
        except AuthError:
            logger.exception("Supabase Auth did not send a recovery email")
            sent = False
    _audit(action="auth.recovery_requested", account=None, label=email, client=client,
           detail={"sent": sent})
    return _secured(JSONResponse(answer))


@router.post("/api/auth/reset")
def reset_password(payload: ResetPassword, request: Request):
    _same_site(request)
    if not LINK_ATTEMPTS.allow(f"client:{_client(request)}"):
        _fail(429, "Too many attempts. Wait a few minutes and try again.")
    if len(payload.password) < 12:
        _fail(422, password_problem(payload.password) or "Choose a longer password.")
    try:
        session = auth_service().verify_link(payload.token_hash, "recovery")
    except AuthError as exc:
        _fail(exc.status, exc.message)
    store = accounts_store()
    store.forget(session.user_id)
    profile = store.user(session.user_id)
    if profile and profile["status"] == "invited":
        # A resent invitation can arrive as a recovery link: it completes the invitation.
        return _accept(request, session, password=payload.password, full_name="", kind="recovery")
    account = store.account(session.user_id)
    if account is None or not account.active:
        auth_service().sign_out(session.access_token)
        _audit(action="auth.password_reset_refused", account=account, label=session.email,
               client=_client(request))
        _fail(403, "Your account is not active. Ask a Compass administrator.")
    problem = password_problem(payload.password, email=account.email, name=account.full_name)
    if problem:
        _fail(422, problem)
    try:
        auth_service().set_password(session.access_token, payload.password)
    except AuthError as exc:
        _fail(exc.status, exc.message)
    _keep_only(session)
    _audit(action="auth.password_reset", account=account, client=_client(request))
    store.mark_login(account.user_id)
    return _signed_in_response(request, session, account)


# -- signed in: one's own profile and password ---------------------------------------------
class ProfileChange(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=1, max_length=512)


def _public_user(row: dict) -> dict:
    return {k: row[k] for k in ("user_id", "email", "full_name", "role", "role_label", "status",
                                "status_label", "created_at", "last_login_at", "deactivated_at",
                                "invitation")}


@router.get("/api/account/profile")
def my_profile(request: Request):
    me = _me(request)
    row = accounts_store().user(me.user_id)
    return {"profile": _public_user(row), "permissions": sorted(me.permissions)}


@router.patch("/api/account/profile")
def update_my_profile(payload: ProfileChange, request: Request):
    me = _me(request)
    name = clean_name(payload.full_name)
    if name is None:
        _fail(422, "Enter your name (at most 120 characters).")
    if name != me.full_name:
        accounts_store().update_profile(me.user_id, full_name=name)
        _audit(action="profile.updated", account=me, label=name, client=_client(request),
               entity_type="user", entity_id=me.user_id, detail={"full_name": [me.full_name, name]})
    return my_profile(request)


@router.post("/api/account/password")
def change_my_password(payload: PasswordChange, request: Request):
    from backend.access import FAILURES

    me, client = _me(request), _client(request)
    if FAILURES.retry_after(me.email, client):
        _fail(429, "Too many attempts. Wait a few minutes and try again.")
    problem = password_problem(payload.new_password, email=me.email, name=me.full_name)
    if problem:
        _fail(422, problem)
    if payload.new_password == payload.current_password:
        _fail(422, "Choose a password different from your current one.")
    try:
        session = auth_service().sign_in(me.email, payload.current_password)
    except AuthError as exc:
        if exc.status == 401:
            FAILURES.failed(me.email, client, payload.current_password)
            _fail(403, "Your current password is not right.")
        _fail(exc.status, exc.message)
    try:
        auth_service().set_password(session.access_token, payload.new_password)
    except AuthError as exc:
        _fail(exc.status, exc.message)
    _keep_only(session)
    _audit(action="auth.password_changed", account=me, client=client)
    old = request.cookies.get(ACCESS_COOKIE)
    if old:
        SIGNED_OUT.add(old, time.time() + max_session_seconds())
    return _signed_in_response(request, session, accounts_store().account(me.user_id) or me,
                               {"changed": True})


# -- administration (users.manage) ------------------------------------------------------------
class Invite(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    full_name: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=40)


class RoleChange(BaseModel):
    role: str = Field(min_length=1, max_length=40)


class Deactivation(BaseModel):
    reason: str = Field(default="", max_length=500)


def _no_escalation(me: Account, role_code: str) -> None:
    roles = {r["code"]: set(r["permissions"]) for r in accounts_store().roles()}
    if role_code not in roles:
        _fail(400, "Unknown role.")
    beyond = roles[role_code] - set(me.permissions)
    if beyond:
        _fail(403, "You cannot give a role with permissions you do not have.")


def _account_error(exc: AccountError):
    _fail(exc.status, exc.message)


@router.get("/api/admin/users")
def list_users(request: Request):
    store = accounts_store()
    return {"users": [_public_user(u) for u in store.users()], "roles": store.roles(),
            "me": _me(request).user_id, "invitation_days": invitation_days()}


@router.post("/api/admin/invitations")
def invite(payload: Invite, request: Request):
    me, store, auth = _me(request), accounts_store(), auth_service()
    email, name = clean_email(payload.email), clean_name(payload.full_name)
    if email is None:
        _fail(422, "Enter a valid email address.")
    if name is None:
        _fail(422, "Enter the person's name (at most 120 characters).")
    _no_escalation(me, payload.role)
    if not INVITES_PER_ADMIN.allow(f"admin:{me.user_id}"):
        _fail(429, "Too many invitations in the last hour. Try again later.")
    try:
        store.check_can_invite(email)
    except AccountError as exc:
        _account_error(exc)
    try:
        user_id = auth.invite(email, full_name=name, redirect_to=f"{site_url(request)}/accept")
    except AuthError as exc:
        _fail(exc.status, exc.message)
    try:
        invitation = store.record_invitation(user_id=user_id, email=email, full_name=name,
                                             role_code=payload.role, invited_by=me.user_id,
                                             days=invitation_days())
    except (AccountError, psycopg.Error) as exc:
        auth.delete_user(user_id)      # the email names an account that now does not exist
        logger.warning("Invitation not recorded for %s: %s", email, exc)
        if isinstance(exc, AccountError):
            _account_error(exc)
        _fail(409, "That address was invited at the same moment by someone else. Refresh the list.")
    _audit(action="invitation.created", account=me, client=_client(request), entity_type="user",
           entity_id=user_id, detail={"email": email, "role": payload.role,
                                      "expires_at": invitation["expires_at"]})
    return {"invitation": invitation, "user": _public_user(store.user(user_id))}


@router.post("/api/admin/invitations/{invitation_id}/revoke")
def revoke(invitation_id: str, request: Request):
    me = _me(request)
    try:
        found = accounts_store().revoke_invitation(invitation_id, by=me.user_id)
    except AccountError as exc:
        _account_error(exc)
    _audit(action="invitation.revoked", account=me, client=_client(request), entity_type="user",
           entity_id=found["user_id"], detail={"email": found["email"], "invitation_id": invitation_id})
    return {"user": _public_user(accounts_store().user(found["user_id"]))}


@router.post("/api/admin/invitations/{invitation_id}/resend")
def resend(invitation_id: str, request: Request):
    me, store, auth = _me(request), accounts_store(), auth_service()
    current = store.invitation(invitation_id)
    if current is None:
        _fail(404, "Unknown invitation.")
    _no_escalation(me, current["role_code"])
    if not INVITES_PER_ADMIN.allow(f"admin:{me.user_id}"):
        _fail(429, "Too many invitations in the last hour. Try again later.")
    try:
        fresh = store.reissue_invitation(invitation_id, by=me.user_id, days=invitation_days())
    except AccountError as exc:
        _account_error(exc)
    try:
        auth.invite(fresh["email"], full_name=fresh["full_name"], redirect_to=f"{site_url(request)}/accept")
        channel = "invite"
    except AuthError as exc:
        if exc.status != 409:
            _fail(exc.status, exc.message)
        # Supabase Auth will not re-invite an address that opened an earlier link:
        # its recovery email completes the invitation instead (see /api/auth/reset).
        auth.send_recovery(fresh["email"], redirect_to=f"{site_url(request)}/reset")
        channel = "recovery"
    _audit(action="invitation.resent", account=me, client=_client(request), entity_type="user",
           entity_id=fresh["user_id"], detail={"email": fresh["email"], "channel": channel,
                                               "expires_at": fresh["expires_at"]})
    return {"invitation": {"invitation_id": fresh["invitation_id"], "expires_at": fresh["expires_at"]},
            "user": _public_user(store.user(fresh["user_id"]))}


@router.post("/api/admin/users/{user_id}/role")
def change_role(user_id: str, payload: RoleChange, request: Request):
    me = _me(request)
    _no_escalation(me, payload.role)
    store = accounts_store()
    target = store.user(user_id)
    if target is None:
        _fail(404, "Unknown user.")
    if target["role"] and target["role"] != payload.role:
        _no_escalation(me, target["role"])         # nor take away a role above one's own
    try:
        old, new = store.set_role(user_id, payload.role)
    except AccountError as exc:
        _account_error(exc)
    if old != new:
        _audit(action="user.role_changed", account=me, client=_client(request), entity_type="user",
               entity_id=user_id, detail={"email": target["email"], "from": old, "to": new})
    return {"user": _public_user(store.user(user_id))}


@router.post("/api/admin/users/{user_id}/deactivate")
def deactivate(user_id: str, payload: Deactivation, request: Request):
    me = _me(request)
    if user_id == me.user_id:
        _fail(409, "You cannot deactivate your own account.")
    store = accounts_store()
    target = store.user(user_id)
    if target is None:
        _fail(404, "Unknown user.")
    try:
        store.deactivate(user_id, by=me.user_id)
    except AccountError as exc:
        _account_error(exc)
    blocked = True
    try:
        auth_service().set_blocked(user_id, True)
    except AuthError:
        blocked = False
        logger.exception("Supabase Auth did not block %s; Compass refuses the account anyway", user_id)
    _audit(action="user.deactivated", account=me, client=_client(request), entity_type="user",
           entity_id=user_id, detail={"email": target["email"], "reason": payload.reason.strip(),
                                      "blocked_in_supabase_auth": blocked})
    return {"user": _public_user(store.user(user_id)), "blocked_in_supabase_auth": blocked}


@router.post("/api/admin/users/{user_id}/activate")
def activate(user_id: str, request: Request):
    me = _me(request)
    store = accounts_store()
    target = store.user(user_id)
    if target is None:
        _fail(404, "Unknown user.")
    if target["role"]:
        _no_escalation(me, target["role"])
    if target["status"] != "deactivated":
        _fail(409, "Only a deactivated account can be activated.")
    # Supabase Auth first: if it fails, nothing changed and Activate can simply be retried.
    try:
        auth_service().set_blocked(user_id, False)
    except AuthError:
        logger.exception("Supabase Auth did not unblock %s", user_id)
        _fail(502, "Supabase Auth did not confirm the change. Nothing changed; try again.")
    try:
        store.activate(user_id)
    except AccountError as exc:
        _account_error(exc)
    _audit(action="user.activated", account=me, client=_client(request), entity_type="user",
           entity_id=user_id, detail={"email": target["email"]})
    return {"user": _public_user(store.user(user_id))}


# -- the audit history (audit.view_all) ---------------------------------------------------
@router.get("/api/admin/audit")
def audit_history(request: Request, user_id: str | None = None, action: str | None = None,
                  entity_type: str | None = None, entity_id: str | None = None, limit: int = 200):
    """The permanent history of sensitive actions, newest first. Read-only: the
    database refuses any change to it."""
    if action and not all(c.isalnum() or c in "._" for c in action):
        _fail(422, "Unknown action filter.")
    if user_id:
        try:
            user_id = str(uuid.UUID(user_id))
        except ValueError:
            _fail(422, "Unknown user.")
    return {"entries": accounts_store().audit_entries(
        user_id=user_id or None, actions=(action,) if action else (), entity_type=entity_type or None,
        entity_id=entity_id or None, limit=max(1, min(limit, 1000)))}
