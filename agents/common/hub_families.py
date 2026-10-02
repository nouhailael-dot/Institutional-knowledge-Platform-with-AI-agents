"""Fail-closed family resolution for Architecture V2 hub detection."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

FAMILY_RELATIONSHIP_TYPES = frozenset({"unit_of", "operated_by"})


@dataclass(frozen=True)
class FamilyEdge:
    child_actor_id: str
    parent_actor_id: str
    relationship_type: str


@dataclass(frozen=True)
class FamilyResolution:
    family_by_actor: dict[str, str]
    unresolved: dict[str, str]


def resolve_actor_families(
    actor_ids: Iterable[str], edges: Iterable[FamilyEdge]
) -> FamilyResolution:
    """Resolve one top-level root using only authoritative structural edges.

    Cycles and multiple distinct roots fail closed. Irrelevant relationship
    types are ignored rather than interpreted as hierarchy.
    """
    targets = tuple(sorted({str(actor_id) for actor_id in actor_ids}))
    parents: dict[str, set[str]] = {}
    for edge in edges:
        if edge.relationship_type not in FAMILY_RELATIONSHIP_TYPES:
            continue
        child = str(edge.child_actor_id)
        parent = str(edge.parent_actor_id)
        if child == parent:
            parents.setdefault(child, set()).add(parent)
        else:
            parents.setdefault(child, set()).add(parent)

    cache: dict[str, tuple[frozenset[str], str | None]] = {}

    def roots(node: str, path: tuple[str, ...]) -> tuple[frozenset[str], str | None]:
        if node in path:
            return frozenset(), "cycle"
        if node in cache:
            return cache[node]
        direct = sorted(parents.get(node, ()))
        if not direct:
            result = (frozenset({node}), None)
            cache[node] = result
            return result
        found: set[str] = set()
        next_path = (*path, node)
        for parent in direct:
            parent_roots, reason = roots(parent, next_path)
            if reason:
                result = (frozenset(), reason)
                cache[node] = result
                return result
            found.update(parent_roots)
        if len(found) != 1:
            result = (frozenset(found), "multiple_distinct_roots")
        else:
            result = (frozenset(found), None)
        cache[node] = result
        return result

    family_by_actor: dict[str, str] = {}
    unresolved: dict[str, str] = {}
    for actor_id in targets:
        actor_roots, reason = roots(actor_id, ())
        if reason or len(actor_roots) != 1:
            unresolved[actor_id] = reason or "ambiguous_qualifying_ancestry"
        else:
            family_by_actor[actor_id] = next(iter(actor_roots))
    return FamilyResolution(family_by_actor, unresolved)
