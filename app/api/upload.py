# -*- coding: utf-8 -*-
"""DXF processing routes."""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path
import time

from fastapi import APIRouter, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from app.services.dxf_service import dxf_to_csv_file, dxf_to_csv_text
from app.services.validation_service import run_inline_rule_validation_for_csv_text
from app.utils.file_utils import safe_stem, validate_extension

logger = logging.getLogger(__name__)
router = APIRouter()


def _save_file(file: UploadFile, destination: Path) -> None:
    """Blocking file save, called via run_in_threadpool."""
    with destination.open("wb") as buf:
        shutil.copyfileobj(file.file, buf, length=1024 * 1024)


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


@router.post(
    "/process-validate-dxf",
    summary="Convert a DXF file and validate it against request-body rules",
    responses={
        200: {"description": "DXF processed and validation completed"},
        400: {"description": "Unsupported file type, invalid rules, or invalid DXF"},
        422: {"description": "No file or rule_json provided"},
        500: {"description": "Internal processing or validation error"},
    },
)
async def process_validate_dxf(
    file: UploadFile,
    rule_json: str = Form(...),
):
    t0 = time.perf_counter()
    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"status": "error", "message": "No file provided."},
        )

    try:
        validate_extension(file.filename)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "error", "message": str(exc)},
        ) from exc

   
    try:
        rules = json.loads(rule_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "error", "message": f"Invalid rule_json: {exc.msg}"},
        ) from exc

    if not isinstance(rules, list) or not rules:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "error", "message": "rule_json must be a non-empty JSON array."},
        )

    stem = safe_stem(file.filename)

    try:
        
        csv_text = await run_in_threadpool(dxf_to_csv_text, file.file)
        logger.info("Processing dxf to csv  %s ", round(time.perf_counter() - t0, 2))
        result = await run_in_threadpool(
            run_inline_rule_validation_for_csv_text,
            csv_text,
            rules,
            stem,
        )
        logger.info("Result of validation  %s ", round(time.perf_counter() - t0, 2))
    except ValueError as exc:
        logger.exception("DXF processing/validation failed for uploaded file %s", file.filename)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "error", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to process and validate uploaded DXF file %s", file.filename)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": f"Failed to process and validate DXF: {exc}"},
        ) from exc
    finally:
        await file.close()

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "success",
            "file_name": file.filename,
            **result,
        },
    )
