"""Email copies of notifications: prepared, not sent (accounts Phase 4).

A notification records whether its owner asked for email (their preferences).
This module finds those not yet emailed and writes the message. Delivery is
refused: no sender exists until one is approved (an SMTP or transactional email
service, its credentials in the host's secrets, and GHUS_NOTIFY_EMAIL=1).
"""

from __future__ import annotations

import os


class EmailNotEnabled(RuntimeError):
    """Email delivery of notifications is not approved or not configured."""


def pending(store, *, limit: int = 100) -> list[dict]:
    """Notifications whose owner asked for email and that were not emailed yet."""
    with store.connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT n.notification_id, p.email, p.full_name, n.title, n.body, n.link, n.created_at
              FROM compass.notification n JOIN compass.user_profile p ON p.user_id = n.user_id
             WHERE n.email_requested AND n.emailed_at IS NULL AND p.status = 'active'
             ORDER BY n.created_at LIMIT %s
        """, (limit,))
        keys = ("id", "to", "name", "title", "body", "link", "created_at")
        return [dict(zip(keys, row)) for row in cur.fetchall()]


def render(item: dict, *, site_url: str) -> dict:
    """Subject and plain-text body of one notification email (no tracking, no secrets)."""
    link = f"{site_url.rstrip('/')}/" + (f"?tab={item['link']}" if item.get("link") else "")
    return {"to": item["to"], "subject": f"GHUS Compass: {item['title']}",
            "text": f"Hello {item['name']},\n\n{item['title']}\n{item.get('body') or ''}\n\n"
                    f"Open Compass: {link}\n\nYou receive this because email notifications are on "
                    "in your Compass preferences (My profile).\n"}


def deliver(*_args, **_kwargs) -> None:
    """Refused until a sender is approved and configured."""
    if os.environ.get("GHUS_NOTIFY_EMAIL") != "1":
        raise EmailNotEnabled("Email notifications are not switched on (GHUS_NOTIFY_EMAIL).")
    raise EmailNotEnabled("No approved email sender is configured yet.")
