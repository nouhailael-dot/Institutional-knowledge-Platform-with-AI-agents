"""Personal preferences (accounts Phase 4), kept in compass.user_profile.preferences.

They change only what one person sees: their preferred sectors, saved
Directory filters, whether the Directory opens on My Records or All Records,
which Dashboard sections show, and which notifications they receive. Shared
records are never changed by them.

Everything is checked here, on the server: unknown keys are dropped, sizes are
limited, and a missing value takes its default.
"""

from __future__ import annotations

import copy

NOTIFY_KINDS = {
    "run_finished": "A Discovery, Update or map run finished",
    "run_failed": "A run failed or was interrupted",
    "import_review": "Records from my import wait in Review",
    "decisions": "Someone decided on or changed a record I brought in",
    "schedule": "One of my requests runs in the next 24 hours",
}
# What My profile offers to show or hide on the Dashboard (GHUS, 20 Nov 2026: the
# original Dashboard, with Notifications and Pending Deletion added), and the
# permission each needs (None: everyone).
DASHBOARD_CHOICES = {"summary": None, "spending": "requests.view", "notifications": None,
                     "deletions": "records.delete_permanent", "maps": None, "requests": "requests.view",
                     "directory": None}
# Every name a saved preference may hold: the choices above and the earlier
# personal Dashboard's, so preferences saved before still load.
DASHBOARD_SECTIONS = ("notifications", "runs", "activity", "records", "requests", "maps", "imports",
                      "reviews", "sectors", "summary", "spending", "deletions", "directory")


def dashboard_choices(permissions) -> list[str]:
    held = set(permissions or ())
    return [name for name, need in DASHBOARD_CHOICES.items() if need is None or need in held]
DIRECTORY_TABS = ("actors", "hubs", "people", "events")

DEFAULTS = {
    "sectors": [],
    "directory": {"default_view": "all", "saved_filters": []},
    "dashboard": {"hidden": []},
    "notifications": {**{kind: True for kind in NOTIFY_KINDS}, "email": False},
}

MAX_SECTORS = 20
MAX_FILTERS = 20
MAX_FILTER_VALUES = 20


class PreferenceError(ValueError):
    """A preference that cannot be kept; the message is safe to show."""


def _text(value, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        raise PreferenceError(f"Keep it under {limit} characters.")
    return text


def complete(stored: dict | None) -> dict:
    """The stored preferences with every default filled in (unknown keys dropped)."""
    try:
        return clean(stored or {})
    except PreferenceError:
        return copy.deepcopy(DEFAULTS)


def clean(raw: dict) -> dict:
    """Validated, complete preferences from what a person sent; PreferenceError otherwise."""
    if not isinstance(raw, dict):
        raise PreferenceError("Preferences must be an object.")
    out = copy.deepcopy(DEFAULTS)

    sectors = raw.get("sectors", [])
    if not isinstance(sectors, list) or len(sectors) > MAX_SECTORS:
        raise PreferenceError(f"Choose at most {MAX_SECTORS} sectors.")
    out["sectors"] = list(dict.fromkeys(s for s in (_text(x, 80) for x in sectors) if s))

    directory = raw.get("directory", {}) or {}
    if not isinstance(directory, dict):
        raise PreferenceError("Directory preferences must be an object.")
    view = directory.get("default_view", "all")
    if view not in ("all", "mine"):
        raise PreferenceError("The Directory opens on All Records or My Records.")
    out["directory"]["default_view"] = view
    filters = directory.get("saved_filters", []) or []
    if not isinstance(filters, list) or len(filters) > MAX_FILTERS:
        raise PreferenceError(f"Keep at most {MAX_FILTERS} saved filters.")
    seen = set()
    for item in filters:
        if not isinstance(item, dict):
            raise PreferenceError("A saved filter needs a name, a tab and its values.")
        name, tab, values = _text(item.get("name"), 60), item.get("tab"), item.get("values") or {}
        if not name or tab not in DIRECTORY_TABS or not isinstance(values, dict):
            raise PreferenceError("A saved filter needs a name, a Directory tab and its values.")
        if len(values) > MAX_FILTER_VALUES:
            raise PreferenceError("A saved filter keeps at most 20 values.")
        clean_values = {_text(k, 40): _text(v, 120) for k, v in values.items() if _text(v, 120)}
        if (tab, name.lower()) in seen:
            raise PreferenceError(f"Two saved filters are called {name!r}.")
        seen.add((tab, name.lower()))
        entry = {"name": name, "tab": tab, "values": clean_values}
        if item.get("search"):
            entry["search"] = _text(item["search"], 120)
        out["directory"]["saved_filters"].append(entry)

    dashboard = raw.get("dashboard", {}) or {}
    hidden = dashboard.get("hidden", []) if isinstance(dashboard, dict) else None
    if not isinstance(hidden, list) or any(h not in DASHBOARD_SECTIONS for h in hidden):
        raise PreferenceError("Unknown Dashboard section.")
    out["dashboard"]["hidden"] = [h for h in DASHBOARD_SECTIONS if h in hidden]

    notifications = raw.get("notifications", {}) or {}
    if not isinstance(notifications, dict):
        raise PreferenceError("Notification preferences must be an object.")
    for kind in (*NOTIFY_KINDS, "email"):
        if kind in notifications:
            if not isinstance(notifications[kind], bool):
                raise PreferenceError("Notification choices are on or off.")
            out["notifications"][kind] = notifications[kind]
    return out


def merge(current: dict, change: dict) -> dict:
    """``change`` applied over ``current`` (one level deep per section), then checked."""
    if not isinstance(change, dict):
        raise PreferenceError("Preferences must be an object.")
    base = complete(current)
    for key, value in change.items():
        if key not in DEFAULTS:
            raise PreferenceError(f"Unknown preference {key!r}.")
        if isinstance(DEFAULTS[key], dict) and isinstance(value, dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return clean(base)
