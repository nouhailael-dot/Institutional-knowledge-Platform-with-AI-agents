"""Field policy loading for generalized enrichment."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class FieldPolicy:
    entity_type: str
    name: str
    enrichable: bool
    auto_apply_floor: Optional[float] = None

    def allows_auto_apply(self, confidence: float) -> bool:
        return self.auto_apply_floor is not None and confidence >= self.auto_apply_floor


def load_field_config(root: Path) -> dict[str, object]:
    path = root / "agents" / "config" / "fields.yaml"
    return json.loads(path.read_text(encoding="utf-8"))


def policies_for_entity(config: dict[str, object], entity_type: str) -> dict[str, FieldPolicy]:
    entity_config = _entity_config(config, entity_type)
    fields = dict(entity_config.get("fields", {}))
    policies: dict[str, FieldPolicy] = {}
    for field_name, raw_policy in fields.items():
        raw = dict(raw_policy or {})
        floor = raw.get("auto_apply_floor")
        policies[field_name] = FieldPolicy(
            entity_type=entity_type,
            name=field_name,
            enrichable=bool(raw.get("enrichable", False)),
            auto_apply_floor=None if floor is None else float(floor),
        )
    return policies


def resolve_field_set(
    config: dict[str, object],
    entity_type: str,
    field_set: Optional[str],
) -> tuple[str, ...]:
    entity_config = _entity_config(config, entity_type)
    policies = policies_for_entity(config, entity_type)
    selected_set = field_set or str(entity_config.get("default_field_set") or "default")

    if selected_set == "all":
        fields = tuple(name for name, policy in policies.items() if policy.enrichable)
    else:
        field_sets = dict(entity_config.get("field_sets", {}))
        if selected_set not in field_sets:
            valid = ", ".join(sorted(set(field_sets) | {"all"}))
            raise ValueError(f"unknown field-set {selected_set!r} for {entity_type}; valid: {valid}")
        fields = tuple(str(field) for field in field_sets[selected_set])

    unknown = [field for field in fields if field not in policies]
    if unknown:
        raise ValueError(f"field-set {selected_set!r} references unknown fields: {', '.join(unknown)}")
    blocked = [field for field in fields if not policies[field].enrichable]
    if blocked:
        raise ValueError(f"field-set {selected_set!r} includes non-enrichable fields: {', '.join(blocked)}")
    return fields


def _entity_config(config: dict[str, object], entity_type: str) -> dict[str, object]:
    entities = dict(config.get("entities", {}))
    raw = entities.get(entity_type)
    if raw is None:
        valid = ", ".join(sorted(entities))
        raise ValueError(f"unknown entity {entity_type!r}; valid: {valid}")
    return dict(raw)
