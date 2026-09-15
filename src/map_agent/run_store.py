"""Local, durable map jobs and atomic budget reservations (integer micro-USD).

Separate from the production actor database. Run one API worker per store:
startup recovery marks unfinished work interrupted and never retries paid calls.
"""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

MICRO = 1_000_000
DEFAULT_BUDGET = 2 * MICRO
MAX_BUDGET = 3 * MICRO
ACTIVE = ("planning", "running", "verifying")


class MapStopped(RuntimeError):
    pass


class BudgetStopped(MapStopped):
    pass


class RunStore:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("MAP_RUN_DB") or
                         Path(__file__).resolve().parents[2] / ".map_runs" / "runs.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, description TEXT NOT NULL,
                    status TEXT NOT NULL, stage TEXT NOT NULL, error TEXT,
                    budget INTEGER NOT NULL, cancelled INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL, updated REAL NOT NULL,
                    result TEXT, messages TEXT NOT NULL DEFAULT '[]',
                    plan TEXT, doc_text TEXT
                );
                CREATE TABLE IF NOT EXISTS calls (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    stage TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL,
                    reserved INTEGER NOT NULL, cost INTEGER, usage TEXT,
                    pricing TEXT NOT NULL, response TEXT, error TEXT,
                    started REAL NOT NULL, finished REAL
                );
                CREATE INDEX IF NOT EXISTS calls_run ON calls(run_id);
                CREATE TABLE IF NOT EXISTS budget_approvals (
                    run_id TEXT PRIMARY KEY REFERENCES runs(id),
                    previous_budget INTEGER NOT NULL, approved_budget INTEGER NOT NULL,
                    approved_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS work_cache (
                    run_id TEXT NOT NULL REFERENCES runs(id), key TEXT NOT NULL,
                    value TEXT NOT NULL, PRIMARY KEY(run_id,key)
                );
            """)
            columns = {r[1] for r in db.execute("PRAGMA table_info(calls)")}
            if "operation_key" not in columns:
                db.execute("ALTER TABLE calls ADD COLUMN operation_key TEXT")
            if "attempt" not in {r[1] for r in db.execute("PRAGMA table_info(runs)")}:
                db.execute("ALTER TABLE runs ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS calls_operation "
                       "ON calls(run_id,operation_key) WHERE operation_key IS NOT NULL")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, description="", budget=DEFAULT_BUDGET):
        if type(budget) is not int or not 0 < budget <= DEFAULT_BUDGET:
            raise ValueError("Initial map budget must be positive integer micro-dollars and at most $2.")
        run_id, now = uuid4().hex, time.time()
        with self.connect() as db:
            db.execute("INSERT INTO runs(id,description,status,stage,budget,created,updated) "
                       "VALUES(?,?,'draft','Ready',?,?,?)",
                       (run_id, description, budget, now, now))
        return run_id

    @staticmethod
    def _can_extend(row, calls):
        return (row["budget"] == DEFAULT_BUDGET
                and row["status"] in ("draft", "awaiting_reply", "ready", "done", "budget_stopped")
                and (not row["cancelled"] or row["status"] == "budget_stopped")
                and all(c["status"] == "complete" and c["cost"] is not None
                        and c["cost"] <= c["reserved"] for c in calls))

    def approve_extension(self, run_id):
        """Record explicit approval of $3 total. Never restart work or clear a stop."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            # Repeated clicks/retries cannot add another dollar.
            if row["budget"] == MAX_BUDGET:
                return
            calls = db.execute("SELECT status,cost,reserved FROM calls WHERE run_id=?",
                               (run_id,)).fetchall()
            if not self._can_extend(row, calls):
                raise MapStopped("Budget cannot be extended while work or charges are unresolved, "
                                 "after a manual stop, or for a legacy budget.")
            now = time.time()
            db.execute("INSERT INTO budget_approvals VALUES(?,?,?,?)",
                       (run_id, row["budget"], MAX_BUDGET, now))
            db.execute("UPDATE runs SET budget=?,updated=? WHERE id=?", (MAX_BUDGET, now, run_id))

    def update(self, run_id, **fields):
        allowed = {"description", "status", "stage", "error", "result", "messages", "plan", "doc_text"}
        if not fields.keys() <= allowed:
            raise ValueError("Unsupported run fields")
        fields = {k: json.dumps(v) if k in {"result", "messages", "plan"} else v
                  for k, v in fields.items()}
        fields["updated"] = time.time()
        with self.connect() as db:
            db.execute(f"UPDATE runs SET {','.join(k+'=?' for k in fields)} WHERE id=?",
                       (*fields.values(), run_id))

    def cached(self, run_id, key):
        with self.connect() as db:
            row = db.execute("SELECT value FROM work_cache WHERE run_id=? AND key=?",
                             (run_id, key)).fetchone()
        return json.loads(row[0]) if row else None

    def cache(self, run_id, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO work_cache VALUES(?,?,?)",
                       (run_id, key, json.dumps(value)))

    def checkpoint_workflow(self, run_id, state, result, attempt=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if attempt is not None and db.execute("SELECT attempt FROM runs WHERE id=?", (run_id,)).fetchone()[0] != attempt:
                raise MapStopped("An older worker cannot overwrite continued research.")
            db.execute("INSERT OR REPLACE INTO work_cache VALUES(?,'workflow',?)",
                       (run_id, json.dumps(state)))
            db.execute("UPDATE runs SET result=?,updated=? WHERE id=?",
                       (json.dumps(result), time.time(), run_id))

    def operation(self, run_id, key):
        with self.connect() as db:
            row = db.execute("SELECT * FROM calls WHERE run_id=? AND operation_key=?",
                             (run_id, key)).fetchone()
        if row is None:
            return None
        if row["status"] != "complete" or row["cost"] is None:
            raise MapStopped("This operation has unresolved usage; it will not be retried.")
        return json.loads(row["response"])

    @staticmethod
    def _can_resume(row, calls, workflow, required_allowance=1):
        return (bool(workflow) and workflow.get("version") == 1 and workflow.get("phase") != "done"
                and row["status"] in ("budget_stopped", "error", "interrupted")
                and all(c["status"] == "complete" and c["cost"] is not None
                        and c["cost"] <= c["reserved"] for c in calls)
                and sum(c["cost"] for c in calls) + required_allowance <= row["budget"])

    def resume(self, run_id):
        """Explicit continuation only, under the original budget and saved plan."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            cached = db.execute("SELECT value FROM work_cache WHERE run_id=? AND key='workflow'",
                                (run_id,)).fetchone()
            workflow = json.loads(cached[0]) if cached else None
            needed = db.execute("SELECT value FROM work_cache WHERE run_id=? AND key='required_allowance'",
                                (run_id,)).fetchone()
            calls = db.execute("SELECT * FROM calls WHERE run_id=?", (run_id,)).fetchall()
            if not self._can_resume(row, calls, workflow, json.loads(needed[0]) if needed else 1):
                raise MapStopped("No safe unfinished research to continue. Check the budget and saved status.")
            db.execute("UPDATE runs SET status='running',cancelled=0,attempt=attempt+1,stage='Continuing saved research',"
                       "error=NULL,updated=? WHERE id=?", (time.time(), run_id))

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            out = dict(row)
            calls = [dict(r) for r in db.execute(
                "SELECT id,stage,model,status,reserved,cost,usage,pricing,error,started,finished "
                "FROM calls WHERE run_id=? ORDER BY started", (run_id,))]
            cached = db.execute("SELECT value FROM work_cache WHERE run_id=? AND key='workflow'",
                                (run_id,)).fetchone()
            workflow = json.loads(cached[0]) if cached else None
            needed = db.execute("SELECT value FROM work_cache WHERE run_id=? AND key='required_allowance'",
                                (run_id,)).fetchone()
        for key in ("result", "messages", "plan"):
            out[key] = json.loads(out[key]) if out[key] else None
        spent = sum(c["cost"] or 0 for c in calls)
        held = sum(c["reserved"] for c in calls if c["status"] in ("pending", "unknown"))
        stages = {}
        for call in calls:
            call["usage"] = json.loads(call["usage"]) if call["usage"] else None
            call["pricing"] = json.loads(call["pricing"])
            call["estimated_usd"] = None if call["cost"] is None else call["cost"] / MICRO
            call["reserved_usd"] = call["reserved"] / MICRO
            call["duration_seconds"] = (call["finished"] - call["started"]
                                         if call["finished"] else None)
            stages[call["stage"]] = stages.get(call["stage"], 0) + (call["cost"] or 0) / MICRO
        out["cost"] = {"estimated_usd": spent / MICRO, "reserved_usd": held / MICRO,
                       "budget_usd": out["budget"] / MICRO,
                       "remaining_usd": max(0, out["budget"] - spent - held) / MICRO,
                       "usage_complete": not any(c["status"] == "unknown" for c in calls),
                       "can_extend": self._can_extend(out, calls),
                       "can_resume": self._can_resume(out, calls, workflow, json.loads(needed[0]) if needed else 1),
                       "by_stage": stages, "calls": calls}
        return out

    def recent(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT id,description,status,stage,created,updated FROM runs ORDER BY created DESC LIMIT 30")]

    def claim(self, run_id, status, stage, expected):
        """Reject duplicate start/chat/verify requests before any paid work."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            if row["cancelled"] or row["status"] not in expected:
                raise MapStopped("This map is already active or stopped. Open its saved results.")
            db.execute("UPDATE runs SET status=?,stage=?,error=NULL,attempt=attempt+1,updated=? WHERE id=?",
                       (status, stage, time.time(), run_id))

    def stop(self, run_id, status="cancelled", reason="Stopped by user. Results have been saved."):
        with self.connect() as db:
            cur = db.execute("UPDATE runs SET cancelled=1,status=?,stage=?,error=?,updated=? WHERE id=?",
                             (status, "Stopped", reason, time.time(), run_id))
            if not cur.rowcount:
                raise KeyError(run_id)

    def check(self, run_id, attempt=None):
        row = self.get(run_id)
        if attempt is not None and row["attempt"] != attempt:
            raise MapStopped("This worker has been superseded by an explicit continuation.")
        if row["cancelled"] or row["status"] in ("interrupted", "cost_unknown", "budget_stopped"):
            raise MapStopped(row["error"] or "Map stopped.")

    def finish(self, run_id, status="done", error=None, attempt=None):
        with self.connect() as db:
            # A late response must not erase cancellation or an unknown charge.
            db.execute("UPDATE runs SET status=?,stage=?,error=?,updated=? "
                       "WHERE id=? AND cancelled=0 AND status IN ('planning','running','verifying') "
                       "AND (? IS NULL OR attempt=?)",
                       (status, "Complete" if status == "done" else status, error, time.time(), run_id, attempt, attempt))

    def reserve(self, run_id, stage, model, amount, pricing, operation_key=None, attempt=None):
        if amount <= 0:
            raise ValueError("Reservation must be positive")
        denied = False
        call_id = uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            if attempt is not None and row["attempt"] != attempt:
                raise MapStopped("An older worker cannot dispatch new paid calls.")
            if row["cancelled"] or row["status"] not in ACTIVE:
                raise MapStopped(row["error"] or "Map is not active.")
            used = db.execute("SELECT COALESCE(SUM(CASE WHEN status IN ('pending','unknown') "
                              "THEN reserved ELSE cost END),0) FROM calls WHERE run_id=?", (run_id,)).fetchone()[0]
            if used + amount > row["budget"]:
                db.execute("INSERT OR REPLACE INTO work_cache VALUES(?,'required_allowance',?)",
                           (run_id, json.dumps(amount)))
                db.execute("UPDATE runs SET cancelled=1,status='budget_stopped',stage='Budget reached',"
                           "error='Remaining budget cannot cover the next call.',updated=? WHERE id=?",
                           (time.time(), run_id))
                denied = True
            else:
                if operation_key and db.execute("SELECT 1 FROM calls WHERE run_id=? AND operation_key=?",
                                                (run_id, operation_key)).fetchone():
                    raise MapStopped("Operation already recorded; duplicate dispatch blocked.")
                db.execute("INSERT INTO calls(id,run_id,stage,model,status,reserved,pricing,started,operation_key) "
                           "VALUES(?,?,?,?,'pending',?,?,?,?)",
                           (call_id, run_id, stage, model, amount, json.dumps(pricing), time.time(), operation_key))
                db.execute("UPDATE runs SET stage=?,updated=? WHERE id=?", (stage, time.time(), run_id))
        if denied:
            raise BudgetStopped("Remaining budget cannot cover the next call. Collected results are saved.")
        return call_id

    def settle(self, call_id, cost, usage, response, error=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
            if row is None or row["status"] != "pending":
                return
            unknown = cost is None
            db.execute("UPDATE calls SET status=?,cost=?,usage=?,response=?,error=?,finished=? WHERE id=?",
                       ("unknown" if unknown else "complete", cost, json.dumps(usage),
                        json.dumps(response), error, time.time(), call_id))
            if error == "Cancelled before dispatch":
                # This operation definitely never reached the provider; a future
                # explicitly approved continuation may dispatch it for the first time.
                db.execute("UPDATE calls SET operation_key=NULL WHERE id=?", (call_id,))
            if unknown or cost > row["reserved"]:
                db.execute("UPDATE runs SET cancelled=1,status=?,stage='Stopped',error=?,updated=? WHERE id=?",
                           ("cost_unknown" if unknown else "budget_stopped",
                            "A call's charge is uncertain; further calls are blocked." if unknown else
                            "Usage exceeded its reserved allowance; further calls are blocked.",
                            time.time(), row["run_id"]))

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE calls SET status='unknown',error='Server restarted before usage was saved',"
                       "finished=? WHERE status='pending'", (time.time(),))
            db.execute("UPDATE runs SET status='interrupted',stage='Interrupted',cancelled=1,"
                       "error='Server restarted. Saved results are available; no paid work was resumed.',updated=? "
                       "WHERE status IN ('planning','running','verifying')", (time.time(),))


class RunContext:
    def __init__(self, store, run_id, attempt=None):
        self.store, self.id = store, run_id
        self.attempt = store.get(run_id)["attempt"] if attempt is None else attempt

    def check(self):
        self.store.check(self.id, self.attempt)

    def checkpoint(self, result):
        # Save already-returned evidence even after Stop was pressed.
        with self.store.connect() as db:
            db.execute("UPDATE runs SET result=?,updated=? WHERE id=? AND attempt=?",
                       (json.dumps(result), time.time(), self.id, self.attempt))
