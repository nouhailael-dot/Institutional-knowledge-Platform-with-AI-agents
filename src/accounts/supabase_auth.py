"""Supabase Auth (GoTrue) for Compass: identities, passwords and sessions.

Compass never stores a password. Signing in, refreshing a session, signing
out, invitations and password resets are Supabase Auth's; this client calls
its HTTP API from the server only. The browser never sees the API keys: it
holds only the session, in HttpOnly cookies the backend sets.

Settings (environment, never the repository):

    SUPABASE_URL                 https://<project>.supabase.co
    SUPABASE_ANON_KEY            public key for sign-in and refresh calls
    SUPABASE_SERVICE_ROLE_KEY    server-only key for invitations (Phase 2)
    SUPABASE_JWT_SECRET          verifies access tokens locally (HS256)

Without SUPABASE_JWT_SECRET, a token is checked by asking Supabase Auth who it
belongs to (GET /auth/v1/user), cached briefly. That also covers projects
that sign tokens with asymmetric keys.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from threading import Lock
from urllib.parse import urlsplit

import httpx

from src.accounts.tokens import InvalidToken, token_algorithm, unverified_claims, verify_access_token


class AuthError(Exception):
    """A sign-in or session call was refused; ``message`` is safe to show."""

    def __init__(self, message: str, *, status: int = 401):
        super().__init__(message)
        self.message, self.status = message, status


class AuthUnavailable(AuthError):
    """Supabase Auth could not be reached or answered unexpectedly."""

    def __init__(self, message: str = "Sign-in is unavailable right now. Try again shortly."):
        super().__init__(message, status=503)


@dataclass(frozen=True)
class Session:
    access_token: str
    refresh_token: str
    expires_at: float
    user_id: str
    email: str


def project_url(value: str) -> str:
    """The project's base address. A copied REST or Auth address
    (https://<ref>.supabase.co/rest/v1/) is reduced to https://<ref>.supabase.co."""
    value = (value or "").strip().strip('"').strip("'")
    parts = urlsplit(value)
    if parts.scheme and parts.hostname and parts.hostname.endswith(".supabase.co"):
        return f"{parts.scheme}://{parts.hostname}"
    return value.rstrip("/")


@dataclass(frozen=True)
class AuthSettings:
    url: str
    # Keys never appear in a repr, a log line or an error message.
    anon_key: str = field(repr=False)
    service_role_key: str = field(repr=False)
    jwt_secret: str = field(repr=False)

    @classmethod
    def from_env(cls, environ=None) -> "AuthSettings":
        env = os.environ if environ is None else environ
        return cls(url=project_url(env.get("SUPABASE_URL") or ""),
                   anon_key=env.get("SUPABASE_ANON_KEY") or "",
                   service_role_key=env.get("SUPABASE_SERVICE_ROLE_KEY") or "",
                   jwt_secret=env.get("SUPABASE_JWT_SECRET") or "")

    @property
    def configured(self) -> bool:
        return bool(self.url and self.anon_key)


class SupabaseAuth:
    TIMEOUT = 10.0
    REMOTE_CACHE_SECONDS = 60

    def __init__(self, settings: AuthSettings, *, transport: httpx.BaseTransport | None = None,
                 clock=time.time):
        self.settings = settings
        self._client = httpx.Client(base_url=f"{settings.url}/auth/v1", timeout=self.TIMEOUT,
                                    transport=transport)
        self._clock = clock
        self._seen: dict[str, tuple[float, dict]] = {}
        self._lock = Lock()

    # -- calls --------------------------------------------------------------
    def _call(self, method: str, path: str, *, token: str | None = None, key: str | None = None,
              **kwargs) -> httpx.Response:
        headers = {"apikey": key or self.settings.anon_key}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            return self._client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise AuthUnavailable() from exc

    @staticmethod
    def _error_code(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return ""
        return str(body.get("error_code") or body.get("code") or body.get("error") or "")

    def _session(self, response: httpx.Response) -> Session:
        if response.status_code in (400, 401, 403, 422) and self._error_code(response) == "user_banned":
            raise AuthError("Your account is not active. Ask a Compass administrator.", status=403)
        if response.status_code in (400, 401, 403, 422):
            raise AuthError("Wrong email or password.")
        if response.status_code == 429:
            raise AuthError("Too many attempts. Wait a few minutes and try again.", status=429)
        if response.status_code != 200:
            raise AuthUnavailable()
        try:
            body = response.json()
            user = body["user"]
            return Session(access_token=body["access_token"], refresh_token=body["refresh_token"],
                           expires_at=float(body.get("expires_at")
                                            or self._clock() + float(body["expires_in"])),
                           user_id=str(user["id"]), email=str(user.get("email") or "").lower())
        except (ValueError, KeyError, TypeError) as exc:
            raise AuthUnavailable() from exc

    def sign_in(self, email: str, password: str) -> Session:
        return self._session(self._call("POST", "/token", params={"grant_type": "password"},
                                        json={"email": email, "password": password}))

    def refresh(self, refresh_token: str) -> Session:
        response = self._call("POST", "/token", params={"grant_type": "refresh_token"},
                              json={"refresh_token": refresh_token})
        if response.status_code in (400, 401, 403, 422):
            raise AuthError("Your session has ended. Sign in again.")
        return self._session(response)

    def sign_out(self, access_token: str, *, others_only: bool = False) -> None:
        """Ends the session in Supabase Auth (its refresh tokens stop working);
        with ``others_only``, every other session of that user instead."""
        try:
            self._call("POST", "/logout", token=access_token,
                       params={"scope": "others"} if others_only else None)
        except AuthUnavailable:
            pass   # the cookies are cleared anyway; the token expires on its own

    # -- invitations, email links and passwords (Phase 2) ----------------------------
    def _admin(self, method: str, path: str, **kwargs) -> httpx.Response:
        key = self.settings.service_role_key
        if not key:
            raise AuthUnavailable("Invitations are not configured on this server.")
        return self._call(method, path, token=key, key=key, **kwargs)

    def invite(self, email: str, *, full_name: str, redirect_to: str | None = None) -> str:
        """Send Supabase Auth's invitation email; the new auth user's id."""
        response = self._admin("POST", "/invite", json={"email": email, "data": {"full_name": full_name}},
                               params={"redirect_to": redirect_to} if redirect_to else None)
        if response.status_code == 422:
            raise AuthError("That address already has a Supabase Auth account.", status=409)
        if response.status_code == 429:
            raise AuthError("Too many emails were sent. Wait an hour and try again.", status=429)
        if response.status_code not in (200, 201):
            raise AuthUnavailable("The invitation email could not be sent. Try again shortly.")
        return str(response.json()["id"])

    def verify_link(self, token_hash: str, kind: str) -> Session:
        """Exchange an email link (invitation or recovery) for a session. Single use."""
        if kind not in ("invite", "recovery"):
            raise AuthError("Unknown link.", status=400)
        response = self._call("POST", "/verify", json={"type": kind, "token_hash": token_hash})
        if response.status_code in (400, 401, 403, 404, 410, 422):
            raise AuthError("This link has expired or was already used. Ask for a new one.", status=400)
        return self._session(response)

    def set_password(self, access_token: str, password: str) -> None:
        response = self._call("PUT", "/user", token=access_token, json={"password": password})
        if response.status_code == 422:
            raise AuthError("Supabase Auth refused that password. Choose a longer, less common one.",
                            status=422)
        if response.status_code != 200:
            raise AuthUnavailable()

    def send_recovery(self, email: str, *, redirect_to: str | None = None) -> None:
        response = self._call("POST", "/recover", json={"email": email},
                              params={"redirect_to": redirect_to} if redirect_to else None)
        if response.status_code not in (200, 204, 429):
            raise AuthUnavailable()

    def set_blocked(self, user_id: str, blocked: bool) -> None:
        """Block (or unblock) sign-in and session renewal in Supabase Auth itself."""
        response = self._admin("PUT", f"/admin/users/{user_id}",
                               json={"ban_duration": "876000h" if blocked else "none"})
        if response.status_code != 200:
            raise AuthUnavailable("Supabase Auth did not confirm the change. Try again.")

    def delete_user(self, user_id: str) -> None:
        """Remove an auth user that was never used (an invitation whose record failed)."""
        try:
            self._admin("DELETE", f"/admin/users/{user_id}")
        except AuthUnavailable:
            pass

    # -- verifying an access token -----------------------------------------------
    def verify(self, access_token: str) -> dict:
        """The token's claims (``sub`` is the user id); InvalidToken when not valid."""
        # A legacy JWT secret verifies HS256 tokens here. Tokens signed with the project's
        # asymmetric keys (ES256/RS256, the default on newer projects, even when a legacy
        # secret still exists) are confirmed by Supabase Auth itself (cached briefly).
        if self.settings.jwt_secret and token_algorithm(access_token) == "HS256":
            return verify_access_token(access_token, self.settings.jwt_secret, now=self._clock())
        key = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
        now = self._clock()
        with self._lock:
            hit = self._seen.get(key)
            if hit and hit[0] > now:
                return hit[1]
        response = self._call("GET", "/user", token=access_token)
        if response.status_code in (401, 403):
            raise InvalidToken("refused by Supabase Auth")
        if response.status_code != 200:
            raise AuthUnavailable()
        user = response.json()
        claims = {"sub": str(user["id"]), "email": str(user.get("email") or "").lower()}
        # Confirmed by Supabase Auth: when it was issued (so ended sessions stay ended).
        issued = unverified_claims(access_token)
        claims.update({k: issued[k] for k in ("iat", "exp", "session_id") if k in issued})
        with self._lock:
            if len(self._seen) > 2000:
                self._seen.clear()
            self._seen[key] = (now + self.REMOTE_CACHE_SECONDS, claims)
        return claims
