"""Who may open the hosted platform (GHUS, 9 Nov 2026, 10-day team trial).

The hosted app is private to the team: every page and every /api call asks the
browser for a login (HTTP Basic, over the host's HTTPS). Accounts come from one
environment variable, never from the code or the repository:

    GHUS_ACCESS_USERS="amina@example.org:long-pass-1,ismail@example.org:long-pass-2"

Entries are separated by commas; each is ``name:password`` (split at the first
colon). Names are matched without regard to case, so an email typed with a
capital letter still signs in. The host's health check (/api/health) is the
only path open without a login, and it reveals nothing.

Hardening (10 Nov 2026, before the team is invited):

* passwords are compared in constant time, and an unknown name costs the same
  comparison as a known one;
* failed sign-ins are limited: after ``MAX_FAILURES_PER_NAME`` wrong passwords
  for one name, or ``MAX_FAILURES_PER_CLIENT`` from one address, within
  ``WINDOW_SECONDS``, that name or address is refused (429) until the window
  passes, even with the right password;
* a browser request that changes something (POST, PUT, PATCH, DELETE) must
  come from this site's own pages (its Origin header), so another site cannot
  make a signed-in browser submit a form or an upload;
* pages may not be framed by another site, and responses are not cached by a
  shared proxy.

Locally nothing changes: without GHUS_REQUIRE_LOGIN=1 and no accounts, no login
is asked. With GHUS_REQUIRE_LOGIN=1 and no accounts it fails closed: every
request is refused rather than served without a login.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import secrets
import time
from collections import deque
from threading import Lock
from urllib.parse import urlsplit

from starlette.responses import PlainTextResponse

OPEN_PATHS = frozenset({"/api/health"})
REALM = 'Basic realm="GHUS Compass", charset="UTF-8"'
MIN_PASSWORD_LENGTH = 12
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

WINDOW_SECONDS = 15 * 60
MAX_FAILURES_PER_NAME = 5
MAX_FAILURES_PER_CLIENT = 20
_MAX_TRACKED = 5000

SECURITY_HEADERS = {
    "X-Frame-Options": "SAMEORIGIN",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}


def accounts(raw: str | None = None) -> dict[str, str]:
    """name (lower case) -> password, from GHUS_ACCESS_USERS."""
    raw = os.environ.get("GHUS_ACCESS_USERS", "") if raw is None else raw
    found: dict[str, str] = {}
    for entry in raw.split(","):
        name, sep, password = entry.strip().partition(":")
        if sep and name.strip() and password:
            found[name.strip().lower()] = password
    return found


def weak_accounts(known: dict[str, str]) -> list[str]:
    """Names whose password is shorter than MIN_PASSWORD_LENGTH."""
    return sorted(name for name, password in known.items() if len(password) < MIN_PASSWORD_LENGTH)


def login_required() -> bool:
    return os.environ.get("GHUS_REQUIRE_LOGIN", "").strip() == "1" or bool(accounts())


def _credentials(header: str | None) -> tuple[str, str] | None:
    if not header or not header.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    name, sep, password = decoded.partition(":")
    if not sep:
        return None
    return name.strip().lower(), password


def signed_in(header: str | None, known: dict[str, str]) -> str | None:
    """The account name the Authorization header proves, or None."""
    given = _credentials(header)
    if given is None:
        return None
    name, password = given
    expected = known.get(name)
    # Compare even for an unknown name, so timing does not tell names apart.
    ok = hmac.compare_digest(password.encode("utf-8"),
                             (expected if expected is not None else "\x00" * 32).encode("utf-8"))
    return name if ok and expected is not None else None


class FailedSignIns:
    """Wrong passwords per name and per client address, in a sliding window.

    Only different wrong passwords count: a browser repeating one stale
    password for every file of a page is one failure, not twenty. Passwords
    are kept only as keyed hashes, and only for the window. Held in memory:
    the hosted app runs one process; a restart clears it, which only gives an
    attacker the same few guesses again.
    """

    def __init__(self, *, window: float = WINDOW_SECONDS, per_name: int = MAX_FAILURES_PER_NAME,
                 per_client: int = MAX_FAILURES_PER_CLIENT, clock=time.monotonic):
        self.window, self.per_name, self.per_client, self.clock = window, per_name, per_client, clock
        self._seen: dict[str, deque[tuple[float, str]]] = {}
        self._lock = Lock()
        self._key = secrets.token_bytes(32)

    def _recent(self, key: str, now: float) -> deque[tuple[float, str]]:
        times = self._seen.get(key)
        if times is None:
            return deque()
        while times and times[0][0] <= now - self.window:
            times.popleft()
        if not times:
            del self._seen[key]
        return times

    def retry_after(self, name: str | None, client: str | None) -> int:
        """Seconds until this name and address may try again; 0 when they may now."""
        now = self.clock()
        wait = 0.0
        with self._lock:
            for key, limit in ((f"name:{name}", self.per_name), (f"client:{client}", self.per_client)):
                if key.endswith(":None"):
                    continue
                times = self._recent(key, now)
                if len(times) >= limit:
                    wait = max(wait, times[-limit][0] + self.window - now)
        return int(wait) + 1 if wait > 0 else 0

    def failed(self, name: str | None, client: str | None, password: str = "") -> None:
        now = self.clock()
        mark = hmac.new(self._key, f"{name}|{password}".encode("utf-8"), hashlib.sha256).hexdigest()
        with self._lock:
            if len(self._seen) >= _MAX_TRACKED:
                for key in list(self._seen):
                    self._recent(key, now)
            if len(self._seen) >= _MAX_TRACKED:
                self._seen.pop(next(iter(self._seen)))
            for key in (f"name:{name}", f"client:{client}"):
                if key.endswith(":None"):
                    continue
                times = self._recent(key, now)
                if all(seen != mark for _, seen in times):
                    self._seen.setdefault(key, times).append((now, mark))

    def succeeded(self, name: str) -> None:
        with self._lock:
            self._seen.pop(f"name:{name}", None)


FAILURES = FailedSignIns()


def same_origin(request) -> bool:
    """False when a browser says the request came from another site."""
    origin = request.headers.get("origin")
    if origin is None:
        # Not sent by a browser page (a script, curl). Browsers send Origin on
        # every cross-site POST, so a forged form always carries one.
        return True
    # The host the browser asked for: Host, or the one the hosting proxy
    # forwards (a forged cross-site form can set neither).
    hosts = {(request.headers.get(name) or "").split(",")[0].strip().lower()
             for name in ("host", "x-forwarded-host")} - {""}
    return urlsplit(origin.lower()).netloc in hosts


def _secured(response):
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    response.headers.setdefault("Cache-Control", "private")
    return response


async def require_login(request, call_next):
    """HTTP middleware: refuse every request without a valid login."""
    if not login_required() or request.url.path in OPEN_PATHS:
        return await call_next(request)
    known = accounts()
    if not known:
        return PlainTextResponse("Access is not configured on this server.", status_code=503)
    client = request.client.host if request.client else None
    given = _credentials(request.headers.get("authorization"))
    tried = given[0] if given else None
    wait = FAILURES.retry_after(tried, client) if given else 0
    if wait:
        minutes = max(1, round(wait / 60))
        return _secured(PlainTextResponse(
            f"Too many wrong passwords. Try again in about {minutes} minute(s).",
            status_code=429, headers={"Retry-After": str(wait)}))
    name = signed_in(request.headers.get("authorization"), known)
    if name is None:
        if given:
            FAILURES.failed(tried, client, given[1])
        return _secured(PlainTextResponse("Sign in to open GHUS Compass.", status_code=401,
                                          headers={"WWW-Authenticate": REALM}))
    FAILURES.succeeded(name)
    if request.method in UNSAFE_METHODS and not same_origin(request):
        return _secured(PlainTextResponse(
            "This change was sent from another site and was refused.", status_code=403))
    request.state.access_user = name
    return _secured(await call_next(request))
