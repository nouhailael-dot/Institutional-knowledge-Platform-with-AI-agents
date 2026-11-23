"""Who is acting: the one place the platform asks (decided 29 Oct 2026, extended 3 Nov).

Nobody types a name or an email. Every decision, upload and request records the
current user from here.

12 Nov 2026: the hosted app's login (backend.access) names the person for the
length of each request, so decisions, requests and Directory activity carry
their sign-in name, and a sign-in name that is an email address is where their
results are emailed. Locally, with no login, nobody is known: a placeholder and
no email, as before.

Individual accounts (GHUS_AUTH_MODE=supabase): the sign-in middleware sets the
signed-in account for the request (``signed_in_as``); it takes precedence over
the shared login's name. The account comes only from a verified session, never
from a request field, so nobody can act as someone else by sending a name or an id.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.accounts.store import Account

NO_SIGN_IN_YET = "Not recorded (no sign-in yet)"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ACTING: ContextVar[str | None] = ContextVar("ghus_acting_user", default=None)
_current: ContextVar["Account | None"] = ContextVar("compass_current_account", default=None)


def acting_as(name: str | None):
    """Name the signed-in person for this request; returns a token for ``done``."""
    return _ACTING.set(str(name).strip() if name and str(name).strip() else None)


def done(token) -> None:
    _ACTING.reset(token)


@contextmanager
def signed_in_as(account: "Account | None"):
    """Individual accounts: set the signed-in account for a block (a request)."""
    token = _current.set(account)
    try:
        yield account
    finally:
        _current.reset(token)


def current_account() -> "Account | None":
    """The signed-in account for this request (individual accounts), or None."""
    return _current.get()


def current_user(request=None) -> str:
    """The acting person's name, as recorded with what they did."""
    account = _current.get()
    if account is not None:
        return account.full_name
    return _ACTING.get() or NO_SIGN_IN_YET


def current_user_id() -> str | None:
    """The acting person's account id (Supabase Auth user id); None with the shared login."""
    account = _current.get()
    return account.user_id if account else None


def current_user_email(request=None) -> str | None:
    """Where their results are emailed: the account's email, else a sign-in name that is one."""
    account = _current.get()
    if account is not None:
        return account.email
    name = _ACTING.get()
    return name if name and _EMAIL.match(name) and len(name) <= 254 else None
