"""Data Feed: check -> preview -> explicit confirmation -> staged for Review.

A preview holds the values read from a file (or typed in the form), every
row's problems, and what each record may already be on the map. It is kept
server-side under ``.datafeed/previews`` (never in a served or versioned
directory) for at most PREVIEW_TTL, and deleted once its records are staged.
The uploaded file itself is never kept: only its name, size and SHA-256.

Nothing is staged until a person confirms a preview; rows with errors are never
staged and the confirmation says how many are left out.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.datafeed import contract, matching, parse, reference, templates, validate
from src.datafeed.bridge import DataFeedBridge, DataFeedBridgeError

ROOT = Path(__file__).resolve().parents[2]
PREVIEW_TTL = 24 * 3600
BATCH_CONTRACT = "ghus-datafeed-batch/1"
_PREVIEW_ID = re.compile(r"^[0-9a-f]{32}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_MANUAL_ROWS = 50
# What the uploader confirms, recorded word for word with the import.
ATTESTATIONS = {
    "source": "I confirm these records come from a GHUS source (a GHUS file, a Compass "
              "import or a Notion CRM export copied into the GHUS template).",
    "verified": "I confirm these records come from a GHUS source, that I am authorized GHUS "
                "staff, and that I verify the organizations in this import.",
    # Explore and Map's Verify (28 Oct 2026): web results a reviewer checked.
    "map": "I confirm that I am authorized GHUS staff, that I checked these records' sources, "
           "and that I verify the organizations among them.",
}
# What a record is, in the words the page uses.
STATUS_LABELS = {
    "invalid": "Needs correction", "new": "New record", "existing": "Matches an existing record",
    "possible": "Possible duplicate", "waiting": "Already waiting in Review",
}


class DataFeedError(ValueError):
    """A request the Data Feed cannot carry out; the message is for the person."""


def readonly_connector(url: str | None = None) -> Callable[[], Any] | None:
    raw = url or os.environ.get("DATAFEED_DATABASE_URL") or ""
    if not raw:
        return None
    conninfo = raw.replace("postgresql+psycopg://", "postgresql://", 1)

    def connect():
        import psycopg

        return psycopg.connect(conninfo, options="-c default_transaction_read_only=on",
                               connect_timeout=15)
    return connect


class DataFeedService:
    def __init__(self, *, bridge: DataFeedBridge | None = None,
                 connect: Callable[[], Any] | None = None,
                 preview_dir: Path | None = None):
        self.bridge = bridge or DataFeedBridge()
        self.connect = connect if connect is not None else readonly_connector(
            self.bridge.database_url)
        self.preview_dir = preview_dir or ROOT / ".datafeed" / "previews"
        self.runs_dir = self.preview_dir.parent / "completion"

    # ------------------------------------------------------------------ catalog
    def vocabularies(self) -> dict[str, Any]:
        return reference.vocabularies(self.connect)

    def catalog(self) -> dict[str, Any]:
        return {**contract.as_payload(), "vocabularies": self.vocabularies(),
                "staging_configured": self.bridge.configured,
                "matching_available": self.connect is not None,
                "limits": {"max_bytes": parse.MAX_BYTES, "max_rows": parse.MAX_ROWS,
                           "max_manual_rows": MAX_MANUAL_ROWS},
                "status_labels": STATUS_LABELS}

    def template(self, record_type: str, extension: str) -> tuple[bytes, str, str]:
        if record_type not in contract.RECORD_TYPES:
            raise DataFeedError("Unknown record type.")
        if extension == "xlsx":
            return (templates.build_xlsx(record_type, self.vocabularies()),
                    templates.file_name(record_type, "xlsx"),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if extension == "csv":
            return (templates.build_csv(record_type), templates.file_name(record_type, "csv"),
                    "text/csv; charset=utf-8")
        raise DataFeedError("Templates are .xlsx or .csv.")

    # ------------------------------------------------------------------ check
    def validate_upload(self, record_type: str, file_name: str, data: bytes) -> dict[str, Any]:
        self._type(record_type)
        try:
            parsed = parse.parse_upload(file_name, data, record_type)
        except parse.UploadRefused as exc:
            raise DataFeedError(str(exc)) from exc
        header_problems = parse.check_headers(parsed, record_type)
        file_info = {"name": parsed.file_name, "size": parsed.size, "sha256": parsed.sha256,
                     "extension": parsed.extension}
        if header_problems:
            return self._save(record_type, "upload", [], file_info=file_info,
                              header_problems=header_problems, notes=parsed.notes)
        if not parsed.rows:
            raise DataFeedError("The file has no records below the header row.")
        return self._preview(record_type, "upload",
                             [(r["row_number"], r["values"]) for r in parsed.rows],
                             file_info=file_info, notes=parsed.notes)

    def validate_manual(self, record_type: str, records: list[dict[str, Any]],
                        method: str = "manual") -> dict[str, Any]:
        """Check records typed by hand, or ("map") results verified in Explore and Map."""
        self._type(record_type)
        if not records:
            raise DataFeedError("Add at least one record.")
        if len(records) > MAX_MANUAL_ROWS:
            raise DataFeedError(f"At most {MAX_MANUAL_ROWS} records at a time by hand; "
                                "use a spreadsheet for more.")
        by_key = {f.key: f for f in contract.fields(record_type)}
        rows = []
        for index, record in enumerate(records, 1):
            unknown = sorted(set(record) - set(by_key))
            if unknown:
                raise DataFeedError("Unknown fields: " + ", ".join(unknown))
            values = {by_key[k].header: str(v if v is not None else "") for k, v in record.items()}
            rows.append((index, values))
        return self._preview(record_type, method, rows)

    def _preview(self, record_type, method, rows, *, file_info=None, notes=None):
        vocab = self.vocabularies()
        checker = validate.RowChecker(record_type, vocab)
        results = [checker.check(number, values) for number, values in rows]
        matcher_notes: list[str] = list(notes or [])
        self._match(record_type, results, matcher_notes)
        validate.file_duplicates(record_type, results)
        backend = self._backend_check(record_type, method, results, file_info)
        if backend.get("message"):
            matcher_notes.append(backend["message"])
        return self._save(record_type, method, results, file_info=file_info,
                          notes=matcher_notes, backend=backend)

    def _match(self, record_type, results, notes) -> None:
        if self.connect is None:
            notes.append("Existing records could not be checked: no database is configured. "
                         "Review will check identity.")
            return
        try:
            with self.connect() as conn:
                matcher = matching.Matcher(conn)
                for result in results:
                    if result["errors"]:
                        continue
                    payload = result["payload"]
                    if record_type == "actor" and payload.get("parent_name"):
                        parent = matcher.parent(payload["parent_name"])
                        if parent.get("error"):
                            result["errors"].append(f"Row {result['row_number']}: "
                                                    f"{parent['error']}")
                            continue
                        payload["parent_connection"] = {
                            "relationship_type": payload.get("parent_relationship"),
                            "actor_id": parent["actor_id"], "confidence": "high"}
                        payload["parent_name"] = parent["name"]
                    if record_type == "person" and payload.get("affiliation"):
                        org = matcher.parent(payload["affiliation"])
                        if org.get("actor_id"):
                            payload["affiliation_actor_id"] = org["actor_id"]
                        else:
                            result["warnings"].append(
                                f"Row {result['row_number']}: the organization is not on the map "
                                "as written. A person is added only once their organization is "
                                "(add it with the Actors feed, or Discovery), so Review will hold "
                                "this record until then.")
                    result["match"] = getattr(matcher, record_type)(payload)
        except Exception as exc:  # noqa: BLE001 - say so; never guess a match
            notes.append("Existing records could not be checked just now "
                         f"({type(exc).__name__}). Review will check identity.")

    def _batch(self, record_type, method, results, file_info, *, import_name,
               uploaded_by=None, rows_invalid=0, admission="review",
               attestation=None) -> dict[str, Any]:
        return {
            "contract": BATCH_CONTRACT, "template_version": contract.TEMPLATE_VERSION,
            "record_type": record_type, "method": method, "import_name": import_name,
            "file_name": (file_info or {}).get("name"),
            "file_sha256": (file_info or {}).get("sha256"), "uploaded_by": uploaded_by,
            "admission": admission, "attestation": attestation or {},
            "submitted_at": datetime.now(UTC).isoformat(),
            "rows_total": len(results), "rows_invalid": rows_invalid,
            "rows": [{"row_number": r["row_number"], "payload": r["payload"],
                      "original": r["values"], "match": r.get("match") or {"kind": "new"},
                      "warnings": r["warnings"]} for r in results],
        }

    def _backend_check(self, record_type, method, results, file_info) -> dict[str, Any]:
        valid = [r for r in results if not r["errors"]]
        if not valid:
            return {"checked": False}
        if not self.bridge.configured:
            return {"checked": False, "message": "The backend's own checks run when the "
                    "records are confirmed: staging is not configured here."}
        try:
            answer = self.bridge.check(self._batch(record_type, method, valid, file_info,
                                                   import_name="Preview"))
        except DataFeedBridgeError as exc:
            return {"checked": False, "message": f"The backend could not check the records: {exc}"}
        by_row = {r["row_number"]: r for r in answer.get("rows") or []}
        for result in valid:
            checked = by_row.get(result["row_number"]) or {}
            prefix = f"Row {result['row_number']}: "
            result["errors"] += [prefix + e for e in checked.get("errors") or []
                                 if not e.startswith("Same record as row")]
            result["warnings"] += [prefix + w for w in checked.get("warnings") or []]
            result["backend_outcome"] = checked.get("outcome")
        return {"checked": True, "already_imported_run_id": answer.get("already_imported_run_id")}

    # ------------------------------------------------------------------ previews
    def _save(self, record_type, method, results, *, file_info=None, header_problems=None,
              notes=None, backend=None) -> dict[str, Any]:
        rows = []
        for result in results:
            match = result.get("match") or {"kind": "new"}
            if result["errors"]:
                status = "invalid"
            elif result.get("backend_outcome") == "already_awaiting_review":
                status = "waiting"
            else:
                status = {"existing": "existing", "possible": "possible"}.get(match["kind"], "new")
            rows.append({"row_number": result["row_number"], "status": status,
                         "errors": result["errors"], "warnings": result["warnings"],
                         "missing": result["missing"], "match": match,
                         "payload": result["payload"], "values": result["values"]})
        counts = {
            "total": len(rows),
            "valid": sum(r["status"] != "invalid" for r in rows),
            "needs_correction": sum(r["status"] == "invalid" for r in rows),
            "possible_duplicates": sum(r["status"] == "possible" for r in rows),
            "existing_matches": sum(r["status"] == "existing" for r in rows),
            "new": sum(r["status"] == "new" for r in rows),
            "already_waiting": sum(r["status"] == "waiting" for r in rows),
            "missing_optional": sum(bool(r["missing"]) for r in rows if r["status"] != "invalid"),
        }
        backend = backend or {}
        stageable = counts["valid"] - counts["already_waiting"]
        preview = {
            "preview_id": uuid.uuid4().hex, "record_type": record_type, "method": method,
            "template_version": contract.TEMPLATE_VERSION, "file": file_info,
            "created_at": datetime.now(UTC).isoformat(),
            "header_problems": header_problems or [], "notes": notes or [],
            "counts": counts, "rows": rows,
            "already_imported_run_id": backend.get("already_imported_run_id"),
            "backend_checked": bool(backend.get("checked")),
            "staging_configured": self.bridge.configured,
            "can_confirm": bool(not header_problems and stageable > 0 and self.bridge.configured
                                and not backend.get("already_imported_run_id")),
        }
        self._store(preview)
        return preview

    def _path(self, preview_id: str) -> Path:
        if not _PREVIEW_ID.match(preview_id or ""):
            raise DataFeedError("Unknown preview.")
        return self.preview_dir / f"{preview_id}.json"

    def _store(self, preview: dict[str, Any]) -> None:
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        now = time.time()
        for old in self.preview_dir.glob("*.json"):
            if now - old.stat().st_mtime > PREVIEW_TTL:
                old.unlink(missing_ok=True)
        self._path(preview["preview_id"]).write_text(
            json.dumps(preview, ensure_ascii=False, default=str), encoding="utf-8")

    def preview(self, preview_id: str) -> dict[str, Any]:
        path = self._path(preview_id)
        if not path.is_file() or time.time() - path.stat().st_mtime > PREVIEW_TTL:
            raise DataFeedError("This preview has expired. Check the file again.")
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ confirm
    def confirm(self, preview_id: str, *, import_name: str, accept_left_out: bool,
                uploaded_by: str | None = None, attest_source: bool = False,
                admission: str = "review", attest_authorized: bool = False) -> dict[str, Any]:
        """Send a checked preview, after the uploader's confirmation.

        Every import names its uploader and confirms the records come from a
        GHUS source. "verified" (organizations only) also needs the uploader's
        attestation that they are authorized GHUS staff verifying them: new
        actors are then admitted Verified through the approved admission path,
        labelled as an import; the rest wait in Review.
        """
        preview = self.preview(preview_id)
        name = " ".join(str(import_name or "").split())
        if not 1 <= len(name) <= 120:
            raise DataFeedError("Give the import a name (up to 120 characters).")
        uploader = " ".join(str(uploaded_by or "").split())
        if not 1 <= len(uploader) <= 120:
            raise DataFeedError("Give your name: every import records who sent it.")
        if not attest_source:
            raise DataFeedError("Confirm that these records come from a GHUS source.")
        if admission not in ("review", "verified"):
            raise DataFeedError("Choose Review or Verified.")
        if admission == "verified":
            if preview["record_type"] != "actor":
                raise DataFeedError("Only organizations can be imported as Verified; events and "
                                    "people go to Review.")
            if not attest_authorized:
                raise DataFeedError("Importing as Verified needs your confirmation that you are "
                                    "authorized GHUS staff verifying these records.")
        if preview["header_problems"]:
            raise DataFeedError("Fix the file's columns and check it again.")
        if not preview["can_confirm"]:
            raise DataFeedError("There is nothing in this preview that can be sent to Review.")
        invalid = preview["counts"]["needs_correction"]
        if invalid and not accept_left_out:
            raise DataFeedError(f"{invalid} record(s) need correction and would be left out. "
                                "Confirm that, or correct the file and check it again.")
        send = [r for r in preview["rows"] if r["status"] not in ("invalid",)]
        results = [{"row_number": r["row_number"], "payload": r["payload"], "values": r["values"],
                    "match": r["match"], "warnings": r["warnings"]} for r in send]
        batch = self._batch(
            preview["record_type"], preview["method"], results, preview["file"],
            import_name=name, uploaded_by=uploader, rows_invalid=invalid, admission=admission,
            attestation={"source": True, "authorized": bool(attest_authorized and
                                                              admission == "verified"),
                         "text": ATTESTATIONS["map" if preview["method"] == "map"
                                              else "verified" if admission == "verified"
                                              else "source"]})
        batch["rows_total"] = preview["counts"]["total"]
        try:
            outcome = self.bridge.stage(batch)
        except DataFeedBridgeError as exc:
            raise DataFeedError(str(exc)) from exc
        self._path(preview_id).unlink(missing_ok=True)
        rows = outcome.get("rows") or []
        admitted = outcome.get("admissions") or []
        return {"status": outcome.get("status"), "run_id": outcome.get("run_id"),
                "import_name": name, "staged": outcome.get("staged", 0),
                "already_awaiting_review": outcome.get("already_awaiting_review", 0),
                "left_out": invalid, "admission": admission, "uploaded_by": uploader,
                "verified": sum(a.get("outcome") == "approved_verified" for a in admitted),
                "held_for_review": [a for a in admitted if a.get("outcome") != "approved_verified"],
                "rows": [{"row_number": r.get("row_number"), "outcome": r.get("outcome")}
                         for r in rows]}

    # ------------------------------------------------------------------ history
    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        if self.connect is None:
            return []
        with self.connect() as conn:
            rows = conn.execute(HISTORY_SQL, (limit,)).fetchall()
        out = []
        for r in rows:
            meta, stats = r[3] or {}, r[4] or {}
            counts = {"pending": r[5], "approved_new": r[6], "matched_existing": r[7],
                      "rejected": r[8], "deferred": r[9]}
            pending = counts["pending"] + counts["deferred"]
            decided = counts["approved_new"] + counts["matched_existing"] + counts["rejected"]
            out.append({
                "run_id": r[0], "record_type": r[1], "uploaded_at": r[2].isoformat()
                if r[2] else None, "import_name": meta.get("import_name"),
                "method": meta.get("method"), "file_name": meta.get("file_name"),
                "uploaded_by": meta.get("uploaded_by"),
                "admission": meta.get("admission") or "review",
                "rows_total": stats.get("rows_total"), "rows_invalid": stats.get("rows_invalid"),
                "staged": stats.get("staged"),
                "already_awaiting_review": stats.get("already_awaiting_review"),
                "counts": counts,
                "status": ("Awaiting Review" if pending and not decided
                           else "Partly reviewed" if pending else "Reviewed"),
                "light_pull_read": r[10],
            })
        return out

    def import_records(self, run_id: str) -> list[dict[str, Any]]:
        if not _UUID.match(run_id or "") or self.connect is None:
            raise DataFeedError("Unknown import.")
        with self.connect() as conn:
            rows = conn.execute(RECORDS_SQL, {"run": run_id}).fetchall()
        labels = {"pending": "Awaiting Review", "deferred": "Deferred in Review",
                  "rejected": "Rejected", "superseded": "Superseded",
                  "new": "Approved and inserted", "same_existing": "Matched to existing record",
                  "imported_verified": "Added to the map as Verified (import)"}
        return [{"row_number": r[0], "name": r[1], "status": labels.get(
            r[3] if r[2] == "approved" and r[3] else r[2], r[2]), "entity_id": r[4],
            "light_pull_read": bool(r[5])} for r in rows]

    # ------------------------------------------------------------------ completion
    def completion_estimate(self, run_id: str) -> dict[str, Any]:
        self._actor_import(run_id)
        try:
            return self.bridge.completion_estimate(run_id)
        except DataFeedBridgeError as exc:
            raise DataFeedError(str(exc)) from exc

    def start_completion(self, run_id: str, *, max_usd: float, confirmed: bool) -> dict[str, Any]:
        self._actor_import(run_id)
        if not confirmed:
            raise DataFeedError("Confirm the expected cost first.")
        if not 0 < max_usd <= 5:
            raise DataFeedError("The spending cap must be between $0.01 and $5.00.")
        estimate = self.completion_estimate(run_id)
        if not estimate.get("organisations"):
            raise DataFeedError("Every record of this import already has all its boxes.")
        log = self.runs_dir / f"{run_id}.log"
        try:
            pid = self.bridge.start_completion(run_id, max_usd, log)
        except DataFeedBridgeError as exc:
            raise DataFeedError(str(exc)) from exc
        return {"started": True, "pid": pid, "organisations": len(estimate["organisations"]),
                "max_usd": max_usd}

    def _actor_import(self, run_id: str) -> None:
        if not _UUID.match(run_id or "") or self.connect is None:
            raise DataFeedError("Unknown import.")
        with self.connect() as conn:
            row = conn.execute("SELECT entity_type FROM scrape_run WHERE run_id = %s::uuid "
                               "AND source_name = 'ghus_data_feed'", (run_id,)).fetchone()
        if row is None:
            raise DataFeedError("Unknown import.")
        if row[0] != "actor":
            raise DataFeedError("Completing missing information uses the Light Pull reader, "
                                "which reads organizations. People and events are completed "
                                "in Review.")

    @staticmethod
    def _type(record_type: str) -> None:
        if record_type not in contract.RECORD_TYPES:
            raise DataFeedError("Choose Actors, People or Events.")


# Per import: what Review has done with its records. Read only.
HISTORY_SQL = """
WITH runs AS (
    SELECT run_id, entity_type, started_at, config->'datafeed' AS meta, stats->'datafeed' AS stats
    FROM scrape_run WHERE source_name = 'ghus_data_feed' AND status = 'succeeded'
    ORDER BY started_at DESC LIMIT %s),
items AS (
    SELECT c.run_id, c.candidate_id AS id, c.review_status::text AS status, 'search_candidate' AS t,
           (c.record_preview ? 'light_pull_read') AS read
    FROM search_candidate c JOIN runs USING (run_id)
    UNION ALL
    SELECT s.run_id, q.event_review_id, q.status, 'event_review_queue', false
    FROM event_review_queue q JOIN staged_record s USING (staged_record_id) JOIN runs USING (run_id)
    UNION ALL
    SELECT s.run_id, q.person_review_id, q.status, 'person_review_queue', false
    FROM person_review_queue q JOIN staged_record s ON s.staged_record_id = q.staged_record_id
    JOIN runs ON runs.run_id = s.run_id),
decided AS (
    SELECT i.*, d.decision_kind FROM items i
    LEFT JOIN LATERAL (SELECT decision_kind FROM review_admission_decision d
                       WHERE d.source_row_id = i.id AND d.source_table = i.t
                       ORDER BY decided_at DESC LIMIT 1) d ON true)
SELECT r.run_id::text, r.entity_type, r.started_at, r.meta, r.stats,
       count(*) FILTER (WHERE d.status = 'pending'),
       count(*) FILTER (WHERE d.status = 'approved' AND d.decision_kind = 'new'),
       count(*) FILTER (WHERE d.status = 'approved' AND d.decision_kind = 'same_existing'),
       count(*) FILTER (WHERE d.status = 'rejected'),
       count(*) FILTER (WHERE d.status = 'deferred'),
       count(*) FILTER (WHERE d.read)
FROM runs r LEFT JOIN decided d ON d.run_id = r.run_id
GROUP BY 1, 2, 3, 4, 5 ORDER BY r.started_at DESC
"""

RECORDS_SQL = """
WITH items AS (
    SELECT (c.record_preview->'data_feed'->>'row_number')::int AS row_number,
           c.record_preview->>'name' AS name, c.review_status::text AS status,
           c.candidate_id AS id, 'search_candidate' AS t,
           c.record_preview ? 'light_pull_read' AS read
    FROM search_candidate c WHERE c.run_id = %(run)s::uuid
    UNION ALL
    SELECT (s.normalized_payload->'data_feed'->>'row_number')::int, s.normalized_payload->>'name',
           q.status, q.event_review_id, 'event_review_queue', false
    FROM event_review_queue q JOIN staged_record s USING (staged_record_id)
    WHERE s.run_id = %(run)s::uuid
    UNION ALL
    SELECT (s.normalized_payload->'data_feed'->>'row_number')::int, s.normalized_payload->>'name',
           q.status, q.person_review_id, 'person_review_queue', false
    FROM person_review_queue q JOIN staged_record s ON s.staged_record_id = q.staged_record_id
    WHERE s.run_id = %(run)s::uuid)
SELECT i.row_number, i.name, i.status,
       CASE WHEN d.notes LIKE 'Data Feed import admitted as Verified%%' THEN 'imported_verified'
            ELSE d.decision_kind END,
       COALESCE(d.target_entity_id::text, d.outcome->>'canonical_entity_id'), i.read
FROM items i
LEFT JOIN LATERAL (SELECT decision_kind, target_entity_id, outcome, notes FROM review_admission_decision d
                   WHERE d.source_row_id = i.id AND d.source_table = i.t
                   ORDER BY decided_at DESC LIMIT 1) d ON true
ORDER BY 1
"""
