# -*- coding: utf-8 -*-
"""
Metric Extraction Layer
-----------------------
Derives all SIDA architectural metrics directly from a CADModel.


Color-code reference (from demo_sidaproject.py)
-----------------------------------------------
 7   → plot boundary       (LWPOLYLINE, area)
 10  → max ground coverage (LWPOLYLINE, area)
 41  → road width          (LINE, length)
151  → building height     (LINE, length)
 45  → mumty height        (LINE, length)
215  → ground floor        (LWPOLYLINE, area)  ← also in FLOOR_CODES
195-200 → 1st–6th floors   (LWPOLYLINE, area)

Setback lines (LINE, length + parallel_distance to color-10 polygon):
  3  → rear
  4  → front
  6  → side 1
  2  → side 2

Parking (LWPOLYLINE, sum_area):
  20  → open parking
 140  → car parking
 213  → mechanical parking
  15  → stilt parking
  31  → basement parking

Ancillary (LWPOLYLINE, area or sum_area):
 182  → guard room
 192  → meter room
   9  → mumty
  60  → green area       (sum)
 184  → canopy
 115  → stairs           (sum)
 116  → fire stairs      (sum)
 221  → loading/unloading
  94  → rain water harvesting

Extension points
----------------
Future geometry validators import from here:

    from app.services.metrics import SCALE, polygon_area, dist, ...

They can also call derive_metrics(model) and augment the result.
"""

from __future__ import annotations

import math
from typing import Any

from app.models.cad_model import CADModel, DxfEntity

# ---------------------------------------------------------------------------
# Scale factor  (1 mm = 1 m in the original project)
# ---------------------------------------------------------------------------
SCALE: float = 1.0

NON_FAR:dist[str,int] = {
    'guard_room_area' : 182,
    'meter_room_area' :192,
    'mumty_area'  :9,
    'stairs_area' :115,
    'fire_stairs' : 116,
    'shaft_area' : 11,
    'lift_area' :22
}

# ---------------------------------------------------------------------------
# Floor color-code mapping
# ---------------------------------------------------------------------------
FLOOR_CODES: dict[str, int] = {
    "ground": 215,
    "first":  195,
    "second": 196,
    "third":  197,
    "fourth": 198,
    "fifth":  199,
    "sixth":  200,
    "seven":  201,
    "eight":  202,
    "nine" :  203,
    "tenth" :  204,
    "eleventh" :  205,
    "twelth" :  206,
    "thirteen" :  207,
    "fourteen" :  208,
    "fivetenn" :  209,
}


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def polygon_area(points: list[tuple[float, float]]) -> float:
    """Shoelace formula — returns area in model units squared."""
    if len(points) < 3:
        return 0.0
    pts = points + [points[0]]
    area = sum(
        pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
        for i in range(len(points))
    )
    return abs(area) / 2.0 * SCALE * SCALE


def dist(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    return math.dist(p1, p2) * SCALE


def dist_point_to_segment(
    px: float, py: float,
    x1: float, y1: float,
    x2: float, y2: float,
) -> float:
    """Perpendicular (clamped) distance from point to segment."""
    seg_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
    if seg_sq == 0:
        return math.dist((px, py), (x1, y1)) * SCALE
    t = max(0.0, min(1.0, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / seg_sq))
    return math.dist((px, py), (x1 + t * (x2 - x1), y1 + t * (y2 - y1))) * SCALE


def segments_of(entity: DxfEntity) -> list[tuple[float, float, float, float]]:
    """
    Return (x1, y1, x2, y2) segments for LINE or poly entities.
    Uses the native .points list — no string parsing needed.
    """
    if entity.entity_type == "LINE":
        return [(entity.start_x, entity.start_y, entity.end_x, entity.end_y)]
    pts = entity.points
    if len(pts) < 2:
        return []
    return [(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1]) for i in range(len(pts) - 1)]


def parallel_distance(a: DxfEntity, b: DxfEntity) -> float:
    """Minimum distance between two entities."""
    seg_a = segments_of(a)
    seg_b = segments_of(b)
    if not seg_a or not seg_b:
        return 0.0

    min_d = float("inf")
    for (Ax1, Ay1, Ax2, Ay2) in seg_a:
        for (Bx1, By1, Bx2, By2) in seg_b:
            a_vert = abs(Ax2 - Ax1) < 1e-9
            b_vert = abs(Bx2 - Bx1) < 1e-9
            a_horiz = abs(Ay2 - Ay1) < 1e-9
            b_horiz = abs(By2 - By1) < 1e-9

            if a_vert and b_vert:
                min_d = min(min_d, abs(Ax1 - Bx1) * SCALE)
                continue
            if a_horiz and b_horiz:
                min_d = min(min_d, abs(Ay1 - By1) * SCALE)
                continue

            min_d = min(
                min_d,
                dist_point_to_segment(Ax1, Ay1, Bx1, By1, Bx2, By2),
                dist_point_to_segment(Ax2, Ay2, Bx1, By1, Bx2, By2),
                dist_point_to_segment(Bx1, By1, Ax1, Ay1, Ax2, Ay2),
                dist_point_to_segment(Bx2, By2, Ax1, Ay1, Ax2, Ay2),
            )
    return min_d


# ---------------------------------------------------------------------------
# Per-entity calculations
# ---------------------------------------------------------------------------

def entity_area(entity: DxfEntity) -> float:
    """Area of a closed polygon entity."""
    return polygon_area(entity.points)


def entity_length(entity: DxfEntity) -> float:
    """Length of a LINE entity."""
    return dist(
        (entity.start_x, entity.start_y),
        (entity.end_x,   entity.end_y),
    )


def sum_area(entities: list[DxfEntity]) -> float:
    return sum(entity_area(e) for e in entities)


# ---------------------------------------------------------------------------
# CADModel query helpers
# ---------------------------------------------------------------------------

def _area(model: CADModel, color: int) -> float:
    """Area of first LWPOLYLINE/POLYLINE with given color."""
    ent = model.get_entity(color, "LWPOLYLINE")
    return entity_area(ent) if ent else 0.0


def _sum_area(model: CADModel, color: int) -> float:
    """Sum of areas of all LWPOLYLINE/POLYLINE with given color."""
    return sum_area(model.get_entities(color, "LWPOLYLINE"))


def _length(model: CADModel, color: int) -> float:
    """Length of first LINE with given color."""
    ent = model.get_entity(color, "LINE")
    return entity_length(ent) if ent else 0.0


def _parallel_dist(model: CADModel, color_a: int, color_b: int) -> float:
    """Min distance between first LINE of color_a and first LWPOLYLINE of color_b."""
    a = model.get_entity(color_a, "LINE")
    b = model.get_entity(color_b, "LWPOLYLINE")
    if a is None or b is None:
        return 0.0
    return parallel_distance(a, b)


def _fmt(v: float, decimals: int = 2) -> float:
    return round(v, decimals)



# ---------------------------------------------------------------------------
# Public metric derivation
# ---------------------------------------------------------------------------

def derive_metrics(model: CADModel , building_type: str, subtype: str, location: str) -> dict[str, Any]:
    """
    Derive all SIDA architectural metrics from a CADModel.

    Operates directly on CADModel indexes — no CSV, no DataFrame.
    Returns the same flat dict shape as the original derive_metrics(df).

    Parameters
    ----------
    model : CADModel
        Output of parse_dxf_to_cad_model().

    Returns
    -------
    dict with keys: plot_area, floor_areas, far_value, far_area,
        ground_coverage_percentage, building_height, road_width, setbacks,
        parking areas, ancillary areas, and derived totals.
    """

    # --- Floor areas ---
    floor_areas: dict[str, float] = {}
    for floor_name, code in FLOOR_CODES.items():
        raw = _fmt(_area(model, code))
        if raw > 0:
            floor_areas[floor_name] = raw

    # --- Direct measurements ---
    plot_area = _fmt(_area(model, 7))

    rear_set_back      = _fmt(_parallel_dist(model, 3, 10))
    rear_set_back_len  = _fmt(_length(model, 3))

    front_set_back     = _fmt(_parallel_dist(model, 4, 10))
    front_set_back_len = _fmt(_length(model, 4))

    side_setback_distance1     = _fmt(_parallel_dist(model, 6, 10))
    side_setback_distance1_len = _fmt(_length(model, 6))

    side_setback_distance2     = _fmt(_parallel_dist(model, 2, 10))
    side_setback_distance2_len = _fmt(_length(model, 2))

    road_width      = _fmt(_length(model, 41))
    building_height = _fmt(_length(model, 151))
    ground_coverage  = _fmt(_area(model, 10))

    
    mumty_height    = _fmt(_length(model, 45))

    # NON FAR
    guard_room_area             = _fmt(_area(model, 182))
    meter_room_area             = _fmt(_area(model, 192))
    mumty_area             = _fmt(_area(model, 9))
    stairs_area            = _fmt(_sum_area(model, 115))
    fire_stairs            = _fmt(_sum_area(model, 116))
    shaft_area            = _fmt(_sum_area(model, 11))
    lift_area             = _fmt(_sum_area(model, 22))

    # --- Parking ---
    open_parking_area       = _fmt(_sum_area(model, 20))
    car_parking_area        = _fmt(_sum_area(model, 140))
    mechanical_parking_area = _fmt(_sum_area(model, 213))
    stilt_parking_area      = _fmt(_sum_area(model, 15))
    basement_parking_area   = _fmt(_sum_area(model, 31))

    # --- Ancillary ---
    
    green_area             = _fmt(_sum_area(model, 60))
    canopy_area            = _fmt(_area(model, 184))
    
    loading_unloading_area = _fmt(_area(model, 221))
    rain_water_harvesting  = _fmt(_area(model, 94))

    # --- Derived totals ---
    ground_area             = floor_areas.get("ground", 0.0)
    non_far_area = (guard_room_area + meter_room_area + mumty_area + stairs_area + fire_stairs + shaft_area + lift_area)

    total_ground_floor_area = _fmt(ground_area + guard_room + meter_room)

    # total_stair_case_area   = _fmt(stairs_area + fire_stairs)

    total_floor_area     = _fmt(sum(floor_areas.values()))

    far_area                = _fmt(total_floor_area - non_far_area)

    far_value               = _fmt(far_area / plot_area) if plot_area else 0.0

    ground_coverage_percentage = _fmt(ground_coverage / plot_area * 100) if plot_area else 0.0

    open_area               = _fmt(plot_area - total_ground_floor_area)

    chargable_area          = _fmt(sum(floor_areas.values()) + mumty_area + guard_room + meter_room)

    covered_area            = chargable_area

    # --- Parking permissible ---
    plot_usage = 0.3 if plot_area < 1000 else 0.5
    ecs        = (far_area * plot_usage) / 100
    permissible_open_parking       = _fmt(ecs * 23)
    permissible_stilt_parking      = _fmt(ecs * 28)
    permissible_basement_parking   = _fmt(ecs * 32)
    permissible_mechanical_parking = _fmt(ecs * 64)

    return {
        # Plot
        "plot_area":               plot_area,
        # Floors
        "floor_areas":             floor_areas,
        "total_floor_builtup":     total_floor_area,
        "total_ground_floor_area": total_ground_floor_area,
        # "total_stair_case_area":   total_stair_case_area,
        # Setbacks
        "front_set_back":              front_set_back,
        "front_set_back_len":          front_set_back_len,
        "rear_set_back":               rear_set_back,
        "rear_set_back_len":           rear_set_back_len,
        "side_setback_distance1":      side_setback_distance1,
        "side_setback_distance1_len":  side_setback_distance1_len,
        "side_setback_distance2":      side_setback_distance2,
        "side_setback_distance2_len":  side_setback_distance2_len,
        # Road / height
        "road_width":      road_width,
        "building_height": building_height,
        "mumty_height":    mumty_height,
        # Coverage / FAR
        "ground_coverage":          ground_coverage,
        "ground_coverage_percentage": ground_coverage_percentage,
        "far_area":                far_area,
        "far_value":               far_value,
        "open_area":               open_area,
        "chargable_area":          chargable_area,
        "covered_area":            covered_area,
        # Parking actuals
        "open_parking_area":       open_parking_area,
        "car_parking_area":        car_parking_area,
        "mechanical_parking_area": mechanical_parking_area,
        "stilt_parking_area":      stilt_parking_area,
        "basement_parking_area":   basement_parking_area,
        # Parking permissible
        "permissible_open_parking":       permissible_open_parking,
        "permissible_stilt_parking":      permissible_stilt_parking,
        "permissible_basement_parking":   permissible_basement_parking,
        "permissible_mechanical_parking": permissible_mechanical_parking,
        # Ancillary
        "guard_room":              guard_room,
        "meter_room":              meter_room,
        "mumty_area":              mumty_area,
        "green_area":              green_area,
        "canopy_area":             canopy_area,
        "stairs_area":             stairs_area,
        "fire_stairs":             fire_stairs,
        "loading_unloading_area":  loading_unloading_area,
        "rain_water_harvesting":   rain_water_harvesting,
    }
