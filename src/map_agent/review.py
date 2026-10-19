"""Park and Reject on a map's organizations, people and events.

A map keeps two copies of what it found: the result shown on the page and the
saved research state that later follow-ups rebuild the result from. Both are
changed together, or a follow-up would bring back what was just rejected.
"""

import time

PARKED = "parked"
ACTIONS = ("park", "unpark", "reject")
KINDS = ("actor", "person", "event")


def _name(entity: dict):
    return entity.get("full_name") if entity.get("_entity_type") == "person" else entity.get("name")


def entity_key(entity: dict) -> str:
    return f"{entity.get('_entity_type')}|{str(_name(entity) or '').strip().casefold()}"


def apply(result, workflow, name: str, website: str | None, action: str, kind: str = "actor"):
    """Return (result, workflow) with the action applied to one record of `kind`."""
    records = ((result or {}).get("entities") or {}).get(kind, [])
    matches = [r for r in records
               if _name({**r, "_entity_type": kind}) == name
               and (r.get("website") or "") == (website or "")]
    if len(matches) != 1:
        raise LookupError("That result is no longer in this map.")
    key = entity_key({**matches[0], "_entity_type": kind})
    found = [e for e in (workflow or {}).get("found", [])
             if e.get("_entity_type") == kind and entity_key(e) == key]

    if action == "park":
        for entity in matches + found:
            entity["_review"], entity["_parked_at"] = PARKED, time.time()
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
