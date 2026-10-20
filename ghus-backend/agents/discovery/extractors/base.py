"""Extractor contracts."""

from __future__ import annotations

from typing import Protocol

from agents.discovery.sources.base import FetchedDoc


class Extractor(Protocol):
    entity_type: str
    prompt_version: str
    json_schema: dict[str, object]

    def extract(self, doc: FetchedDoc) -> list[dict]:
        ...
