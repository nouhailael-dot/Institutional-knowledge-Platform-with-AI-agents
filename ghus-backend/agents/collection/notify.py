"""Tell the person who asked: a monitoring run has findings in Review Results.

Each run of a Monitor and Update request sends what it found to Review Results
for a person to verify. When a run sends anything, the person who created the
request (``requested_by``, an email address) is emailed (GHUS, 2026-10-29);
the Dashboard shows the finished run either way.

Mail goes out only through a server GHUS configures:

    GHUS_SMTP_HOST, GHUS_SMTP_PORT (587), GHUS_SMTP_USER, GHUS_SMTP_PASSWORD,
    GHUS_NOTIFY_FROM (the sender address), GHUS_APP_URL (the link in the email)

Without a host nothing is sent and the outcome says so; a failure to send never
fails the run. The email holds the request's name, what was found and a link -
no record content.
"""

from __future__ import annotations

import os
import re
import smtplib
import ssl
from email.message import EmailMessage

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NOUNS = {"actor": ("organization", "organizations"), "event": ("event", "events"),
         "person": ("person", "people")}


def is_email(value: object) -> bool:
    return bool(EMAIL.match(str(value or "").strip())) and len(str(value)) <= 254


def findings(outcome) -> int:
    counts = dict(getattr(outcome, "counts", None) or {})
    return int(counts.get("staged") or 0) + int(counts.get("review") or 0)


def message_for(outcome, recipient: str, *, sender: str, app_url: str) -> EmailMessage:
    count = findings(outcome)
    one, many = NOUNS.get(getattr(outcome, "entity", "actor"), NOUNS["actor"])
    noun = one if count == 1 else many
    title = getattr(outcome, "title", "") or "Your monitoring request"
    message = EmailMessage()
    message["Subject"] = f"Compass found {count} {noun}: {title}"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        f"Your request “{title}” has finished a run and found {count} {noun}.\n\n"
        f"They are waiting in Review Results for you to verify before they enter the "
        f"Ecosystem Directory:\n{app_url.rstrip('/')}/#review\n\n"
        "This message was sent by Compass, the GHUS Intelligence Platform.\n")
    return message


def notify_findings(outcome, recipient: object, *, environ=None, smtp_factory=None) -> dict:
    """Email ``recipient`` about a run's findings; say what happened, never raise."""

    env = os.environ if environ is None else environ
    if findings(outcome) == 0:
        return {"sent": False, "reason": "nothing found"}
    if not is_email(recipient):
        return {"sent": False, "reason": "no email on the request"}
    host = str(env.get("GHUS_SMTP_HOST") or "").strip()
    if not host:
        return {"sent": False, "reason": "no mail server configured (GHUS_SMTP_HOST)"}
    sender = str(env.get("GHUS_NOTIFY_FROM") or env.get("GHUS_SMTP_USER") or "").strip()
    if not is_email(sender):
        return {"sent": False, "reason": "no sender address configured (GHUS_NOTIFY_FROM)"}
    app_url = str(env.get("GHUS_APP_URL") or "http://127.0.0.1:8030")
    message = message_for(outcome, str(recipient).strip(), sender=sender, app_url=app_url)
    try:
        port = int(env.get("GHUS_SMTP_PORT") or 587)
        factory = smtp_factory or smtplib.SMTP
        with factory(host, port, timeout=20) as server:
            if port != 25:
                server.starttls(context=ssl.create_default_context())
            if env.get("GHUS_SMTP_USER"):
                server.login(str(env["GHUS_SMTP_USER"]), str(env.get("GHUS_SMTP_PASSWORD") or ""))
            server.send_message(message)
    except Exception as exc:  # noqa: BLE001 - a mail failure never fails the run
        return {"sent": False, "reason": f"sending failed: {type(exc).__name__}"}
    return {"sent": True, "to": str(recipient).strip()}
