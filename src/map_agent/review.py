"""Park and Reject on a map's organizations, people and events.

A map keeps two copies of what it found: the result shown on the page and the
saved research state that later follow-ups rebuild the result from. Both are
changed together, or a follow-up would bring back what was just rejected.
"""

import time

PARKED = "parked"
# Verify marks a card ready to save; "Save verified to Compass" then sends the
# ready cards to the database through the Data Feed (28 Oct 2026).
READY = "ready"
ACTIONS = ("park", "unpark", "reject", "ready", "unready")
KINDS = ("actor", "person", "event")


def _name(entity: dict):
    return entity.get("full_name") if entity.get("_entity_type") == "person" else entity.get("name")


def entity_key(entity: dict) -> str:
    return f"{entity.get('_entity_type')}|{str(_name(entity) or '').strip().casefold()}"


def _locate(result, workflow, name, website, kind):
    """The card on the page and its copies in the saved research state."""
    records = ((result or {}).get("entities") or {}).get(kind, [])
    matches = [r for r in records
               if _name({**r, "_entity_type": kind}) == name
               and (r.get("website") or "") == (website or "")]
    if len(matches) != 1:
        raise LookupError("That result is no longer in this map.")
    key = entity_key({**matches[0], "_entity_type": kind})
    found = [e for e in (workflow or {}).get("found", [])
             if e.get("_entity_type") == kind and entity_key(e) == key]
    return records, matches, found


def mark_saved(result, workflow, name, website, kind, saved: dict):
    """Record what saving did with one card (added, sent to Review, not saved).

    Kept under "_db_save", not "_saved": FastAPI's JSON encoder silently drops
    keys starting with "_sa" (it takes them for SQLAlchemy internals)."""
    _records, matches, found = _locate(result, workflow, name, website, kind)
    for entity in matches + found:
        entity["_db_save"] = saved
        if saved.get("outcome") != "not_saved" and entity.get("_review") == READY:
            entity.pop("_review", None)
    return result, workflow


def apply(result, workflow, name: str, website: str | None, action: str, kind: str = "actor"):
    """Return (result, workflow) with the action applied to one record of `kind`."""
    records, matches, found = _locate(result, workflow, name, website, kind)
    key = entity_key({**matches[0], "_entity_type": kind})
    if action in ("ready", "unready", "park") and (matches[0].get("_db_save") or {}).get("outcome") in ("directory", "review"):
        raise LookupError("That result has already been saved.")

    if action == "park":
        for entity in matches + found:
            entity["_review"], entity["_parked_at"] = PARKED, time.time()
    elif action == "ready":
        for entity in matches + found:
            entity["_review"] = READY
            entity.pop("_parked_at", None)
    elif action == "unready":
        for entity in matches + found:
            if entity.get("_review") == READY:
                entity.pop("_review", None)
    elif action == "unpark":
        for entity in matches + found:
            entity.pop("_review", None)
            entity.pop("_parked_at", None)
    elif action == "reject":
        result["entities"][kind] = [r for r in records if r is not matches[0]]
        if "counts" in result:
            result["counts"][kind] = len(result["entities"][kind])
        if workflow is not None:
            workflow["found"] = [e for e in workflow.get("found", []) if not any(e is f for f in found)]
            # Kept only so this map's own follow-up searches don't add it back.
            workflow["rejected"] = list(dict.fromkeys(workflow.get("rejected", []) + [key]))
    else:
        raise ValueError(f"Unknown review action: {action}")
    return result, workflow
