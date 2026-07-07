# -*- coding: utf-8 -*-
"""
Pydantic Schemas
----------------
Request and response models for POST /process-validate-dxf.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


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

    ``location`` is only required when ``building_type`` is Industrial —
    the byelaw's Industrial FAR/height tables differ Rural vs Urban at the
    same plot-size slab, so it's mandatory there; other building types
    don't key their rules off it (yet), so it's optional for them.
    """
    building_type: BuildingType
    # Free-form: byelaw subtypes vary widely per building_type, e.g.
    # "Multiple Units", "Group Housing", "Group Housing Flatted",
    # "Affordable Housing", "Pharmaceutical and related industry", …
    subtype: str
    terrain: Terrain
    location: LocationType | None = None

    @model_validator(mode="after")
    def _require_location_for_industrial(self) -> "ProcessValidateRequest":
        if self.building_type == BuildingType.industrial and self.location is None:
            raise ValueError("location is required when building_type is Industrial")
        return self
