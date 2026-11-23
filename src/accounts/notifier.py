"""Notifications for one person (accounts Phase 4), from data Compass already keeps.

Nothing new is tracked. When a person opens their Dashboard or notifications,
``sync_for`` reads the state of *their own* work - their requests' runs, their
maps, their imports, their requests' schedules - and turns what changed into
notifications. Decisions others take on their records arrive through
``notify`` from the routes that take them.

* One notification per event and person: each has a key (a run and its
  outcome, a map and its outcome, ...) and a second attempt is ignored, so
  syncing again never repeats one.
* A person's notification preferences decide what is created at all.
* Email is prepared, not sent: a notification records whether its owner asked
  for email; no sender exists until one is approved.

Records an import's background completion stores after the upload are given
the import's owner here too (``sync_import_ownership``): first claim wins, and
imports from before accounts have no owner, so nothing old is assigned.
"""

from __future__ import annotations

import logging
import time
from threading import Lock

logger = logging.getLogger(__name__)

SYNC_EVERY_SECONDS = 60
_last_sync: dict[str, float] = {}
_lock = Lock()

MAP_FINISHED = {"done"}
MAP_FAILED = {"error", "interrupted", "budget_stopped", "cancelled"}
# A run still "running" this long after it started has very likely been interrupted.
STALE_RUN_SECONDS = 6 * 3600


def notify(store, user_id: str, *, kind: str, title: str, body: str = "", link: str | None = None,
           key: str) -> bool:
    """Create a notification unless the person turned that kind off or already has it."""
    preferences = store.preferences(user_id)["notifications"]
    if not preferences.get(kind, True):
        return False
    return store.add_notification(user_id=user_id, kind=kind, title=title, body=body, link=link,
                                  dedupe_key=key, email_requested=bool(preferences.get("email")))


def sync_import_ownership(store, created_entities, *, user_id: str | None = None,
                          run_id: str | None = None) -> int:
    """Give an import's owner the records the import created later. ``created_entities``
    is DataFeedService.created_entities. Returns the number of new owners recorded."""
    added = 0
    for imp in store.owned_imports(user_id, run_id):
        kind = imp["record_type"]
        if kind not in ("actor", "person", "event"):
            continue
        try:
            entities = created_entities(imp["run_id"])
        except Exception:
            logger.warning("Could not read what import %s created", imp["run_id"], exc_info=True)
            continue
        for entity_id in entities:
            added += store.claim_owner(entity_type=kind, entity_id=entity_id,
                                       owner_user_id=imp["owner_user_id"], origin=imp["origin"],
                                       source_ref=f"datafeed:{imp['run_id']}")
    return added


def sync_for(store, user_id: str, *, maps: list[dict] = (), imports: list[dict] = (),
             created_entities=None, force: bool = False) -> int:
    """Turn the state of this person's own work into notifications (at most once a
    minute unless ``force``). ``maps`` are their maps (id, description, status);
    ``imports`` their Data Feed history rows. Returns notifications created."""
    now = time.monotonic()
    with _lock:
        if not force and now - _last_sync.get(user_id, -1e9) < SYNC_EVERY_SECONDS:
            return 0
        _last_sync[user_id] = now
    made = 0
    if created_entities is not None:
        try:
            sync_import_ownership(store, created_entities, user_id=user_id)
        except Exception:
            logger.warning("Import ownership sync failed for %s", user_id, exc_info=True)

    for run in store.request_runs(user_id):
        title, rid, status = run["title"], run["run_id"], run["status"]
        if status in ("succeeded", "attention"):
            found = run.get("found") or 0
            review = run.get("for_review") or 0
            made += notify(store, user_id, kind="run_finished", key=f"run:{rid}:done",
                           title=f"Your request '{title}' finished",
                           body=f"{found} found, {review} waiting in Review Results."
                           + (" Some items need your attention." if status == "attention" else ""),
                           link="review")
        elif status == "failed":
            made += notify(store, user_id, kind="run_failed", key=f"run:{rid}:failed",
                           title=f"Your request '{title}' failed",
                           body=run.get("reason") or "Open Monitor and Update for the details.",
                           link="discovery")
        elif status == "running" and run.get("started_at") is not None and \
                time.time() - run["started_at"].timestamp() > STALE_RUN_SECONDS:
            made += notify(store, user_id, kind="run_failed", key=f"run:{rid}:stale",
                           title=f"Your request '{title}' may have been interrupted",
                           body="It started more than 6 hours ago and has not finished. "
                                "Check it in Monitor and Update; Run now starts it again.",
                           link="discovery")

    for m in maps:
        name, status = m.get("description") or "Untitled map", m.get("status")
        if status in MAP_FINISHED:
            made += notify(store, user_id, kind="run_finished", key=f"map:{m['id']}:done",
                           title=f"Your map '{name}' is ready", body="Open it in Explore and Map.",
                           link="map")
        elif status in MAP_FAILED:
            made += notify(store, user_id, kind="run_failed", key=f"map:{m['id']}:{status}",
                           title=f"Your map '{name}' stopped",
                           body={"budget_stopped": "It reached its budget.",
                                 "cancelled": "It was stopped."}.get(status,
                                 "It did not finish. Open it in Explore and Map to resume."),
                           link="map")

    for imp in imports:
        waiting = (imp.get("counts") or {}).get("pending", 0) + (imp.get("counts") or {}).get("deferred", 0)
        if waiting:
            made += notify(store, user_id, kind="import_review", key=f"import-review:{imp['run_id']}",
                           title=f"{waiting} record(s) from your import "
                                 f"'{imp.get('import_name') or 'Untitled import'}' wait in Review",
                           body="Open Review Results to decide on them.", link="review")

    for due in store.requests_due(user_id):
        made += notify(store, user_id, kind="schedule",
                       key=f"due:{due['request_id']}:{due['next_due_at']:%Y-%m-%d}",
                       title=f"Your request '{due['title']}' runs soon",
                       body=f"Next run: {due['next_due_at']:%b %d, %H:%M} UTC.", link="discovery")
    return made
