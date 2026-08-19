"""Delegation adapter for the sibling um6p-rag retriever."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


class RagSearchUnavailable(RuntimeError):
    """Raised when the sibling RAG retriever cannot be called."""


class RagSearchAdapter:
    def __init__(self, *, repo_path: Optional[Path] = None, python_executable: Optional[str] = None):
        self.repo_path = repo_path or _default_rag_repo_path()
        self.python_executable = python_executable or sys.executable

    def search(self, question: str, *, top_k: int = 10) -> list[dict]:
        if not self.repo_path.exists():
            raise RagSearchUnavailable(
                "um6p-rag repo was not found; set UM6P_RAG_REPO_PATH to delegate rag_search"
            )
        script = (
            "import json, sys; "
            "from src.retrieve import retrieve; "
            "print(json.dumps(retrieve(sys.argv[1], top_k=int(sys.argv[2])), default=str))"
        )
        completed = subprocess.run(
            [self.python_executable, "-c", script, question, str(top_k)],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            raise RagSearchUnavailable(_sanitize_error(completed.stderr or completed.stdout))
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RagSearchUnavailable("um6p-rag returned non-JSON output") from exc
        if not isinstance(payload, list):
            raise RagSearchUnavailable("um6p-rag returned an unexpected payload")
        return payload


def _default_rag_repo_path() -> Path:
    env_path = os.environ.get("UM6P_RAG_REPO_PATH")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parents[3] / "Institutional-knowledge-Platform-with-AI-agents"


def _sanitize_error(value: str) -> str:
    text = value.strip()
    for key in ("DATABASE_URL", "ANTHROPIC_API_KEY", "VOYAGE_API_KEY"):
        secret = os.environ.get(key)
        if secret:
            text = text.replace(secret, "<redacted>")
    return text[:2000] or "um6p-rag retrieval failed"
