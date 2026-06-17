# -*- coding: utf-8 -*-
"""
Upload Router  —  POST /upload
-------------------------------
Accepts .dxf or .dwg files.

DXF workflow:
  1. Save uploaded file to disk immediately (fast — just I/O)
  2. Return 202 + job_id to the client right away
  3. Parse DXF → CSV in a background thread (reads from saved path, not request)
  4. Client polls GET /upload/status/{job_id} until status == "converted"

DWG workflow:
  - Store file, return pending_conversion status
"""

from __future__ import annotations
from datetime import datetime
import json
import logging
import shutil
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from app.services.dxf_service import dxf_to_csv_file
from app.utils.file_utils import (
    OUTPUTS_DIR,
    generate_job_id,
    get_csv_path,
    get_upload_path,
    safe_stem,
    validate_extension,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Status helpers  (written to outputs/<job_id>/status.json)
# ---------------------------------------------------------------------------

def _status_path(job_id: str) -> Path:
    return OUTPUTS_DIR / job_id / "status.json"


def _write_status(job_id: str, payload: dict) -> None:
    path = _status_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_status(job_id: str) -> dict | None:
    path = _status_path(job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Background worker  — reads from saved file path, never from request object
# ---------------------------------------------------------------------------

def _process_dxf(job_id: str, upload_path: Path, csv_path: Path) -> None:
    """Convert the saved DXF to CSV. Runs in a background thread."""
    _write_status(job_id, {"status": "processing"})
    t0 = time.perf_counter()

    try:
        dxf_to_csv_file(str(upload_path), str(csv_path))
    except Exception as exc:
        logger.exception("DXF processing failed for job %s", job_id)
        _write_status(job_id, {
            "status": "failed",
            "message": str(exc),
        })
        return

    elapsed = round(time.perf_counter() - t0, 2)
    _write_status(job_id, {
        "status": "converted",
        "csv_path": str(csv_path),
        "processing_time_seconds": elapsed,
    })
    logger.info("DXF processed for job %s in %.2fs → %s", job_id, elapsed, csv_path)


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------

@router.post(
    "/upload",
    summary="Upload a DXF or DWG file",
    responses={
        202: {"description": "DXF accepted — processing in background"},
        200: {"description": "DWG received — conversion pending"},
        400: {"description": "Unsupported file type"},
        422: {"description": "No file provided"},
        500: {"description": "Failed to save file"},
    },
)
async def upload_file(file: UploadFile, background_tasks: BackgroundTasks):
    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"status": "error", "message": "No file provided."},
        )

    try:
        ext = validate_extension(file.filename)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "error", "message": str(exc)},
        ) from exc

    job_id = generate_job_id()
    stem = safe_stem(file.filename)
    upload_path = get_upload_path(job_id, file.filename)

    # --- Save file to disk first (always, for both DXF and DWG) ---
    try:
        upload_path.parent.mkdir(parents=True, exist_ok=True)
        await run_in_threadpool(_save_file, file, upload_path)
    except Exception as exc:
        logger.exception("Failed to save uploaded file for job %s", job_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": f"Failed to save file: {exc}"},
        ) from exc
    finally:
        await file.close()

    # --- DWG: just store, no conversion ---
    if ext == ".dwg":
        logger.info("DWG received for job %s", job_id)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "pending_conversion",
                "message": "DWG conversion will be implemented later.",
            },
        )

    # --- DXF: queue background conversion from saved path ---
    csv_path = get_csv_path(job_id, stem)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_status(job_id, {"status": "queued"})

    # Background task reads from upload_path (already on disk) — safe
    background_tasks.add_task(_process_dxf, job_id, upload_path, csv_path)

    logger.info("DXF upload accepted for job %s, queued for processing", job_id)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "job_id": job_id,
            "status": "processing",
        },
    )


def _save_file(file: UploadFile, destination: Path) -> None:
    """Blocking file save — called via run_in_threadpool."""
    with destination.open("wb") as buf:
        shutil.copyfileobj(file.file, buf, length=1024 * 1024)  # 1 MB chunks


# ---------------------------------------------------------------------------
# POST /parse-dxf  — convert DXF and return CSV directly
# ---------------------------------------------------------------------------

@router.post(
    "/parse-dxf",
    summary="Convert a DXF file to CSV and return it in the response",
    responses={
        200: {"description": "CSV generated successfully"},
        400: {"description": "Unsupported file type or invalid DXF"},
        422: {"description": "No file provided"},
    },
)
async def parse_dxf(file: UploadFile):
    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"status": "error", "message": "No file provided."},
        )

    ext = validate_extension(file.filename)
    

    if ext != ".dxf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "error", "message": "Only DXF files can be parsed to CSV."},
        )

    stem = safe_stem(file.filename)

    try:
        csv_text = await run_in_threadpool(_convert_uploaded_dxf_to_csv_text, file, stem)
    except ValueError as exc:
        logger.exception("DXF parsing failed for uploaded file %s", file.filename)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "error", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to parse uploaded DXF file %s", file.filename)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": f"Failed to parse DXF: {exc}"},
        ) from exc
    finally:
        await file.close()

    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'},
    )


def _convert_uploaded_dxf_to_csv_text(file: UploadFile, stem: str) -> str:
    with tempfile.TemporaryDirectory(prefix="sida-parse-dxf-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        dxf_path = tmp_path / f"{stem}.dxf"
        csv_path = tmp_path / f"{stem}.csv"

        _save_file(file, dxf_path)
        dxf_to_csv_file(str(dxf_path), str(csv_path))
        return csv_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# GET /upload/status/{job_id}
# ---------------------------------------------------------------------------

@router.get(
    "/upload/status/{job_id}",
    summary="Poll DXF processing status",
)
async def upload_status(job_id: str):
    job_dir = OUTPUTS_DIR / job_id

    if not job_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "error", "message": f"No job found with id '{job_id}'."},
        )

    state = _read_status(job_id)

    # If status file is missing but CSV exists, treat as converted
    if state is None or state.get("status") not in ("processing", "queued", "failed"):
        csv_files = list(job_dir.glob("*.csv"))
        if csv_files:
            return {"job_id": job_id, "status": "converted"}

    return {"job_id": job_id, **(state or {"status": "processing"})}


# ---------------------------------------------------------------------------
# GET /upload/csv/{job_id}  — download the extracted CSV
# ---------------------------------------------------------------------------

@router.get(
    "/upload/csv/{job_id}",
    summary="Download the extracted CSV for a processed job",
)
async def download_csv(job_id: str):
    job_dir = OUTPUTS_DIR / job_id

    if not job_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "error", "message": f"No job found with id '{job_id}'."},
        )

    csv_files = list(job_dir.glob("*.csv"))
    if not csv_files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "error", "message": "CSV not ready yet. Check status first."},
        )

    from fastapi.responses import FileResponse
    csv_file = csv_files[0]
    return FileResponse(
        path=str(csv_file),
        media_type="text/csv",
        filename=csv_file.name,
    )
