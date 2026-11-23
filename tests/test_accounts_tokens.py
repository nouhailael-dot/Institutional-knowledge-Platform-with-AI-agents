"""Supabase Auth tokens of both kinds (found by the real Supabase Auth check, 19 Nov 2026).

Newer Supabase projects sign access tokens with asymmetric keys (ES256) even when a
legacy JWT secret still exists. Compass accepted only HS256 when a secret was set,
so every session after sign-in was refused, and a renewal that failed the same way
raised a 500. No database, no network: Supabase Auth is a mock transport.
"""

from __future__ import annotations

import base64
import json
import time

import httpx
import pytest

from src.accounts.supabase_auth import AuthSettings, SupabaseAuth, project_url
from src.accounts.tokens import InvalidToken, make_access_token, token_algorithm, unverified_claims

SECRET = "legacy-jwt-secret-" + "s" * 30


def _b64(value: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def _es256_token(sub="user-1", iat=None) -> str:
    now = int(time.time()) if iat is None else iat
    return f"{_b64({'alg': 'ES256', 'kid': 'k1', 'typ': 'JWT'})}." \
           f"{_b64({'sub': sub, 'aud': 'authenticated', 'iat': now, 'exp': now + 3600})}.c2lnbmF0dXJl"


def _auth(handler) -> SupabaseAuth:
    return SupabaseAuth(AuthSettings(url="https://abcd.supabase.co", anon_key="anon", service_role_key="svc",
                                     jwt_secret=SECRET), transport=httpx.MockTransport(handler))


def test_an_asymmetric_token_is_confirmed_by_supabase_even_with_a_legacy_secret():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"id": "user-1", "email": "Eli@Example.com"})

    token = _es256_token(iat=1_800_000_000)
    claims = _auth(handler).verify(token)
    assert seen == ["/auth/v1/user"]
    assert claims["sub"] == "user-1" and claims["email"] == "eli@example.com"
    assert claims["iat"] == 1_800_000_000                 # ended sessions stay ended


def test_a_refused_asymmetric_token_is_invalid_not_an_error():
    auth = _auth(lambda request: httpx.Response(401, json={"msg": "invalid JWT"}))
    with pytest.raises(InvalidToken):
        auth.verify(_es256_token())


def test_hs256_tokens_are_still_verified_locally_without_a_call():
    def handler(request):                                 # must not be called
        raise AssertionError("no network call expected")

    now = int(time.time())
    token = make_access_token({"sub": "user-2", "aud": "authenticated", "iat": now, "exp": now + 600}, SECRET)
    assert token_algorithm(token) == "HS256"
    assert _auth(handler).verify(token)["sub"] == "user-2"


def test_reading_a_token_never_trusts_a_forged_hs256_token():
    now = int(time.time())
    forged = make_access_token({"sub": "admin", "aud": "authenticated", "iat": now, "exp": now + 600}, "wrong")
    with pytest.raises(InvalidToken):
        _auth(lambda request: httpx.Response(200, json={"id": "admin"})).verify(forged)


def test_helpers_on_bad_input():
    assert token_algorithm("not-a-token") == "" and unverified_claims("a.b") == {}


def test_a_copied_rest_address_is_reduced_to_the_project():
    assert project_url("https://abcd.supabase.co/rest/v1/") == "https://abcd.supabase.co"
    assert project_url(" https://abcd.supabase.co/auth/v1 ") == "https://abcd.supabase.co"
    assert project_url("http://localhost:9999/") == "http://localhost:9999"


def test_a_renewal_that_still_fails_signs_out_instead_of_crashing(monkeypatch):
    from starlette.requests import Request

    from backend import accounts_routes
    from src.accounts.supabase_auth import AuthError, Session
    from src.accounts.tokens import sign

    class Auth:
        def verify(self, token):
            raise InvalidToken("unsupported signing algorithm")

        def refresh(self, refresh_token):
            return Session(access_token="new", refresh_token="r2", user_id="u", email="e", expires_at=0)

    monkeypatch.setattr(accounts_routes, "auth_service", lambda: Auth())
    since = sign(str(int(time.time())), accounts_routes.session_key())
    cookie = f"compass_at=old; compass_rt=r1; compass_since={since}"
    request = Request({"type": "http", "method": "GET", "path": "/api/browse/actors", "query_string": b"",
                       "headers": [(b"cookie", cookie.encode())]})
    with pytest.raises(AuthError) as refused:
        accounts_routes._session_from(request)
    assert "Sign in again" in str(refused.value)
