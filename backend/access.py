"""Who may open the hosted platform (GHUS, 9 Nov 2026, 10-day team trial).

The hosted app is private to the team: every page and every /api call asks the
browser for a login (HTTP Basic, over the host's HTTPS). Accounts come from one
environment variable, never from the code or the repository:

    GHUS_ACCESS_USERS="amina:long-pass-1,ismail:long-pass-2"

Entries are separated by commas; each is ``name:password`` (split at the first
colon). The host's health check (/api/health) is the only path open without a
login, and it reveals nothing.

Locally nothing changes: without GHUS_REQUIRE_LOGIN=1 and no accounts, no login
is asked. With GHUS_REQUIRE_LOGIN=1 and no accounts it fails closed: every
request is refused rather than served without a login.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import os

from starlette.responses import PlainTextResponse

OPEN_PATHS = frozenset({"/api/health"})
REALM = 'Basic realm="GHUS Compass", charset="UTF-8"'


def accounts(raw: str | None = None) -> dict[str, str]:
    """name -> password, from GHUS_ACCESS_USERS."""
    raw = os.environ.get("GHUS_ACCESS_USERS", "") if raw is None else raw
    found: dict[str, str] = {}
    for entry in raw.split(","):
        name, sep, password = entry.strip().partition(":")
        if sep and name.strip() and password:
            found[name.strip()] = password
    return found


def login_required() -> bool:
    return os.environ.get("GHUS_REQUIRE_LOGIN", "").strip() == "1" or bool(accounts())


def signed_in(header: str | None, known: dict[str, str]) -> str | None:
    """The account name the Authorization header proves, or None."""
    if not header or not header.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    name, sep, password = decoded.partition(":")
    if not sep:
        return None
    expected = known.get(name)
    # Compare even for an unknown name, so timing does not tell names apart.
    ok = hmac.compare_digest(password.encode("utf-8"),
                             (expected if expected is not None else "\x00" * 32).encode("utf-8"))
    return name if ok and expected is not None else None


async def require_login(request, call_next):
    """HTTP middleware: refuse every request without a valid login."""
    if not login_required() or request.url.path in OPEN_PATHS:
        return await call_next(request)
    known = accounts()
    if not known:
        return PlainTextResponse("Access is not configured on this server.", status_code=503)
    name = signed_in(request.headers.get("authorization"), known)
    if name is None:
        return PlainTextResponse("Sign in to open GHUS Compass.", status_code=401,
                                 headers={"WWW-Authenticate": REALM})
    request.state.access_user = name
    return await call_next(request)
