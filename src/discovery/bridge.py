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
    GHUS_AGENT_CONTACT_EMAIL         contact address the agents give websites;
                                     reading pages refuses without it, so live
                                     runs and checks are stopped here first

Unconfigured, the page says so and nothing is read or written.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import copy
import functools
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any, Callable

ACTIONS = ("pause", "resume", "cancel")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_CHECK_ID = re.compile(r"^[0-9a-f]{32}$")
_KEYS = re.compile(r"^[a-z0-9_]+(,[a-z0-9_]+)*$")
_SECTOR = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
UPDATE_SCOPES = ("topic", "general", "missing", "outdated", "specific")
UPDATE_DEPTHS = ("light", "deep")
CONTACT_ENV = "GHUS_AGENT_CONTACT_EMAIL"


def _require_contact() -> None:
    """The backend refuses to read any page without a contact address, but only
    after the paid search has run. Say so before anything is searched."""
    if not os.environ.get(CONTACT_ENV, "").strip():
        raise DiscoveryBridgeError(
            f"Discovery needs a contact address before it reads websites: add {CONTACT_ENV}="
            "<address> to .env and restart. Nothing was searched or charged.", rejected=True)


def _update_arguments(actor_id: str, options: dict[str, Any]) -> list[str]:
    """Command-line arguments for one actor update, checked before they leave."""
    if not _UUID.match(actor_id or ""):
        raise DiscoveryBridgeError("unknown organization", rejected=True)
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


# How long a started request reads "Running" before its run record appears.
STARTING_FOR_S = 20 * 60


def _epoch(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value).replace(" ", "T")).timestamp()
    except (TypeError, ValueError):
        return 0.0


# agents/collection/subscription_runner._ADVISORY_LOCK: one runner at a time.
RUNNER_LOCK = 550_001
RUNNABLE_STATUSES = ("active", "paused")


def run_refusal(state: dict[str, Any] | None) -> str | None:
    """Why "Run now" cannot start, in words for the page; None when it can.

    Without this the button answered "started" and the runner then refused in
    the background: an ended request, or another run already going.
    """
    if not state:
        return None
    if not state.get("exists"):
        return "That request no longer exists."
    if state.get("status") not in RUNNABLE_STATUSES:
        ended = f" on {state['end_date']}" if state.get("end_date") else ""
        return (f"This request has ended{ended}, so it cannot run again. Create a new "
                "request with the same settings to run it now.")
    if state.get("runner_busy"):
        return ("Another request is running right now. Run this one when it has "
                "finished: a run takes a few minutes.")
    return None


# 5 Nov 2026: listing requests reads three tables per request from the shared
# database (about 25 seconds for 36 requests) and Monitor, the Dashboard and the
# Review hand-off asked for it every 15 seconds, each starting its own read.
# The app keeps the last list: served at once while fresh, served and refreshed
# in the background while recent, read again after any change.
LIST_FRESH_FOR_S = 10
LIST_KEEP_FOR_S = 900


class _ListCache:
    """The last answer of one read-only list command, refreshed in the background."""

    def __init__(self, load, *, fresh_for: float | None = None):
        self._load = load
        self._fresh_for = fresh_for
        self._value = None
        self._at = 0.0
        self._lock = threading.Lock()
        self._refreshing = False
        self._generation = 0

    @property
    def fresh_for(self) -> float:
        return LIST_FRESH_FOR_S if self._fresh_for is None else self._fresh_for

    def get(self):
        age = time.monotonic() - self._at
        if self._value is not None and age < self.fresh_for:
            return copy.deepcopy(self._value)
        if self._value is not None and age < LIST_KEEP_FOR_S:
            self.refresh_in_background()
            return copy.deepcopy(self._value)
        with self._lock:                       # one read at a time; the others wait for it
            if self._value is not None and time.monotonic() - self._at < self.fresh_for:
                return copy.deepcopy(self._value)
            generation = self._generation
            value = self._load()
            if generation == self._generation:
                self._value, self._at = value, time.monotonic()
            return copy.deepcopy(value)

    def invalidate(self):
        """After a change: the next read waits for the database, never shows the old list."""
        self._generation += 1
        self._value, self._at = None, 0.0

    def refresh_in_background(self):
        if self._refreshing:
            return
        self._refreshing = True
        generation = self._generation

        def run():
            try:
                with self._lock:
                    value = self._load()
                    if generation == self._generation:
                        self._value, self._at = value, time.monotonic()
            except Exception:  # noqa: BLE001 - the last list stays; the next read retries
                pass
            finally:
                self._refreshing = False

        threading.Thread(target=run, name="discovery-list", daemon=True).start()


def _invalidates_lists(method):
    """A write: once it is done, the cached lists are read fresh."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        finally:
            self._changed()
    return wrapper


class DiscoveryBridge:
    def __init__(
        self,
        *,
        project_root: str | Path | None = None,
        python_executable: str | Path | None = None,
        database_url: str | None = None,
        run_command: Callable[..., Any] = subprocess.run,
        start_process: Callable[..., Any] = subprocess.Popen,
        run_state: Callable[[str], dict[str, Any] | None] | None = None,
        cache_lists: bool = False,
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
        self._run_state = run_state or self._read_run_state
        # Requests started by Run now, until their run record appears (4 Nov 2026:
        # the page said "Scheduled" for the minute or two the runner takes to start).
        self._started: dict[str, float] = {}
        # The app caches the two lists (cache_lists=True); tests read them fresh.
        self._lists = ({"requests": _ListCache(lambda: self._call(["list"], retries=1)),
                        # Sectors, regions and kinds: they change with a deployment.
                        "options": _ListCache(lambda: self._call(["options"], retries=1),
                                              fresh_for=300),
                        "updates": _ListCache(lambda: self._call(
                            ["requests"], module="agents.collection.actor_updates", retries=1))}
                       if cache_lists else None)

    @property
    def local_database(self) -> bool:
        raw = str(self.database_url or "").replace("postgresql+psycopg://", "postgresql://")
        parts = urlsplit(raw)
        return parts.hostname in ("127.0.0.1", "localhost", "::1") and parts.path.endswith("_test")

    @property
    def configured(self) -> bool:
        return bool(
            self.database_url
            and self.project_root.is_dir()
            and (self.project_root / "agents" / "collection" / "discovery_requests.py").is_file()
        )

    # ---------------------------------------------------------------- reads
    def options(self) -> dict[str, Any]:
        if self._lists is not None:
            return self._lists["options"].get()
        return self._call(["options"], retries=1)

    def list_requests(self) -> dict[str, Any]:
        if self._lists is not None:
            return self.mark_starting(self._lists["requests"].get())
        return self.mark_starting(self._call(["list"], retries=1))

    def warm_lists(self) -> None:
        """Read both lists in the background (the shared server, at start)."""
        for cache in (self._lists or {}).values():
            cache.refresh_in_background()

    def _changed(self) -> None:
        """A request was created, run or changed: the next list is read fresh."""
        for name in ("requests", "updates"):
            if self._lists is not None:
                self._lists[name].invalidate()

    def mark_starting(self, payload: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
        """Mark a request started by Run now as starting until its run record appears."""
        now = time.time() if now is None else now
        for request in (payload or {}).get("requests") or []:
            sid = str(request.get("subscription_id") or "")
            began = self._started.get(sid)
            if began is None:
                continue
            recorded = any(_epoch(run.get("started_at")) >= began - 120
                           for run in request.get("runs") or [])
            if recorded or now - began > STARTING_FOR_S:
                self._started.pop(sid, None)
                continue
            request["starting"] = True
        return payload

    def preview(self, draft: dict[str, Any]) -> dict[str, Any]:
        return self._call(["preview", "--json", json.dumps(draft)])

    # --------------------------------------------------------------- writes
    @_invalidates_lists
    def create(self, draft: dict[str, Any]) -> dict[str, Any]:
        return self._call(["create", "--json", json.dumps(draft), "--live"])

    @_invalidates_lists
    def change(self, subscription_id: str, action: str) -> dict[str, Any]:
        if action not in ACTIONS:
            raise DiscoveryBridgeError(f"unknown action {action!r}", rejected=True)
        return self._call([action, subscription_id, "--live"])

    @_invalidates_lists
    def set_end_date(self, subscription_id: str, end_date: str) -> dict[str, Any]:
        """Extend or shorten a recurring request; the saved schedule stands until this succeeds."""
        if not _UUID.match(subscription_id or ""):
            raise DiscoveryBridgeError("unknown request", rejected=True)
        return self._call(["end-date", subscription_id, "--json",
                           json.dumps({"end_date": end_date}), "--live"])

    @_invalidates_lists
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
        _require_contact()
        refusal = run_refusal(self._run_state(subscription_id))
        if refusal:
            raise DiscoveryBridgeError(refusal, rejected=True)
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
                 "--live", "--request-id", subscription_id, "--light-pull",
                 "--report-out", str(runs / f"{stem}-summary.md"),
                 # The team database is shared (29 Oct 2026); reading kept
                 # organizations' own pages there was authorised on 4 Nov 2026.
                 *([] if self.local_database else ["--allow-shared-database"])],
                cwd=self.project_root, env=env, stdout=log, stderr=log,
                stdin=subprocess.DEVNULL, creationflags=flags,
            )
        except OSError as exc:
            raise DiscoveryBridgeError("The GHUS discovery run could not be started.") from exc
        finally:
            log.close()
        self._started[subscription_id] = time.time()
        return {"started": True, "subscription_id": subscription_id}

    def _read_run_state(self, subscription_id: str) -> dict[str, Any] | None:
        """The request's status and whether a run is already going (read-only).

        None when it cannot be read: the runner then decides, as before.
        """
        try:
            from src.db import connect_resilient, psycopg_database_url

            with connect_resilient(psycopg_database_url(str(self.database_url)),
                                   connect_timeout=10) as conn:
                row = conn.execute(
                    "SELECT status, end_date::text FROM actor_update_subscription "
                    "WHERE actor_update_subscription_id = %s::uuid", (subscription_id,)).fetchone()
                busy = conn.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' "
                    "AND granted AND objid = %s)", (RUNNER_LOCK,)).fetchone()[0]
        except Exception:  # noqa: BLE001 - an unreadable state never blocks a run
            return None
        return {"exists": row is not None, "status": row[0] if row else None,
                "end_date": row[1] if row else None, "runner_busy": bool(busy)}

    # Actor updates: plan (free), check (one capped read, writes nothing),
    # apply (writes what the check found through the backend's fact writer).
    def plan_update(self, actor_id: str, options: dict[str, Any]) -> dict[str, Any]:
        return self._call(["plan", *_update_arguments(actor_id, options)],
                          module="agents.collection.actor_updates", timeout=120)

    def check_update(self, actor_id: str, options: dict[str, Any]) -> dict[str, Any]:
        """Read the actor's own pages once and compare every box. Nothing is written."""
        arguments = _update_arguments(actor_id, options)   # a bad value is refused first
        _require_contact()
        return self._call(["check", *arguments],
                          module="agents.collection.actor_updates", timeout=600)

    # Update requests: one actor or a bounded group, once or on a frequency.
    # They are saved as requests and run by the backend's request runner -
    # the same one as Discovery requests ("Run now" starts it for one request).
    def list_update_requests(self) -> dict[str, Any]:
        if self._lists is not None:
            return self._lists["updates"].get()
        return self._call(["requests"], module="agents.collection.actor_updates", retries=1)

    def plan_update_request(self, draft: dict[str, Any]) -> dict[str, Any]:
        """What a request would do on its first run. Free: nothing read or written."""
        return self._call(["request-plan", "--json", json.dumps(draft)],
                          module="agents.collection.actor_updates")

    @_invalidates_lists
    def create_update_request(self, draft: dict[str, Any]) -> dict[str, Any]:
        return self._call(["request-create", "--json", json.dumps(draft), "--live"],
                          module="agents.collection.actor_updates",
                          extra_env={"ACTOR_UPDATE_WRITES_ENABLED": "true"})

    @_invalidates_lists
    def change_update_request(self, subscription_id: str, action: str) -> dict[str, Any]:
        if action not in ACTIONS:
            raise DiscoveryBridgeError(f"unknown action {action!r}", rejected=True)
        if not _UUID.match(subscription_id or ""):
            raise DiscoveryBridgeError("unknown request", rejected=True)
        return self._call(["request-status", "--id", subscription_id, "--action", action,
                           "--live"], module="agents.collection.actor_updates",
                          extra_env={"ACTOR_UPDATE_WRITES_ENABLED": "true"})

    @_invalidates_lists
    def apply_update(self, check_id: str) -> dict[str, Any]:
        """A person pressing "Write to the map": the explicit dispatch a write needs."""
        if not _CHECK_ID.match(check_id or ""):
            raise DiscoveryBridgeError("unknown check", rejected=True)
        return self._call(["apply", "--check-id", check_id],
                          module="agents.collection.actor_updates", timeout=600,
                          extra_env={"ACTOR_UPDATE_WRITES_ENABLED": "true"})

    # ------------------------------------------------------------- plumbing
    def _call(self, arguments: list[str], *, module: str = "agents.collection.discovery_requests",
              timeout: float = 120, extra_env: dict[str, str] | None = None,
              retries: int = 0) -> dict[str, Any]:
        """Run one backend command. ``retries`` is for read-only commands only (options,
        the request lists): on 2026-11-03 one crashed mid-start under load ("no readable
        answer") and the whole Monitor page switched itself off; a second try answered."""
        for attempt in range(retries + 1):
            try:
                return self._call_once(arguments, module=module, timeout=timeout, extra_env=extra_env)
            except DiscoveryBridgeError as exc:
                if exc.rejected or attempt == retries:
                    raise
        raise DiscoveryBridgeError("GHUS refused the request.")  # pragma: no cover

    def _call_once(self, arguments: list[str], *, module: str, timeout: float,
                   extra_env: dict[str, str] | None) -> dict[str, Any]:
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
