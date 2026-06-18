# -*- coding: utf-8 -*-
"""
Pydantic Schemas
----------------
Request and response models for POST /process-validate-dxf.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    status: str = Field("error")
    message: str
