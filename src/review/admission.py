"""Fail-closed bridge from the review app to GHUS review admission."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable


class AdmissionBridgeError(RuntimeError):
    pass


class AdmissionBridge:
    def __init__(
        self,
        *,
        project_root: str | Path | None = None,
        python_executable: str | Path | None = None,
        database_url: str | None = None,
        run_command: Callable[..., Any] = subprocess.run,
    ):
        self.project_root = Path(
            project_root or os.environ.get("GHUS_ADMISSION_PROJECT_ROOT") or ""
        )
        self.python_executable = str(
            python_executable or os.environ.get("GHUS_ADMISSION_PYTHON") or "python"
        )
        self.database_url = database_url or os.environ.get("REVIEW_ADMISSION_DATABASE_URL")
        self._run_command = run_command

    @property
    def configured(self) -> bool:
        return bool(
            self.database_url
            and self.project_root.is_dir()
            and (self.project_root / "agents" / "review" / "admission.py").is_file()
        )

    def apply(self, decision: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise AdmissionBridgeError(
                "Canonical admission is not configured. Apply the emitted GHUS migration and "
                "set GHUS_ADMISSION_PROJECT_ROOT plus REVIEW_ADMISSION_DATABASE_URL for the "
                "dedicated review writer."
            )
        request_dir = self.project_root / ".review-requests"
        request_dir.mkdir(exist_ok=True)
        path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", prefix="decision-", dir=request_dir,
                encoding="utf-8", delete=False,
            ) as handle:
                json.dump(decision, handle, ensure_ascii=False, sort_keys=True)
                path = Path(handle.name)
            env = os.environ.copy()
            env["DATABASE_URL"] = str(self.database_url)
            env["REVIEW_ADMISSION_WRITES_ENABLED"] = "true"
            completed = self._run_command(
                [
                    self.python_executable, "-m", "agents.review.admission",
                    "--decision", str(path),
                ],
                cwd=self.project_root,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
            if completed.returncode != 0:
                raise AdmissionBridgeError(
                    "GHUS rejected the decision; no local final decision was recorded. "
                    f"Admission process exited with code {completed.returncode}."
                )
            try:
                outcome = json.loads(completed.stdout)
            except (TypeError, json.JSONDecodeError) as exc:
                raise AdmissionBridgeError(
                    "GHUS returned an invalid admission response; the candidate remains pending."
                ) from exc
            if not isinstance(outcome, dict):
                raise AdmissionBridgeError("GHUS admission response must be an object.")
            return outcome
        except subprocess.TimeoutExpired as exc:
            raise AdmissionBridgeError(
                "GHUS admission timed out; the candidate remains pending for a safe retry."
            ) from exc
        except OSError as exc:
            raise AdmissionBridgeError(
                "GHUS admission could not be started; the candidate remains pending."
            ) from exc
        finally:
            if path is not None:
                path.unlink(missing_ok=True)
