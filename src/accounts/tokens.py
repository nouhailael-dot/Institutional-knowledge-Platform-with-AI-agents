"""Signed tokens, with the standard library only.

* verify_access_token: a Supabase Auth access token (a JWT signed with the
  project's JWT secret, HS256). Only HS256 is accepted, whatever the token's
  header claims, so a token cannot choose a weaker check ("none") or another
  key. Expiry, audience and subject are required.
* sign / unsign: short values the server writes into a cookie (the session's
  start time) so the browser cannot change them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


class InvalidToken(Exception):
    """The token is malformed, forged, expired or not for this application."""


def _b64decode(part: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
    except (ValueError, TypeError) as exc:
        raise InvalidToken("malformed token") from exc


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def verify_access_token(token: str, secret: str, *, audience: str = "authenticated",
                        leeway: int = 30, now: float | None = None) -> dict:
    """The verified claims of a Supabase Auth access token; InvalidToken otherwise."""
    if not secret:
        raise InvalidToken("no JWT secret configured")
    parts = (token or "").split(".")
    if len(parts) != 3:
        raise InvalidToken("malformed token")
    try:
        header = json.loads(_b64decode(parts[0]))
        claims = json.loads(_b64decode(parts[1]))
    except ValueError as exc:
        raise InvalidToken("malformed token") from exc
    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise InvalidToken("unsupported signing algorithm")
    expected = hmac.new(secret.encode("utf-8"), f"{parts[0]}.{parts[1]}".encode("ascii"),
                        hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64decode(parts[2])):
        raise InvalidToken("bad signature")
    if not isinstance(claims, dict):
        raise InvalidToken("malformed claims")
    current = time.time() if now is None else now
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp + leeway < current:
        raise InvalidToken("expired")
    aud = claims.get("aud")
    if audience not in (aud if isinstance(aud, list) else [aud]):
        raise InvalidToken("wrong audience")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise InvalidToken("no subject")
    return claims


def make_access_token(claims: dict, secret: str) -> str:
    """An HS256 JWT. Used by tests and the local stand-in for Supabase Auth."""
    head = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64encode(json.dumps(claims, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode("utf-8"), f"{head}.{body}".encode("ascii"), hashlib.sha256).digest()
    return f"{head}.{body}.{_b64encode(sig)}"


def sign(value: str, key: bytes) -> str:
    mac = hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()
    return f"{value}.{_b64encode(mac)}"


def unsign(signed: str | None, key: bytes) -> str | None:
    """The value, or None when missing or tampered with."""
    if not signed or "." not in signed:
        return None
    value, _, mac = signed.rpartition(".")
    try:
        given = _b64decode(mac)
    except InvalidToken:
        return None
    expected = hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()
    return value if hmac.compare_digest(expected, given) else None
