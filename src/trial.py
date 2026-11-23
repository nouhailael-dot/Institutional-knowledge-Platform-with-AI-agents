"""When the hosted team trial starts (GHUS, 10 Nov 2026).

One setting on the host, ``GHUS_TRIAL_START`` (an ISO date or date-time; a
date alone is midnight UTC), gives every tester a clean start:

* Review lists only what was raised from then on: older pending items are set
  aside after each sync (kept, undecided, reversible with
  ``python -m scripts.set_aside_before_trial --restore --live``);
* the Dashboard's spending, counts and recent items begin there;
* Explore and Map lists only maps made from then on.

Nothing is deleted and nothing canonical is written. Earlier work stays in the
database. The older name ``GHUS_DASHBOARD_SINCE`` is still read. Not set (the
local servers): nothing changes.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SET_ASIDE_REASON = "before_trial_2026-11"


def trial_start(environ=None) -> datetime | None:
    env = os.environ if environ is None else environ
    raw = (env.get("GHUS_TRIAL_START") or env.get("GHUS_DASHBOARD_SINCE") or "").strip()
    if not raw:
        return None
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("GHUS_TRIAL_START is not an ISO date or time (%r); nothing is hidden", raw)
        return None
    return (when if when.tzinfo else when.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def iso(when: datetime | None) -> str | None:
    return when.isoformat().replace("+00:00", "Z") if when else None
