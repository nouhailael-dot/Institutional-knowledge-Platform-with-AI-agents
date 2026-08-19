"""Sanitization helpers for messages that leave the reporting boundary."""

from __future__ import annotations

import os
import re
from typing import Any

_DSN_RE = re.compile(r"\b(?:postgresql|postgres|mysql|mssql|redshift)\+?[a-z0-9_]*://[^\s\"'<>]+", re.IGNORECASE)
_SECRET_PAIR_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|api[_-]?key|token|secret|access[_-]?key|connection[_-]?string)=([^&\s;,'\")]+)"
)


def sanitize_exception(exc: BaseException) -> dict[str, str]:
    return {
        "error_type": exc.__class__.__name__,
        "message": sanitize_text(str(exc)),
    }


def generic_tool_failure(tool_name: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"Tool {tool_name!r} failed. See query_log for the sanitized trace.",
    }


def sanitize_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = _DSN_RE.sub("<redacted-dsn>", text)
    text = _SECRET_PAIR_RE.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    for secret in _known_secret_values():
        if secret and len(secret) >= 8:
            text = text.replace(secret, "<redacted-secret>")
    return text


def _known_secret_values() -> set[str]:
    needles: set[str] = set()
    for key, value in os.environ.items():
        lowered = key.lower()
        if any(
            marker in lowered
            for marker in ("password", "passwd", "pwd", "api_key", "apikey", "token", "secret", "database_url")
        ):
            needles.add(value)
    return needles
