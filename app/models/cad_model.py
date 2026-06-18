# -*- coding: utf-8 -*-
"""
CAD Domain Models
-----------------
Lightweight, typed entity objects and the root CADModel that replaces
the CSV/DataFrame transport layer entirely.

Architecture
------------
DXF stream
    └── parse_dxf_to_cad_model()   [dxf_parser.py]
            └── CADModel
                    ├── layer_colors   {layer_name: color_int}
                    ├── entities       [DxfEntity]
                    ├── by_color       {color: [DxfEntity]}   ← built at parse time
                    ├── by_type        {etype: [DxfEntity]}
                    └── by_layer       {layer: [DxfEntity]}

Consumers (metrics.py, validation_service.py, future geometry rules) query
CADModel directly — no CSV serialisation, no pandas DataFrame.

Extension points
----------------
Future geometry validators (distances, setbacks, intersections, parking
layout) receive a CADModel and can access the spatial indexes directly:

    def validate_setbacks(model: CADModel, rule: dict) -> list[str]: ...
    def validate_parking_layout(model: CADModel, rule: dict) -> list[str]: ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator


# ---------------------------------------------------------------------------
# Supported entity types
# ---------------------------------------------------------------------------

SUPPORTED_TYPES: frozenset[str] = frozenset(
    {"LINE", "CIRCLE", "ARC", "LWPOLYLINE", "POLYLINE", "TEXT", "MTEXT", "INSERT"}
)


# ---------------------------------------------------------------------------
# Entity dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DxfEntity:
    """
    A single CAD entity extracted from the DXF ENTITIES section.

    Stores only the attributes required for metric derivation and rule
    validation.  The ``points`` list is populated natively during parsing
    so geometry helpers never need to re-parse a Details string.
    """
    entity_type: str                          # "LINE" | "LWPOLYLINE" | …
    layer:       str
    color:       int                          # resolved color code
    start_x:     float = 0.0
    start_y:     float = 0.0
    start_z:     float = 0.0
    end_x:       float = 0.0
    end_y:       float = 0.0
    end_z:       float = 0.0
    points:      list[tuple[float, float]] = field(default_factory=list)
    # details kept for CSV export / debug only — not used by metrics
    details:     str = ""


# ---------------------------------------------------------------------------
# CADModel — root domain object
# ---------------------------------------------------------------------------

@dataclass
class CADModel:
    """
    Root CAD domain object produced by a single DXF parse.

    Indexes are built during construction so that all downstream consumers
    (metrics, validation, future geometry rules) can query in O(1) / O(k)
    without re-scanning the entity list.

    Parameters
    ----------
    layer_colors : dict[str, int]
        Mapping from layer name to resolved color code, extracted from the
        DXF TABLES/LAYER section.
    entities : list[DxfEntity]
        All entities from the DXF ENTITIES section.

    Attributes (built automatically)
    ---------------------------------
    by_color  : dict[int, list[DxfEntity]]
    by_type   : dict[str, list[DxfEntity]]
    by_layer  : dict[str, list[DxfEntity]]
    """

    layer_colors: dict[str, int]
    entities:     list[DxfEntity]

    # Indexes — populated by __post_init__
    by_color: dict[int, list[DxfEntity]] = field(default_factory=dict, init=False, repr=False)
    by_type:  dict[str, list[DxfEntity]] = field(default_factory=dict, init=False, repr=False)
    by_layer: dict[str, list[DxfEntity]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._build_indexes()

    # ------------------------------------------------------------------
    # Index builder
    # ------------------------------------------------------------------

    def _build_indexes(self) -> None:
        """Populate by_color / by_type / by_layer from self.entities."""
        by_color: dict[int, list[DxfEntity]] = {}
        by_type:  dict[str, list[DxfEntity]] = {}
        by_layer: dict[str, list[DxfEntity]] = {}

        for ent in self.entities:
            by_color.setdefault(ent.color, []).append(ent)
            by_type.setdefault(ent.entity_type, []).append(ent)
            by_layer.setdefault(ent.layer, []).append(ent)

        self.by_color = by_color
        self.by_type  = by_type
        self.by_layer = by_layer

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_entities(self, color: int, etype: str) -> list[DxfEntity]:
        """
        Return all entities matching *color* and *etype*.

        LWPOLYLINE queries also return POLYLINE entities (same geometry,
        different DXF encoding) — mirrors the original CADData behaviour.
        """
        valid_types = (
            {"LWPOLYLINE", "POLYLINE"} if etype == "LWPOLYLINE" else {etype}
        )
        color_bucket = self.by_color.get(color, [])
        return [e for e in color_bucket if e.entity_type in valid_types]

    def get_entity(self, color: int, etype: str) -> DxfEntity | None:
        """Return the first matching entity, or None."""
        matches = self.get_entities(color, etype)
        return matches[0] if matches else None

    def iter_by_layer(self, layer: str) -> Iterator[DxfEntity]:
        """Iterate over all entities on a named layer."""
        yield from self.by_layer.get(layer, [])

    def iter_by_type(self, etype: str) -> Iterator[DxfEntity]:
        """Iterate over all entities of a given type."""
        yield from self.by_type.get(etype, [])

    # ------------------------------------------------------------------
    # Introspection helpers (useful for future validators)
    # ------------------------------------------------------------------

    def has_layer(self, layer: str) -> bool:
        return layer in self.by_layer

    def has_color(self, color: int) -> bool:
        return color in self.by_color

    def count_by_color(self, color: int) -> int:
        return len(self.by_color.get(color, []))

    def count_by_type(self, etype: str) -> int:
        return len(self.by_type.get(etype, []))
