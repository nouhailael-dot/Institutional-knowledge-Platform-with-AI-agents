"""Local raw-content storage for replayable discovery runs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from agents.discovery.sources.base import FetchedDoc


class RawContentStore:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    @classmethod
    def from_config(cls, project_root: Path, config: dict[str, object]) -> "RawContentStore":
        raw_dir = str(config.get("raw_storage_dir", "agents/raw_documents"))
        path = Path(raw_dir)
        if not path.is_absolute():
            path = project_root / path
        return cls(path)

    def write(self, *, run_id: str, doc: FetchedDoc) -> str:
        target_dir = self.base_dir / _safe_part(run_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{doc.content_hash}.{_extension(doc.content_type)}"
        path.write_text(doc.content, encoding="utf-8", newline="\n")
        return str(path)

    def read(self, storage_path: str) -> str:
        return Path(storage_path).read_text(encoding="utf-8")

    def exists(self, storage_path: Optional[str]) -> bool:
        return bool(storage_path) and Path(str(storage_path)).exists()


def _extension(content_type: str) -> str:
    lowered = (content_type or "").lower()
    if "html" in lowered:
        return "html"
    if "json" in lowered:
        return "json"
    return "txt"


def _safe_part(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value)).strip("-") or "run"
