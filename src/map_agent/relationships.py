"""Normalize organization–person relationships in map results.

Discovery now returns people inside each actor. This module keeps one canonical
person record, records every organization affiliation found, and attaches the
canonical person back to every matching actor. It also handles older plans that
may still return standalone people.
"""

import re

from rapidfuzz import fuzz


def _key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _sources(items: list[dict] | None) -> list[dict]:
    out, seen = [], set()
    for source in items or []:
        url = (source or {}).get("url")
        if url and url not in seen:
            seen.add(url)
            out.append(source)
    return out


def _merge_person(existing: dict, new: dict) -> dict:
    merged = dict(existing)
    for field, value in new.items():
        if not value or field in ("sources", "organizations", "organization_name"):
            continue
        old = merged.get(field)
        if not old or (isinstance(old, str) and isinstance(value, str)
                       and len(value) > len(old)):
            merged[field] = value
    merged["sources"] = _sources(
        (existing.get("sources") or []) + (new.get("sources") or []))
    merged["_entity_type"] = "person"
    return merged


def _matching_actor(person: dict, actors: list[dict]) -> dict | None:
    """Best-effort compatibility path for old standalone person results."""
    explicit = _key(person.get("organization_name"))
    title = _key(person.get("title"))
    best, score = None, 0
    for actor in actors:
        name = _key(actor.get("name"))
        if not name:
            continue
        current = fuzz.token_set_ratio(explicit, name) if explicit else 0
        if name in title:
            current = max(current, 100)
        if current > score:
            best, score = actor, current
    return best if score >= 85 else None


def link_people_to_actors(entities: list[dict]) -> list[dict]:
    """Attach people to actors and retain a normalized top-level people list.

    The top-level list remains for API/export compatibility. The frontend uses
    each actor's `people` collection, so users see an organization together with
    its people instead of two disconnected result sections.
    """
    actors = [e for e in entities if e.get("_entity_type") == "actor"]
    standalone = [e for e in entities if e.get("_entity_type") == "person"]
    others = [e for e in entities if e.get("_entity_type") not in ("actor", "person")]

    people: dict[str, dict] = {}
    memberships: dict[str, set[str]] = {_key(a.get("name")): set() for a in actors}
    affiliations: dict[str, list[dict]] = {}

    def register(person: dict, actor: dict | None) -> None:
        person_key = _key(person.get("full_name"))
        if not person_key:
            return
        people[person_key] = (_merge_person(people[person_key], person)
                              if person_key in people else
                              _merge_person({}, person))
        if actor is None:
            return
        actor_key = _key(actor.get("name"))
        memberships.setdefault(actor_key, set()).add(person_key)
        affiliation = {"actor_name": actor.get("name"),
                       "title": person.get("title"), "is_current": True}
        known = affiliations.setdefault(person_key, [])
        if not any(_key(x.get("actor_name")) == actor_key for x in known):
            known.append(affiliation)

    for actor in actors:
        for person in actor.get("people") or []:
            register(person, actor)

    for person in standalone:
        register(person, _matching_actor(person, actors))

    for person_key, person in people.items():
        person["organizations"] = affiliations.get(person_key, [])

    for actor in actors:
        actor_key = _key(actor.get("name"))
        actor["people"] = [dict(people[k]) for k in sorted(
            memberships.get(actor_key, set()), key=lambda k: people[k].get("full_name", ""))]

    return actors + list(people.values()) + others

