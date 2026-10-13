"""Park and Reject on a map's organizations.

A map keeps two copies of what it found: the result shown on the page and the
saved research state that later follow-ups rebuild the result from. Both are
changed together, or a follow-up would bring back what was just rejected.
"""

import time

PARKED = "parked"
ACTIONS = ("park", "unpark", "reject")


def entity_key(entity: dict) -> str:
    name = entity.get("full_name") if entity.get("_entity_type") == "person" else entity.get("name")
    return f"{entity.get('_entity_type')}|{str(name or '').strip().casefold()}"


def apply(result, workflow, name: str, website: str | None, action: str):
    """Return (result, workflow) with the action applied to one organization."""
    actors = ((result or {}).get("entities") or {}).get("actor", [])
    matches = [a for a in actors
               if a.get("name") == name and (a.get("website") or "") == (website or "")]
    if len(matches) != 1:
        raise LookupError("That organization is no longer in this map.")
    key = entity_key({**matches[0], "_entity_type": "actor"})
    found = [e for e in (workflow or {}).get("found", [])
             if e.get("_entity_type") == "actor" and entity_key(e) == key]

    if action == "park":
        for entity in matches + found:
            entity["_review"], entity["_parked_at"] = PARKED, time.time()
    elif action == "unpark":
        for entity in matches + found:
            entity.pop("_review", None)
            entity.pop("_parked_at", None)
    elif action == "reject":
        result["entities"]["actor"] = [a for a in actors if a is not matches[0]]
        if "counts" in result:
            result["counts"]["actor"] = len(result["entities"]["actor"])
        if workflow is not None:
            workflow["found"] = [e for e in workflow.get("found", []) if not any(e is f for f in found)]
            # Kept only so this map's own follow-up searches don't add it back.
            workflow["rejected"] = list(dict.fromkeys(workflow.get("rejected", []) + [key]))
    else:
        raise ValueError(f"Unknown review action: {action}")
    return result, workflow
