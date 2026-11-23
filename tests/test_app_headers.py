"""The app's response middleware keeps every header, repeated ones included.

18 Nov 2026: plain_reasons rebuilt each /api/ JSON response from a dict of its
headers, which keeps one Set-Cookie. Signing in sets three (access, refresh,
session start), so with individual accounts nobody could stay signed in.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import backend.app as app_module

NAMES = ("compass_at", "compass_rt", "compass_since")


def _app() -> FastAPI:
    app = FastAPI()

    @app.post("/api/auth/login")
    def login():
        response = JSONResponse({"ok": True, "error": "anthropic.RateLimitError: 429"})
        for name in NAMES:
            response.set_cookie(name, "value", httponly=True, samesite="lax")
        response.headers["X-Custom"] = "kept"
        return response

    @app.post("/api/auth/logout")
    def logout():
        response = JSONResponse({"ok": True})
        for name in NAMES:
            response.delete_cookie(name, path="/")
        return response

    app.middleware("http")(app_module.plain_reasons)        # the real middleware
    return app


def _cookies(response) -> list[str]:
    return [v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"]


def test_every_cookie_survives_the_plain_words_middleware():
    response = TestClient(_app()).post("/api/auth/login")
    assert sorted(c.split("=")[0] for c in _cookies(response)) == sorted(NAMES)
    assert response.headers["x-custom"] == "kept"
    assert response.headers["content-type"] == "application/json"
    assert int(response.headers["content-length"]) == len(response.content)
    assert "rate" not in response.json()["error"].lower() or "anthropic." not in response.json()["error"]


def test_a_sign_out_still_clears_all_three_cookies():
    response = TestClient(_app()).post("/api/auth/logout")
    assert len(_cookies(response)) == 3


def test_a_client_keeps_its_session_across_requests_through_the_middleware():
    client = TestClient(_app())
    client.post("/api/auth/login")
    assert sorted(client.cookies.keys()) == sorted(NAMES)
