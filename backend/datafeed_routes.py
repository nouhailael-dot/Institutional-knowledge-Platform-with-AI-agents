"""HTTP routes of the Data Feed page.

Checking a file or a form is read-only. Staging happens only on
``POST /api/datafeed/previews/{id}/confirm``, and the Light Pull completion
only on ``POST /api/datafeed/imports/{id}/complete`` with the cost confirmed:
both are a person's explicit dispatch, carried out by the GHUS backend.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.datafeed.parse import MAX_BYTES
from src.datafeed.service import DataFeedError, DataFeedService

router = APIRouter(prefix="/api/datafeed", tags=["datafeed"])


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
    # Who sends it, as they type it (there is no sign-in yet), and what they confirm.
    uploaded_by: str = Field(default="", max_length=120)
    attest_source: bool = False
    admission: str = "review"
    attest_authorized: bool = False


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
                 accept_left_out=body.accept_left_out, uploaded_by=body.uploaded_by,
                 attest_source=body.attest_source, admission=body.admission,
                 attest_authorized=body.attest_authorized)


@router.get("/history")
def history():
    return {"imports": _call(datafeed_service().history)}


@router.get("/imports/{run_id}")
def import_records(run_id: str):
    return {"records": _call(datafeed_service().import_records, run_id)}


@router.post("/imports/{run_id}/estimate")
def completion_estimate(run_id: str):
    return _call(datafeed_service().completion_estimate, run_id)


@router.post("/imports/{run_id}/complete")
def complete(run_id: str, body: Completion):
    return _call(datafeed_service().start_completion, run_id, max_usd=body.max_usd,
                 confirmed=body.confirmed)
