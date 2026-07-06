# -*- coding: utf-8 -*-
"""
Pydantic Schemas
----------------
Request and response models for POST /process-validate-dxf.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    status: str = Field("error")
    message: str


# ---------------------------------------------------------------------------
# process-validate-dxf request enums
# ---------------------------------------------------------------------------
#
# NOTE: `terrain` and `location` are two distinct fields, easily confused:
#   terrain  -> Hill | Plain   (drives stilt / building-height exemption
#                               rules, Section 3 of the SIDA byelaws)
#   location -> Rural | Urban  (byelaw plot-size / FAR bands differ by
#                               rural vs urban; not yet used in the
#                               geometry/exemption arithmetic, but echoed
#                               through metrics/report for rule matching)


class BuildingType(str, Enum):
    residential   = "Residential"
    commercial    = "Commercial"
    industrial    = "Industrial"
    mall          = "Mall"
    institutional = "Institutional"
    other         = "Other"


class Terrain(str, Enum):
    hill  = "Hill"
    plain = "Plain"


class LocationType(str, Enum):
    rural = "Rural"
    urban = "Urban"


class ProcessValidateRequest(BaseModel):
    """
    Documents the non-file form fields accepted by POST /process-validate-dxf.

    FastAPI binds these individually via ``Form(...)`` in the route (a
    multipart/form-data request cannot bind a nested Pydantic model
    directly), but this class is the single source of truth for the
    field set and allowed values.
    """
    building_type: BuildingType
    # Free-form: byelaw subtypes vary widely per building_type, e.g.
    # "Multiple Units", "Group Housing", "Group Housing Flatted",
    # "Affordable Housing", "Pharmaceutical and related industry", …
    subtype: str
    terrain: Terrain
    location: LocationType
