# -*- coding: utf-8 -*-
"""
Application Configuration
--------------------------
Reads settings from environment variables (populated from .env via python-dotenv).
All other modules import from here — never read os.environ directly.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the backend root (one level above this file's package)
_BACKEND_DIR = Path(__file__).parent.parent
load_dotenv(_BACKEND_DIR / ".env", override=False)  # override=False: real env vars win


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

# ---------------------------------------------------------------------------
# Rules file
# ---------------------------------------------------------------------------
_rules_env = os.getenv("RULES_PATH", "").strip()
RULES_PATH: str | None = _rules_env if _rules_env else None

# Default: backend/New_rules.json
DEFAULT_RULES_PATH: Path = _BACKEND_DIR / "New_rules.json"

# ---------------------------------------------------------------------------
# Storage directories
# ---------------------------------------------------------------------------
_APP_DIR = _BACKEND_DIR / "app"

def _resolve_dir(env_key: str, default: Path) -> Path:
    raw = os.getenv(env_key, "").strip()
    return Path(raw) if raw else default

UPLOADS_DIR: Path = _resolve_dir("UPLOADS_DIR", _APP_DIR / "uploads")
OUTPUTS_DIR: Path = _resolve_dir("OUTPUTS_DIR", _APP_DIR / "outputs")
REPORTS_DIR: Path = _resolve_dir("REPORTS_DIR", _APP_DIR / "reports")
