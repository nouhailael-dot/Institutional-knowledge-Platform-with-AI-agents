"""Scrape-run bookkeeping and audit CSV helpers."""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import text


@dataclass
class RunSnapshot:
    run_id: str
    source_name: str
    entity_type: str
    mode: str
    status: str = "running"
    stats: dict[str, object] = field(default_factory=dict)
    error: Optional[str] = None
    status_reason: str = ""


class InMemoryRunLog:
    def __init__(self):
        self.runs: dict[str, RunSnapshot] = {}
        self.raw_documents: dict[str, dict[str, object]] = {}

    def start_run(self, *, source_name: str, entity_type: str, live: bool, config: dict[str, object]) -> str:
        run_id = str(uuid.uuid4())
        self.runs[run_id] = RunSnapshot(
            run_id=run_id,
            source_name=source_name,
            entity_type=entity_type,
            mode="live" if live else "dry_run",
            stats={"config": _compact_config(config)},
        )
        return run_id

    def get_run(self, run_id: str) -> dict[str, object]:
        run = self.runs.get(run_id)
        if run is None:
            raise RuntimeError(f"scrape_run {run_id} does not exist")
        return run.__dict__.copy()

    def close_run(
        self,
        run_id: str,
        *,
        status: str,
        stats: dict[str, object],
        cost_usd: float = 0.0,
        status_reason: str = "",
    ) -> None:
        run = self.runs[run_id]
        run.status = status
        run.status_reason = status_reason
        run.stats.update(stats)
        run.stats["cost_usd"] = round(float(cost_usd), 6)

    def fail_run(
        self,
        run_id: str,
        *,
        error: str,
        stats: dict[str, object],
        cost_usd: float = 0.0,
        status_reason: str = "",
    ) -> None:
        run = self.runs[run_id]
        run.status = "failed"
        run.error = error
        run.status_reason = status_reason or error
        run.stats.update(stats)
        run.stats["cost_usd"] = round(float(cost_usd), 6)

    def find_raw_document(self, *, url: str, content_hash: str) -> Optional[dict[str, object]]:
        for raw in reversed(list(self.raw_documents.values())):
            if raw["url"] == url and raw["content_hash"] == content_hash:
                return raw.copy()
        return None

    def write_raw_document(self, *, run_id: str, doc, storage_path: str) -> str:
        raw_document_id = str(uuid.uuid4())
        self.raw_documents[raw_document_id] = {
            "raw_document_id": raw_document_id,
            "run_id": run_id,
            "url": doc.url,
            "content_hash": doc.content_hash,
            "content_type": doc.content_type,
            "fetched_at": doc.fetched_at,
            "content": doc.content,
            "storage_path": storage_path,
            "meta": dict(doc.meta or {}),
        }
        return raw_document_id

    def raw_documents_for_run(self, run_id: str) -> list[dict[str, object]]:
        return [raw.copy() for raw in self.raw_documents.values() if raw["run_id"] == run_id]


class SQLRunLog:
    def __init__(self, session):
        self.session = session

    def start_run(self, *, source_name: str, entity_type: str, live: bool, config: dict[str, object]) -> str:
        run_id = str(uuid.uuid4())
        self.session.execute(
            text(
                "INSERT INTO scrape_run (run_id, source_name, entity_type, mode, "
                "status, started_at, config) VALUES (CAST(:run_id AS uuid), "
                ":source_name, :entity_type, :mode, 'running', now(), CAST(:config AS jsonb))"
            ),
            {
                "run_id": run_id,
                "source_name": source_name,
                "entity_type": entity_type,
                "mode": "live" if live else "dry_run",
                "config": json.dumps(_compact_config(config), sort_keys=True),
            },
        )
        self.session.commit()
        return run_id

    def record_progress(self, run_id: str, *, spent_usd: float) -> None:
        """What a running run has spent so far, for the page that follows it.

        On its own short connection: the run's session may be in the middle
        of its own work, which must never be committed by a progress note.
        Only a still-running row is touched; a lock is never waited for.
        """
        bind = self.session.get_bind()
        with bind.connect() as connection:
            connection.execute(text("SET lock_timeout = '2s'"))
            connection.execute(
                text(
                    "UPDATE scrape_run SET cost_usd = :cost, stats = COALESCE(stats, "
                    "'{}'::jsonb) || jsonb_build_object('progress', jsonb_build_object("
                    "'spent_usd', CAST(:cost AS numeric), 'at', now())) "
                    "WHERE run_id = CAST(:run_id AS uuid) AND status = 'running'"
                ),
                {"run_id": run_id, "cost": round(float(spent_usd), 6)},
            )
            connection.commit()

    def get_run(self, run_id: str) -> dict[str, object]:
        row = self.session.execute(
            text(
                "SELECT run_id::text AS run_id, source_name, entity_type, mode, status, "
                "stats, error, cost_usd, status_reason FROM scrape_run WHERE run_id = CAST(:run_id AS uuid)"
            ),
            {"run_id": run_id},
        ).mappings().first()
        if row is None:
            raise RuntimeError(f"scrape_run {run_id} does not exist")
        return dict(row)

    def close_run(
        self,
        run_id: str,
        *,
        status: str,
        stats: dict[str, object],
        cost_usd: float = 0.0,
        status_reason: str = "",
    ) -> None:
        self.session.execute(
            text(
                "UPDATE scrape_run SET status = :status, finished_at = now(), "
                "stats = CAST(:stats AS jsonb), cost_usd = :cost_usd, status_reason = :status_reason "
                "WHERE run_id = CAST(:run_id AS uuid)"
            ),
            {
                "run_id": run_id,
                "status": status,
                "stats": json.dumps(stats, sort_keys=True, default=str),
                "cost_usd": float(cost_usd),
                "status_reason": status_reason,
            },
        )
        self.session.commit()

    def fail_run(
        self,
        run_id: str,
        *,
        error: str,
        stats: dict[str, object],
        cost_usd: float = 0.0,
        status_reason: str = "",
    ) -> None:
        self.session.execute(
            text(
                "UPDATE scrape_run SET status = 'failed', finished_at = now(), "
                "stats = CAST(:stats AS jsonb), error = :error, cost_usd = :cost_usd, "
                "status_reason = :status_reason "
                "WHERE run_id = CAST(:run_id AS uuid)"
            ),
            {
                "run_id": run_id,
                "stats": json.dumps(stats, sort_keys=True, default=str),
                "error": error,
                "cost_usd": float(cost_usd),
                "status_reason": status_reason or error,
            },
        )
        self.session.commit()

    def find_raw_document(self, *, url: str, content_hash: str) -> Optional[dict[str, object]]:
        row = self.session.execute(
            text(
                "SELECT raw_document_id::text AS raw_document_id, run_id::text AS run_id, "
                "url, content_hash, content_type, fetched_at, content, storage_path, meta "
                "FROM raw_document WHERE url = :url AND content_hash = :content_hash "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"url": url, "content_hash": content_hash},
        ).mappings().first()
        return dict(row) if row else None

    def write_raw_document(self, *, run_id: str, doc, storage_path: str) -> str:
        raw_document_id = str(uuid.uuid4())
        row = self.session.execute(
            text(
                "INSERT INTO raw_document (raw_document_id, run_id, url, content_hash, "
                "content_type, fetched_at, content, storage_path, meta) "
                "VALUES (CAST(:raw_document_id AS uuid), CAST(:run_id AS uuid), :url, "
                ":content_hash, :content_type, :fetched_at, :content, :storage_path, "
                "CAST(:meta AS jsonb)) "
                "ON CONFLICT (run_id, url, content_hash) DO UPDATE SET "
                "fetched_at = EXCLUDED.fetched_at, content = EXCLUDED.content, "
                "storage_path = EXCLUDED.storage_path, meta = EXCLUDED.meta "
                "RETURNING raw_document_id::text"
            ),
            {
                "raw_document_id": raw_document_id,
                "run_id": run_id,
                "url": doc.url,
                "content_hash": doc.content_hash,
                "content_type": doc.content_type,
                "fetched_at": doc.fetched_at,
                "content": doc.content,
                "storage_path": storage_path,
                "meta": json.dumps(doc.meta or {}, sort_keys=True, default=str),
            },
        ).scalar_one()
        self.session.commit()
        return str(row)

    def raw_documents_for_run(self, run_id: str) -> list[dict[str, object]]:
        rows = self.session.execute(
            text(
                "SELECT raw_document_id::text AS raw_document_id, run_id::text AS run_id, "
                "url, content_hash, content_type, fetched_at, content, storage_path, meta "
                "FROM raw_document WHERE run_id = CAST(:run_id AS uuid) "
                "ORDER BY created_at ASC, raw_document_id ASC"
            ),
            {"run_id": run_id},
        ).mappings().all()
        return [dict(row) for row in rows]


def write_audit_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "run_id",
        "source",
        "entity_type",
        "source_url",
        "content_hash",
        "natural_key",
        "zone",
        "score",
        "target_entity_id",
        "candidate_ids",
        "status",
        "error",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            clean = row.copy()
            if isinstance(clean.get("candidate_ids"), list):
                clean["candidate_ids"] = ";".join(str(item) for item in clean["candidate_ids"])
            writer.writerow(clean)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _compact_config(config: dict[str, object]) -> dict[str, object]:
    copied = json.loads(json.dumps(config, default=str))
    for key in list(copied):
        if "key" in key.lower() or "secret" in key.lower():
            copied[key] = "<redacted>"
    return copied
