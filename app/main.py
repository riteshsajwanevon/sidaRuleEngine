# -*- coding: utf-8 -*-
"""
SIDA FastAPI Application
------------------------
Entry point for the AutoCAD DXF validation backend.

Run with:
    uvicorn app.main:app --reload

Swagger UI:  http://127.0.0.1:8000/docs
ReDoc:       http://127.0.0.1:8000/redoc
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.upload import router as upload_router
from app.config import CORS_ORIGINS, LOG_LEVEL

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SIDA — AutoCAD DXF Validation API",
    description=(
        "Parses AutoCAD DXF files, extracts architectural metrics, "
        "and validates them against building rules."
    ),
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router, tags=["validate"])


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "An unexpected error occurred."},
    )


@app.get("/health", tags=["health"], summary="Health check")
async def health():
    return {"status": "ok", "service": "SIDA DXF Validation API"}
