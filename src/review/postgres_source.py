"""Read-only import of discovery candidates and PostgreSQL review queues.

This adapter deliberately returns plain candidate dictionaries.  It has no
decision or mutation methods, and every database session is forced into
PostgreSQL's transaction-level read-only mode before any schema inspection.
"""

from __future__ import annotations

import ast
import os
import ipaddress
import math
import re
import socket
import subprocess
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dotenv import dotenv_values


DATAFEED_SOURCE = "ghus_data_feed"


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


# Resolved once per host for a while, not on every connection. Each Review
# refresh and each actor-search keystroke opens a connection; resolving every
# time cost ~4 s each (three PowerShell DNS lookups on Windows).
_HOSTADDR_TTL_S = 600.0
_hostaddr_cache: dict[str, tuple[float, str | None]] = {}


def _reachable_hostaddr(database_url: str) -> str | None:
    parsed = urlsplit(database_url)
    host = parsed.hostname
    if not host or host == "localhost":
        return None
    try:
        ipaddress.ip_address(host)
        # An address already: nothing to resolve. 127.0.0.1 used to fall
        # through to the PowerShell lookups, because loopback is not "global".
        return None
    except ValueError:
        pass
    port = parsed.port or 5432
    key = f"{host}:{port}"
    cached = _hostaddr_cache.get(key)
    if cached and time.monotonic() - cached[0] < _HOSTADDR_TTL_S:
        return cached[1]
    found = None
    for ip in _public_ipv4_addresses(host, port):
        try:
            with socket.create_connection((ip, port), timeout=3):
                found = ip
                break
        except OSError:
            continue
    _hostaddr_cache[key] = (time.monotonic(), found)
    return found


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


def _coordinate(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _haversine_miles(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Great-circle miles. The same formula the backend hub module uses.

    Duplicated rather than imported: this app must not depend on the backend
    repository being present, and a wrong distance here would be visible to a
    reviewer. Covered by a test that checks it against known city pairs.
    """

    radius_miles = 3958.7613
    lat1, lon1, lat2, lon2 = map(math.radians, (lat_a, lon_a, lat_b, lon_b))
    sin_lat = math.sin((lat2 - lat1) / 2) ** 2
    sin_lon = math.sin((lon2 - lon1) / 2) ** 2
    haversine = sin_lat + math.cos(lat1) * math.cos(lat2) * sin_lon
    return 2 * radius_miles * math.asin(min(1.0, math.sqrt(haversine)))


def _number(value: Any) -> float | None:
    """A numeric column as a float, or None. Decimal does not survive JSON."""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# The run-ledger jobs an actor update records (backend actor_updates.py and
# the request runner).
UPDATE_JOBS = "('actor_update','actor_update_request')"


def _timestamp(value: Any) -> float | None:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _iso(value: Any) -> str | None:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value) if value not in (None, "") else None


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


def _lift_quality(payload: dict[str, Any], metadata: dict[str, Any]) -> None:
    """A discovered person's or event's page facts and quality checks, for the boxes.

    The agent stages them beside the record (agents/discovery/page_facts.py,
    quality_gates.py). They are evidence for the reviewer, not record fields,
    so they move out of the editable payload into the card's metadata.
    """
    facts = payload.pop("facts", None)
    quality = payload.pop("quality", None)
    if isinstance(facts, dict) and facts:
        metadata["page_facts"] = facts
    if isinstance(quality, dict) and quality:
        metadata["quality"] = {k: _as_list(v) if k in _QUALITY_LISTS else v
                               for k, v in quality.items()}


_QUALITY_LISTS = ("reasons", "missing_mandatory", "missing_priority", "conflicts", "checks")


def _as_list(value: Any) -> list[Any]:
    """A list, also from the Python text of a tuple ("('a', 'b')") that staged
    records stored before 2026-10-24; the Review page crashed joining it."""
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text[0] in "([":
            try:
                parsed = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                parsed = None
            if isinstance(parsed, (list, tuple)):
                return [str(item) for item in parsed]
        return [text]
    return []


def _event_name(payload: dict[str, Any], fallback: Any) -> None:
    if not payload.get("name"):
        payload["name"] = payload.get("title") or fallback


class PostgresReviewSource:
    """Fetch human-review work from the original discovery database."""

    TABLES = {
        "scrape_run", "search_candidate", "staged_record",
        "event_review_queue", "person_review_queue", "hub",
        "review_item", "actor", "actor_fact", "actor_fact_current_v2",
        "actor_fact_history", "entity_edge", "source",
        "hub_actor", "hub_sector", "sector", "actor_sector", "actor_location",
        "actor_update_subscription", "actor_update_subscription_run", "collection_run",
        "proposed_hub", "proposed_hub_member", "hub_detection_run", "topic",
        "collection_request", "fact_corroboration", "actor_fact_current_pointer",
    }

    def __init__(self, database_url: str):
        self.database_url = _validate_database_url(database_url)
        # Source keys the last fetch no longer serves, and why (see fetch_candidates).
        self.retired_keys: dict[str, str] = {}

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
            hub_context = self._hub_context(db, columns)

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
                    entry = hub_context.get(str(row.get("entity_id") or ""))
                    if entry is not None:
                        metadata = candidate["agent_metadata"]
                        metadata["hub_memberships"] = entry["current"]
                        metadata["hub_suggestions"] = entry["suggestions"]
                        metadata["hubs"] = entry["available"]
                    candidates[candidate["source_key"]] = candidate

            self._attach_discovery_runs(db, columns, candidates)

            self.retired_keys = {}
            if {"collection_run", "collection_request", "actor_fact",
                    "actor_update_subscription_run"} <= set(columns):
                cards = self._actor_update_cards(db)
                # One name per update run: what its cards say (the request's
                # title, or the actor), also on the conflicts and proposals it
                # raised - otherwise the run took whichever item came first.
                names = {c["source_run_id"]: c["source_description"] for c in cards}
                for candidate in candidates.values():
                    if candidate["source_run_id"] in names:
                        candidate["source_description"] = names[candidate["source_run_id"]]
                raised = [c for c in candidates.values()
                          if c["agent_metadata"].get("source_table") == "review_item"
                          and str(c["source_run_id"]).startswith("actor-update:")]
                profiles, folded, retired = self._actor_update_profiles(
                    db, columns, cards, raised, hub_context)
                for key in (*folded, *retired):
                    candidates.pop(key, None)
                for profile in profiles:
                    candidates[profile["source_key"]] = profile
                self.retired_keys = retired

            return list(candidates.values()), warnings

    # ------------------------------------------- event and people discovery runs
    def _attach_discovery_runs(self, db, columns, candidates) -> None:
        """One name per event or people discovery run.

        A run's records reach Review two ways - review-band search candidates
        and staged records in the event/person queues - and each carried its own
        description, so the run took whichever came first. Both now take the
        name from the run itself: its request title, or its automatic kind. A
        read only.
        """
        runs = {
            str(c["source_run_id"]).removeprefix("discovery:")
            for c in candidates.values()
            if c["entity_type"] in ("event", "person")
            and str(c["source_run_id"]).startswith("discovery:")
        }
        if not runs or not {"run_id", "stats"} <= columns.get("scrape_run", set()):
            return
        rows = {str(r["run_id"]): r for r in db.execute(
            "SELECT run_id::text AS run_id, mode, stats->>'discovery_request_title' AS title "
            "FROM scrape_run WHERE run_id::text = ANY(%s)", (sorted(runs),)).fetchall()}
        for candidate in candidates.values():
            run_id = str(candidate["source_run_id"]).removeprefix("discovery:")
            row = rows.get(run_id)
            if row is None or candidate["entity_type"] not in ("event", "person"):
                continue
            candidate["source_description"] = (
                f"Discovery request: {row['title']} · {row.get('mode') or ''} · {run_id}"
                if row.get("title")
                else self._run_description(candidate["entity_type"], run_id, row.get("mode")))

    # One profile per actor: its update runs, what they wrote into its boxes,
    # and only the changes that need a person.
    FACT_REASONS = {
        "conflict_flagged": "The new reading is older or less confident than the value on the "
                            "map, so the map kept its value and the difference waits here.",
        "pending_update": "The value on the map was set by GHUS, so an update never replaces "
                          "it on its own.",
    }

    def _actor_update_profiles(self, db, columns, cards, raised, hub_context):
        """Fold every update run of an actor, and what they raised, into one profile.

        Returns (profiles, folded source keys, retired source keys). Folded
        keys are the per-run cards and per-change items a profile now shows;
        retired keys are update runs on an inactive (test) sector, which no
        sector list shows either. Nothing is written: this is a read.
        """
        topics: dict[str, dict[str, Any]] = {}
        by_code: dict[str, dict[str, Any]] = {}
        topic_columns = columns.get("topic", set())
        if {"topic_id", "code"} <= topic_columns:
            active = "active" if "active" in topic_columns else "true AS active"
            name = "name" if "name" in topic_columns else "code AS name"
            for row in db.execute(
                f"SELECT topic_id::text AS topic_id, code, {name}, {active} FROM topic"
            ).fetchall():
                topics[row["topic_id"]] = dict(row)
                by_code[str(row["code"] or "").upper()] = dict(row)

        def topic_for(meta: dict[str, Any]) -> dict[str, Any] | None:
            return (topics.get(str(meta.get("topic_id") or ""))
                    or by_code.get(str(meta.get("topic_code") or "").upper()))

        retired: dict[str, str] = {}
        runs_by_actor: dict[str, list[tuple[dict[str, Any], dict[str, Any] | None]]] = {}
        for card in cards:
            topic = topic_for(card["agent_metadata"])
            if topic is not None and topic.get("active") is False:
                retired[card["source_key"]] = "inactive_sector"
                continue
            runs_by_actor.setdefault(card["agent_metadata"]["entity_id"], []).append((card, topic))
        raised_by_actor: dict[str, list[dict[str, Any]]] = {}
        for item in raised:
            topic = topic_for(item["agent_metadata"])
            if topic is not None and topic.get("active") is False:
                retired[item["source_key"]] = "inactive_sector"
                continue
            raised_by_actor.setdefault(str(item["agent_metadata"].get("entity_id")), []).append(item)

        profiles, folded = [], []
        for actor_id, runs in runs_by_actor.items():
            runs.sort(key=lambda pair: pair[0].get("created_at") or 0, reverse=True)
            latest, topic = runs[0]
            meta = latest["agent_metadata"]
            topic_id = (topic or {}).get("topic_id") or meta.get("topic_id")
            facts, history = self._actor_topic_facts(db, columns, actor_id, topic_id)
            # A box this sector has not filled shows what the actor's facts in
            # another sector say, labelled with that sector - stored facts only.
            have = {f["fact_key"] for f in facts}
            for other in self._other_sector_facts(db, columns, actor_id, topic_id, topics):
                if other["fact_key"] not in have:
                    have.add(other["fact_key"])
                    facts.append(other)
            # The earlier GHUS profile (migrated legacy facts) fills what no read
            # has; beside a box read and not found, it is shown, never merged.
            by_key = {f["fact_key"]: f for f in facts}
            legacy = self._legacy_record_facts(
                db, actor_id, str(latest["payload"].get("actor_category") or ""))
            for record in legacy:
                current = by_key.get(record["fact_key"])
                if current is None:
                    facts.append(record)
                elif current.get("collection_state") != "found":
                    current["record_value"] = record["value"]
            notes = self._box_notes(runs, topic_id)
            for fact in facts:
                if fact["fact_key"] in notes:
                    fact["update"] = notes[fact["fact_key"]]
            changes, mine = [], []
            for item in raised_by_actor.get(actor_id, []):
                change = self._change_of(item, topics)
                if change is None:
                    continue                   # not a decision a profile holds; stays its own card
                changes.append(change)
                mine.append(item["source_key"])
            run_rows = []
            for card, run_topic in runs:
                run_meta = card["agent_metadata"]
                run_rows.append({
                    "run_id": run_meta["run_id"], "date": card.get("created_at"),
                    "title": str(card["source_description"]).removeprefix("Actor update: "),
                    "status": run_meta.get("run_status"), "scope": run_meta.get("scope"),
                    "topic_name": (run_topic or {}).get("name"),
                    "pages_read": run_meta.get("pages_read") or [],
                    "spent_usd": run_meta.get("spent_usd"),
                    "counts": self._run_counts(run_meta),
                })
                mine.append(card["source_key"])
                # The profile a newer run replaces, if one was made for this run.
                mine.append(f"postgres:actor_updates:{actor_id}:{run_meta['run_id']}")
            evidence, seen = [], set()
            for card, _topic in runs:
                for row in card.get("evidence") or []:
                    if row.get("url") not in seen:
                        seen.add(row.get("url"))
                        evidence.append(row)
            hubs = hub_context.get(actor_id) or {}
            source_key = f"postgres:actor_updates:{actor_id}:{meta['run_id']}"
            mine = [key for key in dict.fromkeys(mine) if key != source_key]
            folded.extend(mine)
            profiles.append({
                "source_key": source_key,
                # The cards this profile now shows: earlier per-run cards, the
                # per-change items, and the profile of an earlier run.
                "folds": mine,
                "source_run_id": latest["source_run_id"],
                "source_index": f"actor-updates:{actor_id}:{meta['run_id']}",
                "source_description": latest["source_description"],
                "entity_type": "actor",
                "payload": dict(latest["payload"]),
                "evidence": evidence,
                "agent_metadata": {
                    "source_table": "actor_update", "review_kind": "actor_profile",
                    "entity_id": actor_id, "run_id": meta["run_id"],
                    "record_status": meta.get("record_status"),
                    "topic_id": topic_id, "topic_name": (topic or {}).get("name"),
                    "topic_code": (topic or {}).get("code") or meta.get("topic_code"),
                    "facts": facts, "fact_history": history,
                    "relationships": self._actor_relationships(db, columns, actor_id),
                    "update_runs": run_rows, "changes": changes,
                    "hub_memberships": hubs.get("current", []),
                    "hub_suggestions": hubs.get("suggestions", []),
                    "hubs": hubs.get("available", []),
                },
                "duplicate_state": "not_checked",
                "created_at": latest.get("created_at"),
            })
        return profiles, folded, retired

    @staticmethod
    def _run_counts(meta: dict[str, Any]) -> dict[str, int]:
        """What one run found for this actor: new, changed, confirmed, not found, to review."""
        counts: dict[str, int] = {}
        outcomes = meta.get("outcomes") or {}
        if outcomes:
            for outcome in outcomes.values():
                word = PostgresReviewSource.OUTCOME_WORDS.get(str(outcome), str(outcome))
                counts[word] = counts.get(word, 0) + 1
            return counts
        for fact in meta.get("written") or []:
            word = PostgresReviewSource._outcome_of(fact)
            counts[word] = counts.get(word, 0) + 1
        if meta.get("corroborated"):
            counts["confirmed"] = counts.get("confirmed", 0) + int(meta["corroborated"])
        return counts

    OUTCOME_WORDS = {"corroborated": "confirmed", "unchanged": "no_change",
                     "not_yet_collected": "not_found"}

    @staticmethod
    def _outcome_of(fact: dict[str, Any]) -> str:
        if fact.get("lifecycle_state") == "conflict_flagged":
            return "conflict"
        if fact.get("lifecycle_state") == "pending_update":
            return "protected"
        if fact.get("collection_state") != "found":
            return "not_found"
        return "changed" if fact.get("previous_value") is not None else "new"

    def _box_notes(self, runs, topic_id) -> dict[str, dict[str, Any]]:
        """For each box, what the most recent update of this sector found."""
        notes: dict[str, dict[str, Any]] = {}
        for card, _topic in runs:                      # newest first
            meta = card["agent_metadata"]
            if topic_id and meta.get("topic_id") and meta.get("topic_id") != topic_id:
                continue
            base = {"run_id": meta["run_id"], "date": card.get("created_at"),
                    "run_title": str(card["source_description"]).removeprefix("Actor update: ")}
            for fact in meta.get("written") or []:
                notes.setdefault(fact["fact_key"], {
                    **base, "outcome": self._outcome_of(fact),
                    "previous_value": fact.get("previous_value"),
                    "source_url": fact.get("source_url")})
            for key, outcome in (meta.get("outcomes") or {}).items():
                notes.setdefault(key, {**base, "outcome": self.OUTCOME_WORDS.get(
                    str(outcome), str(outcome)), "previous_value": None})
        return notes

    def _change_of(self, item: dict[str, Any], topics) -> dict[str, Any] | None:
        meta = item["agent_metadata"]
        kind = str(meta.get("review_kind") or "")
        pipeline = meta.get("pipeline") or {}
        base = {
            "review_item_id": meta.get("review_item_id"), "review_kind": kind,
            "topic_name": (topics.get(str(meta.get("topic_id") or "")) or {}).get("name"),
            "run_id": str(item["source_run_id"]).removeprefix("actor-update:"),
            "raised_at": item.get("created_at"),
        }
        if kind in ("fact_conflict", "pending_update"):
            change = meta.get("fact_change") or {}
            field = change.get("field_key") or pipeline.get("field_key")
            return {**base, "kind": "fact", "field_key": field,
                    "current": change.get("current"), "proposed": change.get("proposed"),
                    "reason": self.FACT_REASONS.get(str(pipeline.get("state") or kind),
                                                    self.FACT_REASONS["conflict_flagged"]),
                    # Only a location can hold two values (actor_location).
                    "can_keep_both": field == "location"}
        if kind == "relationship_review":
            return {**base, "kind": "relationship", "candidate_name": meta.get("candidate_name"),
                    "relationship_type": pipeline.get("proposed_relationship_type"),
                    "subject_actor_id": pipeline.get("subject_actor_id"),
                    "source_url": pipeline.get("source_url")}
        if kind == "hub_assignment" and pipeline.get("proposal") == "membership":
            return {**base, "kind": "hub", "hub_name": meta.get("proposed_hub_name"),
                    "evidence": pipeline.get("deterministic_evidence") or {}}
        return None

    def _actor_topic_facts(self, db, columns, actor_id, topic_id):
        """The actor's current boxes for one sector, and every value they held."""
        if not topic_id or "actor_fact_current_pointer" not in columns:
            return [], []
        rows = db.execute(
            "SELECT f.fact_key, f.fact_type, f.layer, f.collection_state, f.fact_value AS value, "
            "f.confidence, f.retrieved_at, f.source_origin, s.url AS source_url, "
            "to_jsonb(f)->>'creator_class' AS set_by "
            "FROM actor_fact_current_pointer p JOIN actor_fact f ON f.actor_fact_id = p.actor_fact_id "
            "LEFT JOIN source s ON s.source_id = f.source_id "
            "WHERE p.actor_id = CAST(%s AS uuid) AND p.topic_id = CAST(%s AS uuid) "
            "ORDER BY f.fact_key", (actor_id, topic_id)
        ).fetchall()
        facts = [{
            "fact_key": r["fact_key"], "fact_type": r["fact_type"], "layer": r["layer"],
            "collection_state": r["collection_state"], "value": r["value"],
            "confidence": r["confidence"], "date_read": _iso(r["retrieved_at"]),
            "source_origin": r["source_origin"], "source_url": r["source_url"],
            "set_by": r["set_by"], "is_current": True,
        } for r in rows]
        history = db.execute(
            "SELECT f.fact_key, f.fact_value AS value, f.confidence, f.retrieved_at, "
            "f.lifecycle_state, (p.actor_fact_id = f.actor_fact_id) AS is_current "
            "FROM actor_fact f LEFT JOIN actor_fact_current_pointer p ON p.actor_id = f.actor_id "
            " AND p.topic_id = f.topic_id AND p.fact_key = f.fact_key "
            "WHERE f.actor_id = CAST(%s AS uuid) AND f.topic_id = CAST(%s AS uuid) "
            "ORDER BY f.fact_key, f.created_at", (actor_id, topic_id)
        ).fetchall()
        return facts, [{
            "fact_key": r["fact_key"], "value": r["value"], "confidence": r["confidence"],
            "date_read": _iso(r["retrieved_at"]), "lifecycle_state": r["lifecycle_state"],
            "is_current": bool(r["is_current"]),
        } for r in history]

    def _other_sector_facts(self, db, columns, actor_id, topic_id, topics) -> list[dict[str, Any]]:
        """The actor's current found facts in its other active sectors, newest first."""
        if "actor_fact_current_pointer" not in columns:
            return []
        rows = db.execute(
            "SELECT f.fact_key, f.fact_type, f.layer, f.collection_state, f.fact_value AS value, "
            "f.confidence, f.retrieved_at, f.source_origin, s.url AS source_url, "
            "to_jsonb(f)->>'creator_class' AS set_by, p.topic_id::text AS topic_id "
            "FROM actor_fact_current_pointer p JOIN actor_fact f ON f.actor_fact_id = p.actor_fact_id "
            "LEFT JOIN source s ON s.source_id = f.source_id "
            "WHERE p.actor_id = CAST(%s AS uuid) AND p.topic_id IS DISTINCT FROM CAST(%s AS uuid) "
            "AND f.collection_state = 'found' ORDER BY f.retrieved_at DESC",
            (actor_id, topic_id)
        ).fetchall()
        out = []
        for r in rows:
            topic = topics.get(r["topic_id"]) or {}
            if topic.get("active") is False:
                continue                       # a test sector's facts are not shown
            out.append({
                "fact_key": r["fact_key"], "fact_type": r["fact_type"], "layer": r["layer"],
                "collection_state": r["collection_state"], "value": r["value"],
                "confidence": r["confidence"], "date_read": _iso(r["retrieved_at"]),
                "source_origin": r["source_origin"], "source_url": r["source_url"],
                "set_by": r["set_by"], "is_current": True,
                "from_sector": topic.get("name") or "another sector",
            })
        return out

    # Legacy (pre-V2) profile facts and the boxes they answer: the same mapping
    # the Review uses for a discovery page's statements (_CATEGORY_PAGE_ROWS).
    # Each legacy fact fills ONE box - the category's own first - so a
    # paragraph is never repeated across boxes; and undated legacy text is
    # never "recent activity", which is one dated thing.
    _LEGACY_COMMON = {"funding_signal": "funding_summary"}

    def _legacy_record_facts(self, db, actor_id, category) -> list[dict[str, Any]]:
        boxes: dict[str, str] = {}
        used: set[str] = set()
        for box, legacy_key in (*_CATEGORY_PAGE_ROWS.get(category, ()),
                                *self._LEGACY_COMMON.items()):
            if legacy_key not in used:
                used.add(legacy_key)
                boxes[box] = legacy_key
        rows = db.execute(
            "SELECT f.fact_key, f.fact_value AS value, f.confidence, f.retrieved_at, f.fact_type, "
            "s.url AS source_url FROM actor_fact f LEFT JOIN source s ON s.source_id = f.source_id "
            "WHERE f.actor_id = CAST(%s AS uuid) AND f.fact_type IN ('legacy_profile','legacy_baseline') "
            "AND f.collection_state = 'found' AND f.fact_key = ANY(%s) "
            # The curated profile summary first, then the baseline; newest first.
            "ORDER BY (f.fact_type = 'legacy_profile') DESC, f.retrieved_at DESC NULLS LAST",
            (actor_id, sorted(set(boxes.values())))
        ).fetchall()
        first: dict[str, Any] = {}
        for row in rows:
            first.setdefault(row["fact_key"], row)
        out = []
        for box, legacy_key in boxes.items():
            row = first.get(legacy_key)
            if row is None or row["value"] in (None, "", [], {}):
                continue
            out.append({
                "fact_key": box, "fact_type": "light_pull", "layer": 1,
                "collection_state": "found", "value": row["value"],
                "confidence": row["confidence"], "date_read": _iso(row["retrieved_at"]),
                "source_origin": "imported", "source_url": row["source_url"],
                "is_current": False, "from_record": "earlier GHUS profile",
            })
        return out

    def _actor_relationships(self, db, columns, actor_id) -> list[dict[str, Any]]:
        if not {"subject_type", "subject_id", "object_type", "object_id",
                "relationship_type"} <= columns.get("entity_edge", set()):
            return []
        rows = db.execute(
            "SELECT CASE WHEN ee.subject_id = CAST(%s AS uuid) THEN 'outgoing' ELSE 'incoming' END "
            " AS direction, ee.relationship_type, "
            "CASE WHEN ee.subject_id = CAST(%s AS uuid) THEN ee.object_type ELSE ee.subject_type END "
            " AS counterpart_type, "
            "CASE WHEN ee.subject_id = CAST(%s AS uuid) THEN ee.object_id ELSE ee.subject_id END::text "
            " AS counterpart_id, s.url AS source_url "
            "FROM entity_edge ee LEFT JOIN source s ON s.source_id = ee.source_id "
            "WHERE (ee.subject_type = 'actor' AND ee.subject_id = CAST(%s AS uuid)) "
            "   OR (ee.object_type = 'actor' AND ee.object_id = CAST(%s AS uuid)) "
            "ORDER BY ee.created_at", (actor_id,) * 5
        ).fetchall()
        edges = [dict(r) for r in rows]
        ids = [e["counterpart_id"] for e in edges if e.get("counterpart_type") == "actor"]
        if ids:
            names = {r["actor_id"]: r["name"] for r in db.execute(
                "SELECT actor_id::text AS actor_id, name FROM actor WHERE actor_id::text = ANY(%s)",
                (ids,)).fetchall()}
            for edge in edges:
                edge["counterpart_name"] = names.get(edge["counterpart_id"])
        return edges

    def _actor_update_cards(self, db, *, limit: int = 200) -> list[dict[str, Any]]:
        """What each actor update wrote, as one card per actor, under its run.

        Read-only. An update writes through the backend's fact writer; most of
        what it writes needs no decision, so it never reached Review and could
        not be shown there. A card lists every fact the run wrote for the
        actor - before and after, with its source - and its run groups it as
        "Actor update". Conflicts and proposals it raised join the same run.
        """
        # A request run is named by its request; a one-actor update by its actor.
        # The request title arrives with migration 550; before it, runs are
        # named by their actor and the rest of Review still reads.
        columns = self._columns(db)
        if not (columns.get("collection_run") and columns.get("collection_request")):
            return []
        request_title = (
            "(SELECT s.title FROM actor_update_subscription_run sr JOIN actor_update_subscription s "
            " ON s.actor_update_subscription_id = sr.actor_update_subscription_id "
            " WHERE sr.collection_run_id = r.collection_run_id LIMIT 1) AS request_title "
            if "title" in columns.get("actor_update_subscription", set())
            and columns.get("actor_update_subscription_run") else "NULL::text AS request_title ")
        runs = db.execute(
            "SELECT r.collection_run_id::text AS run_id, r.started_at, r.finished_at, r.status, "
            "r.spent_usd, r.job_name, q.collection_request_id::text AS request_id, "
            "q.actor_id::text AS actor_id, q.topic_id::text AS topic_id, r.config_snapshot, "
            + request_title +
            "FROM collection_run r JOIN collection_request q USING (collection_request_id) "
            f"WHERE r.job_name IN {UPDATE_JOBS} AND r.status IN ('succeeded','attention') "
            "ORDER BY r.started_at DESC LIMIT %s", (limit,)
        ).fetchall()
        cards = []
        for run in runs:
            snapshot = _json_object(run.get("config_snapshot"))
            actor_ids = ([run["actor_id"]] if run.get("actor_id") else
                         [str(a.get("actor_id")) for a in _json_list(snapshot.get("actor_results"))
                          if isinstance(a, dict) and a.get("ok")])
            for actor_id in actor_ids:
                card = self._actor_update_card(db, run, snapshot, actor_id)
                if card is not None:
                    cards.append(card)
        return cards

    def _actor_update_card(self, db, run, snapshot, actor_id) -> dict[str, Any] | None:
        actor = db.execute(
            "SELECT a.actor_id::text AS actor_id, a.name, a.website, a.description, "
            "NULLIF(to_jsonb(a)->>'actor_category','') AS actor_category, "
            "NULLIF(to_jsonb(a)->>'category_type','') AS category_type, "
            "COALESCE(NULLIF(to_jsonb(a)->>'location_city',''), NULLIF(to_jsonb(a)->>'city','')) "
            "AS location_city, COALESCE(NULLIF(to_jsonb(a)->>'state_code',''), "
            "NULLIF(to_jsonb(a)->>'state','')) AS state, "
            "NULLIF(to_jsonb(a)->>'region_code','') AS region_code, a.country, "
            "COALESCE(NULLIF(to_jsonb(a)->>'status',''), NULLIF(to_jsonb(a)->>'record_status','')) "
            "AS record_status FROM actor a WHERE a.actor_id = CAST(%s AS uuid)", (actor_id,)
        ).fetchone()
        if actor is None:
            return None
        written = db.execute(
            "SELECT f.fact_key, f.collection_state, f.fact_value, f.confidence, f.retrieved_at, "
            "f.topic_id::text AS topic_id, "
            "f.lifecycle_state, s.url AS source_url, pf.fact_value AS previous_value, "
            "(cp.actor_fact_id = f.actor_fact_id) AS is_current "
            "FROM actor_fact f LEFT JOIN source s ON s.source_id = f.source_id "
            "LEFT JOIN actor_fact pf ON pf.actor_fact_id = f.supersedes_fact_id "
            "LEFT JOIN actor_fact_current_pointer cp ON cp.actor_id = f.actor_id "
            " AND cp.topic_id = f.topic_id AND cp.fact_key = f.fact_key "
            "WHERE f.request_id = CAST(%s AS uuid) AND f.actor_id = CAST(%s AS uuid) "
            "AND f.created_at BETWEEN %s AND COALESCE(%s, now()) ORDER BY f.fact_key",
            (run["request_id"], actor_id, run["started_at"], run["finished_at"])
        ).fetchall()
        corroborated = db.execute(
            "SELECT count(*) AS n FROM fact_corroboration c JOIN actor_fact f "
            # A corroboration carries the page's read time (before the write),
            # so it is matched by its update request, not by the run's window.
            "ON f.actor_fact_id = c.actor_fact_id WHERE c.request_id = CAST(%s AS uuid) "
            "AND f.actor_id = CAST(%s AS uuid)",
            (run["request_id"], actor_id)
        ).fetchone()
        facts = [{
            "fact_key": w["fact_key"], "collection_state": w["collection_state"],
            "value": w["fact_value"], "previous_value": w["previous_value"],
            "confidence": w["confidence"], "date_read": _timestamp(w["retrieved_at"]),
            "lifecycle_state": w["lifecycle_state"], "source_url": w["source_url"],
            "is_current": bool(w["is_current"]),
        } for w in written]
        pages = [str(u) for u in _json_list(snapshot.get("pages_read")) if u]
        # The sector the run wrote under: its facts say so; a one-actor run's
        # request names it too. A request run records it per actor, by code.
        topic_id = next((w["topic_id"] for w in written if w["topic_id"]), None) or run.get("topic_id")
        topic_code = next((str(a.get("topic") or "") for a in _json_list(snapshot.get("actor_results"))
                           if isinstance(a, dict) and str(a.get("actor_id")) == actor_id), None)
        result = next((a for a in _json_list(snapshot.get("actor_results"))
                       if isinstance(a, dict) and str(a.get("actor_id")) == actor_id), {})
        payload = {k: v for k, v in {
            "name": actor["name"], "website": actor["website"],
            "description": actor["description"], "actor_category": actor["actor_category"],
            "category_type": actor["category_type"], "location_city": actor["location_city"],
            "state": actor["state"], "region": actor["region_code"], "country": actor["country"],
        }.items() if v is not None}
        evidence = []
        for url in dict.fromkeys([*pages, *(f["source_url"] for f in facts if f["source_url"])]):
            evidence.extend(_source_evidence(url, supports="Page read by the actor update"))
        return {
            "source_key": f"postgres:actor_update:{run['run_id']}:{actor_id}",
            "source_run_id": f"actor-update:{run['run_id']}",
            "source_index": f"actor-update:{run['run_id']}:{actor_id}",
            "source_description": f"Actor update: {run.get('request_title') or actor['name']}",
            "entity_type": "actor",
            "payload": payload,
            "evidence": evidence,
            "agent_metadata": {
                "source_table": "actor_update", "review_kind": "actor_update",
                "entity_id": actor_id, "run_id": run["run_id"], "run_status": run["status"],
                "record_status": actor["record_status"],
                "spent_usd": float(run["spent_usd"] or 0), "pages_read": pages,
                "written": facts, "corroborated": int(corroborated["n"] or 0),
                "scope": snapshot.get("scope") or (snapshot.get("update_request") or {}).get("scope"),
                "topic_id": topic_id, "topic_code": topic_code,
                # Per box, what the update found - including what it confirmed
                # or left unchanged, which writes no new fact. One-actor runs
                # record it; request runs record counts per actor.
                "outcomes": _json_object(snapshot.get("outcomes")),
                "counts": _json_object(result.get("counts")) if isinstance(result, dict) else {},
                "run_title": run.get("request_title"),
            },
            "duplicate_state": "not_checked",
            "created_at": _timestamp(run["finished_at"] or run["started_at"]),
        }

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
            "NULL::text AS run_status_reason", "NULL::text AS run_request_title",
            *self._datafeed_run_fields(set()),
        ]
        run_cols = all_columns.get("scrape_run", set())
        if {"run_id", "mode", "status"} <= run_cols:
            joins = " LEFT JOIN scrape_run sr ON sr.run_id = sc.run_id"
            run_fields = [
                "sr.mode AS run_mode", "sr.status AS run_status",
                self._select("sr", run_cols, "status_reason") .replace(
                    " AS status_reason", " AS run_status_reason"
                ),
                # The Discovery-page request a run was made for, so Review can
                # tell one request's finds from another's.
                ("sr.stats->>'discovery_request_title' AS run_request_title"
                 if "stats" in run_cols else "NULL::text AS run_request_title"),
                *self._datafeed_run_fields(run_cols),
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
        run_cols = all_columns.get("scrape_run", set())
        fields = [
            "q.event_review_id::text AS queue_id",
            "q.staged_record_id::text AS staged_record_id", "q.created_at",
            "s.run_id::text AS run_id", "s.normalized_payload", "s.source_url",
            "s.sector_codes",
        ] + [self._select("q", queue, name, cast) for name, cast in optional] \
            + self._datafeed_run_fields(run_cols)
        query = (
            "SELECT " + ", ".join(fields) +
            " FROM event_review_queue q JOIN staged_record s "
            "ON s.staged_record_id = q.staged_record_id "
            + (" LEFT JOIN scrape_run sr ON sr.run_id = s.run_id " if "run_id" in run_cols else "")
            + "WHERE q.status = 'pending' ORDER BY q.created_at"
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
        run_cols = all_columns.get("scrape_run", set())
        fields = [
            "q.person_review_id::text AS queue_id",
            "q.staged_record_id::text AS staged_record_id", "q.created_at",
            "s.run_id::text AS run_id", "s.normalized_payload",
            "s.source_url AS staged_source_url", "s.sector_codes",
        ] + [self._select("q", queue, name, cast) for name, cast in optional] \
            + self._datafeed_run_fields(run_cols)
        query = (
            "SELECT " + ", ".join(fields) +
            " FROM person_review_queue q JOIN staged_record s "
            "ON s.staged_record_id = q.staged_record_id "
            + (" LEFT JOIN scrape_run sr ON sr.run_id = s.run_id " if "run_id" in run_cols else "")
            + "WHERE q.status = 'pending' ORDER BY q.created_at"
        )
        return db.execute(query).fetchall()

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
        # actor_sector.is_primary arrives with the sector-dimension migration
        # (520). Without it no sector is ranked, so the first by code is shown
        # and the reviewer chooses - never a guess presented as the primary.
        primary_rank = ("asec.is_primary DESC, "
                        if "is_primary" in all_columns.get("actor_sector", set()) else "")
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
        # The sector's code, so a verified actor's Deep Pull can be offered for
        # exactly the sector it was verified for.
        # The actor update run that raised this item, if one did: a fact it
        # wrote (conflict, GHUS change) or a proposal carrying its request.
        # It groups the item under "Actor update", not "Map checks". A database
        # from before the collection ledger has no runs to point at.
        update_run = (
            "COALESCE("
            " (SELECT ur.collection_run_id::text FROM actor_fact uf JOIN collection_run ur "
            "  ON ur.collection_request_id=uf.request_id "
            f"  WHERE uf.actor_fact_id::text=ri.payload->>'new_fact_id' AND ur.job_name IN {UPDATE_JOBS} "
            "  AND uf.created_at BETWEEN ur.started_at AND COALESCE(ur.finished_at, now()) "
            "  ORDER BY ur.started_at DESC LIMIT 1),"
            " (SELECT ur.collection_run_id::text FROM collection_run ur "
            "  WHERE ur.collection_request_id::text=ri.payload->>'request_id' "
            f"  AND ur.job_name IN {UPDATE_JOBS} "
            "  AND ri.created_at BETWEEN ur.started_at AND COALESCE(ur.finished_at, now()) "
            "  ORDER BY ur.started_at DESC LIMIT 1)) AS update_run_id, "
            if all_columns.get("collection_run") else "NULL::text AS update_run_id, ")
        topic_code = ("(SELECT t.code FROM topic t WHERE t.topic_id=ri.topic_id) AS topic_code, "
                      if "code" in all_columns.get("topic", set()) else "NULL::text AS topic_code, ")
        return db.execute(
            "SELECT ri.review_item_id::text AS review_item_id, ri.review_kind, "
            "ri.entity_type, ri.entity_id::text AS entity_id, "
            "ri.topic_id::text AS topic_id, " + topic_code +
            "ri.priority, ri.payload, ri.created_at, "
            "(SELECT rel.name FROM actor rel WHERE rel.actor_id=ri.candidate_entity_id) "
            "AS related_actor_name, "
            "a.name, NULLIF(to_jsonb(a)->>'actor_category','') AS actor_category, "
            "NULLIF(to_jsonb(a)->>'category_type','') AS category_type, "
            "NULLIF(to_jsonb(a)->>'category_note','') AS category_note, "
            "NULLIF(to_jsonb(a)->>'actor_type','') AS actor_type, a.description, "
            "a.website, a.country, "
            # The V2 contract migration renames location_city -> city and
            # state -> state_code. Every other renameable column in this
            # SELECT already reads through to_jsonb for that reason; these
            # two did not, so this query raised UndefinedColumn against a
            # post-contract database and the whole V2 review-item feed
            # vanished from the queue. The output aliases are unchanged.
            "COALESCE(NULLIF(to_jsonb(a)->>'location_city',''), "
            "NULLIF(to_jsonb(a)->>'city','')) AS location_city, "
            "COALESCE(NULLIF(to_jsonb(a)->>'state',''), "
            "NULLIF(to_jsonb(a)->>'state_code','')) AS state, "
            "NULLIF(to_jsonb(a)->>'state_code','') AS state_code, "
            "NULLIF(to_jsonb(a)->>'region_code','') AS region_code, "
            # V2 `status` is the authority and `record_status` is the legacy
            # column the cutover drops. Reading record_status alone showed a
            # migrated actor as Parked when status already said verified, and
            # would read NULL once the column is gone. V2 first, legacy second.
            "COALESCE(NULLIF(to_jsonb(a)->>'status',''), "
            "NULLIF(to_jsonb(a)->>'record_status','')) AS record_status, "
            # The sector the agent recorded, so the Review dropdown has a value
            # instead of looking like nothing was ever collected. Prefers the
            # one marked primary; with several and none ranked, it stays empty
            # and the reviewer chooses rather than the screen guessing.
            "(SELECT s2.code FROM actor_sector asec JOIN sector s2 "
            " ON s2.sector_id = asec.sector_id WHERE asec.actor_id = a.actor_id "
            f" ORDER BY {primary_rank}s2.code LIMIT 1) AS primary_sector, "
            "(SELECT count(*) FROM actor_sector asec WHERE asec.actor_id = a.actor_id) "
            " AS sector_link_count, "
            "s.url AS actor_source_url, "
            # A fact conflict or pending update names two facts: the current
            # one and the one proposed. Both are shown so the reviewer decides
            # between values, not between ids. Compared as text so a malformed
            # payload yields nothing rather than a failed query.
            "CASE WHEN ri.review_kind IN ('fact_conflict','pending_update') THEN "
            " jsonb_build_object('field_key',ri.payload->>'field_key',"
            "  'current',(SELECT jsonb_build_object('value',cf.fact_value,"
            "   'confidence',cf.confidence,'date_read',cf.retrieved_at,"
            "   'set_by',to_jsonb(cf)->>'creator_class','source_url',cs.url)"
            "   FROM actor_fact cf LEFT JOIN source cs ON cs.source_id=cf.source_id"
            "   WHERE cf.actor_fact_id::text=ri.payload->>'current_fact_id'),"
            "  'proposed',(SELECT jsonb_build_object('value',nf.fact_value,"
            "   'confidence',nf.confidence,'date_read',nf.retrieved_at,"
            "   'set_by',to_jsonb(nf)->>'creator_class','source_url',ns.url)"
            "   FROM actor_fact nf LEFT JOIN source ns ON ns.source_id=nf.source_id"
            "   WHERE nf.actor_fact_id::text=ri.payload->>'new_fact_id')) END AS fact_change, "
            # The other side of a proposed link, and the hub a membership is
            # proposed for, by name: a reviewer decides between names, not ids.
            "(SELECT ca.name FROM actor ca WHERE ca.actor_id=ri.candidate_entity_id) "
            " AS candidate_name, "
            "(SELECT ph.name FROM hub ph WHERE ph.hub_id::text=ri.payload->>'proposed_hub_id') "
            " AS proposed_hub_name, " +
            update_run +
            "COALESCE(f.facts,'[]'::jsonb) AS facts, " + history_field + ", " + edge_field +
            "FROM review_item ri "
            "JOIN actor a ON ri.entity_type='actor' AND a.actor_id=ri.entity_id "
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
            ") f ON true " + history_join + edge_join +
            "WHERE ri.status='pending' "
            # Rejected actors must not re-enter the pending review feed.
            "AND COALESCE(to_jsonb(a)->>'status', '') <> 'rejected' "
            # Every actor review kind the database allows. The earlier list
            # named seven and left out geocode_failed, possible_duplicate,
            # fact_conflict and pending_update, so those items were pending in
            # the database and invisible on the screen: 154 geocode_failed rows
            # in the restored production copy alone.
            "AND ri.review_kind IN ("
            " 'verify_actor','category_doubt','geocode_failed','geocode',"
            " 'hub_assignment','hub_needs_review','hub_radius_overlap',"
            " 'hub_member_outside_radius','hub_center_drift','hub_proposal','new_hub',"
            " 'same_topic_overlap','possible_duplicate','fact_conflict','pending_update',"
            " 'pending_human_update','identity','classification','relationship_review'"
            ") ORDER BY ri.created_at"
        ).fetchall()

    def fetch_sectors(self) -> list[dict[str, Any]]:
        """Active sectors from the database, read-only.

        The sector dropdown used to be a fixed list in code, so a sector GHUS
        added could never be chosen. The database is now the list.
        """
        with self.connect() as db:
            columns = self._columns(db).get("sector")
            if not columns:
                return []
            # `active` and `is_thematic` arrive with the sector-dimension
            # migration (520). A database that has not had it - production on
            # 2026-10-16 - still has sectors, so the list is read without them
            # rather than failing and leaving the dropdown empty.
            thematic = "is_thematic" if "is_thematic" in columns else "true AS is_thematic"
            where = " WHERE active" if "active" in columns else ""
            rows = db.execute(
                f"SELECT code, name, {thematic} FROM sector{where} ORDER BY name"
            ).fetchall()
        return [{"code": str(r["code"]).upper(), "name": r["name"],
                 "is_thematic": bool(r["is_thematic"])} for r in rows]

    def search_actors(self, query: str = "", *, sector: str | None = None,
                      category: str | None = None, state: str | None = None,
                      updatable_only: bool = True, limit: int = 12) -> dict[str, Any]:
        """Existing actors for the Discovery page's actor updates, read-only.

        Two ways in, and both narrow the same group: words typed (a name, an
        alternate name or a website), and filters - sector, category, state.
        With a filter set, nothing needs to be typed: the page lists the group.
        ``total`` is the size of the whole group, not just the rows returned.

        ``updatable_only`` (the default) keeps to actors with a website of their
        own, the only ones an update can read. It also keeps out the unnamed
        placeholders imported with the map ("Water Technology Startups"), which
        have no category and no website. Merged and aggregate rows are never
        offered. Columns go through to_jsonb so the query works before and after
        the V2 cutover.
        """
        needle = " ".join(str(query or "").split())
        filtered = bool(sector or category or state)
        if len(needle) < 2 and not filtered:
            return {"actors": [], "total": 0}
        like = f"%{needle}%" if needle else "%"
        with self.connect() as db:
            sectors_sql = self._actor_sectors_sql(self._columns(db))
            rows = db.execute(
                "WITH base AS ("
                " SELECT a.actor_id::text AS actor_id, a.name, "
                " NULLIF(to_jsonb(a)->>'website','') AS website, "
                " NULLIF(to_jsonb(a)->>'actor_category','') AS actor_category, "
                " COALESCE(NULLIF(to_jsonb(a)->>'city',''), "
                "          NULLIF(to_jsonb(a)->>'location_city','')) AS city, "
                " COALESCE(NULLIF(to_jsonb(a)->>'state_code',''), "
                "          NULLIF(to_jsonb(a)->>'state','')) AS state, "
                " COALESCE(NULLIF(to_jsonb(a)->>'status',''), "
                "          NULLIF(to_jsonb(a)->>'record_status','')) AS status, "
                f" {sectors_sql} AS sectors "
                " FROM actor a "
                " WHERE (a.name ILIKE %s "
                "   OR COALESCE(to_jsonb(a)->>'website','') ILIKE %s "
                "   OR COALESCE(to_jsonb(a)->>'alt_names', to_jsonb(a)->>'alternate_names', '') ILIKE %s) "
                " AND COALESCE(to_jsonb(a)->>'merged_into_actor_id','') = '' "
                " AND COALESCE(to_jsonb(a)->>'actor_category','') <> 'aggregate' "
                " AND (NOT %s OR COALESCE(to_jsonb(a)->>'website','') <> '') "
                " AND (%s::text IS NULL OR to_jsonb(a)->>'actor_category' = %s::text) "
                " AND (%s::text IS NULL OR upper(COALESCE(to_jsonb(a)->>'state_code', "
                "      to_jsonb(a)->>'state','')) = upper(%s::text)) "
                "), matched AS ("
                " SELECT * FROM base WHERE %s::text IS NULL OR %s::text = ANY(sectors)"
                ") "
                "SELECT m.*, count(*) OVER () AS total, "
                "(SELECT f.fact_value FROM actor_fact f WHERE f.actor_id = m.actor_id::uuid "
                " AND f.fact_key = 'funding_signal' AND f.collection_state = 'found' "
                " ORDER BY f.retrieved_at DESC LIMIT 1) AS funding_signal, "
                "(SELECT f.fact_value FROM actor_fact f WHERE f.actor_id = m.actor_id::uuid "
                " AND f.fact_key = 'recent_activity' AND f.collection_state = 'found' "
                " ORDER BY f.retrieved_at DESC LIMIT 1) AS recent_activity, "
                "(SELECT max(f.retrieved_at) FROM actor_fact f WHERE f.actor_id = m.actor_id::uuid "
                " AND f.layer = 1) AS last_read "
                "FROM matched m "
                "ORDER BY (m.name ILIKE %s) DESC, length(m.name), m.name LIMIT %s",
                (like, like, like, bool(updatable_only),
                 category or None, category or None, state or None, state or None,
                 (sector or None) and sector.upper(), (sector or None) and sector.upper(),
                 f"{needle}%" if needle else "%", int(limit)),
            ).fetchall()
        total = int(rows[0]["total"]) if rows else 0
        return {"total": total, "actors": [
            {**{k: v for k, v in dict(row).items() if k != "total"},
             "sectors": list(row["sectors"] or []),
             "last_read": str(row["last_read"])[:10] if row["last_read"] else None}
            for row in rows]}

    @staticmethod
    def _actor_sectors_sql(columns: dict[str, set[str]]) -> str:
        """An actor's sector codes by every route this schema has.

        The same routes, in the same order, as the backend's
        actor_updates.actor_topics: imported actors have no direct sector
        link, and in production (no migration 520) their hub's own topic is
        the only route there is.
        """
        routes = []
        if {"actor_sector", "sector"} <= set(columns):
            routes.append("SELECT s.code FROM actor_sector x JOIN sector s "
                          "ON s.sector_id = x.sector_id WHERE x.actor_id = a.actor_id")
        if {"hub_actor", "hub_sector", "sector"} <= set(columns):
            routes.append("SELECT s.code FROM hub_actor ha JOIN hub_sector hs ON hs.hub_id = ha.hub_id "
                          "JOIN sector s ON s.sector_id = hs.sector_id WHERE ha.actor_id = a.actor_id")
        if "hub_actor" in columns and "topic" in columns and "topic_id" in columns.get("hub", set()):
            routes.append("SELECT t.code FROM hub_actor ha JOIN hub h ON h.hub_id = ha.hub_id "
                          "JOIN topic t ON t.topic_id = h.topic_id WHERE ha.actor_id = a.actor_id")
        if not routes:
            return "NULL::text[]"
        return ("(SELECT array_agg(DISTINCT code ORDER BY code) FROM ("
                + " UNION ".join(routes) + ") routes(code))")

    def fetch_hub_proposals(self) -> list[dict[str, Any]]:
        """Open hub proposals from Phase 7 detection, read-only.

        Detection only ever proposes; nothing here creates or changes a hub. The
        proposals had no surface anywhere in the platform before this, so a run
        could produce one and nobody would see it.

        Returns an empty list when the tables are absent, which is the state
        before the detection migrations are applied.
        """

        with self.connect() as db:
            columns = self._columns(db)
            if "proposed_hub" not in columns:
                return []
            available = columns["proposed_hub"]

            def column(name: str, cast: str = "text") -> str:
                return f"p.{name}" if name in available else f"NULL::{cast} AS {name}"

            rows = db.execute(
                "SELECT p.proposed_hub_id::text AS proposed_hub_id, p.name, p.primary_city, "
                "p.state, p.country, p.rationale, p.status, p.created_at, "
                f"{column('independent_family_count', 'int')}, {column('category_count', 'int')}, "
                f"{column('minimum_families_required', 'int')}, "
                f"{column('minimum_categories_required', 'int')}, "
                f"{column('center_latitude', 'numeric')}, {column('center_longitude', 'numeric')}, "
                f"{column('radius_miles', 'numeric')}, {column('core_radius_miles', 'numeric')}, "
                f"{column('dimension')}, {column('dimension_key')}, "
                f"{column('membership_fingerprint')}, {column('proposal_kind')}, "
                "p.final_hub_id::text AS final_hub_id "
                "FROM proposed_hub p WHERE p.status = 'open' "
                "ORDER BY p.created_at DESC, p.name"
            ).fetchall()

            members: dict[str, list[dict[str, Any]]] = {}
            if {"proposed_hub_member", "actor"} <= set(columns):
                for row in db.execute(
                    "SELECT m.proposed_hub_id::text AS proposed_hub_id, a.name, "
                    "NULLIF(to_jsonb(a)->>'actor_category','') AS actor_category, "
                    "NULLIF(to_jsonb(a)->>'category_type','') AS category_type, "
                    "m.family_root_actor_id::text AS family_root_actor_id "
                    "FROM proposed_hub_member m JOIN actor a ON a.actor_id = m.actor_id "
                    "ORDER BY a.name"
                ).fetchall():
                    members.setdefault(str(row["proposed_hub_id"]), []).append({
                        "name": row["name"],
                        "actor_category": row["actor_category"],
                        "category_type": row["category_type"],
                        "family_root_actor_id": row["family_root_actor_id"],
                    })

            return [
                {
                    "proposed_hub_id": str(row["proposed_hub_id"]),
                    "name": row["name"],
                    "primary_city": row["primary_city"],
                    "state": row["state"],
                    "country": row["country"],
                    "rationale": row["rationale"],
                    "status": row["status"],
                    "created_at": _timestamp(row["created_at"]),
                    "family_count": row["independent_family_count"],
                    "category_count": row["category_count"],
                    "families_required": row["minimum_families_required"],
                    "categories_required": row["minimum_categories_required"],
                    "center_latitude": _number(row["center_latitude"]),
                    "center_longitude": _number(row["center_longitude"]),
                    "radius_miles": _number(row["radius_miles"]),
                    "core_radius_miles": _number(row["core_radius_miles"]),
                    "dimension": row["dimension"],
                    "dimension_key": row["dimension_key"],
                    "fingerprint": row["membership_fingerprint"],
                    "proposal_kind": row["proposal_kind"],
                    # A proposal that created a hub would no longer be a proposal.
                    "created_hub": bool(row["final_hub_id"]),
                    "members": members.get(str(row["proposed_hub_id"]), []),
                }
                for row in rows
            ]

    def fetch_subscriptions(self) -> list[dict[str, Any]]:
        """Actor update subscriptions and their runs (WS6), read-only.

        Returns an empty list when the table is absent, which is the state
        before migration 540 is applied. An empty list and "no subscriptions
        exist" look the same to the screen, which is correct: in both cases
        there is nothing to show and nothing is being swept.
        """

        with self.connect() as db:
            columns = self._columns(db)
            if "actor_update_subscription" not in columns:
                return []
            rows = db.execute(
                "SELECT s.actor_update_subscription_id::text AS id, s.actor_ids, "
                "s.sector_codes, s.topic_ids, s.country, s.state_code, s.city, "
                "s.region_code, s.start_date, s.end_date, s.cadence, s.requested_by, "
                "s.requested_via, s.status, s.last_run_at, s.next_due_at, s.created_at "
                "FROM actor_update_subscription s "
                "ORDER BY s.status, s.next_due_at NULLS LAST, s.created_at"
            ).fetchall()

            runs: dict[str, list[dict[str, Any]]] = {}
            if {"actor_update_subscription_run", "collection_run"} <= set(columns):
                for row in db.execute(
                    "SELECT r.actor_update_subscription_id::text AS id, "
                    "r.collection_run_id::text AS run_id, r.dry_run, r.created_at, "
                    "c.status, c.status_reason "
                    "FROM actor_update_subscription_run r "
                    "JOIN collection_run c ON c.collection_run_id = r.collection_run_id "
                    "ORDER BY r.created_at DESC"
                ).fetchall():
                    runs.setdefault(str(row["id"]), []).append({
                        "run_id": str(row["run_id"]),
                        "dry_run": bool(row["dry_run"]),
                        "created_at": _timestamp(row["created_at"]),
                        "status": row["status"],
                        "status_reason": row["status_reason"],
                    })

            return [
                {
                    "subscription_id": str(row["id"]),
                    "scope": {
                        "actor_ids": [str(value) for value in (row["actor_ids"] or [])],
                        "sector_codes": list(row["sector_codes"] or []),
                        "topic_ids": [str(value) for value in (row["topic_ids"] or [])],
                        "country": row["country"],
                        "state_code": row["state_code"],
                        "city": row["city"],
                        "region_code": row["region_code"],
                    },
                    "start_date": str(row["start_date"]) if row["start_date"] else None,
                    "end_date": str(row["end_date"]) if row["end_date"] else None,
                    "cadence": row["cadence"],
                    # Never defaulted: an unknown requester stays null and the
                    # screen says "Not Recorded".
                    "requested_by": row["requested_by"],
                    "requested_via": row["requested_via"],
                    "status": row["status"],
                    "last_run_at": _timestamp(row["last_run_at"]),
                    "next_due_at": _timestamp(row["next_due_at"]),
                    "runs": runs.get(str(row["id"]), []),
                }
                for row in rows
            ]

    def _hub_context(self, db, columns: dict[str, set[str]]) -> dict[str, dict[str, Any]]:
        """Per-actor hub context for the Review screen (WS5.1).

        Three different things, kept apart because they mean different things:

          current      memberships that already exist, with the distance that
                       was recorded when they were made
          suggestions  hubs the deterministic rule would propose now, each with
                       its reason and a freshly measured distance
          available    every live hub, for a reviewer who wants to choose one by
                       hand

        A membership is never inferred from a suggestion, and a suggestion never
        becomes a membership here: this is a read.
        """

        hub_columns = columns.get("hub", set())
        if not {"hub_id", "name"} <= hub_columns:
            return {}

        has_center = {"center_latitude", "center_longitude"} <= hub_columns
        center_select = (
            "h.center_city, h.center_state_code, h.center_latitude, h.center_longitude, "
            if has_center else
            "NULL AS center_city, NULL AS center_state_code, "
            "NULL AS center_latitude, NULL AS center_longitude, "
        )
        radius_select = (
            "COALESCE(h.radius_miles, 200) AS radius_miles "
            if "radius_miles" in hub_columns else "200 AS radius_miles "
        )
        sector_select = (
            ", (SELECT s.code FROM hub_sector hs JOIN sector s ON s.sector_id = hs.sector_id "
            "WHERE hs.hub_id = h.hub_id AND hs.is_primary LIMIT 1) AS sector_code "
            if {"hub_sector", "sector"} <= set(columns) else ", NULL AS sector_code "
        )

        live = [
            {
                "hub_id": str(row["hub_id"]),
                "name": str(row["name"]),
                "center_city": row["center_city"],
                "center_state_code": row["center_state_code"],
                "center_latitude": _coordinate(row["center_latitude"]),
                "center_longitude": _coordinate(row["center_longitude"]),
                "radius_miles": float(row["radius_miles"]) if row["radius_miles"] is not None else 200.0,
                "sector_code": row["sector_code"],
            }
            for row in db.execute(
                "SELECT h.hub_id::text AS hub_id, h.name, " + center_select + radius_select
                + sector_select + "FROM hub h ORDER BY h.name"
            ).fetchall()
        ]
        by_id = {item["hub_id"]: item for item in live}

        context: dict[str, dict[str, Any]] = {}

        membership_columns = columns.get("hub_actor", set())
        if {"hub_id", "actor_id"} <= membership_columns:
            distance = "ha.distance_miles" if "distance_miles" in membership_columns else "NULL"
            outcome = (
                "ha.assignment_outcome" if "assignment_outcome" in membership_columns else "NULL"
            )
            outside = "ha.outside_radius" if "outside_radius" in membership_columns else "NULL"
            for row in db.execute(
                "SELECT ha.actor_id::text AS actor_id, ha.hub_id::text AS hub_id, "
                f"{distance} AS distance_miles, {outcome} AS assignment_outcome, "
                f"{outside} AS outside_radius "
                "FROM hub_actor ha ORDER BY ha.actor_id, ha.hub_id"
            ).fetchall():
                hub = by_id.get(str(row["hub_id"]))
                entry = context.setdefault(
                    str(row["actor_id"]), {"current": [], "suggestions": [], "available": live}
                )
                entry["current"].append({
                    "hub_id": str(row["hub_id"]),
                    "name": hub["name"] if hub else str(row["hub_id"]),
                    "sector_code": hub["sector_code"] if hub else None,
                    "distance_miles": _coordinate(row["distance_miles"]),
                    "assignment_outcome": row["assignment_outcome"],
                    "outside_radius": row["outside_radius"],
                    "suggested": False,
                })

        # Suggestions need the actor's sectors and coordinates. Both may be
        # absent, in which case there is nothing to suggest and the screen says
        # "Not Yet Collected" rather than offering a guess.
        if {"actor_sector", "sector"} <= set(columns) and has_center:
            placed = {
                (actor_id, item["hub_id"])
                for actor_id, entry in context.items()
                for item in entry["current"]
            }
            # Same compatibility as fetch_sectors: without migration 520 there
            # is no `active` column, and every sector counts.
            only_active = (" AND s.active"
                           if "active" in (self._columns(db).get("sector") or set()) else "")
            for row in db.execute(
                "SELECT a.actor_id::text AS actor_id, s.code AS sector_code, "
                "COALESCE(al.latitude, a.latitude) AS latitude, "
                "COALESCE(al.longitude, a.longitude) AS longitude "
                "FROM actor a JOIN actor_sector asec ON asec.actor_id = a.actor_id "
                f"JOIN sector s ON s.sector_id = asec.sector_id{only_active} "
                "LEFT JOIN LATERAL (SELECT latitude, longitude FROM actor_location "
                "WHERE actor_id = a.actor_id ORDER BY is_primary DESC, created_at LIMIT 1) al "
                "ON TRUE ORDER BY a.actor_id, s.code"
            ).fetchall():
                actor_id = str(row["actor_id"])
                latitude, longitude = _coordinate(row["latitude"]), _coordinate(row["longitude"])
                if latitude is None or longitude is None:
                    continue
                entry = context.setdefault(
                    actor_id, {"current": [], "suggestions": [], "available": live}
                )
                for hub in live:
                    if hub["sector_code"] != row["sector_code"]:
                        continue
                    if hub["center_latitude"] is None or hub["center_longitude"] is None:
                        continue
                    if (actor_id, hub["hub_id"]) in placed:
                        continue
                    miles = _haversine_miles(
                        latitude, longitude, hub["center_latitude"], hub["center_longitude"]
                    )
                    if miles > hub["radius_miles"]:
                        continue
                    entry["suggestions"].append({
                        "hub_id": hub["hub_id"],
                        "name": hub["name"],
                        "sector_code": hub["sector_code"],
                        "distance_miles": round(miles, 2),
                        "suggested": True,
                        "reason": (
                            f"Sector {hub['sector_code']} matches and the actor is "
                            f"{miles:.1f} miles from the hub centre, inside its "
                            f"{hub['radius_miles']:g}-mile radius."
                        ),
                    })
        for entry in context.values():
            entry["suggestions"].sort(key=lambda item: (item["distance_miles"], item["hub_id"]))
        return context

    @staticmethod
    def _datafeed_run_fields(run_cols: set[str]) -> list[str]:
        """The run's source, and its Data Feed import name and file, when recorded."""
        if not {"source_name", "config"} <= run_cols:
            return ["NULL::text AS run_source", "NULL::text AS run_import_name",
                    "NULL::text AS run_file_name"]
        return ["sr.source_name AS run_source",
                "sr.config->'datafeed'->>'import_name' AS run_import_name",
                "sr.config->'datafeed'->>'file_name' AS run_file_name"]

    @staticmethod
    def _datafeed(row: dict[str, Any], payload: dict[str, Any], record: dict[str, Any]) -> dict:
        """A Data Feed record: its own run key and name, and the match it was checked against.

        GHUS supplied it (a spreadsheet or the form), so it is labelled as such
        - never as an open-web discovery - and the existing record its check
        found is offered as "Same as existing". Review still decides.
        """
        if row.get("run_source") != DATAFEED_SOURCE:
            return record
        run_id = str(row["run_id"])
        feed = payload.get("data_feed") if isinstance(payload.get("data_feed"), dict) else {}
        where = row.get("run_file_name") or "manual entry"
        name = row.get("run_import_name") or feed.get("import_name") or "Data Feed"
        record["source_run_id"] = f"datafeed:{run_id}"
        record["source_description"] = f"Data Feed import: {name} · {where}"
        match = feed.get("match") if isinstance(feed.get("match"), dict) else {}
        meta = record["agent_metadata"]
        meta["data_feed"] = {k: feed.get(k) for k in (
            "import_name", "file_name", "row_number", "method", "uploaded_by", "submitted_at",
            "template_version", "warnings", "original_values")}
        if match.get("entity_id") and not meta.get("top_matches"):
            meta["top_matches"] = [{"entity_id": match["entity_id"], "name": match.get("name"),
                                    "score": match.get("score"), "reason": match.get("reason")}]
        if match.get("kind") in ("existing", "possible"):
            record["duplicate_state"] = "possible_duplicate"
        # Its boxes were supplied by GHUS (a spreadsheet or the form), not read
        # from a page: say so on every fact taken from the record itself.
        origin = "ghus_manual" if feed.get("method") == "manual" else "uploaded_document"
        for item in meta.get("facts") or []:
            if item.get("read_from") == "discovery_page":
                item["source_origin"], item["read_from"] = origin, "data_feed"
        url = (record.get("evidence") or [{}])[0].get("url")
        record["evidence"] = _source_evidence(
            url, supports="Source given by GHUS with this record (Data Feed)")
        return record

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
        if entity_type == "actor":
            _attach_page_facts(payload, metadata, url=row.get("url"),
                               read_at=row.get("created_at"),
                               request_title=row.get("run_request_title"))
        else:
            _lift_quality(payload, metadata)
        record = {
            "source_key": f"postgres:search_candidate:{candidate_id}",
            "source_run_id": f"discovery:{run_id}",
            "source_index": candidate_id,
            "source_description": (
                f"Discovery request: {row['run_request_title']} · {row.get('run_mode') or ''} · {run_id}"
                if row.get("run_request_title")
                else self._run_description(entity_type, run_id, row.get("run_mode"))
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
        return self._datafeed(row, payload, record)

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
        _lift_quality(payload, metadata)
        record = {
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
        return self._datafeed(row, payload, record)

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
        _lift_quality(payload, metadata)
        record = {
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
        return self._datafeed(row, payload, record)

    def _from_v2_review_item(self, row: dict[str, Any]) -> dict[str, Any]:
        review_id = str(row["review_item_id"])
        payload = _json_object(row.get("payload"))
        actor_payload = {
            "name": row.get("name"),
            "actor_category": row.get("actor_category") or row.get("actor_type"),
            "category_type": row.get("category_type"),
            "category_note": row.get("category_note"),
            "actor_type": row.get("actor_type"),
            "description": row.get("description"),
            "website": row.get("website"),
            "location_city": row.get("location_city"),
            "state": row.get("state") or row.get("state_code"),
            "region": row.get("region_code"),
            "country": row.get("country"),
            # Only when one sector is unambiguous. Several unranked sectors are
            # a reviewer's decision, not a default the screen invents.
            "primary_sector": (
                row.get("primary_sector") if int(row.get("sector_link_count") or 0) == 1 else None
            ),
        }
        actor_payload = {key: value for key, value in actor_payload.items() if value is not None}
        source_urls: list[str] = []
        for value in [payload.get("source_url"), row.get("actor_source_url")]:
            if isinstance(value, str) and value.strip() and value.strip() not in source_urls:
                source_urls.append(value.strip())
        facts = _json_list(row.get("facts"))
        fact_history = _json_list(row.get("fact_history"))
        relationships = _json_list(row.get("relationships"))
        for fact in facts:
            if isinstance(fact, dict):
                value = fact.get("source_url")
                if isinstance(value, str) and value.strip() and value.strip() not in source_urls:
                    source_urls.append(value.strip())
        evidence = []
        for url in source_urls:
            evidence.extend(_source_evidence(url, supports="Architecture V2 actor fact or discovery evidence"))
        update_run = row.get("update_run_id")
        return {
            "source_key": f"postgres:review_item:{review_id}",
            "source_run_id": (f"actor-update:{update_run}" if update_run
                              else f"v2-review:{row.get('topic_id') or 'unscoped'}"),
            "source_index": f"review-item:{review_id}",
            "source_description": (f"Actor update: {row.get('name')}" if update_run
                                   else f"Architecture V2 {row.get('review_kind')} review"),
            "entity_type": "actor",
            "payload": actor_payload,
            "evidence": evidence,
            "agent_metadata": {
                "source_table": "review_item",
                "review_item_id": review_id,
                "review_kind": row.get("review_kind"),
                "entity_id": row.get("entity_id"),
                "related_actor_name": row.get("related_actor_name"),
                "topic_id": row.get("topic_id"),
                "topic_code": row.get("topic_code"),
                "record_status": row.get("record_status"),
                "priority": row.get("priority"),
                "pipeline": payload,
                "facts": facts,
                "fact_history": fact_history,
                "relationships": relationships,
                "fact_change": _json_object(row.get("fact_change")) or None,
                "candidate_name": row.get("candidate_name"),
                "proposed_hub_name": row.get("proposed_hub_name"),
            },
            "duplicate_state": (
                "possible_duplicate" if row.get("review_kind") == "possible_duplicate"
                else "new"
            ),
            "created_at": _timestamp(row.get("created_at")),
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


# -------------------------------------------------- discovery page -> Light Pull
# A discovery candidate waiting in Review is not yet an actor, so it has no
# Light Pull facts of its own, and every box read "Not Collected" although the
# page the agent read stated most of them. These are those statements, in the
# same keys and shapes as Light Pull facts, marked as read from the discovery
# page. Nothing is inferred: a field the page did not state is left out.
_CATEGORY_PAGE_ROWS: dict[str, tuple[tuple[str, str], ...]] = {
    "university_academic": (("topic_unit_and_work", "primary_technical_focus"),
                            ("relevant_centers_programs", "current_activities")),
    "research_center": (("topic_research_focus", "primary_technical_focus"),
                        ("active_recent_projects", "current_activities"),
                        ("main_funders", "funding_summary")),
    "national_laboratory": (("topic_program_area", "primary_technical_focus"),),
    "applied_facility": (("testing_demonstration_scope", "technical_approach"),
                         ("current_project", "current_activities")),
    "hospital_clinical": (("clinical_research_focus", "primary_technical_focus"),
                          ("current_initiative", "current_activities")),
    "company": (("topic_business_segment_product", "primary_technical_focus"),),
    "startup": (("technology_and_problem", "primary_technical_focus"),),
    "innovation_platform": (("sector_focus", "primary_technical_focus"),
                            ("platform_offerings", "technical_approach")),
    "investor": (("topic_investment_thesis", "primary_technical_focus"),),
    "government": (("topic_mandate_program", "current_activities"),
                   ("visible_funding_programs", "funding_summary")),
    "foundation_nonprofit": (("mission_sector_focus", "primary_technical_focus"),
                             ("relevant_program", "current_activities")),
    "association_network": (("sector_geographic_scope", "primary_technical_focus"),
                            ("current_initiative_working_group", "current_activities")),
}


def _text(value: Any) -> str | None:
    text = " ".join(str(value or "").split())
    return text or None


def _attach_page_facts(payload: dict[str, Any], metadata: dict[str, Any], *,
                       url: Any, read_at: Any, request_title: Any = None) -> None:
    rubric = metadata.get("rubric") or {}
    sector_rows = [row for row in (rubric.get("sector_codes") or []) if isinstance(row, dict)]
    sectors = [str(row.get("code") or "").upper() for row in sector_rows if row.get("code")]
    metadata["sector_codes"] = sectors
    if sectors and not payload.get("primary_sector"):
        payload["primary_sector"] = sectors[0]
    if not sectors:
        # No GHUS sector fitted. What the page says the organisation works on
        # is the starting point for a new sector, if a reviewer creates one.
        metadata["unmatched_sector_suggestion"] = _text(payload.get("primary_technical_focus"))
    reason = _text(payload.get("match_reason"))
    evidence_quotes = [_text(row.get("evidence")) for row in sector_rows if _text(row.get("evidence"))]
    if not reason and evidence_quotes:
        # Candidates read from an official site (leads, re-reads) were not
        # given a match sentence at discovery; their page's own sector
        # evidence is exactly why they matched.
        found_for = (f"Found for the discovery request '{_text(request_title)}'"
                     if _text(request_title) else "Matched")
        reason = (f"{evidence_quotes[0].rstrip('.')}. {found_for} on the page's own "
                  f"{', '.join(sectors)} sector evidence.")
    # The page's own sector evidence is a "strong" match by the agent's rule.
    strength = payload.get("match_strength") or ("strong" if evidence_quotes else None)
    if reason:
        metadata["why_matched"] = {
            "reason": reason, "strength": strength,
            "source_url": str(url or "") or None,
        }

    date_read = str(read_at or "")[:10] or None
    facts: list[dict[str, Any]] = []

    def fact(key: str, value: Any) -> None:
        if value in (None, "", [], {}):
            return
        facts.append({
            "fact_key": key, "fact_type": "light_pull", "layer": 1, "value": value,
            "collection_state": "found", "confidence": "medium",
            "source_url": str(url or "") or None, "source_origin": "newly_found",
            "date_read": date_read, "read_from": "discovery_page",
        })

    name = _text(payload.get("name"))
    fact("official_identity", {"name": name, "other_names": []} if name else None)
    category, type_code = payload.get("actor_category"), payload.get("category_type")
    fact("actor_category_type", {"category": category, "type": type_code,
                                 "category_note": _text(payload.get("category_note"))}
         if category else None)
    fact("website", _text(payload.get("website")))
    fact("description", _text(payload.get("description")))
    place = {k: _text(payload.get(src)) for k, src in
             (("city", "location_city"), ("state", "state"), ("country", "country"))}
    fact("location", {k: v for k, v in place.items() if v} or None)
    evidence = [_text(row.get("evidence")) for row in sector_rows if _text(row.get("evidence"))]
    fact("sector_topic", {"sector_codes": sectors, "evidence": evidence[0] if evidence else None}
         if sectors else None)
    hubs = [str(row.get("name")) for row in (rubric.get("hub_matches") or [])
            if isinstance(row, dict) and row.get("name")]
    fact("hub_assignment", {"suggested_hubs": hubs} if hubs else None)
    fact("recent_activity", _text(payload.get("current_activities")))
    fact("funding_signal", _text(payload.get("funding_summary")))
    if reason:
        fact("why_matched", {"reason": reason, "strength": strength,
                             "source_url": str(url or "") or None})
    for key, field in _CATEGORY_PAGE_ROWS.get(str(category or ""), ()):
        fact(key, _text(payload.get(field)))
    metadata["facts"] = _with_collected_light_pull(facts, payload, metadata)


# Boxes that show the reviewer-editable record (or the pipeline's own
# computation). A Light Pull read of the organisation's pages never replaces
# them; it fills location and why-matched only when the record has none.
_RECORD_OWNED_BOXES = frozenset({
    "official_identity", "actor_category_type", "website", "description",
    "sector_topic", "hub_assignment", "parent_connection",
})
_FILL_ONLY_IF_ABSENT = frozenset({"location", "why_matched"})


def _with_collected_light_pull(facts: list[dict[str, Any]], payload: dict[str, Any],
                               metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge the backend Light Pull read (light_pull_candidates) into the boxes.

    Every box it answered is shown: found, with the page and checked quote it
    came from, or not stated on the pages read - which pages, listed. These
    keys are taken OUT of the editable payload: they are evidence for the
    reviewer, not record fields to edit, and admission reads them from the
    candidate row itself.
    """
    collected = payload.pop("light_pull_evidence", None)
    read = payload.pop("light_pull_read", None)
    if not isinstance(collected, dict):
        return facts
    read = read if isinstance(read, dict) else {}
    metadata["light_pull_read"] = read
    pages = [str(url) for url in (read.get("pages_read") or []) if url]
    by_key = {f["fact_key"]: f for f in facts}
    for key, evidence in collected.items():
        if not isinstance(evidence, dict) or key in _RECORD_OWNED_BOXES:
            continue
        found = evidence.get("collection_state") == "found"
        if key in by_key and (key in _FILL_ONLY_IF_ABSENT or not found):
            continue
        by_key[key] = {
            "fact_key": key, "fact_type": "light_pull", "layer": 1,
            "value": evidence.get("value") if found else None,
            "collection_state": "found" if found else "not_found",
            "confidence": evidence.get("confidence") or "medium",
            "source_url": evidence.get("source_url") if found else None,
            "source_origin": "newly_found",
            "date_read": str(evidence.get("date_read") or read.get("read_at") or "")[:10] or None,
            "read_from": "official_pages",
            "pages_read": pages,
        }
    return list(by_key.values())
