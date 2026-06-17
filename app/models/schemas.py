# -*- coding: utf-8 -*-
"""
Pydantic Schemas
----------------
Request and response models for all API endpoints.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Upload endpoint  (POST /upload)
# ---------------------------------------------------------------------------

class UploadDXFResponse(BaseModel):
    """Successful DXF upload response."""
    job_id: str = Field(..., description="Unique job identifier (UUID)")
    status: str = Field("converted", description="Processing status")
    csv_path: str = Field(..., description="Path to the generated CSV file")
    available_area_types: list[str] = Field(
        ..., description="Area types available in the rule set"
    )
    available_locations: list[str] = Field(
        ..., description="Locations available in the rule set"
    )


class UploadDWGResponse(BaseModel):
    """DWG upload response (conversion pending)."""
    status: str = Field("pending_conversion", description="Processing status")
    message: str = Field(
        "DWG conversion will be implemented later.",
        description="Informational message",
    )


class ErrorResponse(BaseModel):
    """Generic error response."""
    status: str = Field("error", description="Always 'error'")
    message: str = Field(..., description="Human-readable error description")


# ---------------------------------------------------------------------------
# Validate endpoint  (POST /validate)
# ---------------------------------------------------------------------------

class ValidateRequest(BaseModel):
    """Request body for POST /validate."""
    job_id: str = Field(..., description="Job ID returned by POST /upload")
    area_type: str = Field(
        ...,
        description=(
            "Building area type, e.g. 'Industrial Unit', "
            "'Cottage/Micro/Household', 'Industrial Flatted Units', 'IT Unit'"
        ),
    )
    location: str = Field(
        ...,
        description="Location type: 'Urban' or 'Rural'",
    )


class FetchedDetail(BaseModel):
    """A single extracted CAD metric."""
    label: str
    value: Any
    unit: str


class ValidationReport(BaseModel):
    """Structured validation report."""
    file_name: str
    fetched_details: list[FetchedDetail]
    passed_checks: list[str]
    failed_checks: list[str]
    validation_status: str


class ValidatePassResponse(BaseModel):
    """Validation passed response."""
    job_id: str
    status: str = Field("success")
    validation_status: str = Field("PASS")
    report: ValidationReport


class ValidateFailResponse(BaseModel):
    """Validation failed response."""
    job_id: str
    status: str = Field("success")
    validation_status: str = Field("FAIL")
    report: ValidationReport
    errors: list[str]
