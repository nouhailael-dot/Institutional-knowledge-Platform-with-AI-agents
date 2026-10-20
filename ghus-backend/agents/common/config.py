"""Shared agent configuration loading."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml


def project_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def load_sources_config(root: Optional[Path] = None) -> dict[str, object]:
    """Load the shipped YAML source configuration.

    The file intentionally keeps its existing ``sources.yaml`` name. It used to
    contain JSON parsed by ``json.loads``; parsing as YAML matches the filename
    and allows CI to catch syntax errors in the shipped file directly.
    """
    root = root or project_root_from_here()
    path = root / "agents" / "config" / "sources.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError("agents/config/sources.yaml must contain a mapping")
    return loaded
