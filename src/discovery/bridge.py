"""Fail-closed bridge from the Discovery page to GHUS discovery requests.

The platform never writes discovery requests itself. Every read and write goes
through the backend's own command, ``python -m agents.collection.discovery_requests``,
which validates with the same rules the scheduler and the database use. This is
the pattern Review uses for admission (``src/review/admission.py``).

Configuration:
    GHUS_DISCOVERY_PROJECT_ROOT      backend checkout (falls back to
                                     GHUS_ADMISSION_PROJECT_ROOT)
    GHUS_DISCOVERY_PYTHON            its Python (falls back to GHUS_ADMISSION_PYTHON)
    DISCOVERY_REQUESTS_DATABASE_URL  where requests are kept

Unconfigured, the page says so and nothing is read or written.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

ACTIONS = ("pause", "resume", "cancel")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_CHECK_ID = re.compile(r"^[0-9a-f]{32}$")
_KEYS = re.compile(r"^[a-z0-9_]+(,[a-z0-9_]+)*$")
_SECTOR = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
UPDATE_SCOPES = ("topic", "general", "missing", "outdated", "specific")
UPDATE_DEPTHS = ("light", "deep")


def _update_arguments(actor_id: str, options: dict[str, Any]) -> list[str]:
    """Command-line arguments for one actor update, checked before they leave."""
    if not _UUID.match(actor_id or ""):
        raise DiscoveryBridgeError("unknown actor", rejected=True)
    scope = str(options.get("scope") or "general")
    depth = str(options.get("depth") or "light")
    if scope not in UPDATE_SCOPES or depth not in UPDATE_DEPTHS:
        raise DiscoveryBridgeError("unknown update scope or depth", rejected=True)
    arguments = ["--actor-id", actor_id, "--scope", scope, "--depth", depth]
    topic = str(options.get("topic") or "")
    if topic:
        if not _SECTOR.match(topic):
            raise DiscoveryBridgeError("unknown sector", rejected=True)
        arguments += ["--topic", topic]
    for name in ("fields", "categories"):
        value = ",".join(str(v).strip() for v in options.get(name) or () if str(v).strip())
        if value:
            if not _KEYS.match(value):
                raise DiscoveryBridgeError(f"unknown {name}", rejected=True)
            arguments += [f"--{name}", value]
    focus = " ".join(str(options.get("focus") or "").split())[:200]
    if focus:
        arguments += ["--focus", focus]
    return arguments


class DiscoveryBridgeError(RuntimeError):
    """The request could not be carried out. ``rejected`` means GHUS refused it."""

    def __init__(self, message: str, *, rejected: bool = False):
        super().__init__(message)
        self.rejected = rejected


class DiscoveryBridge:
    def __init__(
        self,
        *,
        project_root: str | Path | None = None,
        python_executable: str | Path | None = None,
        database_url: str | None = None,
        run_command: Callable[..., Any] = subprocess.run,
        start_process: Callable[..., Any] = subprocess.Popen,
    ):
        self.project_root = Path(
            project_root
            or os.environ.get("GHUS_DISCOVERY_PROJECT_ROOT")
            or os.environ.get("GHUS_ADMISSION_PROJECT_ROOT")
            or ""
        )
        self.python_executable = str(
            python_executable
            or os.environ.get("GHUS_DISCOVERY_PYTHON")
            or os.environ.get("GHUS_ADMISSION_PYTHON")
            # This app's interpreter: a bare "python" from PATH may lack the
            # backend's dependencies (the admission bridge failed that way).
            or sys.executable
            or "python"
        )
        self.database_url = database_url or os.environ.get("DISCOVERY_REQUESTS_DATABASE_URL")
        self._run_command = run_command
        self._start_process = start_process

    @property
    def configured(self) -> bool:
        return bool(
            self.database_url
            and self.project_root.is_dir()
            and (self.project_root / "agents" / "collection" / "discovery_requests.py").is_file()
        )

    # ---------------------------------------------------------------- reads
    def options(self) -> dict[str, Any]:
        return self._call(["options"])

    def list_requests(self) -> dict[str, Any]:
        return self._call(["list"])

    def preview(self, draft: dict[str, Any]) -> dict[str, Any]:
        return self._call(["preview", "--json", json.dumps(draft)])

    # --------------------------------------------------------------- writes
    def create(self, draft: dict[str, Any]) -> dict[str, Any]:
        return self._call(["create", "--json", json.dumps(draft), "--live"])

    def change(self, subscription_id: str, action: str) -> dict[str, Any]:
        if action not in ACTIONS:
            raise DiscoveryBridgeError(f"unknown action {action!r}", rejected=True)
        return self._call([action, subscription_id, "--live"])

    def run_now(self, subscription_id: str) -> dict[str, Any]:
        """Start a live run of one request, in the background.

        A person pressing "Run now" is the explicit dispatch a live run needs.
        The run takes minutes (search, read pages, score), so it is started and
        left to finish; the page follows it through the request's run history.
        """
        if not self.configured:
            raise DiscoveryBridgeError("Discovery requests are not configured.")
        if not _UUID.match(subscription_id or ""):
            raise DiscoveryBridgeError("unknown request", rejected=True)
        env = os.environ.copy()
        env["DATABASE_URL"] = str(self.database_url)
        runs = self.project_root / "agents" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        stem = f"discovery-request-{subscription_id[:8]}"
        log = open(runs / f"{stem}-run.log", "a", encoding="utf-8")  # noqa: SIM115
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        try:
            self._start_process(
                [self.python_executable, "-m", "agents.collection.subscription_runner",
                 "--live", "--request-id", subscription_id,
                 "--report-out", str(runs / f"{stem}-summary.md")],
                cwd=self.project_root, env=env, stdout=log, stderr=log,
                stdin=subprocess.DEVNULL, creationflags=flags,
            )
        except OSError as exc:
            raise DiscoveryBridgeError("The GHUS discovery run could not be started.") from exc
        finally:
            log.close()
        return {"started": True, "subscription_id": subscription_id}

    # Actor updates: plan (free), check (one capped read, writes nothing),
    # apply (writes what the check found through the backend's fact writer).
    def plan_update(self, actor_id: str, options: dict[str, Any]) -> dict[str, Any]:
        return self._call(["plan", *_update_arguments(actor_id, options)],
                          module="agents.collection.actor_updates", timeout=120)

    def check_update(self, actor_id: str, options: dict[str, Any]) -> dict[str, Any]:
        """Read the actor's own pages once and compare every box. Nothing is written."""
        return self._call(["check", *_update_arguments(actor_id, options)],
                          module="agents.collection.actor_updates", timeout=300)

    def apply_update(self, check_id: str) -> dict[str, Any]:
        """A person pressing "Write to the map": the explicit dispatch a write needs."""
        if not _CHECK_ID.match(check_id or ""):
            raise DiscoveryBridgeError("unknown check", rejected=True)
        return self._call(["apply", "--check-id", check_id],
                          module="agents.collection.actor_updates", timeout=300,
                          extra_env={"ACTOR_UPDATE_WRITES_ENABLED": "true"})

    # ------------------------------------------------------------- plumbing
    def _call(self, arguments: list[str], *, module: str = "agents.collection.discovery_requests",
              timeout: float = 120, extra_env: dict[str, str] | None = None) -> dict[str, Any]:
        if not self.configured:
            raise DiscoveryBridgeError(
                "Discovery requests are not configured. Set GHUS_DISCOVERY_PROJECT_ROOT and "
                "DISCOVERY_REQUESTS_DATABASE_URL."
            )
        env = os.environ.copy()
        env["DATABASE_URL"] = str(self.database_url)
        env.update(extra_env or {})
        try:
            completed = self._run_command(
                [self.python_executable, "-m", module, *arguments],
                cwd=self.project_root,
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DiscoveryBridgeError("GHUS did not answer in time; nothing was changed.") from exc
        except OSError as exc:
            raise DiscoveryBridgeError("The GHUS discovery command could not be started.") from exc
        try:
            payload = json.loads((completed.stdout or "").strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise DiscoveryBridgeError(
                f"GHUS returned no readable answer (exit code {completed.returncode})."
            ) from exc
        if not isinstance(payload, dict):
            raise DiscoveryBridgeError("GHUS returned an unexpected answer.")
        if payload.get("ok") is not True:
            raise DiscoveryBridgeError(str(payload.get("error") or "GHUS refused the request."),
                                       rejected=completed.returncode == 2)
        payload.pop("ok", None)
        return payload
