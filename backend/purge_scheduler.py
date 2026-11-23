"""The scheduled cleanup, run by the server itself (GHUS policy, 17 Nov 2026).

Records deleted more than 30 days ago are removed permanently by the backend's
cleanup job (``python -m agents.review.purge``), never by a page in someone's
browser. This module runs that job on a timer inside the platform's server:

    GHUS_PURGE_MODE=off       (default) never runs
    GHUS_PURGE_MODE=dry-run   runs daily, reports what would be removed, changes nothing
    GHUS_PURGE_MODE=live      runs daily and removes what is due

Every run, dry or live, writes one entry ("cleanup.purge") to the audit history.
The job is safe to run again at any time: it skips what is already purged,
restored or not yet due, takes one deletion per transaction, and holds a
database lock so two servers never purge at once. A missed day is caught up on
the next run, because each run takes everything that is due.

The same job can instead run as an external cron (Render Cron Job) with
``python -m agents.review.purge --live``; see docs/ACCOUNTS_ACTIVATION.md.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

MODES = ("off", "dry-run", "live")
LABEL = "Scheduled cleanup"


def purge_mode() -> str:
    mode = os.environ.get("GHUS_PURGE_MODE", "off").strip().lower() or "off"
    if mode not in MODES:
        logger.warning("GHUS_PURGE_MODE=%r is not one of %s; the cleanup stays off.", mode, MODES)
        return "off"
    return mode


def _hours(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(name, default)))
    except ValueError:
        return default


class PurgeScheduler:
    """Runs the backend cleanup once a day in a background thread."""

    def __init__(self, *, bridge, store=None, mode: str | None = None,
                 run_command: Callable[..., Any] = subprocess.run,
                 interval_hours: float | None = None, first_delay_minutes: float | None = None):
        self.bridge = bridge                  # AdmissionBridge: backend folder, interpreter, database
        self.store = store                    # AccountStore, for the audit entry and the hidden cache
        self.mode = mode or purge_mode()
        self._run = run_command
        self.interval_s = 3600 * (interval_hours if interval_hours is not None
                                  else _hours("GHUS_PURGE_INTERVAL_HOURS", 24))
        self.first_delay_s = 60 * (first_delay_minutes if first_delay_minutes is not None
                                   else _hours("GHUS_PURGE_FIRST_DELAY_MINUTES", 10))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_report: dict | None = None

    # ------------------------------------------------------------------ one run
    def run_once(self) -> dict:
        """Run the cleanup once in the configured mode and audit it. Never raises."""
        live = self.mode == "live"
        if self.mode == "off":
            return {"skipped": "GHUS_PURGE_MODE is off"}
        if not self.bridge.configured:
            report = {"live": live, "error": "Review's decision writer is not configured on this server."}
            self._audit(report)
            return report
        env = os.environ.copy()
        env["DATABASE_URL"] = str(self.bridge.database_url)
        env["NO_COLOR"] = "1"
        command = [self.bridge.python_executable, "-m", "agents.review.purge"]
        if live:
            env["REVIEW_ADMISSION_WRITES_ENABLED"] = "true"
            command.append("--live")
        else:
            env.pop("REVIEW_ADMISSION_WRITES_ENABLED", None)
        try:
            completed = self._run(command, cwd=self.bridge.project_root, env=env, text=True,
                                  capture_output=True, check=False,
                                  timeout=float(os.environ.get("GHUS_PURGE_TIMEOUT_S") or 1800))
            try:
                report = json.loads(completed.stdout or "")
            except json.JSONDecodeError:
                tail = [line for line in str(completed.stderr or "").splitlines() if line.strip()]
                report = {"live": live, "error": (tail[-1] if tail else f"exit code {completed.returncode}")[:400]}
        except (OSError, subprocess.TimeoutExpired) as exc:
            report = {"live": live, "error": f"{type(exc).__name__}: {exc}"[:400]}
        self.last_report = report
        self._audit(report)
        if live and (report.get("outcomes") or {}).get("purged") and self.store is not None:
            self.store.forget_hidden()
        return report

    def _audit(self, report: dict) -> None:
        results = report.get("results") or []
        detail = {
            "mode": self.mode, "due": report.get("due", 0), "outcomes": report.get("outcomes", {}),
            "error": report.get("error"), "skipped": report.get("skipped"),
            # who was removed (or would be), never personal details: people are "Deleted person"
            "records": [{k: r.get(k) for k in ("deletion_id", "entity_type", "entity_id", "name", "outcome",
                                               "reason") if r.get(k) is not None} for r in results][:200],
        }
        level = logging.WARNING if report.get("error") or detail["outcomes"].get("error") \
            or detail["outcomes"].get("blocked") else logging.INFO
        logger.log(level, "Cleanup (%s): %s", self.mode, json.dumps(detail["outcomes"] or detail, default=str))
        if self.store is None:
            return
        try:
            self.store.audit(action="cleanup.purge", account=None, label=LABEL, entity_type="deletion",
                             detail=detail)
        except Exception:  # noqa: BLE001 - the log line above still records the run
            logger.exception("Could not write the cleanup's audit entry")

    # ------------------------------------------------------------------ timer
    def start(self) -> bool:
        if self.mode == "off" or self._thread is not None:
            return False
        self._thread = threading.Thread(target=self._loop, name="ghus-purge", daemon=True)
        self._thread.start()
        logger.info("Cleanup scheduled (%s): first run in %.0f min, then every %.0f h.",
                    self.mode, self.first_delay_s / 60, self.interval_s / 3600)
        return True

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        wait = self.first_delay_s
        while not self._stop.wait(wait):
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - keep the timer alive
                logger.exception("Cleanup run failed")
            wait = max(self.interval_s, 60)
