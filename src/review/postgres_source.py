"""Read-only import of discovery candidates and PostgreSQL review queues.

This adapter deliberately returns plain candidate dictionaries.  It has no
decision or mutation methods, and every database session is forced into
PostgreSQL's transaction-level read-only mode before any schema inspection.
"""

from __future__ import annotations

import os
import ipaddress
import re
import socket
import subprocess
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dotenv import dotenv_values


class PostgresReviewSourceError(RuntimeError):
    """A sanitized failure from the optional discovery source."""


_SAFE_HOST = re.compile(r"^[A-Za-z0-9.-]+$")


def _extend_with_powershell_dns(
    addresses: list[str], host: str, *, dns_server: str | None = None
) -> None:
    if not _SAFE_HOST.fullmatch(host):
        return
    server_arg = f" -Server {dns_server}" if dns_server else ""
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                (
                    f"Resolve-DnsName -Type A -Name {host}{server_arg} | "
                    "Where-Object { $_.IPAddress } | "
                    "Select-Object -ExpandProperty IPAddress"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return
    for line in result.stdout.splitlines():
        ip = line.strip()
        try:
            parsed = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if parsed.version == 4 and parsed.is_global and ip not in addresses:
            addresses.append(ip)


def _public_ipv4_addresses(host: str, port: int) -> list[str]:
    addresses: list[str] = []
    try:
        infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        infos = []
    for info in infos:
        ip = info[4][0]
        try:
            is_global = ipaddress.ip_address(ip).is_global
        except ValueError:
            is_global = False
        if is_global and ip not in addresses:
            addresses.append(ip)
    if not addresses and os.name == "nt":
        for dns_server in (None, "1.1.1.1", "8.8.8.8"):
            _extend_with_powershell_dns(addresses, host, dns_server=dns_server)
            if addresses:
                break
    return addresses


def _reachable_hostaddr(database_url: str) -> str | None:
    parsed = urlsplit(database_url)
    if not parsed.hostname:
        return None
    port = parsed.port or 5432
    for ip in _public_ipv4_addresses(parsed.hostname, port):
        try:
            with socket.create_connection((ip, port), timeout=3):
                return ip
        except OSError:
            continue
    return None


def _database_url_from_environment() -> str | None:
    direct = os.environ.get("REVIEW_SOURCE_DATABASE_URL", "").strip()
    if direct:
        return direct
    configured = os.environ.get("REVIEW_SOURCE_POSTGRES_ENV_FILE", "").strip()
    if not configured:
        return None
    path = Path(configured).expanduser()
    if not path.is_file():
        raise PostgresReviewSourceError(
            "The configured PostgreSQL review-source environment file does not exist."
        )
    value = str(dotenv_values(path).get("DATABASE_URL") or "").strip()
    if not value:
        raise PostgresReviewSourceError(
            "The PostgreSQL review-source environment file has no DATABASE_URL."
        )
    return value


def _validate_database_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise PostgresReviewSourceError(
            "The PostgreSQL review-source URL is invalid."
        ) from exc
    supported = {"postgres", "postgresql", "postgresql+psycopg", "postgresql+psycopg2"}
    if parsed.scheme not in supported or not parsed.hostname:
        raise PostgresReviewSourceError(
            "The review source must be a PostgreSQL connection URL."
        )
    if "+" in parsed.scheme:
        return "postgresql" + value[len(parsed.scheme):]
    return value


def _json_object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _json_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _timestamp(value: Any) -> float | None:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _source_evidence(url: Any, *, supports: str) -> list[dict[str, str]]:
    if not isinstance(url, str):
        return []
    cleaned = url.strip()
    try:
        parsed = urlsplit(cleaned)
    except ValueError:
        return []
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return []
    return [{
        "url": cleaned,
        "supports": supports,
        "evidence_type": "discovery_source_page",
    }]


def _event_name(payload: dict[str, Any], fallback: Any) -> None:
    if not payload.get("name"):
        payload["name"] = payload.get("title") or fallback


class PostgresReviewSource:
    """Fetch human-review work from the original discovery database."""

    TABLES = {
        "scrape_run", "search_candidate", "staged_record",
        "event_review_queue", "person_review_queue", "hub",
    }

    def __init__(self, database_url: str):
        self.database_url = _validate_database_url(database_url)

    @classmethod
    def from_environment(cls) -> "PostgresReviewSource | None":
        value = _database_url_from_environment()
        return cls(value) if value else None

    @contextmanager
    def connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row

            connection_options: dict[str, Any] = {}
            hostaddr = _reachable_hostaddr(self.database_url)
            if hostaddr:
                connection_options["hostaddr"] = hostaddr
            connection_options["sslmode"] = "require"
            db = psycopg.connect(
                self.database_url,
                autocommit=False,
                connect_timeout=10,
                application_name="ghus_review_read_only",
                options="-c default_transaction_read_only=on -c statement_timeout=15000",
                row_factory=dict_row,
                **connection_options,
            )
        except Exception as exc:
            raise PostgresReviewSourceError(
                "Unable to connect to the PostgreSQL review source in read-only mode."
            ) from exc
        try:
            # Some transaction poolers ignore startup ``options``. Make the
            # first statement a transaction-local guard, then verify it before
            # any schema or application-data query.
            db.execute("SET TRANSACTION READ ONLY")
            setting = db.execute("SHOW transaction_read_only").fetchone()
            read_only = next(iter(setting.values())) if isinstance(setting, dict) else setting[0]
            if str(read_only).lower() not in {"on", "true", "1"}:
                raise PostgresReviewSourceError(
                    "The PostgreSQL review source refused read-only mode."
                )
            yield db
        except PostgresReviewSourceError:
            raise
        except Exception as exc:
            raise PostgresReviewSourceError(
                "Unable to read the PostgreSQL review queues."
            ) from exc
        finally:
            try:
                db.rollback()
            finally:
                db.close()

    def fetch_candidates(self) -> tuple[list[dict[str, Any]], list[str]]:
        with self.connect() as db:
            columns = self._columns(db)
            candidates: dict[str, dict[str, Any]] = {}
            warnings: list[str] = []
            hubs = []
            if {"hub_id", "name"} <= columns.get("hub", set()):
                hubs = [
                    {"hub_id": str(row["hub_id"]), "name": str(row["name"])}
                    for row in db.execute(
                        "SELECT hub_id::text AS hub_id, name FROM hub ORDER BY name"
                    ).fetchall()
                ]

            search_columns = columns.get("search_candidate", set())
            required_search = {
                "candidate_id", "run_id", "entity_type", "url", "created_at",
                "score_band", "record_preview",
            }
            if required_search <= search_columns:
                for row in self._search_rows(db, search_columns, columns):
                    candidate = self._from_search_candidate(row)
                    if candidate["entity_type"] == "actor":
                        candidate["agent_metadata"]["hubs"] = hubs
                    candidates[candidate["source_key"]] = candidate
            else:
                warnings.append(
                    "PostgreSQL search_candidate rubric columns are unavailable; "
                    "apply the original platform's emitted rubric migrations."
                )

            event_columns = columns.get("event_review_queue", set())
            if event_columns and "staged_record" in columns:
                for row in self._event_queue_rows(db, event_columns, columns):
                    candidate = self._from_event_queue(row)
                    self._merge_queue_candidate(candidates, candidate)
            elif "event_review_queue" not in columns:
                warnings.append("PostgreSQL event_review_queue is unavailable.")

            person_columns = columns.get("person_review_queue", set())
            if person_columns and "staged_record" in columns:
                for row in self._person_queue_rows(db, person_columns, columns):
                    candidate = self._from_person_queue(row)
                    self._merge_queue_candidate(candidates, candidate)
            elif "person_review_queue" not in columns:
                warnings.append("PostgreSQL person_review_queue is unavailable.")

            return list(candidates.values()), warnings

    def _columns(self, db) -> dict[str, set[str]]:
        rows = db.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = ANY (current_schemas(false)) "
            "AND table_name = ANY (%s)",
            (list(self.TABLES),),
        ).fetchall()
        output: dict[str, set[str]] = {}
        for row in rows:
            output.setdefault(str(row["table_name"]), set()).add(str(row["column_name"]))
        return output

    @staticmethod
    def _select(alias: str, columns: set[str], name: str, cast: str = "text") -> str:
        if name in columns:
            return f"{alias}.{name} AS {name}"
        return f"NULL::{cast} AS {name}"

    def _search_rows(self, db, sc: set[str], all_columns: dict[str, set[str]]):
        optional = [
            ("query", "text"), ("provider", "text"), ("title", "text"),
            ("snippet", "text"), ("domain", "text"), ("triage_verdict", "text"),
            ("triage_reason", "text"), ("fit_score", "numeric"),
            ("duplicate_of", "uuid"), ("rubric", "jsonb"),
            ("score_breakdown", "jsonb"), ("qualification_paths", "jsonb"),
            ("identity_outcome", "text"), ("rerank_position", "integer"),
            ("rerank_reason", "text"),
        ]
        fields = [
            "sc.candidate_id::text AS candidate_id", "sc.run_id::text AS run_id",
            "sc.entity_type", "sc.url", "sc.created_at", "sc.score_band",
            "sc.record_preview",
        ] + [self._select("sc", sc, name, cast) for name, cast in optional]
        joins = ""
        run_fields = [
            "NULL::text AS run_mode", "NULL::text AS run_status",
            "NULL::text AS run_status_reason",
        ]
        run_cols = all_columns.get("scrape_run", set())
        if {"run_id", "mode", "status"} <= run_cols:
            joins = " LEFT JOIN scrape_run sr ON sr.run_id = sc.run_id"
            run_fields = [
                "sr.mode AS run_mode", "sr.status AS run_status",
                self._select("sr", run_cols, "status_reason") .replace(
                    " AS status_reason", " AS run_status_reason"
                ),
            ]
        fields.extend(run_fields)
        review_identity = (
            "sc.identity_outcome IS NOT NULL AND "
            "sc.identity_outcome NOT IN ('create','already_held','not_evaluated')"
            if "identity_outcome" in sc else "FALSE"
        )
        query = (
            "SELECT " + ", ".join(fields) + " FROM search_candidate sc" + joins +
            " WHERE sc.record_preview IS NOT NULL AND (sc.score_band = 'review' "
            f"OR (sc.entity_type = 'person' AND {review_identity}))"
        )
        if run_cols:
            query += " AND (sr.status IS NULL OR sr.status <> 'running')"
        query += " ORDER BY sc.created_at"
        return db.execute(query).fetchall()

    def _event_queue_rows(self, db, queue: set[str], all_columns: dict[str, set[str]]):
        required = {"event_review_id", "staged_record_id", "status", "created_at"}
        if not required <= queue:
            return []
        optional = [
            ("candidate_event_id", "uuid"), ("similarity_score", "numeric"),
            ("staged_title", "text"), ("candidate_title", "text"),
            ("shared_start_date", "date"), ("review_kind", "text"),
            ("search_candidate_id", "uuid"), ("rubric", "jsonb"),
            ("score_breakdown", "jsonb"), ("qualification_paths", "jsonb"),
            ("rerank_position", "integer"), ("rerank_reason", "text"),
        ]
        fields = [
            "q.event_review_id::text AS queue_id",
            "q.staged_record_id::text AS staged_record_id", "q.created_at",
            "s.run_id::text AS run_id", "s.normalized_payload", "s.source_url",
            "s.sector_codes",
        ] + [self._select("q", queue, name, cast) for name, cast in optional]
        query = (
            "SELECT " + ", ".join(fields) +
            " FROM event_review_queue q JOIN staged_record s "
            "ON s.staged_record_id = q.staged_record_id "
            "WHERE q.status = 'pending' ORDER BY q.created_at"
        )
        return db.execute(query).fetchall()

    def _person_queue_rows(self, db, queue: set[str], all_columns: dict[str, set[str]]):
        required = {"person_review_id", "staged_record_id", "status", "created_at"}
        if not required <= queue:
            return []
        optional = [
            ("candidate_person_id", "uuid"), ("score", "numeric"),
            ("staged_name", "text"), ("affiliation", "text"), ("role", "text"),
            ("public_profile_url", "text"), ("research_area", "text"),
            ("candidate_name", "text"), ("source_url", "text"),
            ("review_kind", "text"), ("rubric", "jsonb"),
            ("score_breakdown", "jsonb"), ("rerank_position", "integer"),
            ("rerank_reason", "text"), ("identity_outcome", "text"),
        ]
        fields = [
            "q.person_review_id::text AS queue_id",
            "q.staged_record_id::text AS staged_record_id", "q.created_at",
            "s.run_id::text AS run_id", "s.normalized_payload",
            "s.source_url AS staged_source_url", "s.sector_codes",
        ] + [self._select("q", queue, name, cast) for name, cast in optional]
        query = (
            "SELECT " + ", ".join(fields) +
            " FROM person_review_queue q JOIN staged_record s "
            "ON s.staged_record_id = q.staged_record_id "
            "WHERE q.status = 'pending' ORDER BY q.created_at"
        )
        return db.execute(query).fetchall()

    @staticmethod
    def _run_description(entity_type: str, run_id: str, mode: Any = None) -> str:
        suffix = f" · {mode}" if mode else ""
        return f"Open-web {entity_type} discovery{suffix} · {run_id}"

    def _from_search_candidate(self, row: dict[str, Any]) -> dict[str, Any]:
        entity_type = str(row["entity_type"])
        payload = _json_object(row.get("record_preview"))
        if entity_type == "event":
            _event_name(payload, row.get("title"))
        elif entity_type == "person" and not payload.get("name"):
            payload["name"] = row.get("title")
        elif entity_type == "actor" and not payload.get("name"):
            payload["name"] = row.get("title")
        run_id = str(row["run_id"])
        candidate_id = str(row["candidate_id"])
        metadata = {
            "source_table": "search_candidate",
            "source_candidate_id": candidate_id,
            "query": row.get("query"),
            "provider": row.get("provider"),
            "triage_verdict": row.get("triage_verdict"),
            "triage_reason": row.get("triage_reason"),
            "rubric_score": row.get("fit_score"),
            "score_band": row.get("score_band"),
            "rubric": _json_object(row.get("rubric")),
            "score_breakdown": _json_object(row.get("score_breakdown")),
            "qualification_paths": _json_list(row.get("qualification_paths")),
            "identity_outcome": row.get("identity_outcome"),
            "rerank_position": row.get("rerank_position"),
            "rerank_reason": row.get("rerank_reason"),
            "run_mode": row.get("run_mode"),
            "run_status": row.get("run_status"),
            "run_status_reason": row.get("run_status_reason"),
        }
        return {
            "source_key": f"postgres:search_candidate:{candidate_id}",
            "source_run_id": f"discovery:{run_id}",
            "source_index": candidate_id,
            "source_description": self._run_description(
                entity_type, run_id, row.get("run_mode")
            ),
            "entity_type": entity_type,
            "payload": payload,
            "evidence": _source_evidence(
                row.get("url"), supports="Fetched page used for rubric scoring and extraction"
            ),
            "agent_metadata": metadata,
            "duplicate_state": "possible_duplicate" if row.get("duplicate_of") else "not_checked",
            "created_at": _timestamp(row.get("created_at")),
            "match_key": (entity_type, run_id, str(row.get("url") or "").strip()),
        }

    def _from_event_queue(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = _json_object(row.get("normalized_payload"))
        _event_name(payload, row.get("staged_title"))
        payload.setdefault("website", row.get("source_url"))
        if row.get("shared_start_date") and not payload.get("start_date"):
            payload["start_date"] = str(row["shared_start_date"])
        if row.get("sector_codes") and not payload.get("sector_codes"):
            payload["sector_codes"] = list(row["sector_codes"])
        run_id = str(row["run_id"])
        queue_id = str(row["queue_id"])
        search_id = str(row.get("search_candidate_id") or "").strip()
        metadata = {
            "source_table": "event_review_queue",
            "review_queue_id": queue_id,
            "review_kind": row.get("review_kind"),
            "candidate_event_id": str(row.get("candidate_event_id") or "") or None,
            "candidate_title": row.get("candidate_title"),
            "similarity_score": row.get("similarity_score"),
            "rubric": _json_object(row.get("rubric")),
            "score_breakdown": _json_object(row.get("score_breakdown")),
            "qualification_paths": _json_list(row.get("qualification_paths")),
            "rerank_position": row.get("rerank_position"),
            "rerank_reason": row.get("rerank_reason"),
            "top_matches": ([{
                "entity_id": str(row.get("candidate_event_id")),
                "name": row.get("candidate_title"),
                "next_date": str(row.get("shared_start_date") or "") or None,
                "score": row.get("similarity_score"),
            }] if row.get("candidate_event_id") else []),
        }
        return {
            "source_key": (
                f"postgres:search_candidate:{search_id}" if search_id
                else f"postgres:event_review_queue:{queue_id}"
            ),
            "source_run_id": f"discovery:{run_id}",
            "source_index": search_id or f"event-queue:{queue_id}",
            "source_description": self._run_description("event", run_id),
            "entity_type": "event", "payload": payload,
            "evidence": _source_evidence(
                row.get("source_url"), supports="Source page attached to the event review queue"
            ),
            "agent_metadata": metadata,
            "duplicate_state": (
                "possible_duplicate" if row.get("candidate_event_id") else "not_checked"
            ),
            "created_at": _timestamp(row.get("created_at")),
            "match_key": ("event", run_id, str(row.get("source_url") or "").strip()),
        }

    def _from_person_queue(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = _json_object(row.get("normalized_payload"))
        for field in ("affiliation", "role", "public_profile_url", "research_area"):
            if row.get(field) is not None:
                payload.setdefault(field, row[field])
        payload.setdefault("name", row.get("staged_name"))
        source_url = row.get("source_url") or row.get("staged_source_url")
        run_id = str(row["run_id"])
        queue_id = str(row["queue_id"])
        metadata = {
            "source_table": "person_review_queue",
            "review_queue_id": queue_id,
            "review_kind": row.get("review_kind"),
            "candidate_person_id": str(row.get("candidate_person_id") or "") or None,
            "candidate_name": row.get("candidate_name"),
            "rubric_score": row.get("score"),
            "rubric": _json_object(row.get("rubric")),
            "score_breakdown": _json_object(row.get("score_breakdown")),
            "identity_outcome": row.get("identity_outcome"),
            "rerank_position": row.get("rerank_position"),
            "rerank_reason": row.get("rerank_reason"),
            "top_matches": ([{
                "entity_id": str(row.get("candidate_person_id")),
                "name": row.get("candidate_name"),
                "score": row.get("score"),
            }] if row.get("candidate_person_id") else []),
        }
        return {
            "source_key": f"postgres:person_review_queue:{queue_id}",
            "source_run_id": f"discovery:{run_id}",
            "source_index": f"person-queue:{queue_id}",
            "source_description": self._run_description("person", run_id),
            "entity_type": "person", "payload": payload,
            "evidence": _source_evidence(
                source_url, supports="Source page attached to the person review queue"
            ),
            "agent_metadata": metadata,
            "duplicate_state": (
                "possible_duplicate" if row.get("candidate_person_id") else "not_checked"
            ),
            "created_at": _timestamp(row.get("created_at")),
            "match_key": ("person", run_id, str(source_url or "").strip()),
        }

    @staticmethod
    def _merge_queue_candidate(
        candidates: dict[str, dict[str, Any]], incoming: dict[str, Any]
    ) -> None:
        existing = candidates.get(incoming["source_key"])
        if existing is None:
            existing = next(
                (row for row in candidates.values()
                 if row.get("match_key") == incoming.get("match_key")),
                None,
            )
        if existing is None:
            candidates[incoming["source_key"]] = incoming
            return
        existing["payload"].update({
            key: value for key, value in incoming["payload"].items()
            if value not in (None, "", [], {})
        })
        existing["agent_metadata"].update(incoming["agent_metadata"])
        if incoming["evidence"]:
            existing["evidence"] = incoming["evidence"]
        if incoming["duplicate_state"] != "not_checked":
            existing["duplicate_state"] = incoming["duplicate_state"]
