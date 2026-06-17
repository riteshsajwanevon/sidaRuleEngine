# -*- coding: utf-8 -*-
"""
SIDA FastAPI Application
------------------------
Entry point for the AutoCAD DXF validation backend.

Run with:
    uvicorn app.main:app --reload

Swagger UI:  http://127.0.0.1:8000/docs
ReDoc:       http://127.0.0.1:8000/redoc
OpenAPI:     http://127.0.0.1:8000/openapi.json
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.upload import router as upload_router
from app.api.validate import router as validate_router
from app.config import CORS_ORIGINS, LOG_LEVEL
from app.utils.file_utils import ensure_dirs

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SIDA — AutoCAD DXF Validation API",
    description=(
        "Processes AutoCAD DXF files, extracts architectural metrics, "
        "and validates them against SIDA building regulations (New_rules.json)."
    ),
    version="1.0.0",
    contact={
        "name": "SIDA Development Team",
    },
    license_info={
        "name": "Proprietary",
    },
    openapi_tags=[
        {
            "name": "upload",
            "description": "Upload DXF/DWG files and convert to CSV.",
        },
        {
            "name": "validate",
            "description": "Validate processed jobs against building rules.",
        },
    ],
)

# ---------------------------------------------------------------------------
# CORS  (adjust origins for production)
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(upload_router, tags=["upload"])
app.include_router(validate_router, tags=["validate"])

# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "An unexpected error occurred."},
    )

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    ensure_dirs()
    logger.info("SIDA API started — uploads/outputs/reports directories ready.")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["health"], summary="Health check")
async def health():
    """Returns 200 OK when the service is running."""
    return {"status": "ok", "service": "SIDA DXF Validation API"}
