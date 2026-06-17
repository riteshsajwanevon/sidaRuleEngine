# -*- coding: utf-8 -*-
"""
Validate Router  —  POST /validate
------------------------------------
Loads the CSV for a given job_id, applies New_JSON rules, and returns
a structured validation report.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.models.schemas import ValidateRequest
from app.services.validation_service import run_validation_for_job
from app.utils.file_utils import OUTPUTS_DIR

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/validate",
    summary="Validate a processed DXF job against building rules",
    response_description="Validation report with PASS/FAIL status",
    responses={
        200: {"description": "Validation completed (PASS or FAIL)"},
        400: {"description": "Missing or invalid input"},
        404: {"description": "Job ID not found"},
        500: {"description": "Internal validation error"},
    },
)
async def validate_job(request: ValidateRequest):
    """
    Validate a previously uploaded and processed DXF file.

    Loads the CSV associated with **job_id**, derives all architectural metrics,
    matches the applicable rule from **New_rules.json**, and runs all checks.

    Returns a detailed report with passed and failed checks.
    """
    # --- Input validation ---
    if not request.job_id or not request.job_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "error", "message": "job_id is required."},
        )
    if not request.area_type or not request.area_type.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "error", "message": "area_type is required."},
        )
    if not request.location or not request.location.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "error", "message": "location is required."},
        )

    # --- Locate CSV for this job ---
    job_dir = OUTPUTS_DIR / request.job_id
    if not job_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "status": "error",
                "message": f"No job found with id '{request.job_id}'. "
                           "Please upload a DXF file first.",
            },
        )

    csv_files = list(job_dir.glob("*.csv"))
    if not csv_files:
        status_file = job_dir / "status.json"
        if status_file.exists():
            try:
                job_status = json.loads(status_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                job_status = {"status": "processing"}
            if job_status.get("status") == "failed":
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "status": "failed",
                        "message": job_status.get("message", "DXF processing failed."),
                    },
                )
            raise HTTPException(
                status_code=status.HTTP_202_ACCEPTED,
                detail={
                    "status": "processing",
                    "message": f"Job '{request.job_id}' is still processing. Please try again shortly.",
                },
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "status": "error",
                "message": f"No CSV found for job '{request.job_id}'. "
                           "The DXF may not have been processed successfully.",
            },
        )

    csv_path = str(csv_files[0])  # one CSV per job

    # --- Run validation pipeline ---
    try:
        result = run_validation_for_job(
            csv_path=csv_path,
            area_type=request.area_type,
            location=request.location,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "error", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Validation failed for job %s", request.job_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": f"Validation error: {exc}"},
        ) from exc

    # --- Build response ---
    validation_status = result["validation_status"]
    response_body: dict = {
        "job_id": request.job_id,
        "status": "success",
        "validation_status": validation_status,
        "report": result["report"],
    }

    if validation_status == "FAIL":
        response_body["errors"] = result.get("errors", [])

    logger.info(
        "Validation complete for job %s — %s (%d failures)",
        request.job_id,
        validation_status,
        len(result.get("errors", [])),
    )

    return JSONResponse(status_code=status.HTTP_200_OK, content=response_body)
