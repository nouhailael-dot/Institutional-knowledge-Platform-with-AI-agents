"""Fail-closed bridge from the review app to GHUS review admission."""

from __future__ import annotations

import json
import logging
import re
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


# The backend's own refusals, in words a reviewer can act on. Only these named
# exceptions are passed through; anything else (a traceback, a driver error)
# stays a generic message, so no internal detail reaches the page.
_REFUSAL = re.compile(r"^(?:\w+\.)*(AdmissionConflict|AdmissionValidationError): (.+)$")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_EXACT_MATCH = re.compile(r"\((website_domain|name_or_alternate_name): (.+?) [0-9a-f-]{36}\)")


def refusal_reason(stderr: str | None, returncode: int) -> str:
    """Why GHUS refused, from the backend's last named refusal, else the exit code.

    "Admission process exited with code 1" told a reviewer nothing; the backend
    had already said the organisation was on the map under the same website.
    """
    # Python 3.13 colours tracebacks when the environment asks for colour
    # ("\x1b[1;35mAdmissionConflict\x1b[0m: ..."), which hid every refusal.
    plain = _ANSI.sub("", str(stderr or ""))
    for line in reversed(plain.strip().splitlines()):
        found = _REFUSAL.match(line.strip())
        if not found:
            continue
        kind, message = found.groups()
        match = _EXACT_MATCH.search(message)
        if kind == "AdmissionConflict" and match:
            rule, name = match.groups()
            how = "the same website" if rule == "website_domain" else "the same name"
            return (f"It is already on the map as “{name}” ({how}). "
                    "Choose “Same as existing” to add this evidence to it, or Defer.")
        if kind == "AdmissionConflict":
            return ("It may already be on the map: a close match was found. "
                    "Choose “Same as existing” with the right record, or Defer.")
        return message[:300]
    return f"Admission process exited with code {returncode}."


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
        # The interpreter running this app, unless one is named. A bare
        # "python" picked up whatever was first on PATH, which on this machine
        # had none of the backend's dependencies: every decision came back
        # "admission process exited with code 1".
        self.python_executable = str(
            python_executable or os.environ.get("GHUS_ADMISSION_PYTHON") or sys.executable
            or "python"
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
            # Plain error output, so the refusal can be read and shown.
            env["NO_COLOR"] = "1"
            env["PYTHON_COLORS"] = "0"
            env.pop("FORCE_COLOR", None)
            completed = self._run_command(
                [
                    self.python_executable, "-m", "agents.review.admission",
                    "--decision", str(path),
                ],
                cwd=self.project_root,
                env=env,
                text=True,
                capture_output=True,
                # The backend loads its entity-resolution model before it can
                # route a decision; a cold process needs minutes, not 120 s.
                timeout=float(os.environ.get("GHUS_ADMISSION_TIMEOUT_S") or 600),
                check=False,
            )
            if completed.returncode != 0:
                # The backend's last error line, for whoever runs the server: a
                # refusal (duplicate, invalid field) or an environment failure.
                tail = [line for line in str(getattr(completed, "stderr", "") or "").splitlines()
                        if line.strip()]
                logging.getLogger(__name__).warning(
                    "GHUS admission exited %s: %s", completed.returncode,
                    _ANSI.sub("", tail[-1] if tail else "(no error output)")[:400])
                raise AdmissionBridgeError(
                    "GHUS rejected the decision; no local final decision was recorded. "
                    + refusal_reason(getattr(completed, "stderr", ""), completed.returncode)
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
