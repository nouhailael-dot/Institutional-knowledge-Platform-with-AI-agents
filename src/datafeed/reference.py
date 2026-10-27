"""The controlled vocabularies of the Data Feed, from GHUS reference data.

Categories, types, states, regions and parent links come from the Intern Guide
taxonomy (``src.review.taxonomy``, kept in step with the frontend and the
backend catalog by tests). Sectors and topics come from the database's own
``sector`` and ``topic`` tables, which hold the approved names; when the
database cannot be read, sectors fall back to the taxonomy and topics are
unavailable (a topic column then cannot be checked, and says so).

Each vocabulary is a list of ``{"code", "label"}``. A spreadsheet may carry
either; the label is what the dropdowns show.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from src.review import taxonomy

# Approved event types: the backend's Discovery event options
# (agents/collection/subscriptions.py EVENT_TYPES).
EVENT_TYPES = ("conference", "summit", "workshop", "forum", "symposium", "expo",
               "webinar", "hackathon", "training")
EVENT_FORMATS = (("in_person", "In person"), ("online", "Online"), ("hybrid", "Hybrid"))
RECURRENCE = (("annual", "Annual"), ("recurring", "Recurring"), ("one_time", "One-time"))
US = "United States"
# Dropdown suggestion only: a non-US country is accepted as written (its region
# is then "Not Applicable (Non-US)"). There is no country table in V2.
COUNTRIES = (US, "Canada", "Mexico", "Morocco", "United Kingdom", "France", "Germany")
CACHE_SECONDS = 300

_cache: dict[str, Any] = {}


def _items(pairs) -> list[dict[str, str]]:
    return [{"code": code, "label": label} for code, label in pairs]


def _database_lists(connect: Callable[[], Any] | None) -> dict[str, Any]:
    if connect is None:
        return {}
    try:
        with connect() as conn:
            sectors = conn.execute(
                "SELECT code, name FROM sector WHERE COALESCE(active, true) ORDER BY "
                "COALESCE(is_thematic, true) DESC, name").fetchall()
            topics = conn.execute(
                "SELECT code, name, topic_id::text FROM topic WHERE COALESCE(active, true) "
                "ORDER BY name").fetchall()
    except Exception:  # noqa: BLE001 - a reference read must not stop the page
        return {}
    return {"sectors": [{"code": r[0], "label": r[1]} for r in sectors],
            "topics": [{"code": r[0], "label": r[1], "topic_id": r[2]} for r in topics]}


def vocabularies(connect: Callable[[], Any] | None = None) -> dict[str, Any]:
    """Every controlled list, cached for a few minutes."""
    now = time.monotonic()
    if _cache.get("at") and now - _cache["at"] < CACHE_SECONDS and _cache.get("connect") is connect:
        return _cache["value"]
    db = _database_lists(connect)
    sectors = db.get("sectors") or _items(
        (*taxonomy.THEMATIC_SECTORS, *taxonomy.NON_THEMATIC_SECTORS))
    value = {
        "actor_categories": _items((code, label) for code, label, _t in taxonomy.CATEGORIES),
        "category_types": {
            code: _items((t_code, t_label) for t_code, t_label, _m in types)
            for code, _label, types in taxonomy.CATEGORIES
        },
        "sectors": sectors,
        "topics": db.get("topics") or [],
        "states": _items(sorted(taxonomy.STATE_NAMES.items(), key=lambda kv: kv[1])),
        "regions": [{"code": code, "label": label, "states": list(states)}
                    for code, label, states in taxonomy.REGIONS],
        "countries": _items((c, c) for c in COUNTRIES),
        "parent_links": _items((code, label) for code, label, is_parent in taxonomy.LINK_TYPES
                               if is_parent),
        "event_types": _items((t, t.capitalize()) for t in EVENT_TYPES),
        "event_formats": _items(EVENT_FORMATS),
        "recurrence": _items(RECURRENCE),
        "source": "database" if db else "taxonomy",
    }
    _cache.update(at=now, value=value, connect=connect)
    return value


def clear_cache() -> None:
    _cache.clear()


def lookup(items: list[dict[str, str]], raw: Any) -> dict[str, str] | None:
    """The item a cell names, by code or label, ignoring case and spacing."""
    wanted = " ".join(str(raw or "").split()).casefold()
    if not wanted:
        return None
    for item in items:
        if wanted in (item["code"].casefold(), item["label"].casefold()):
            return item
    return None


def region_for(state_code: str, country: str | None) -> str:
    """The region code a state belongs to; '' outside the US or without a state."""
    land = " ".join(str(country or "").split()).upper()
    if land and land not in taxonomy.US_COUNTRY_NAMES:
        return ""
    for code, _label, states in taxonomy.REGIONS:
        if state_code in states:
            return code
    return ""
