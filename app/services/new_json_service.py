# -*- coding: utf-8 -*-
"""
New JSON Service
----------------
Loads and exposes the New_rules.json rule set.

Responsibilities:
  - Load New_rules.json (supports both JSON and Python-literal formats)
  - Provide available area_types and locations extracted from the rules
  - Expose the raw RULES list for use by validation_service

Original source: demo_sidaproject.py → RULES loading block,
                 location_matches(), area_type_matches(), get_applicable_rule()
"""

from __future__ import annotations

import ast
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import DEFAULT_RULES_PATH, RULES_PATH as _ENV_RULES_PATH

logger = logging.getLogger(__name__)

# Use env-configured path if set, otherwise the default beside New_rules.json
_DEFAULT_RULES_PATH = Path(_ENV_RULES_PATH) if _ENV_RULES_PATH else DEFAULT_RULES_PATH


# ---------------------------------------------------------------------------
# Rule loader
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_rules(rules_path: str | None = None) -> list[dict[str, Any]]:
    """
    Load rules from New_rules.json.

    The file uses Python-literal syntax (None instead of null, etc.),
    so we try ast.literal_eval first, then fall back to standard JSON.

    Reused from demo_sidaproject.py → RULES loading block.
    """
    path = Path(rules_path) if rules_path else _DEFAULT_RULES_PATH

    if not path.exists():
        raise FileNotFoundError(f"Rules file not found: {path}")

    text = path.read_text(encoding="utf-8")

    # Try Python literal first (original format uses None, not null)
    try:
        rules = ast.literal_eval(text)
        logger.info("Rules loaded via ast.literal_eval: %d rules", len(rules))
        return rules
    except Exception:
        pass

    # Fall back to standard JSON
    try:
        rules = json.loads(text)
        logger.info("Rules loaded via json.loads: %d rules", len(rules))
        return rules
    except Exception as exc:
        raise ValueError(f"Cannot parse rules file {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Available options extraction
# ---------------------------------------------------------------------------

def get_available_area_types(rules_path: str | None = None) -> list[str]:
    """
    Return a deduplicated list of all area_type values from the rules.

    Splits compound types like "Cottage/Micro/Household" into individual entries.
    """
    rules = load_rules(rules_path)
    seen: set[str] = set()
    result: list[str] = []

    for rule in rules:
        raw = rule.get("area_type", "")
        for part in raw.split("/"):
            normalized = part.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)

    return sorted(result)


def get_available_locations(rules_path: str | None = None) -> list[str]:
    """
    Return a deduplicated list of all location values from the rules.

    Expands "Urban/Rural" into ["Urban", "Rural"].
    """
    rules = load_rules(rules_path)
    seen: set[str] = set()
    result: list[str] = []

    for rule in rules:
        raw = rule.get("location", "")
        for part in raw.split("/"):
            normalized = part.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)

    return sorted(result)


def reload_rules(rules_path: str | None = None) -> list[dict[str, Any]]:
    """Force-reload rules (clears the lru_cache)."""
    load_rules.cache_clear()
    return load_rules(rules_path)
