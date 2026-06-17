# -*- coding: utf-8 -*-
"""
CSV Service
-----------
Reused directly from demo_sidaproject.py.

Responsibilities:
  - Load a CSV file into a pandas DataFrame
  - Provide the CADData wrapper class for entity lookup
  - Expose all geometry helpers (polygon_area, dist, etc.)
  - Expose the calculate() / safe_calc() router
  - Derive all architectural metrics from the DataFrame
  - Return structured metric dict + available_area_types / available_locations

Original source: demo_sidaproject.py → CADData class, geometry helpers,
                 floor_codes, metric derivation block.
"""

from __future__ import annotations

import ast
import math
import re
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# Scale factor  (1 mm = 1 m in the original project)
# ---------------------------------------------------------------------------
SCALE = 1.0

# ---------------------------------------------------------------------------
# Floor color-code mapping  (reused verbatim from demo_sidaproject.py)
# ---------------------------------------------------------------------------
FLOOR_CODES: dict[str, int] = {
    "ground": 215,
    "first": 195,
    "second": 196,
    "third": 197,
    "fourth": 198,
    "fifth": 199,
    "sixth": 200,
}

FLOOR_PRINT_NAMES: dict[str, str] = {
    "ground": "Existing Ground Floor Area",
    "first": "Existing First Floor Area",
    "second": "Existing Second Floor Area",
    "third": "Existing Third Floor Area",
    "fourth": "Existing Fourth Floor Area",
    "fifth": "Existing Fifth Floor Area",
    "sixth": "Existing Sixth Floor Area",
}


# ---------------------------------------------------------------------------
# Geometry helpers  (reused verbatim from demo_sidaproject.py)
# ---------------------------------------------------------------------------

def extract_points(details: Any) -> list[tuple[float, float]]:
    """Extract 2-D polyline points from a Details cell string."""
    if not isinstance(details, str):
        return []
    if "points=" not in details:
        return []
    try:
        match = re.search(r"points\s*=\s*(\[.*\])", details)
        if not match:
            return []
        cleaned = re.sub(r"np\.float64\((.*?)\)", r"\1", match.group(1))
        pts = ast.literal_eval(cleaned)
        return [(p[0], p[1]) for p in pts]
    except Exception:
        return []


def polygon_area(points: list[tuple[float, float]]) -> float:
    """Shoelace formula for polygon area."""
    if len(points) < 3:
        return 0.0
    pts = points + [points[0]]
    area = sum(
        pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
        for i in range(len(points))
    )
    return abs(area) / 2 * SCALE * SCALE


def dist(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    return math.dist(p1, p2) * SCALE


def horizontal_distance(x1: float, x2: float) -> float:
    return abs(x1 - x2) * SCALE


def vertical_distance(y1: float, y2: float) -> float:
    return abs(y1 - y2) * SCALE


def dist_point_to_segment(
    px: float, py: float,
    x1: float, y1: float,
    x2: float, y2: float,
) -> float:
    """Perpendicular distance from point (px,py) to segment (x1,y1)-(x2,y2)."""
    seg_len_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
    if seg_len_sq == 0:
        return math.dist((px, py), (x1, y1)) * SCALE
    t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / seg_len_sq))
    proj_x = x1 + t * (x2 - x1)
    proj_y = y1 + t * (y2 - y1)
    return math.dist((px, py), (proj_x, proj_y)) * SCALE


def segment_list(entity: pd.Series) -> list[tuple[float, float, float, float]]:
    """Return a list of (x1,y1,x2,y2) segments for LINE or POLYLINE entities."""
    if str(entity["Type"]).lower() == "line":
        return [(entity["StartX"], entity["StartY"],
                 entity["EndX"], entity["EndY"])]
    pts = extract_points(entity["Details"])
    return [
        (pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
        for i in range(len(pts) - 1)
    ]


def calc_parallel_distance(entityA: pd.Series, entityB: pd.Series) -> float:
    """Minimum distance between two entities (parallel or closest-point)."""
    segA = segment_list(entityA)
    segB = segment_list(entityB)
    min_d = float("inf")

    for (Ax1, Ay1, Ax2, Ay2) in segA:
        for (Bx1, By1, Bx2, By2) in segB:
            Avertical = abs(Ax2 - Ax1) < 1e-9
            Bvertical = abs(Bx2 - Bx1) < 1e-9
            Ahorizontal = abs(Ay2 - Ay1) < 1e-9
            Bhorizontal = abs(By2 - By1) < 1e-9

            if Avertical and Bvertical:
                min_d = min(min_d, abs(Ax1 - Bx1) * SCALE)
                continue
            if Ahorizontal and Bhorizontal:
                min_d = min(min_d, abs(Ay1 - By1) * SCALE)
                continue

            d1 = dist_point_to_segment(Ax1, Ay1, Bx1, By1, Bx2, By2)
            d2 = dist_point_to_segment(Ax2, Ay2, Bx1, By1, Bx2, By2)
            d3 = dist_point_to_segment(Bx1, By1, Ax1, Ay1, Ax2, Ay2)
            d4 = dist_point_to_segment(Bx2, By2, Ax1, Ay1, Ax2, Ay2)
            min_d = min(min_d, d1, d2, d3, d4)

    return min_d


# ---------------------------------------------------------------------------
# CADData wrapper 
# ---------------------------------------------------------------------------

class CADData:
    """Wraps a pandas DataFrame and provides entity lookup by color + type."""

    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df

    def get_entities(self, color_code: int, etype: str) -> pd.DataFrame | None:
        df_fixed = self.df.copy()
        df_fixed["ColorCode"] = (
            df_fixed["ColorCode"].astype(str).str.extract(r"(\d+)")[0].astype(int)
        )
        valid_types = ["LWPOLYLINE", "POLYLINE"] if etype == "LWPOLYLINE" else [etype]
        rows = df_fixed[
            (df_fixed["ColorCode"] == int(color_code))
            & (df_fixed["Type"].isin(valid_types))
        ]
        return rows if not rows.empty else None

    def get_entity(self, color_code: int, etype: str) -> pd.Series | None:
        rows = self.get_entities(color_code, etype)
        return rows.iloc[0] if rows is not None else None


# ---------------------------------------------------------------------------
# Area / Length helpers  (reused verbatim from demo_sidaproject.py)
# ---------------------------------------------------------------------------

def calc_area(entity: pd.Series) -> float:
    return polygon_area(extract_points(entity["Details"]))


def calc_length(entity: pd.Series) -> float:
    return dist(
        (entity["StartX"], entity["StartY"]),
        (entity["EndX"], entity["EndY"]),
    )


# ---------------------------------------------------------------------------
# Main calculation router  (reused verbatim from demo_sidaproject.py)
# ---------------------------------------------------------------------------

def calculate(
    action: str,
    entity_type: str,
    color_code: int,
    color_code2: int | None = None,
    type2: str | None = None,
    db: CADData | None = None,
) -> float:
    """Route a calculation request to the appropriate geometry function."""
    entity = db.get_entity(color_code, entity_type)
    if entity is None:
        return 0.0

    if action == "area":
        return calc_area(entity)

    if action == "sum_area":
        entities = db.get_entities(color_code, entity_type)
        if entities is None:
            return 0.0
        return sum(calc_area(row) for _, row in entities.iterrows())

    if action == "length":
        return calc_length(entity)

    if action == "parallel_distance":
        entity2 = db.get_entity(color_code2, type2)
        if entity2 is None:
            return 0.0
        return calc_parallel_distance(entity, entity2)

    return 0.0


def _fmt(v: Any, decimals: int = 2) -> Any:
    """Round numerics, pass through non-numeric values."""
    try:
        return round(float(v), decimals)
    except Exception:
        return v


def _get_num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def safe_calc(*args, db: CADData, default: float = 0.0) -> float:
    """Wrapper around calculate() that swallows exceptions."""
    try:
        return _get_num(calculate(*args, db=db))
    except Exception:
        return default


# ---------------------------------------------------------------------------
# CSV loader
# ---------------------------------------------------------------------------

def load_csv(csv_path: str) -> pd.DataFrame:
    """Load a CSV file produced by dxf_service into a DataFrame."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    return pd.read_csv(path)


def load_csv_from_text(csv_text: str) -> pd.DataFrame:
    """Load CSV from an in-memory string."""
    return pd.read_csv(StringIO(csv_text))


# ---------------------------------------------------------------------------
# Metric derivation  (reused from demo_sidaproject.py metric block)
# ---------------------------------------------------------------------------

def derive_metrics(df: pd.DataFrame) -> dict[str, Any]:
    """
    Derive all architectural metrics from a CAD DataFrame.

    Reused from demo_sidaproject.py metric derivation block.
    Returns a flat dict of all computed values.
    """
    db = CADData(df)

    # --- Floor areas (only floors that exist) ---
    floor_areas: dict[str, float] = {}
    for floor_name, code in FLOOR_CODES.items():
        raw = safe_calc("area", "LWPOLYLINE", code, db=db)
        if raw > 0:
            floor_areas[floor_name] = _fmt(raw)

    # --- Direct measurements ---
    plot_area = _fmt(safe_calc("area", "LWPOLYLINE", 7, db=db))

    rear_set_back = _fmt(safe_calc("parallel_distance", "LINE", 3, 10, "LWPOLYLINE", db=db))
    rear_set_back_len = _fmt(safe_calc("length", "LINE", 3, db=db))

    front_set_back = _fmt(safe_calc("parallel_distance", "LINE", 4, 10, "LWPOLYLINE", db=db))
    front_set_back_len = _fmt(safe_calc("length", "LINE", 4, db=db))

    side_setback_distance1 = _fmt(safe_calc("parallel_distance", "LINE", 6, 10, "LWPOLYLINE", db=db))
    side_setback_distance1_len = _fmt(safe_calc("length", "LINE", 6, db=db))

    side_setback_distance2 = _fmt(safe_calc("parallel_distance", "LINE", 2, 10, "LWPOLYLINE", db=db))
    side_setback_distance2_len = _fmt(safe_calc("length", "LINE", 2, db=db))

    road_width = _fmt(safe_calc("length", "LINE", 41, db=db))
    building_height = _fmt(safe_calc("length", "LINE", 151, db=db))
    max_ground_cov = _fmt(safe_calc("area", "LWPOLYLINE", 10, db=db))
    mumty_height = _fmt(safe_calc("length", "LINE", 45, db=db))

    # --- Parking ---
    open_parking_area = _fmt(calculate("sum_area", "LWPOLYLINE", 20, db=db))
    car_parking_area = _fmt(calculate("sum_area", "LWPOLYLINE", 140, db=db))
    mechanical_parking_area = _fmt(calculate("sum_area", "LWPOLYLINE", 213, db=db))
    stilt_parking_area = _fmt(calculate("sum_area", "LWPOLYLINE", 15, db=db))
    basement_parking_area = _fmt(calculate("sum_area", "LWPOLYLINE", 31, db=db))

    # --- Ancillary areas ---
    guard_room = _fmt(safe_calc("area", "LWPOLYLINE", 182, db=db))
    meter_room = _fmt(safe_calc("area", "LWPOLYLINE", 192, db=db))
    mumty_area = _fmt(safe_calc("area", "LWPOLYLINE", 9, db=db))
    green_area = _fmt(safe_calc("sum_area", "LWPOLYLINE", 60, db=db))
    canopy_area = _fmt(safe_calc("area", "LWPOLYLINE", 184, db=db))
    stairs_area = _fmt(safe_calc("sum_area", "LWPOLYLINE", 115, db=db))
    fire_stairs = _fmt(safe_calc("sum_area", "LWPOLYLINE", 116, db=db))
    loading_unloading_area = _fmt(safe_calc("area", "LWPOLYLINE", 221, db=db))
    rain_water_harvesting = _fmt(safe_calc("area", "LWPOLYLINE", 94, db=db))

    ground_area = floor_areas.get("ground", 0.0)
    total_ground_floor_area = _fmt(ground_area + guard_room + meter_room)
    total_stair_case_area = _fmt(stairs_area + fire_stairs)

    # --- Derived metrics ---
    total_floor_builtup = _fmt(sum(floor_areas.values()))
    far_area = _fmt(total_floor_builtup - total_stair_case_area)
    far_value = _fmt(far_area / plot_area) if plot_area else 0.0
    max_ground_coverage_pre = _fmt(max_ground_cov / plot_area * 100) if plot_area else 0.0
    open_area = _fmt(plot_area - total_ground_floor_area)
    chargable_area = _fmt(sum(floor_areas.values()) + mumty_area + guard_room + meter_room)
    covered_area = chargable_area

    # --- Parking permissible values ---
    plot_usage = 0.3 if plot_area < 1000 else 0.5
    ecs = (far_area * plot_usage) / 100
    permissible_open_parking = ecs * 23
    permissible_stilt_parking = ecs * 28
    permissible_basement_parking = ecs * 32
    permissible_mechanical_parking = ecs * 64

    return {
        # Plot
        "plot_area": plot_area,
        # Floors
        "floor_areas": floor_areas,
        "total_floor_builtup": total_floor_builtup,
        "total_ground_floor_area": total_ground_floor_area,
        "total_stair_case_area": total_stair_case_area,
        # Setbacks
        "front_set_back": front_set_back,
        "front_set_back_len": front_set_back_len,
        "rear_set_back": rear_set_back,
        "rear_set_back_len": rear_set_back_len,
        "side_setback_distance1": side_setback_distance1,
        "side_setback_distance1_len": side_setback_distance1_len,
        "side_setback_distance2": side_setback_distance2,
        "side_setback_distance2_len": side_setback_distance2_len,
        # Road / height
        "road_width": road_width,
        "building_height": building_height,
        "mumty_height": mumty_height,
        # Coverage / FAR
        "max_ground_cov": max_ground_cov,
        "max_ground_coverage_pre": max_ground_coverage_pre,
        "far_area": far_area,
        "far_value": far_value,
        "open_area": open_area,
        "chargable_area": chargable_area,
        "covered_area": covered_area,
        # Parking
        "open_parking_area": open_parking_area,
        "car_parking_area": car_parking_area,
        "mechanical_parking_area": mechanical_parking_area,
        "stilt_parking_area": stilt_parking_area,
        "basement_parking_area": basement_parking_area,
        "permissible_open_parking": _fmt(permissible_open_parking),
        "permissible_stilt_parking": _fmt(permissible_stilt_parking),
        "permissible_basement_parking": _fmt(permissible_basement_parking),
        "permissible_mechanical_parking": _fmt(permissible_mechanical_parking),
        # Ancillary
        "guard_room": guard_room,
        "meter_room": meter_room,
        "mumty_area": mumty_area,
        "green_area": green_area,
        "canopy_area": canopy_area,
        "stairs_area": stairs_area,
        "fire_stairs": fire_stairs,
        "loading_unloading_area": loading_unloading_area,
        "rain_water_harvesting": rain_water_harvesting,
    }
