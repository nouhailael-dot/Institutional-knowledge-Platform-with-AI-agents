"""HTTP routes of the Data Feed page.

Checking a file or a form is read-only. Staging happens only on
``POST /api/datafeed/previews/{id}/confirm``, and the Light Pull completion
only on ``POST /api/datafeed/imports/{id}/complete`` with the cost confirmed:
both are a person's explicit dispatch, carried out by the GHUS backend.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.datafeed.parse import MAX_BYTES
from src.datafeed.service import XLSX, DataFeedError, DataFeedService
from src.identity import current_user

router = APIRouter(prefix="/api/datafeed", tags=["datafeed"])
logger = logging.getLogger(__name__)
# The last Import History read from the database, shown when it cannot be reached.
_last_history: list[dict[str, Any]] | None = None


@lru_cache(maxsize=1)
def datafeed_service() -> DataFeedService:
    return DataFeedService()


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DataFeedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ManualRecords(BaseModel):
    record_type: str
    records: list[dict[str, Any]] = Field(default_factory=list, max_length=50)


class Confirmation(BaseModel):
    import_name: str = Field(min_length=1, max_length=120)
    accept_left_out: bool = False
    # Ignored: who sends it is the current user (src.identity). What they confirm stays theirs.
    uploaded_by: str = Field(default="", max_length=120)
    attest_source: bool = False
    admission: str = "directory"
    attest_authorized: bool = False
    # "Complete information with AI enrichment" (5 Nov 2026): the uploader's choice.
    ai_enrichment: bool = False


class Completion(BaseModel):
    max_usd: float = Field(gt=0, le=5)
    confirmed: bool = False


@router.get("/catalog")
def catalog():
    return datafeed_service().catalog()


@router.get("/templates/{record_type}.{extension}")
def template(record_type: str, extension: str):
    data, name, media = _call(datafeed_service().template, record_type, extension)
    return Response(content=data, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "Cache-Control": "no-store"})


@router.post("/validate")
def validate_upload(record_type: str = Form(...), file: UploadFile = File(...)):
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="The file is larger than 5 MB.")
    return _call(datafeed_service().validate_upload, record_type, file.filename or "", data)


@router.post("/validate-manual")
def validate_manual(body: ManualRecords):
    return _call(datafeed_service().validate_manual, body.record_type, body.records)


@router.get("/previews/{preview_id}")
def preview(preview_id: str):
    return _call(datafeed_service().preview, preview_id)


@router.post("/previews/{preview_id}/confirm")
def confirm(preview_id: str, body: Confirmation):
    return _call(datafeed_service().confirm, preview_id, import_name=body.import_name,
                 accept_left_out=body.accept_left_out, uploaded_by=current_user(),
                 attest_source=body.attest_source, admission=body.admission,
                 attest_authorized=body.attest_authorized, ai_enrichment=body.ai_enrichment)


@router.get("/history")
def history():
    """Import History; never an error page when the database is slow to answer.

    5 Nov 2026: a connection timeout to the shared database turned the whole
    tab into "Something went wrong". Now the last list read is shown (or none,
    so the page shows its example import) with ``unavailable`` set.
    """
    global _last_history
    try:
        imports = _call(datafeed_service().history)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - database unreachable: show what we have
        logger.warning("Import History could not be read from the database", exc_info=True)
        return {"imports": list(_last_history or []), "unavailable": True}
    _last_history = imports
    return {"imports": imports}


@router.get("/example-import.xlsx")
def example_import():
    """The Excel file of Import history's example card (never real data)."""
    data, name = _call(datafeed_service().example_file)
    return Response(content=data, media_type=XLSX, headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/imports/{run_id}")
def import_records(run_id: str):
    return {"records": _call(datafeed_service().import_records, run_id)}


@router.get("/imports/{run_id}/file")
def original_file(run_id: str):
    """The file as it was uploaded, for Import history."""
    path = datafeed_service().original_file(run_id)
    if path is None:
        raise HTTPException(status_code=404, detail="The original file is not kept on this computer.")
    name = path.name.split("__", 1)[1].replace('"', "")  # "<run or sha-fingerprint>__<name>"
    return Response(content=path.read_bytes(), media_type="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.post("/imports/{run_id}/withdraw")
def withdraw(run_id: str):
    """Take back an import so the same file can be uploaded again (13 Nov 2026)."""
    outcome = _call(datafeed_service().withdraw, run_id, by=current_user())
    # Its records were rejected in the database; the Review page's own copy is
    # told here, since its sync never drops a record that leaves the source.
    from backend.app import review_store

    outcome["left_review"] = review_store().retire_run(f"datafeed:{run_id}")
    return outcome


@router.post("/imports/{run_id}/estimate")
def completion_estimate(run_id: str):
    return _call(datafeed_service().completion_estimate, run_id)


@router.post("/imports/{run_id}/complete")
def complete(run_id: str, body: Completion):
    return _call(datafeed_service().start_completion, run_id, max_usd=body.max_usd,
                 confirmed=body.confirmed)
