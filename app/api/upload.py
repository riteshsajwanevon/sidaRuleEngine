# -*- coding: utf-8 -*-
"""DXF processing routes."""

from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.services.dxf_parser import parse_dxf_to_cad_model
from app.services.validation_service import run_validation_from_cad_model
from app.utils.file_utils import safe_stem, validate_extension

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/process-validate-dxf",
    summary="Validate a DXF file against request-body rules",
    responses={
        200: {"description": "Validation completed"},
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
        # DXF → CADModel (single pass, no CSV)
        t1 = time.perf_counter()
        cad_model = await run_in_threadpool(parse_dxf_to_cad_model, file.file)
        print(cad_model)
        logger.info(
            "DXF parse → CADModel: %.2fs  (%d entities)",
            time.perf_counter() - t1,
            len(cad_model.entities),
        )

        # CADModel → metrics → validation
        t2 = time.perf_counter()
        result = await run_in_threadpool(
            run_validation_from_cad_model,
            cad_model,
            rules,
            stem,
        )
        logger.info("Validation: %.2fs", time.perf_counter() - t2)
        logger.info("Total processing: %.2fs", time.perf_counter() - t0)

    except ValueError as exc:
        logger.exception("DXF processing/validation failed for %s", file.filename)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "error", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error processing %s", file.filename)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": f"Failed to process DXF: {exc}"},
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
