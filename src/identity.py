"""Who is acting: the one place the platform asks (decided 29 Oct 2026, extended 3 Nov).

Nobody types a name or an email. Every decision, upload and request records the
current user from here.

12 Nov 2026: the hosted app's login (backend.access) names the person for the
length of each request, so decisions, requests and Directory activity carry
their sign-in name, and a sign-in name that is an email address is where their
results are emailed. Locally, with no login, nobody is known: a placeholder and
no email, as before.
"""

from __future__ import annotations

import re
from contextvars import ContextVar

NO_SIGN_IN_YET = "Not recorded (no sign-in yet)"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ACTING: ContextVar[str | None] = ContextVar("ghus_acting_user", default=None)


def acting_as(name: str | None):
    """Name the signed-in person for this request; returns a token for ``done``."""
    return _ACTING.set(str(name).strip() if name and str(name).strip() else None)


def done(token) -> None:
    _ACTING.reset(token)


def current_user(request=None) -> str:
    """The acting person's name, as recorded with what they did."""
    return _ACTING.get() or NO_SIGN_IN_YET


def current_user_email(request=None) -> str | None:
    """Where their results are emailed: their sign-in name when it is an email address."""
    name = _ACTING.get()
    return name if name and _EMAIL.match(name) and len(name) <= 254 else None
