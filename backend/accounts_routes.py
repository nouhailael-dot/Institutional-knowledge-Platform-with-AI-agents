"""Individual accounts for Compass (GHUS_AUTH_MODE=supabase).

Replaces the shared HTTP Basic login only when GHUS_AUTH_MODE=supabase is set;
without it nothing here runs and backend/access.py keeps working as before.

Every request goes through ``require_account``:

1. the route's permission comes from src.accounts.permissions; a route with no
   policy is refused (fail closed);
2. the session is read from HttpOnly cookies the server set at sign-in: the
   Supabase Auth access token, its refresh token, and the signed time the
   session began. An expired access token is renewed with the refresh token;
   a session older than GHUS_SESSION_MAX_HOURS (default 12) ends;
3. the account must exist, be active and have a role; deactivating someone or
   removing their role takes effect within 30 seconds (or at once on this
   server, which forgets its cached copy);
4. a change (POST, PUT, PATCH, DELETE) must come from this site's own pages;
5. the request then runs as that account (src.identity), so everything it
   records names the real person, never a name sent by the browser.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from backend.access import FAILURES, SECURITY_HEADERS, UNSAFE_METHODS, same_origin
from src.accounts import activity
from src.accounts.permissions import (PUBLIC, SIGNED_IN, audit_entity, audit_name, permission_for,
                                      rule_for)
from src.accounts.store import Account, AccountsStore
from src.accounts.supabase_auth import AuthError, AuthSettings, SupabaseAuth
from src.accounts.tokens import InvalidToken, sign, unsign
from src.identity import signed_in_as

logger = logging.getLogger(__name__)

ACCESS_COOKIE = "compass_at"
REFRESH_COOKIE = "compass_rt"
SINCE_COOKIE = "compass_since"
# Sign in, forgotten password, accept an invitation, set a new password: one page.
LOGIN_PAGE = Path(__file__).resolve().parents[1] / "frontend" / "auth.html"

router = APIRouter()


def auth_mode() -> str:
    return (os.environ.get("GHUS_AUTH_MODE") or "").strip().lower()


def accounts_enabled() -> bool:
    return auth_mode() == "supabase"


# -- configured services (tests replace these) ---------------------------------
_services: dict[str, object] = {}


def auth_service() -> SupabaseAuth:
    if "auth" not in _services:
        _services["auth"] = SupabaseAuth(AuthSettings.from_env())
    return _services["auth"]  # type: ignore[return-value]


def accounts_store() -> AccountsStore:
    if "store" not in _services:
        _services["store"] = AccountsStore()
    return _services["store"]  # type: ignore[return-value]


def configure(*, auth: SupabaseAuth | None = None, store: AccountsStore | None = None) -> None:
    """Set the services explicitly (tests, or a server that builds its own)."""
    _services.clear()
    if auth is not None:
        _services["auth"] = auth
    if store is not None:
        _services["store"] = store


_session_key = os.environ.get("GHUS_SESSION_KEY", "").encode("utf-8") or secrets.token_bytes(32)


def session_key() -> bytes:
    """Signs the session's start time. Set GHUS_SESSION_KEY so a restart keeps sessions."""
    return _session_key


class SignedOut:
    """Access tokens of sessions that signed out, refused until they expire.

    Supabase Auth revokes the refresh token at sign-out, but an access token is
    valid until its expiry (an hour); this makes Sign out immediate on this
    server. Kept in memory: Compass runs one process.
    """

    def __init__(self):
        self._until: dict[str, float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def add(self, token: str, until: float) -> None:
        now = time.time()
        with self._lock:
            self._until = {k: v for k, v in self._until.items() if v > now}
            self._until[self._key(token)] = until

    def __contains__(self, token: str) -> bool:
        with self._lock:
            return self._until.get(self._key(token), 0) > time.time()


SIGNED_OUT = SignedOut()


def max_session_seconds() -> int:
    try:
        hours = float(os.environ.get("GHUS_SESSION_MAX_HOURS") or 12)
    except ValueError:
        hours = 12
    return int(max(0.25, min(hours, 24 * 7)) * 3600)


# -- responses -------------------------------------------------------------------
def _secured(response):
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    response.headers["Cache-Control"] = "no-store"
    return response


def _secure_cookies(request: Request) -> bool:
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").split(",")[0]
    return proto.strip().lower() == "https"


def _set_session(response, request: Request, session, since: int) -> None:
    secure = _secure_cookies(request)
    lifetime = max(60, since + max_session_seconds() - int(time.time()))
    common = {"httponly": True, "secure": secure, "samesite": "lax", "path": "/"}
    response.set_cookie(ACCESS_COOKIE, session.access_token, max_age=lifetime, **common)
    response.set_cookie(REFRESH_COOKIE, session.refresh_token, max_age=lifetime, **common)
    response.set_cookie(SINCE_COOKIE, sign(str(since), session_key()), max_age=lifetime, **common)


def _clear_session(response, request: Request) -> None:
    for name in (ACCESS_COOKIE, REFRESH_COOKIE, SINCE_COOKIE):
        response.delete_cookie(name, path="/", secure=_secure_cookies(request), httponly=True,
                               samesite="lax")


def _refuse(request: Request, status: int, message: str, *, clear: bool = False):
    wants_page = request.method == "GET" and not request.url.path.startswith("/api/")
    if status == 401 and wants_page:
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        response = RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)
    else:
        response = JSONResponse({"detail": message}, status_code=status)
    if clear:
        _clear_session(response, request)
    return _secured(response)


def _client(request: Request) -> str | None:
    return request.client.host if request.client else None


# -- the middleware ----------------------------------------------------------------
def _session_from(request: Request):
    """(account, renewed_session, since) for a valid session; raises AuthError otherwise."""
    access = request.cookies.get(ACCESS_COOKIE)
    refresh = request.cookies.get(REFRESH_COOKIE)
    since_text = unsign(request.cookies.get(SINCE_COOKIE), session_key())
    if not access or not refresh or not since_text or not since_text.isdigit():
        raise AuthError("Sign in to continue.")
    since = int(since_text)
    if time.time() - since > max_session_seconds():
        raise AuthError("Your session has ended. Sign in again.")
    if access in SIGNED_OUT:
        raise AuthError("You signed out. Sign in again.")
    auth = auth_service()
    renewed = None
    try:
        claims = auth.verify(access)
    except InvalidToken:
        renewed = auth.refresh(refresh)            # AuthError when the session is over
        try:
            claims = auth.verify(renewed.access_token)
        except InvalidToken as exc:                # never a 500: the person signs in again
            raise AuthError("Your session has ended. Sign in again.") from exc
    account = accounts_store().account(claims["sub"])
    issued = claims.get("iat")
    if (account is not None and account.sessions_valid_after is not None
            and isinstance(issued, (int, float)) and issued < int(account.sessions_valid_after)):
        raise AuthError("Your session has ended. Sign in again.")
    return account, renewed, since


async def require_account(request: Request, call_next):
    path, method = request.url.path, request.method
    needed = permission_for(method, path)
    if needed == PUBLIC:
        return _secured(await call_next(request))
    if needed is None:
        return _refuse(request, 403, "This action is not available.")
    try:
        account, renewed, since = _session_from(request)
    except AuthError as exc:
        status = 503 if exc.status == 503 else 401
        return _refuse(request, status, exc.message, clear=status == 401)
    if account is None or not account.active:
        return _refuse(request, 403, "Your account is not active. Ask a Compass administrator.",
                       clear=True)
    if needed != SIGNED_IN and not account.can(needed):
        _audit_request(request, account, "access.denied", needed=needed)
        return _refuse(request, 403, "Your role does not allow this.")
    if method in UNSAFE_METHODS and not same_origin(request):
        _audit_request(request, account, "access.cross_site")
        return _refuse(request, 403, "This change was sent from another site and was refused.")
    request.state.account = account
    token = activity.begin()
    try:
        with signed_in_as(account):
            response = await call_next(request)
    finally:
        notes = activity.end(token)
    if method in UNSAFE_METHODS and needed not in SELF_AUDITED and response.status_code < 400:
        _audit_request(request, account, None, notes=notes, status=response.status_code)
    if renewed is not None:
        _set_session(response, request, renewed, since)
    return _secured(response)


# Account and user-management routes write their own, more precise entries.
SELF_AUDITED = {PUBLIC, SIGNED_IN, "users.manage"}


def _audit_request(request: Request, account: Account, action: str | None, *, notes: dict | None = None,
                   needed: str | None = None, status: int | None = None) -> None:
    """One audit entry for a change (or a refusal), from the route and its notes.
    Never fails the request: the action has already happened."""
    found = rule_for(request.method, request.url.path)
    rule, values = found if found else (None, {})
    entity_type, entity_id = audit_entity(values)
    detail = dict(notes or {})
    # The record the route names comes first (a Review item, a map); what the
    # route created is the subject only when the route names none (a new map).
    noted_type, noted_id = detail.pop("entity_type", None), detail.pop("entity_id", None)
    if not entity_id:
        entity_type, entity_id = noted_type, noted_id
    detail.update({"route": f"{request.method} {rule.template if rule else request.url.path}"})
    if status is not None:
        detail["status"] = status
    if needed:
        detail["needed"] = needed
    try:
        accounts_store().audit(action=action or (audit_name(rule) if rule else "request.change"),
                               account=account, entity_type=entity_type,
                               entity_id=str(entity_id) if entity_id else None, detail=detail,
                               client=_client(request))
    except Exception:
        logger.exception("AUDIT NOT WRITTEN for %s %s by %s", request.method, request.url.path,
                         account.user_id)


def warn_without_administrator() -> None:
    """Compass must never run with accounts on and nobody able to manage them."""
    try:
        store = accounts_store()
        if store.active_manager_count() == 0:
            pending = store.open_bootstrap_invitations()
            logger.error(
                "ACCOUNTS: no active administrator. %s",
                "A first-administrator invitation is open; it must be accepted." if pending else
                "Run scripts/bootstrap_admin.py (see docs/ACCOUNTS_ACTIVATION.md) before anyone signs in.")
    except Exception:
        logger.exception("ACCOUNTS: could not check for an administrator")


# -- sign-in, sign-out, who am I -----------------------------------------------------
class SignIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


def _account_view(account: Account) -> dict:
    return {"user_id": account.user_id, "email": account.email, "full_name": account.full_name,
            "role": account.role_code, "role_label": account.role_label,
            "permissions": sorted(account.permissions)}


@router.get("/login", include_in_schema=False)
def login_page():
    return _secured(FileResponse(LOGIN_PAGE, media_type="text/html"))


@router.post("/api/auth/login")
def login(payload: SignIn, request: Request):
    if not same_origin(request):
        return _refuse(request, 403, "This sign-in was sent from another site and was refused.")
    email, client = payload.email.strip().lower(), _client(request)
    wait = FAILURES.retry_after(email, client)
    if wait:
        return _secured(JSONResponse(
            {"detail": f"Too many attempts. Try again in about {max(1, round(wait / 60))} minute(s)."},
            status_code=429, headers={"Retry-After": str(wait)}))
    store = accounts_store()
    try:
        session = auth_service().sign_in(email, payload.password)
    except AuthError as exc:
        if exc.status == 401:
            FAILURES.failed(email, client, payload.password)
            try:
                store.audit(action="auth.login_failed", account=None, label=email, client=client)
            except Exception:
                logger.exception("Could not record a failed sign-in")
        return _secured(JSONResponse({"detail": exc.message}, status_code=exc.status))
    store.forget(session.user_id)
    account = store.account(session.user_id)
    if account is None or not account.active:
        auth_service().sign_out(session.access_token)
        store.audit(action="auth.login_refused", account=account, label=email, client=client,
                    detail={"reason": "no account" if account is None else account.status})
        return _secured(JSONResponse(
            {"detail": "Your account is not active. Ask a Compass administrator."}, status_code=403))
    FAILURES.succeeded(email)
    store.mark_login(account.user_id)
    store.audit(action="auth.login", account=account, client=client)
    response = JSONResponse({"account": _account_view(account)})
    _set_session(response, request, session, int(time.time()))
    return _secured(response)


@router.post("/api/auth/logout")
def logout(request: Request):
    account = getattr(request.state, "account", None)
    access = request.cookies.get(ACCESS_COOKIE)
    if access:
        SIGNED_OUT.add(access, time.time() + max_session_seconds())
        auth_service().sign_out(access)
    try:
        accounts_store().audit(action="auth.logout", account=account, client=_client(request))
    except Exception:
        logger.exception("Could not record a sign-out")
    response = JSONResponse({"signed_out": True})
    _clear_session(response, request)
    return _secured(response)


@router.get("/api/auth/me")
def me(request: Request):
    return {"account": _account_view(request.state.account)}
