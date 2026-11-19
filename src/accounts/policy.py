"""Password rules, names and addresses, and request limits for account actions."""

from __future__ import annotations

import re
import time
from collections import deque
from threading import Lock

MIN_PASSWORD = 12
MAX_PASSWORD = 256
# The most common long passwords and obvious choices; Supabase Auth adds its own checks.
_COMMON = {"password1234", "123456789012", "qwertyuiopas", "passwordpassword", "letmein12345",
           "compass12345", "ghuscompass1", "welcome12345", "iloveyou1234", "administrator"}
_EMAIL = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")


def password_problem(password: str, *, email: str = "", name: str = "") -> str | None:
    """Why a password is refused, or None."""
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if len(password) > MAX_PASSWORD:
        return f"Use at most {MAX_PASSWORD} characters."
    low = password.lower()
    if low in _COMMON or len(set(password)) < 4:
        return "That password is too easy to guess. Choose a less common one."
    local = email.split("@")[0].lower()
    if (local and len(local) >= 4 and local in low) or (email and email.lower() in low):
        return "Do not use your email address in your password."
    if name and len(name.strip()) >= 4 and name.strip().lower().replace(" ", "") in low.replace(" ", ""):
        return "Do not use your name in your password."
    return None


def clean_email(value: str) -> str | None:
    email = (value or "").strip().lower()
    return email if len(email) <= 254 and _EMAIL.match(email) else None


def clean_name(value: str) -> str | None:
    name = " ".join((value or "").split())
    return name if 1 <= len(name) <= 120 else None


class Limiter:
    """At most ``limit`` actions per key in a sliding ``window`` (seconds). In memory."""

    def __init__(self, limit: int, window: float, *, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self._seen: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, *keys: str | None) -> bool:
        """Count one action against every key; False (and nothing counted) when any is full."""
        now = self.clock()
        with self._lock:
            if len(self._seen) > 10000:
                self._seen.clear()
            queues = []
            for key in keys:
                if not key:
                    continue
                q = self._seen.setdefault(key, deque())
                while q and q[0] <= now - self.window:
                    q.popleft()
                if len(q) >= self.limit:
                    return False
                queues.append(q)
            for q in queues:
                q.append(now)
            return True
