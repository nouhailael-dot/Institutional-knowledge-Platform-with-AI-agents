"""Fail-closed bridge from the Data Feed page to the GHUS backend.

The platform never writes a staging or canonical row itself. Checking and
staging a batch go through ``python -m agents.datafeed.stage_import``; the
optional Light Pull completion goes through the existing
``python -m agents.collection.light_pull_candidates``. Same pattern as
Discovery (``src/discovery/bridge.py``) and Review admission.

Configuration:
    GHUS_DATAFEED_PROJECT_ROOT   backend checkout (falls back to Discovery's,
                                 then admission's)
    GHUS_DATAFEED_PYTHON         its Python (falls back likewise)
    DATAFEED_DATABASE_URL        the database records are staged in

Unconfigured, the page says so; files can still be checked, nothing is staged.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class DataFeedBridgeError(RuntimeError):
    def __init__(self, message: str, *, rejected: bool = False):
        super().__init__(message)
        self.rejected = rejected


def _env_first(*names: str) -> str:
    return next((os.environ[n] for n in names if os.environ.get(n)), "")


class DataFeedBridge:
    def __init__(self, *, project_root: str | Path | None = None,
                 python_executable: str | Path | None = None,
                 database_url: str | None = None,
                 run_command: Callable[..., Any] = subprocess.run,
                 start_process: Callable[..., Any] = subprocess.Popen):
        self.project_root = Path(project_root or _env_first(
            "GHUS_DATAFEED_PROJECT_ROOT", "GHUS_DISCOVERY_PROJECT_ROOT",
            "GHUS_ADMISSION_PROJECT_ROOT") or "")
        self.python_executable = str(python_executable or _env_first(
            "GHUS_DATAFEED_PYTHON", "GHUS_DISCOVERY_PYTHON", "GHUS_ADMISSION_PYTHON")
            or sys.executable or "python")
        self.database_url = database_url or os.environ.get("DATAFEED_DATABASE_URL") or ""
        self._run = run_command
        self._start = start_process

    @property
    def configured(self) -> bool:
        return bool(self.database_url and self.project_root.is_dir()
                    and (self.project_root / "agents" / "datafeed" / "stage_import.py").is_file())

    @property
    def local_database(self) -> bool:
        raw = self.database_url.replace("postgresql+psycopg://", "postgresql://")
        parts = urlsplit(raw)
        return parts.hostname in ("127.0.0.1", "localhost", "::1") and parts.path.endswith("_test")

    def _env(self, *, writes: bool = False) -> dict[str, str]:
        env = os.environ.copy()
        env["DATABASE_URL"] = self.database_url
        env["NO_COLOR"], env["PYTHON_COLORS"] = "1", "0"
        env.pop("FORCE_COLOR", None)
        if writes:
            env["DATAFEED_WRITES_ENABLED"] = "true"
        else:
            env.pop("DATAFEED_WRITES_ENABLED", None)
        return env

    def _require(self) -> None:
        if not self.configured:
            raise DataFeedBridgeError(
                "Data Feed staging is not configured: set GHUS_DATAFEED_PROJECT_ROOT and "
                "DATAFEED_DATABASE_URL for the backend that stages records for Review.")

    def _stage_command(self, batch: dict[str, Any], *, live: bool) -> dict[str, Any]:
        self._require()
        request_dir = self.project_root / ".review-requests"
        request_dir.mkdir(exist_ok=True)
        path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".json", prefix="datafeed-",
                                             dir=request_dir, encoding="utf-8",
                                             delete=False) as handle:
                json.dump(batch, handle, ensure_ascii=False)
                path = Path(handle.name)
            command = [self.python_executable, "-m", "agents.datafeed.stage_import",
                       "--batch", str(path)] + (["--live"] if live else [])
            done = self._run(command, cwd=self.project_root, env=self._env(writes=live),
                             text=True, capture_output=True, check=False,
                             # An import admitted as Verified loads entity resolution
                             # and admits each record: minutes, not seconds.
                             timeout=float(os.environ.get("GHUS_DATAFEED_TIMEOUT_S") or 1200))
        except subprocess.TimeoutExpired as exc:
            raise DataFeedBridgeError("The backend did not answer in time; nothing was "
                                      "staged. Try again.") from exc
        except OSError as exc:
            raise DataFeedBridgeError("The backend command could not be started.") from exc
        finally:
            if path is not None:
                path.unlink(missing_ok=True)
        try:
            result = json.loads((done.stdout or "").strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise DataFeedBridgeError("The backend returned no readable answer; nothing was "
                                      "staged.") from exc
        if result.get("status") == "refused":
            raise DataFeedBridgeError(str(result.get("error") or "Refused."), rejected=True)
        if done.returncode != 0:
            raise DataFeedBridgeError("The backend could not check the records.")
        return result

    def check(self, batch: dict[str, Any]) -> dict[str, Any]:
        """The backend's own checks on every row. Writes nothing."""
        return self._stage_command(batch, live=False)

    def stage(self, batch: dict[str, Any]) -> dict[str, Any]:
        """Stage the batch for Review, in one transaction."""
        return self._stage_command(batch, live=True)

    # ---------------------------------------------------------- Light Pull completion
    def _light_pull_command(self, run_id: str, extra: list[str]) -> list[str]:
        command = [self.python_executable, "-m", "agents.collection.light_pull_candidates",
                   "--search-run", run_id, "--missing-only", *extra]
        if not self.local_database:
            # The command refuses a shared database unless its operator says so;
            # configuring DATAFEED_DATABASE_URL is that decision.
            command.append("--allow-shared-database")
        return command

    def completion_estimate(self, run_id: str) -> dict[str, Any]:
        self._require()
        done = self._run(self._light_pull_command(run_id, ["--estimate"]), cwd=self.project_root,
                         env=self._env(), text=True, capture_output=True, check=False,
                         timeout=120)
        if done.returncode != 0:
            raise DataFeedBridgeError("The cost could not be estimated.")
        try:
            return json.loads(done.stdout)
        except json.JSONDecodeError as exc:
            raise DataFeedBridgeError("The estimate could not be read.") from exc

    def start_completion(self, run_id: str, max_usd: float, log_path: Path) -> int:
        """Start the paid read in the background; returns its process id."""
        self._require()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as log:
            process = self._start(
                self._light_pull_command(run_id, ["--live", "--max-usd", f"{max_usd:.2f}"]),
                cwd=self.project_root, env=self._env(), stdout=log, stderr=subprocess.STDOUT)
        return int(getattr(process, "pid", 0) or 0)
