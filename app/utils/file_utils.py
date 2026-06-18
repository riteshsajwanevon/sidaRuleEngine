# -*- coding: utf-8 -*-
"""File utilities for the DXF validation endpoint."""

from __future__ import annotations

from pathlib import Path

ALLOWED_EXTENSIONS = {".dxf"}


def validate_extension(filename: str) -> str:
    """Return lowercase extension or raise ValueError if not allowed."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    return ext


def safe_stem(filename: str) -> str:
    """Return the filename stem, sanitized for use in paths and reports."""
    stem = Path(filename).stem
    return "".join(c if c.isalnum() or c in "-_ " else "_" for c in stem).strip()
