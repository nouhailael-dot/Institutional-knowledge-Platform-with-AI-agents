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


def _source_environment(database_url: str) -> str:
    """Classify only explicit database-name markers; never infer from V2 IDs."""
    try:
        database_name = urlsplit(database_url).path.rsplit("/", 1)[-1].casefold()
    except ValueError:
        return "operational"
    tokens = {token for token in re.split(r"[^a-z0-9]+", database_name) if token}
    if tokens & {"test", "testing", "fixture", "fixtures", "sandbox"}:
        return "test"
    if tokens & {"dev", "development"}:
        return "development"
    if tokens & {"stage", "staging"}:
        return "staging"
    return "operational"


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
        "review_item", "actor", "actor_fact", "actor_fact_current_v2",
        "actor_fact_history", "entity_edge", "source", "topic", "actor_topic",
        "hub_actor", "hub_assignment_evidence", "proposed_hub",
        "proposed_hub_member",
    }

    def __init__(self, database_url: str):
        self.database_url = _validate_database_url(database_url)
        self.source_environment = _source_environment(self.database_url)

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
            parsed = urlsplit(self.database_url)
            connection_options["sslmode"] = (
                "disable" if parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                else "require"
            )
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

            review_columns = columns.get("review_item", set())
            if review_columns and "actor" in columns:
                for row in self._v2_review_rows(db, review_columns, columns):
                    candidate = self._from_v2_review_item(row)
                    candidates[candidate["source_key"]] = candidate

            return list(candidates.values()), warnings

    def fetch_latest_runs(self) -> list[dict[str, Any]]:
        """Return compact, truthful status for the latest actor/event/person run."""
        with self.connect() as db:
            columns = self._columns(db)
            run_columns = columns.get("scrape_run", set())
            required = {
                "run_id", "source_name", "entity_type", "mode", "status",
                "started_at", "finished_at", "stats",
            }
            if not required <= run_columns:
                return []
            fields = [
                "run_id::text AS run_id", "source_name", "entity_type", "mode",
                "status", "started_at", "finished_at", "stats",
                self._select("scrape_run", run_columns, "status_reason"),
                self._select("scrape_run", run_columns, "error"),
            ]
            rows = db.execute(
                "SELECT DISTINCT ON (entity_type) " + ", ".join(fields) +
                " FROM scrape_run WHERE entity_type IN ('actor','event','person') "
                "ORDER BY entity_type, COALESCE(finished_at,started_at) DESC NULLS LAST"
            ).fetchall()
            output = []
            for row in rows:
                stats = _json_object(row.get("stats"))
                entity_type = str(row["entity_type"])
                pending_count = self._pending_run_reviews(
                    db, columns, entity_type, str(row["run_id"])
                )
                raw_status = str(row.get("status") or "unknown")
                output.append({
                    "run_id": str(row["run_id"]),
                    "entity_type": entity_type,
                    "label": f"{entity_type.title()} Discovery",
                    "source_name": str(row.get("source_name") or "").replace("_", " ").title(),
                    "mode": row.get("mode"),
                    "status": raw_status,
                    "status_label": (
                        "Needs attention" if raw_status in {"failed", "error"}
                        else "Attention" if raw_status == "attention"
                        else "Completed" if raw_status in {"done", "completed", "success"}
                        else raw_status.replace("_", " ").title()
                    ),
                    "started_at": _timestamp(row.get("started_at")),
                    "finished_at": _timestamp(row.get("finished_at")),
                    "records_staged": int(stats.get("records_staged") or 0),
                    "queued_for_review": int(stats.get("queued_for_review") or 0),
                    "records_promoted": int(stats.get("records_promoted") or 0),
                    "pending_review": pending_count,
                    "issue": self._run_issue(entity_type, raw_status, row),
                })
            return sorted(output, key=lambda item: ("actor", "event", "person").index(item["entity_type"]))

    @staticmethod
    def _pending_run_reviews(
        db, columns: dict[str, set[str]], entity_type: str, run_id: str
    ) -> int:
        table = {
            "event": "event_review_queue", "person": "person_review_queue",
        }.get(entity_type)
        if not table or not {"staged_record_id", "status"} <= columns.get(table, set()):
            return 0
        if not {"staged_record_id", "run_id"} <= columns.get("staged_record", set()):
            return 0
        row = db.execute(
            f"SELECT count(*) AS n FROM {table} q JOIN staged_record s "
            "ON s.staged_record_id=q.staged_record_id "
            "WHERE s.run_id=%s AND q.status='pending'", (run_id,),
        ).fetchone()
        return int(row["n"] if row else 0)

    @staticmethod
    def _run_issue(entity_type: str, status: str, row: dict[str, Any]) -> str | None:
        detail = f"{row.get('status_reason') or ''} {row.get('error') or ''}".casefold()
        if entity_type == "actor" and "ck_actor_category_complete" in detail:
            return "Promotion stopped by the actor-category completeness constraint."
        if entity_type == "person" and "affiliation_raw" in detail:
            return "Review-queue persistence is pending the affiliation field integration."
        if status == "attention":
            return "Completed with records requiring review attention."
        if status in {"failed", "error"}:
            return "Discovery produced evidence, but the run did not complete."
        return None

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
            "NULL::text AS run_status_reason", "NULL::text AS run_source_name",
            "NULL::text AS run_entity_type", "NULL::timestamptz AS run_started_at",
            "NULL::timestamptz AS run_finished_at",
        ]
        run_cols = all_columns.get("scrape_run", set())
        if {"run_id", "mode", "status"} <= run_cols:
            joins = " LEFT JOIN scrape_run sr ON sr.run_id = sc.run_id"
            run_fields = [
                "sr.mode AS run_mode", "sr.status AS run_status",
                self._select("sr", run_cols, "status_reason") .replace(
                    " AS status_reason", " AS run_status_reason"
                ),
                self._select("sr", run_cols, "source_name").replace(
                    " AS source_name", " AS run_source_name"
                ),
                self._select("sr", run_cols, "entity_type").replace(
                    " AS entity_type", " AS run_entity_type"
                ),
                self._select("sr", run_cols, "started_at", "timestamptz").replace(
                    " AS started_at", " AS run_started_at"
                ),
                self._select("sr", run_cols, "finished_at", "timestamptz").replace(
                    " AS finished_at", " AS run_finished_at"
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
        if joins:
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
        run_join, run_fields = self._queue_run_metadata(all_columns)
        fields.extend(run_fields)
        query = (
            "SELECT " + ", ".join(fields) +
            " FROM event_review_queue q JOIN staged_record s "
            "ON s.staged_record_id = q.staged_record_id " + run_join +
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
        run_join, run_fields = self._queue_run_metadata(all_columns)
        fields.extend(run_fields)
        query = (
            "SELECT " + ", ".join(fields) +
            " FROM person_review_queue q JOIN staged_record s "
            "ON s.staged_record_id = q.staged_record_id " + run_join +
            "WHERE q.status = 'pending' ORDER BY q.created_at"
        )
        return db.execute(query).fetchall()

    def _queue_run_metadata(
        self, all_columns: dict[str, set[str]]
    ) -> tuple[str, list[str]]:
        run_columns = all_columns.get("scrape_run", set())
        aliases = (
            ("mode", "run_mode", "text"),
            ("status", "run_status", "text"),
            ("status_reason", "run_status_reason", "text"),
            ("source_name", "run_source_name", "text"),
            ("entity_type", "run_entity_type", "text"),
            ("started_at", "run_started_at", "timestamptz"),
            ("finished_at", "run_finished_at", "timestamptz"),
        )
        if "run_id" not in run_columns:
            return "", [f"NULL::{cast} AS {alias}" for _, alias, cast in aliases]
        fields = []
        for source, alias, cast in aliases:
            expression = self._select("sr", run_columns, source, cast)
            fields.append(expression.replace(f" AS {source}", f" AS {alias}"))
        return "LEFT JOIN scrape_run sr ON sr.run_id=s.run_id ", fields

    def _v2_review_rows(self, db, queue: set[str], all_columns: dict[str, set[str]]):
        required = {
            "review_item_id", "review_kind", "entity_type", "entity_id",
            "topic_id", "payload", "status", "created_at",
        }
        if not required <= queue:
            return []
        current_fact_relation = (
            "actor_fact_current_v2"
            if all_columns.get("actor_fact_current_v2") else "actor_fact"
        )
        history_field = "'[]'::jsonb AS fact_history "
        history_join = ""
        if all_columns.get("actor_fact_history"):
            history_field = "COALESCE(h.fact_history,'[]'::jsonb) AS fact_history "
            history_join = (
                "LEFT JOIN LATERAL ("
                " SELECT jsonb_agg(jsonb_build_object("
                "   'actor_fact_id',ah.actor_fact_id,'fact_key',ah.fact_key,"
                "   'fact_type',ah.fact_type,'layer',ah.layer,"
                "   'collection_state',ah.collection_state,'value',ah.fact_value,"
                "   'confidence',ah.confidence,'date_read',ah.retrieved_at,"
                "   'lifecycle_state',ah.lifecycle_state,'is_current',ah.is_current,"
                "   'supersedes_fact_id',ah.supersedes_fact_id"
                " ) ORDER BY ah.fact_key,ah.created_at,ah.actor_fact_id) AS fact_history "
                " FROM actor_fact_history ah WHERE ah.actor_id=a.actor_id "
                " AND ah.topic_id IS NOT DISTINCT FROM ri.topic_id"
                ") h ON true "
            )
        edge_field = "'[]'::jsonb AS relationships "
        edge_join = ""
        if {
            "entity_edge_id", "subject_type", "subject_id", "relationship_type",
            "object_type", "object_id", "topic_id", "source_id", "confidence",
            "created_at",
        } <= all_columns.get("entity_edge", set()):
            edge_field = "COALESCE(e.relationships,'[]'::jsonb) AS relationships "
            edge_join = (
                "LEFT JOIN LATERAL ("
                " SELECT jsonb_agg(jsonb_build_object("
                "   'direction',CASE WHEN ee.subject_type='actor' AND ee.subject_id=a.actor_id "
                "     THEN 'outgoing' ELSE 'incoming' END,"
                "   'relationship_type',ee.relationship_type,"
                "   'counterpart_type',CASE WHEN ee.subject_type='actor' AND ee.subject_id=a.actor_id "
                "     THEN ee.object_type ELSE ee.subject_type END,"
                "   'counterpart_id',CASE WHEN ee.subject_type='actor' AND ee.subject_id=a.actor_id "
                "     THEN ee.object_id ELSE ee.subject_id END,"
                "   'topic_id',ee.topic_id,'confidence',ee.confidence,"
                "   'source_url',es.url,'created_at',ee.created_at"
                " ) ORDER BY ee.created_at,ee.entity_edge_id) AS relationships "
                " FROM entity_edge ee JOIN source es ON es.source_id=ee.source_id "
                " WHERE ((ee.subject_type='actor' AND ee.subject_id=a.actor_id) "
                "     OR (ee.object_type='actor' AND ee.object_id=a.actor_id)) "
                "   AND (ee.topic_id IS NULL OR ee.topic_id IS NOT DISTINCT FROM ri.topic_id)"
                ") e ON true "
            )
        actor_topics_field = "'[]'::jsonb AS actor_topics "
        actor_topics_join = ""
        if {"actor_id", "topic_id"} <= all_columns.get("actor_topic", set()) and {
            "topic_id", "name",
        } <= all_columns.get("topic", set()):
            actor_topics_field = "COALESCE(at.actor_topics,'[]'::jsonb) AS actor_topics "
            actor_topics_join = (
                "LEFT JOIN LATERAL ("
                " SELECT jsonb_agg(jsonb_build_object("
                "   'topic_id',t.topic_id::text,'topic_name',t.name"
                " ) ORDER BY t.name,t.topic_id) AS actor_topics "
                " FROM actor_topic actor_topic_row "
                " JOIN topic t ON t.topic_id=actor_topic_row.topic_id "
                " WHERE actor_topic_row.actor_id=a.actor_id"
                ") at ON true "
            )
        hub_evaluations_field = "'[]'::jsonb AS hub_evaluations "
        hub_evaluations_join = ""
        evidence_columns = all_columns.get("hub_assignment_evidence", set())
        if {
            "hub_assignment_evidence_id", "actor_id", "hub_id", "topic_id",
            "outcome", "topic_matched", "location_evaluated", "distance_miles",
            "radius_miles", "outside_radius", "selected", "created_at",
        } <= evidence_columns and {"hub_id", "name"} <= all_columns.get("hub", set()):
            topic_join = ""
            topic_name = "NULL::text"
            if {"topic_id", "name"} <= all_columns.get("topic", set()):
                topic_join = " LEFT JOIN topic ht ON ht.topic_id=latest.topic_id"
                topic_name = "ht.name"
            method_version = (
                "latest.method_version" if "method_version" in evidence_columns
                else "NULL::text"
            )
            evidence = (
                "latest.evidence" if "evidence" in evidence_columns else "'{}'::jsonb"
            )
            hub_evaluations_field = (
                "COALESCE(hae.hub_evaluations,'[]'::jsonb) AS hub_evaluations "
            )
            hub_evaluations_join = (
                "LEFT JOIN LATERAL ("
                " SELECT jsonb_agg(jsonb_build_object("
                "   'hub_assignment_evidence_id',latest.hub_assignment_evidence_id::text,"
                "   'hub_id',latest.hub_id::text,'hub_name',hh.name,"
                "   'topic_id',latest.topic_id::text,'topic_name'," + topic_name + ","
                "   'outcome',latest.outcome,'topic_matched',latest.topic_matched,"
                "   'location_evaluated',latest.location_evaluated,"
                "   'distance_miles',latest.distance_miles,"
                "   'radius_miles',latest.radius_miles,"
                "   'outside_radius',latest.outside_radius,'selected',latest.selected,"
                "   'method_version'," + method_version + ",'evidence'," + evidence + ","
                "   'created_at',latest.created_at"
                " ) ORDER BY latest.topic_id,latest.selected DESC,latest.distance_miles NULLS LAST,"
                " latest.hub_id) AS hub_evaluations "
                " FROM ("
                "   SELECT DISTINCT ON (raw.topic_id,raw.hub_id) raw.* "
                "   FROM hub_assignment_evidence raw WHERE raw.actor_id=a.actor_id "
                "   AND raw.created_at=(SELECT max(newer.created_at) "
                "     FROM hub_assignment_evidence newer "
                "     WHERE newer.actor_id=raw.actor_id "
                "       AND newer.topic_id IS NOT DISTINCT FROM raw.topic_id) "
                "   ORDER BY raw.topic_id,raw.hub_id,raw.created_at DESC,"
                "     raw.hub_assignment_evidence_id DESC"
                " ) latest JOIN hub hh ON hh.hub_id=latest.hub_id" + topic_join +
                ") hae ON true "
            )
        hub_reviews_field = "'[]'::jsonb AS hub_reviews "
        hub_reviews_join = ""
        if required <= queue:
            review_topic_join = ""
            review_topic_name = "NULL::text"
            if {"topic_id", "name"} <= all_columns.get("topic", set()):
                review_topic_join = " LEFT JOIN topic hrt ON hrt.topic_id=hri.topic_id"
                review_topic_name = "hrt.name"
            hub_reviews_field = "COALESCE(hr.hub_reviews,'[]'::jsonb) AS hub_reviews "
            hub_reviews_join = (
                "LEFT JOIN LATERAL ("
                " SELECT jsonb_agg(jsonb_build_object("
                "   'review_item_id',hri.review_item_id::text,"
                "   'topic_id',hri.topic_id::text,'topic_name'," + review_topic_name + ","
                "   'review_kind',hri.review_kind,"
                "   'payload',hri.payload,'created_at',hri.created_at"
                " ) ORDER BY hri.created_at DESC,hri.review_item_id DESC) AS hub_reviews "
                " FROM review_item hri" + review_topic_join +
                " WHERE hri.entity_type='actor' "
                " AND hri.entity_id=a.actor_id AND hri.status='pending' "
                " AND hri.review_kind IN ("
                "   'hub_assignment','same_topic_overlap','hub_needs_review',"
                "   'hub_radius_overlap','hub_member_outside_radius'"
                " )"
                ") hr ON true "
            )
        existing_memberships_field = "'[]'::jsonb AS existing_memberships "
        existing_memberships_join = ""
        membership_columns = all_columns.get("hub_actor", set())
        hub_columns = all_columns.get("hub", set())
        if {"actor_id", "hub_id"} <= membership_columns and {"hub_id", "name"} <= hub_columns:
            topic_parts = []
            if "topic_id" in membership_columns:
                topic_parts.append("hm.topic_id")
            if "topic_id" in hub_columns:
                topic_parts.append("membership_hub.topic_id")
            membership_topic = (
                topic_parts[0] if len(topic_parts) == 1
                else "COALESCE(" + ",".join(topic_parts) + ")" if topic_parts
                else "NULL::uuid"
            )
            topic_join = ""
            topic_name = "NULL::text"
            if topic_parts and {"topic_id", "name"} <= all_columns.get("topic", set()):
                topic_join = " LEFT JOIN topic mt ON mt.topic_id=" + membership_topic
                topic_name = "mt.name"
            existing_memberships_field = (
                "COALESCE(hm_rows.existing_memberships,'[]'::jsonb) AS existing_memberships "
            )
            existing_memberships_join = (
                "LEFT JOIN LATERAL ("
                " SELECT jsonb_agg(jsonb_build_object("
                "   'hub_id',membership_hub.hub_id::text,'name',membership_hub.name,"
                "   'topic_id',(" + membership_topic + ")::text,"
                "   'topic_name'," + topic_name +
                " ) ORDER BY membership_hub.name,membership_hub.hub_id) AS existing_memberships "
                " FROM hub_actor hm JOIN hub membership_hub ON membership_hub.hub_id=hm.hub_id" +
                topic_join + " WHERE hm.actor_id=a.actor_id"
                ") hm_rows ON true "
            )
        proposals_field = "'[]'::jsonb AS hub_proposal_memberships "
        proposals_join = ""
        proposal_member_columns = all_columns.get("proposed_hub_member", set())
        proposal_columns = all_columns.get("proposed_hub", set())
        if {"proposed_hub_id", "actor_id"} <= proposal_member_columns and {
            "proposed_hub_id", "name",
        } <= proposal_columns:
            def proposal_value(name: str, cast: str) -> str:
                return f"ph.{name}" if name in proposal_columns else f"NULL::{cast}"

            center_parts = [
                proposal_value("primary_city", "text"),
                proposal_value("state", "text"),
                proposal_value("country", "text"),
            ]
            center_name = (
                "NULLIF(concat_ws(', '," + ",".join(
                    f"NULLIF(btrim({part}), '')" for part in center_parts
                ) + "),'')"
            )
            proposals_field = (
                "COALESCE(phm_rows.hub_proposal_memberships,'[]'::jsonb) "
                "AS hub_proposal_memberships "
            )
            proposals_join = (
                "LEFT JOIN LATERAL ("
                " SELECT jsonb_agg(jsonb_build_object("
                "   'proposal_id',ph.proposed_hub_id::text,'name',ph.name,"
                "   'independent_family_count'," + proposal_value(
                    "independent_family_count", "integer"
                ) + ","
                "   'independent_category_count'," + proposal_value(
                    "category_count", "integer"
                ) + ","
                "   'radius_miles'," + proposal_value("radius_miles", "numeric") + ","
                "   'center_name'," + center_name + ",'review_url',NULL::text"
                " ) ORDER BY ph.name,ph.proposed_hub_id) AS hub_proposal_memberships "
                " FROM proposed_hub_member phm "
                " JOIN proposed_hub ph ON ph.proposed_hub_id=phm.proposed_hub_id "
                " WHERE phm.actor_id=a.actor_id"
                ") phm_rows ON true "
            )
        return db.execute(
            "SELECT ri.review_item_id::text AS review_item_id, ri.review_kind, "
            "ri.entity_type, ri.entity_id::text AS entity_id, "
            "ri.topic_id::text AS topic_id, ri.priority, ri.payload, ri.created_at, "
            "a.name, NULLIF(to_jsonb(a)->>'actor_category','') AS actor_category, "
            "NULLIF(to_jsonb(a)->>'category_type','') AS category_type, "
            "NULLIF(to_jsonb(a)->>'category_note','') AS category_note, "
            "NULLIF(to_jsonb(a)->>'actor_type','') AS actor_type, a.description, "
            "a.website, COALESCE(NULLIF(to_jsonb(a)->>'location_city',''), "
            "NULLIF(to_jsonb(a)->>'city','')) AS location_city, "
            "COALESCE(NULLIF(to_jsonb(a)->>'state',''), "
            "NULLIF(to_jsonb(a)->>'state_code','')) AS state, "
            "NULLIF(to_jsonb(a)->>'country','') AS country, "
            "NULLIF(to_jsonb(a)->>'state_code','') AS state_code, "
            "NULLIF(to_jsonb(a)->>'region_code','') AS region_code, "
            "NULLIF(to_jsonb(a)->>'record_status','') AS record_status, "
            "s.url AS actor_source_url, "
            "COALESCE(f.facts,'[]'::jsonb) AS facts, " + history_field + ", " + edge_field +
            ", " + actor_topics_field + ", " + hub_evaluations_field +
            ", " + hub_reviews_field + ", " + existing_memberships_field +
            ", " + proposals_field +
            "FROM review_item ri "
            "LEFT JOIN actor a ON ri.entity_type='actor' AND a.actor_id=ri.entity_id "
            "LEFT JOIN source s ON s.source_id=a.source_id "
            "LEFT JOIN LATERAL ("
            " SELECT jsonb_agg(jsonb_build_object("
            "   'fact_key',af.fact_key,'fact_type',af.fact_type,'layer',af.layer,"
            "   'collection_state',af.collection_state,'value',af.fact_value,"
            "   'confidence',af.confidence,'date_read',af.retrieved_at,"
            "   'source_origin',af.source_origin,'source_url',fs.url,'is_current',true"
            " ) ORDER BY af.created_at,af.actor_fact_id) AS facts "
            f" FROM {current_fact_relation} af JOIN source fs ON fs.source_id=af.source_id "
            " WHERE af.actor_id=a.actor_id "
            "   AND af.topic_id IS NOT DISTINCT FROM ri.topic_id"
            ") f ON true " + history_join + edge_join + actor_topics_join +
            hub_evaluations_join + hub_reviews_join + existing_memberships_join +
            proposals_join +
            "WHERE ri.status='pending' "
            "AND ri.review_kind IN ("
            " 'verify_actor','possible_duplicate','classification','category_doubt',"
            " 'hub_assignment','same_topic_overlap',"
            " 'hub_needs_review','hub_radius_overlap','hub_member_outside_radius'"
            ") ORDER BY ri.created_at"
        ).fetchall()

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
            **self._review_run_metadata(row, entity_type),
        }
        if entity_type == "actor":
            metadata.update({
                "actor_topics": [],
                "hub_assignments": [],
                "existing_memberships": [],
                "hub_proposal_memberships": [],
            })
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
            **self._review_run_metadata(row, "event"),
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
            **self._review_run_metadata(row, "person"),
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

    def _from_v2_review_item(self, row: dict[str, Any]) -> dict[str, Any]:
        review_id = str(row["review_item_id"])
        payload = _json_object(row.get("payload"))
        staged_record = _json_object(payload.get("record"))
        actor_payload = {
            "name": row.get("name") or staged_record.get("name"),
            "actor_category": row.get("actor_category") or row.get("actor_type")
                              or staged_record.get("actor_category") or staged_record.get("actor_type"),
            "category_type": row.get("category_type") or staged_record.get("category_type"),
            "category_note": row.get("category_note") or staged_record.get("category_note"),
            "actor_type": row.get("actor_type") or staged_record.get("actor_type"),
            "description": row.get("description") or staged_record.get("description"),
            "website": row.get("website") or staged_record.get("website"),
            "location_city": row.get("location_city") or staged_record.get("location_city")
                             or staged_record.get("city"),
            "state": row.get("state") or row.get("state_code") or staged_record.get("state")
                     or staged_record.get("state_code"),
            "region": row.get("region_code") or staged_record.get("region")
                      or staged_record.get("region_code"),
            "country": row.get("country") or staged_record.get("country"),
        }
        actor_payload = {key: value for key, value in actor_payload.items() if value is not None}
        source_urls: list[str] = []
        for value in [payload.get("source_url"), row.get("actor_source_url")]:
            if isinstance(value, str) and value.strip() and value.strip() not in source_urls:
                source_urls.append(value.strip())
        facts = _json_list(row.get("facts"))
        fact_history = _json_list(row.get("fact_history"))
        relationships = _json_list(row.get("relationships"))
        hub_contract = self._review_hub_contract(row)
        for fact in facts:
            if isinstance(fact, dict):
                value = fact.get("source_url")
                if isinstance(value, str) and value.strip() and value.strip() not in source_urls:
                    source_urls.append(value.strip())
        evidence = []
        for url in source_urls:
            evidence.extend(_source_evidence(url, supports="Architecture V2 actor fact or discovery evidence"))
        return {
            "source_key": f"postgres:review_item:{review_id}",
            "source_run_id": f"v2-review:{row.get('topic_id') or 'unscoped'}",
            "source_index": f"review-item:{review_id}",
            "source_description": f"Architecture V2 {row.get('review_kind')} review",
            "entity_type": "actor",
            "payload": actor_payload,
            "evidence": evidence,
            "agent_metadata": {
                "source_table": "review_item",
                "source_environment": self.source_environment,
                "review_run_type": "architecture_v2_review",
                "review_run_source": "review_item",
                "review_run_entity_type": "actor",
                "review_record_created_at": _timestamp(row.get("created_at")),
                "review_item_id": review_id,
                "review_kind": (
                    "category_doubt"
                    if row.get("review_kind") == "classification"
                    and payload.get("issue") == "category_doubt"
                    else row.get("review_kind")
                ),
                "stored_review_kind": row.get("review_kind"),
                "entity_id": row.get("entity_id"),
                "topic_id": row.get("topic_id"),
                "record_status": row.get("record_status"),
                "priority": row.get("priority"),
                "pipeline": payload,
                "facts": facts,
                "fact_history": fact_history,
                "relationships": relationships,
                **hub_contract,
            },
            "duplicate_state": (
                "possible_duplicate" if row.get("review_kind") == "possible_duplicate"
                else "new"
            ),
            "created_at": _timestamp(row.get("created_at")),
        }

    def _review_run_metadata(
        self, row: dict[str, Any], entity_type: str
    ) -> dict[str, Any]:
        """Expose only run semantics that really exist in the source schema."""
        return {
            "source_environment": self.source_environment,
            "review_run_type": row.get("run_source_name") or "open_web_search",
            "review_run_source": row.get("run_source_name") or "open_web_search",
            "review_run_entity_type": row.get("run_entity_type") or entity_type,
            "review_run_mode": row.get("run_mode"),
            "review_run_status": row.get("run_status"),
            "review_run_status_reason": row.get("run_status_reason"),
            "review_run_started_at": _timestamp(row.get("run_started_at")),
            "review_run_finished_at": _timestamp(row.get("run_finished_at")),
        }

    @staticmethod
    def _review_hub_contract(row: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        """Serialize persisted Phase 6/7 data without rerunning assignment logic."""
        actor_topics: list[dict[str, Any]] = []
        topic_names: dict[str, Any] = {}
        seen_topics: set[tuple[Any, Any]] = set()
        for raw in _json_list(row.get("actor_topics")):
            if not isinstance(raw, dict):
                continue
            topic_id = str(raw.get("topic_id") or "").strip() or None
            topic_name = raw.get("topic_name")
            key = (topic_id, topic_name)
            if key in seen_topics or (topic_id is None and not topic_name):
                continue
            seen_topics.add(key)
            actor_topics.append({"topic_id": topic_id, "topic_name": topic_name})
            if topic_id and topic_name:
                topic_names[topic_id] = topic_name

        evaluations = [
            item for item in _json_list(row.get("hub_evaluations"))
            if isinstance(item, dict)
        ]
        reviews = [
            item for item in _json_list(row.get("hub_reviews"))
            if isinstance(item, dict)
        ]
        evaluations_by_topic: dict[str, list[dict[str, Any]]] = {}
        reviews_by_topic: dict[str, list[dict[str, Any]]] = {}
        topic_order: list[str] = []
        for item in evaluations:
            topic_id = str(item.get("topic_id") or "").strip()
            if not topic_id:
                continue
            if topic_id not in evaluations_by_topic:
                evaluations_by_topic[topic_id] = []
                topic_order.append(topic_id)
            evaluations_by_topic[topic_id].append(item)
            if item.get("topic_name"):
                topic_names.setdefault(topic_id, item.get("topic_name"))
        for item in reviews:
            topic_id = str(item.get("topic_id") or "").strip()
            if not topic_id:
                continue
            reviews_by_topic.setdefault(topic_id, []).append(item)
            if item.get("topic_name"):
                topic_names.setdefault(topic_id, item.get("topic_name"))
            if topic_id not in evaluations_by_topic and topic_id not in topic_order:
                topic_order.append(topic_id)

        hub_assignments: list[dict[str, Any]] = []
        for topic_id in topic_order:
            topic_evaluations = evaluations_by_topic.get(topic_id, [])
            topic_reviews = reviews_by_topic.get(topic_id, [])
            review = topic_reviews[0] if topic_reviews else {}
            review_payload = _json_object(review.get("payload"))
            review_kind = review_payload.get("canonical_review_kind") or review.get(
                "review_kind"
            )
            issue = review_payload.get("issue") or review_payload.get("canonical_outcome")

            selected = next(
                (item for item in topic_evaluations if item.get("selected") is True),
                None,
            )
            matched = [
                item for item in topic_evaluations if item.get("topic_matched") is True
            ]
            reference = selected or (matched[0] if matched else None)
            if reference is None and topic_evaluations:
                reference = topic_evaluations[0]

            outcome = selected.get("outcome") if selected else None
            if outcome is None:
                persisted_outcomes = {
                    str(item.get("outcome") or "") for item in topic_evaluations
                }
                for candidate_outcome in ("needs_review_location", "needs_review_topic"):
                    if candidate_outcome in persisted_outcomes:
                        outcome = candidate_outcome
                        break
            if outcome is None:
                canonical_outcome = review_payload.get("canonical_outcome")
                if canonical_outcome in {"needs_review_location", "needs_review_topic"}:
                    outcome = canonical_outcome

            competing_hubs = []
            if selected:
                for item in topic_evaluations:
                    if item is selected or item.get("selected") is True:
                        continue
                    if not (
                        item.get("topic_matched") is True
                        and item.get("location_evaluated") is True
                        and item.get("outside_radius") is False
                        and item.get("outcome") == "assigned"
                    ):
                        continue
                    competing_hubs.append({
                        "hub_id": str(item.get("hub_id") or "").strip() or None,
                        "name": item.get("hub_name"),
                        "topic_id": topic_id,
                        "topic_name": topic_names.get(topic_id),
                        "distance_miles": item.get("distance_miles"),
                        "radius_miles": item.get("radius_miles"),
                    })

            topic_match = reference.get("topic_matched") if reference else None
            location_evaluated = (
                reference.get("location_evaluated") if reference else None
            )
            within_radius = None
            if reference and location_evaluated is True:
                outside_radius = reference.get("outside_radius")
                if isinstance(outside_radius, bool):
                    within_radius = not outside_radius

            hub_assignments.append({
                "topic_id": topic_id,
                "topic_name": topic_names.get(topic_id),
                "outcome": outcome,
                "recommended_hub_id": (
                    str(selected.get("hub_id") or "").strip() or None if selected else None
                ),
                "recommended_hub_name": selected.get("hub_name") if selected else None,
                "distance_miles": selected.get("distance_miles") if selected else None,
                "radius_miles": selected.get("radius_miles") if selected else None,
                "topic_match": topic_match,
                "location_evaluated": location_evaluated,
                "within_radius": within_radius,
                "competing_hubs": competing_hubs,
                "review_kind": review_kind,
                "issue": issue,
            })

        existing_memberships = []
        for item in _json_list(row.get("existing_memberships")):
            if not isinstance(item, dict):
                continue
            existing_memberships.append({
                "hub_id": str(item.get("hub_id") or "").strip() or None,
                "name": item.get("name"),
                "topic_id": str(item.get("topic_id") or "").strip() or None,
                "topic_name": item.get("topic_name"),
            })

        hub_proposal_memberships = []
        for item in _json_list(row.get("hub_proposal_memberships")):
            if not isinstance(item, dict):
                continue
            hub_proposal_memberships.append({
                "proposal_id": str(item.get("proposal_id") or "").strip() or None,
                "name": item.get("name"),
                "independent_family_count": item.get("independent_family_count"),
                "independent_category_count": item.get("independent_category_count"),
                "radius_miles": item.get("radius_miles"),
                "center_name": item.get("center_name"),
                "review_url": item.get("review_url"),
            })

        return {
            "actor_topics": actor_topics,
            "hub_assignments": hub_assignments,
            "existing_memberships": existing_memberships,
            "hub_proposal_memberships": hub_proposal_memberships,
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
