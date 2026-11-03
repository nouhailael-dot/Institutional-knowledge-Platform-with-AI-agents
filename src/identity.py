"""Who is acting: the one place the platform asks (decided 29 Oct 2026, extended 3 Nov).

Nobody types a name or an email. Every decision, upload and request records the
current user from here; until accounts exist that is a placeholder (and no email),
and once sign-in exists these two functions return the signed-in user.
"""

from __future__ import annotations

NO_SIGN_IN_YET = "Not recorded (no sign-in yet)"


def current_user(request=None) -> str:
    """The acting person's name, as recorded with what they did."""
    return NO_SIGN_IN_YET


def current_user_email(request=None) -> str | None:
    """Where their results are emailed; None until accounts give the user's address."""
    return None
