# -*- coding: utf-8 -*-
"""
Application Configuration
--------------------------
Reads settings from environment variables (.env via python-dotenv).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).parent.parent
load_dotenv(_BACKEND_DIR / ".env", override=False)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
_raw_origins = os.getenv("CORS_ORIGINS", "*")
CORS_ORIGINS: list[str] = (
    ["*"] if _raw_origins.strip() == "*"
    else [o.strip() for o in _raw_origins.split(",") if o.strip()]
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
