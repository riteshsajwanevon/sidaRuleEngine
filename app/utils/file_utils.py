# -*- coding: utf-8 -*-
"""
File Utilities
--------------
Helpers for file handling, job ID management, and path resolution.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from app.config import OUTPUTS_DIR, REPORTS_DIR, UPLOADS_DIR  # noqa: F401 — re-exported

# ---------------------------------------------------------------------------
# Base directories  (resolved from config / .env)
# ---------------------------------------------------------------------------
# UPLOADS_DIR, OUTPUTS_DIR, REPORTS_DIR are imported from config and
# re-exported here so the rest of the codebase can keep importing from
# app.utils.file_utils without change.


def ensure_dirs() -> None:
    """Create all required directories if they don't exist."""
    for d in (UPLOADS_DIR, OUTPUTS_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Job ID helpers
# ---------------------------------------------------------------------------

def generate_job_id() -> str:
    """Generate a new unique job ID."""
    return str(uuid.uuid4())


def get_upload_path(job_id: str, filename: str) -> Path:
    """Return the full path for an uploaded file."""
    ensure_dirs()
    return UPLOADS_DIR / job_id / filename


def get_csv_path(job_id: str, stem: str) -> Path:
    """Return the full path for a generated CSV file."""
    ensure_dirs()
    return OUTPUTS_DIR / job_id / f"{stem}.csv"


def get_report_path(job_id: str, stem: str) -> Path:
    """Return the full path for a generated report file."""
    ensure_dirs()
    return REPORTS_DIR / job_id / f"{stem}_report.json"


# ---------------------------------------------------------------------------
# File type helpers
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {".dxf", ".dwg"}


def validate_extension(filename: str) -> str:
    """
    Return the lowercase extension of *filename*.

    Raises:
        ValueError: If the extension is not in ALLOWED_EXTENSIONS.
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    return ext


def safe_stem(filename: str) -> str:
    """Return the file stem (name without extension), sanitized."""
    stem = Path(filename).stem
    # Replace characters that are unsafe in file paths
    return "".join(c if c.isalnum() or c in "-_ " else "_" for c in stem).strip()
