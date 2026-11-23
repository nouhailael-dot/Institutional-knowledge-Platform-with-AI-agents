"""A stand-in for Supabase Auth (GoTrue) for tests: the same HTTP calls and
answers Compass uses, real HS256 access tokens, rotating refresh tokens,
sign-out that revokes them, invitations and recovery emails (kept in an
outbox), single-use email links, bans. Synthetic users only; nothing leaves
the process."""

from __future__ import annotations

import json
import secrets
import time
import uuid

import httpx

from src.accounts.tokens import make_access_token

JWT_SECRET = "test-only-jwt-secret-" + "x" * 24
SERVICE_KEY = "service-role-test-key-" + "y" * 20


class FakeGoTrue:
    def __init__(self, secret: str = JWT_SECRET, *, on_create=None):
        self.secret = secret
        self.users: dict[str, dict] = {}            # email -> {id, password, confirmed, banned}
        self.refresh_tokens: dict[str, str] = {}    # refresh token -> user id
        self.links: dict[str, tuple[str, str, float]] = {}   # token hash -> (user id, type, expires)
        self.outbox: list[dict] = []                # {"to", "type", "token_hash", "redirect_to"}
        self.ttl = 3600
        self.shift = 0                               # seconds added to new tokens' iat
        self.link_ttl = 86400
        self.calls: list[str] = []
        self.on_create = on_create                   # writes auth.users in the test database

    # -- helpers ---------------------------------------------------------------
    def add_user(self, email: str, password: str | None, user_id: str | None = None,
                 confirmed: bool = True) -> str:
        user_id = user_id or str(uuid.uuid4())
        self.users[email.lower()] = {"id": user_id, "password": password, "confirmed": confirmed,
                                     "banned": False}
        return user_id

    def by_id(self, user_id: str) -> tuple[str, dict]:
        return next((e, u) for e, u in self.users.items() if u["id"] == user_id)

    def last_link(self, email: str, kind: str) -> str:
        return [m for m in self.outbox if m["to"] == email and m["type"] == kind][-1]["token_hash"]

    def _session(self, user_id: str, email: str) -> dict:
        now = int(time.time()) + self.shift
        access = make_access_token({"sub": user_id, "email": email, "aud": "authenticated",
                                    "role": "authenticated", "iat": now, "exp": now + self.ttl,
                                    "session_id": secrets.token_hex(8)}, self.secret)
        refresh = secrets.token_urlsafe(24)
        self.refresh_tokens[refresh] = user_id
        return {"access_token": access, "refresh_token": refresh, "token_type": "bearer",
                "expires_in": self.ttl, "expires_at": now + self.ttl,
                "user": {"id": user_id, "email": email, "aud": "authenticated"}}

    def _send(self, email: str, kind: str, user_id: str, redirect_to: str | None) -> None:
        token_hash = secrets.token_hex(28)
        self.links[token_hash] = (user_id, kind, time.time() + self.link_ttl)
        self.outbox.append({"to": email, "type": kind, "token_hash": token_hash,
                            "redirect_to": redirect_to})

    def _sub(self, token: str) -> str | None:
        from src.accounts.tokens import InvalidToken, verify_access_token
        try:
            return verify_access_token(token, self.secret)["sub"]
        except InvalidToken:
            return None

    @staticmethod
    def _bearer(request: httpx.Request) -> str:
        return request.headers.get("authorization", "").removeprefix("Bearer ")

    # -- the HTTP API ------------------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append(f"{method} {path}")
        if not request.headers.get("apikey"):
            return httpx.Response(401, json={"message": "No API key found in request"})
        body = json.loads(request.content or b"{}") if request.content else {}
        service = self._bearer(request) == SERVICE_KEY and request.headers.get("apikey") == SERVICE_KEY

        if path.endswith("/token"):
            grant = request.url.params.get("grant_type")
            if grant == "password":
                user = self.users.get(str(body.get("email", "")).lower())
                if not user or not user["password"] or user["password"] != body.get("password"):
                    return httpx.Response(400, json={"error": "invalid_grant", "error_code": "invalid_credentials"})
                if user["banned"]:
                    return httpx.Response(400, json={"error_code": "user_banned"})
                return httpx.Response(200, json=self._session(user["id"], body["email"].lower()))
            if grant == "refresh_token":
                user_id = self.refresh_tokens.pop(str(body.get("refresh_token")), None)  # rotates
                if user_id is None or self.by_id(user_id)[1]["banned"]:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json=self._session(user_id, self.by_id(user_id)[0]))
        if path.endswith("/logout"):
            sub = self._sub(self._bearer(request))
            if sub:
                # scope=others keeps the caller's own (newest) refresh token
                keep = [k for k, v in self.refresh_tokens.items() if v == sub][-1:] \
                    if request.url.params.get("scope") == "others" else []
                for key in [k for k, v in self.refresh_tokens.items() if v == sub and k not in keep]:
                    del self.refresh_tokens[key]
            return httpx.Response(204)
        if path.endswith("/user") and method == "GET":
            sub = self._sub(self._bearer(request))
            if not sub:
                return httpx.Response(401, json={"message": "invalid JWT"})
            return httpx.Response(200, json={"id": sub, "email": self.by_id(sub)[0]})
        if path.endswith("/user") and method == "PUT":
            sub = self._sub(self._bearer(request))
            if not sub:
                return httpx.Response(401, json={"message": "invalid JWT"})
            if len(str(body.get("password", ""))) < 6:
                return httpx.Response(422, json={"error_code": "weak_password"})
            self.by_id(sub)[1]["password"] = body["password"]
            return httpx.Response(200, json={"id": sub})
        if path.endswith("/invite"):
            if not service:
                return httpx.Response(401, json={"message": "service role required"})
            email = str(body["email"]).lower()
            user = self.users.get(email)
            if user and user["confirmed"]:
                return httpx.Response(422, json={"error_code": "email_exists"})
            if user is None:
                user_id = self.add_user(email, None, confirmed=False)
                if self.on_create:
                    self.on_create(user_id, email)
                user = self.users[email]
            self._send(email, "invite", user["id"], request.url.params.get("redirect_to"))
            return httpx.Response(200, json={"id": user["id"], "email": email})
        if path.endswith("/recover"):
            email = str(body.get("email", "")).lower()
            if email in self.users:
                self._send(email, "recovery", self.users[email]["id"], request.url.params.get("redirect_to"))
            return httpx.Response(200, json={})
        if path.endswith("/verify"):
            found = self.links.pop(str(body.get("token_hash")), None)     # single use
            if found is None or found[1] != body.get("type") or found[2] < time.time():
                return httpx.Response(403, json={"error_code": "otp_expired"})
            email, user = self.by_id(found[0])
            user["confirmed"] = True
            return httpx.Response(200, json=self._session(user["id"], email))
        if "/admin/users/" in path:
            if not service:
                return httpx.Response(401, json={"message": "service role required"})
            user_id = path.rsplit("/", 1)[1]
            try:
                email, user = self.by_id(user_id)
            except StopIteration:
                return httpx.Response(404)
            if method == "DELETE":
                del self.users[email]
                return httpx.Response(200, json={})
            if method == "PUT":
                user["banned"] = body.get("ban_duration") not in (None, "none")
                if user["banned"]:
                    for key in [k for k, v in self.refresh_tokens.items() if v == user_id]:
                        del self.refresh_tokens[key]
                return httpx.Response(200, json={"id": user_id})
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
