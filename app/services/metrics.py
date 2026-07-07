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
 221  → loading/unloading (sum_area — used only for the loading/unloading
        validation rule, not a floor-area total)
  94  → rain water harvesting

FAR-exemption geometry (LWPOLYLINE area / LINE height, see Section 4 of the
SIDA / UGIDCR / UHUDA byelaws for the exemption clauses these implement):
   5  → stilt floor boundary     (area)   — FLOOR-STILT layer
  21  → stilt floor height       (length) — bottom of beam, qualifies <= 2.4 m
  32  → basement boundary        (sum area) — FLOOR-BF1/BF2… layers, always FAR-exempt
   8  → service floor            (sum area) — FLOOR-SERVICE layer
  89  → service floor height     (length) — qualifies <= 2.4 m
  35  → cantilever balcony       (sum area, threshold-based)
  85  → chajja projection        (sum area, threshold-based)
 219  → cantilever projection    (sum area, threshold-based)
 187  → pump room                (sum area)
 188  → air conditioning room    (sum area)
 191  → open transformer / electric substation (sum area)
 185  → watchman shelter/booth   (sum area)

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

NON_FAR: dict[str, int] = {
    'guard_room_area' : 182,
    'meter_room_area' :192,
    'mumty_area'  :9,
    'stairs_area' :115,
    'fire_stairs' : 116,
    'shaft_area' : 11,
    'lift_area' :22
}

# ---------------------------------------------------------------------------
# FAR-exemption color codes (Section 4, FAR relaxations, SIDA byelaws)
# ---------------------------------------------------------------------------
STILT_FLOOR_BOUNDARY_COLOR:  int = 5
STILT_FLOOR_HEIGHT_COLOR:    int = 21
BASEMENT_BOUNDARY_COLOR:     int = 32
SERVICE_FLOOR_COLOR:         int = 8
SERVICE_FLOOR_HEIGHT_COLOR:  int = 89
CANTILEVER_BALCONY_COLOR:    int = 35
CHAJJA_PROJECTION_COLOR:     int = 85
CANTILEVER_PROJECTION_COLOR: int = 219
PUMP_ROOM_COLOR:             int = 187
AC_ROOM_COLOR:               int = 188
OPEN_TRANSFORMER_COLOR:      int = 191
WATCHMAN_SHELTER_COLOR:      int = 185

# Height / width thresholds from the byelaws
STILT_HEIGHT_LIMIT_M:          float = 2.4
SERVICE_FLOOR_HEIGHT_LIMIT_M:  float = 2.4
BALCONY_LIMIT_INDUSTRIAL_M:    float = 1.2   # Industries: relaxed till 1.2 m width
BALCONY_LIMIT_OTHERS_M:        float = 1.8   # All other building types: relaxed till 1.8 m width

# ---------------------------------------------------------------------------
# Building-height color codes (Section 3, Building Height, SIDA byelaws)
# ---------------------------------------------------------------------------
BUILDING_HEIGHT_DRAWN_COLOR:   int = 151   # "Height Of the Building after exemptions" (as drawn)
FLOOR_TO_FLOOR_HEIGHT_COLOR:   int = 233
MUMTY_HEIGHT_COLOR:            int = 45
MACHINE_ROOM_HEIGHT_COLOR:     int = 46
PLINTH_HEIGHT_COLOR:           int = 105

# Height relaxation thresholds
MUMTY_HEIGHT_LIMIT_M:          float = 2.4
MACHINE_ROOM_HEIGHT_LIMIT_M:   float = 4.2
BASEMENT_ABOVE_GROUND_LIMIT_M: float = 1.2
ROOF_FEATURE_HEIGHT_LIMIT_M:   float = 1.5   # water tank / parapet / chimney / decoration features

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


def bbox_dims(entity: DxfEntity) -> tuple[float, float]:
    """
    Approximate (depth, length) of a projection polygon (balcony / chajja /
    cantilever) from its axis-aligned bounding box.

    ``depth`` is the smaller bounding-box dimension (assumed to be how far
    the projection sticks out from the building line) and ``length`` is the
    larger dimension (assumed to run along the building face). This is a
    geometric approximation — good enough for rectangular projections, which
    is how these elements are normally drawn.
    """
    pts = entity.points
    if not pts:
        return 0.0, 0.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    w = (max(xs) - min(xs)) * SCALE
    h = (max(ys) - min(ys)) * SCALE
    return (w, h) if w <= h else (h, w)


def chargeable_projection_area(entities: list[DxfEntity], limit_m: float) -> float:
    """
    Sum the FAR-chargeable portion of balcony/chajja/projection polygons.

    Per byelaw Section 4.c.ii.4: projections are relaxed (exempt) up to
    ``limit_m`` width; only the area beyond that width is counted in FAR.
    For a projection of depth ``d`` and area ``A`` (running length
    ``A / d``), the chargeable slice is::

        A * (1 - limit_m / d)   if d > limit_m
        0                       otherwise
    """
    total = 0.0
    for ent in entities:
        area = entity_area(ent)
        if area <= 0:
            continue
        depth, _ = bbox_dims(ent)
        if depth <= 0 or depth <= limit_m:
            continue
        total += area * (1 - (limit_m / depth))
    return total


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
# Loading / Unloading area requirement
# ---------------------------------------------------------------------------
LOADING_UNLOADING_BASE_AREA_SQM: float = 26.25
LOADING_UNLOADING_FAR_AREA_DIVISOR: float = 1000.0


def calculate_required_loading_unloading_area(far_area: float) -> float:
    """
    Required Loading/Unloading area, scaled by FAR area:

        factor = far_area / 1000
        required = 26.25                  if factor <= 1
        required = 26.25 * factor          otherwise
    """
    factor = far_area / LOADING_UNLOADING_FAR_AREA_DIVISOR
    if factor <= 1:
        return _fmt(LOADING_UNLOADING_BASE_AREA_SQM)
    return _fmt(LOADING_UNLOADING_BASE_AREA_SQM * factor)


# ---------------------------------------------------------------------------
# Rain Water Harvesting (RWH) requirement
# ---------------------------------------------------------------------------
RWH_AREA_COLOR:   int = 94   # RWH Tank (LWPOLYLINE, area)
RWH_HEIGHT_COLOR: int = 92   # RWH Height (LINE, length)

RWH_GROUND_COVERAGE_THRESHOLD_SQM: float = 400.0
RWH_MIN_VOLUME_CUM:               float = 3.5
RWH_EXCESS_FACTOR:                float = 0.5
RWH_EXCESS_DIVISOR:               float = 50.0


def calculate_required_rwh_volume(ground_coverage_area: float) -> float:
    """
    Required Rain Water Harvesting volume (cu.m), scaled by ground coverage
    area:

        required = 3.5                                              if ground_coverage_area <= 400
        required = ((ground_coverage_area - 400) * 0.5) / 50 + 3.5   otherwise
    """
    if ground_coverage_area <= RWH_GROUND_COVERAGE_THRESHOLD_SQM:
        return _fmt(RWH_MIN_VOLUME_CUM)
    excess = ground_coverage_area - RWH_GROUND_COVERAGE_THRESHOLD_SQM
    return _fmt((excess * RWH_EXCESS_FACTOR) / RWH_EXCESS_DIVISOR + RWH_MIN_VOLUME_CUM)


# ---------------------------------------------------------------------------
# FAR calculation
# ---------------------------------------------------------------------------

def calculate_far(
    model: CADModel,
    floor_areas: dict[str, float],
    plot_area: float,
    building_type: str = "",
    subtype: str = "",
    terrain: str = "",
    stilt_height: float = 0.0,
    service_floor_height: float = 0.0,
    stilt_qualifies: bool = True,
) -> dict[str, Any]:
    """
    Compute FAR area / FAR value from a CADModel, applying every FAR
    relaxation clause in Section 4 ("Floor Area Ratio") of the SIDA /
    UGIDCR / UHUDA byelaws.

    FAR = Total chargeable Floor Area ÷ Plot Area, where the chargeable
    floor area is the sum of all constructed floor plates **minus** the
    areas the byelaws explicitly exempt.

    Parameters
    ----------
    model : CADModel
        Parsed drawing.
    floor_areas : dict[str, float]
        Ground + numbered floor areas already extracted via FLOOR_CODES
        (as returned by the "Floor areas" step of ``derive_metrics``).
    plot_area : float
        Plot boundary area (color 7), used as the FAR denominator.
    building_type : str
        e.g. "industrial", "residential", "commercial" … Only "industrial"
        changes the balcony/projection exemption threshold (1.2 m instead
        of 1.8 m) per byelaw Section 4.c.ii.4.
    subtype : str
        e.g. "pharmaceutical". Pharmaceutical / related industries are
        permitted more than one FAR-exempt service floor — since every
        service-floor polygon on color 8 is already summed regardless of
        count, this only affects reporting, not the arithmetic.
    terrain : str
        "hill" or "plain". Hilly plots do not permit a 2nd stilt floor —
        kept for reporting/validation context; not required by the FAR
        arithmetic itself (stilt area is exempt as a whole below).
    stilt_height : float
        Stilt floor clear height (color 21), used to test the <= 2.4 m
        exemption condition.
    service_floor_height : float
        Service floor clear height (color 89), used to test the <= 2.4 m
        exemption condition.
    stilt_qualifies : bool
        Whether the stilt floor otherwise qualifies as a byelaw "Stilt
        Floor" (open >= 3 sides, used only for parking/services). This
        cannot be derived from 2D geometry alone, so it is accepted as an
        explicit input (defaults to True); if False, the stilt area is
        fully chargeable to FAR regardless of height.

    Returns
    -------
    dict with keys: far_area, far_value, and far_exempt_breakdown (a
    dict of every exempted / chargeable component, for reporting).
    """
    is_industrial = building_type.strip().lower() == "industrial"
    is_pharma = "pharma" in (subtype or "").strip().lower()
    balcony_limit = BALCONY_LIMIT_INDUSTRIAL_M if is_industrial else BALCONY_LIMIT_OTHERS_M

    # 1. Base constructed floor area — ground + numbered floors (already extracted).
    total_floor_area = _fmt(sum(floor_areas.values()))

    # 2. Stilt floor — FAR-exempt only if height <= 2.4 m AND it otherwise
    #    qualifies as a byelaw "Stilt Floor". Stilt polygons are never part
    #    of `floor_areas`, so a non-qualifying stilt floor's area must be
    #    *added* to the chargeable total (it counts as ordinary floor area).
    stilt_area_total = _fmt(_sum_area(model, STILT_FLOOR_BOUNDARY_COLOR))
    stilt_ok = stilt_qualifies and 0 < stilt_height <= STILT_HEIGHT_LIMIT_M
    stilt_exempt_area = stilt_area_total if stilt_ok else 0.0
    stilt_chargeable_area = 0.0 if stilt_ok else stilt_area_total
    total_floor_area += stilt_chargeable_area

    # 3. Basement — always fully FAR-exempt (height only affects Building
    #    Height, never FAR). Basement is never part of `floor_areas`.
    basement_exempt_area = _fmt(_sum_area(model, BASEMENT_BOUNDARY_COLOR))

    # 4. Service floor — FAR-exempt if height <= 2.4 m. Pharma / related
    #    industries may stack more than one service floor, all exempt.
    service_floor_area_total = _fmt(_sum_area(model, SERVICE_FLOOR_COLOR))
    service_floor_ok = 0 < service_floor_height <= SERVICE_FLOOR_HEIGHT_LIMIT_M
    service_floor_exempt_area = service_floor_area_total if service_floor_ok else 0.0
    service_floor_chargeable_area = 0.0 if service_floor_ok else service_floor_area_total
    total_floor_area += service_floor_chargeable_area

    # 5. Balcony / chajja / cantilever projections — exempt up to the
    #    threshold width; only the excess is chargeable. These polygons are
    #    never part of `floor_areas`, so the chargeable slice is added.
    balcony_entities    = model.get_entities(CANTILEVER_BALCONY_COLOR, "LWPOLYLINE")
    chajja_entities     = model.get_entities(CHAJJA_PROJECTION_COLOR, "LWPOLYLINE")
    projection_entities = model.get_entities(CANTILEVER_PROJECTION_COLOR, "LWPOLYLINE")

    balcony_chargeable    = _fmt(chargeable_projection_area(balcony_entities, balcony_limit))
    chajja_chargeable     = _fmt(chargeable_projection_area(chajja_entities, balcony_limit))
    projection_chargeable = _fmt(chargeable_projection_area(projection_entities, balcony_limit))
    total_floor_area += balcony_chargeable + chajja_chargeable + projection_chargeable

    # 6. Ancillary rooms — always fully FAR-exempt. These sit inside the
    #    already-extracted floor polygons, so they are *deducted*.
    guard_room_area  = _fmt(_area(model, NON_FAR["guard_room_area"]))
    meter_room_area  = _fmt(_area(model, NON_FAR["meter_room_area"]))
    mumty_area       = _fmt(_area(model, NON_FAR["mumty_area"]))
    stairs_area      = _fmt(_sum_area(model, NON_FAR["stairs_area"]))
    fire_stairs_area = _fmt(_sum_area(model, NON_FAR["fire_stairs"]))
    shaft_area       = _fmt(_sum_area(model, NON_FAR["shaft_area"]))
    lift_area        = _fmt(_sum_area(model, NON_FAR["lift_area"]))
    pump_room_area       = _fmt(_sum_area(model, PUMP_ROOM_COLOR))
    ac_room_area         = _fmt(_sum_area(model, AC_ROOM_COLOR))
    substation_area      = _fmt(_sum_area(model, OPEN_TRANSFORMER_COLOR))
    watchman_booth_area  = _fmt(_sum_area(model, WATCHMAN_SHELTER_COLOR))

    ancillary_exempt_area = _fmt(
        guard_room_area + meter_room_area + mumty_area + stairs_area +
        fire_stairs_area + shaft_area + lift_area + pump_room_area +
        ac_room_area + substation_area + watchman_booth_area
    )
    total_floor_area = _fmt(total_floor_area - ancillary_exempt_area)

    far_area = _fmt(total_floor_area)
    far_value = _fmt(far_area / plot_area) if plot_area else 0.0

    return {
        "far_area": far_area,
        "far_value": far_value,
        "far_exempt_breakdown": {
            "is_industrial": is_industrial,
            "is_pharma": is_pharma,
            "balcony_limit_m": balcony_limit,
            "stilt_floor_area_total": stilt_area_total,
            "stilt_floor_qualifies": stilt_ok,
            "stilt_floor_exempt_area": _fmt(stilt_exempt_area),
            "stilt_floor_chargeable_area": _fmt(stilt_chargeable_area),
            "basement_exempt_area": basement_exempt_area,
            "service_floor_area_total": service_floor_area_total,
            "service_floor_qualifies": service_floor_ok,
            "service_floor_exempt_area": _fmt(service_floor_exempt_area),
            "service_floor_chargeable_area": _fmt(service_floor_chargeable_area),
            "balcony_chargeable_area": balcony_chargeable,
            "chajja_chargeable_area": chajja_chargeable,
            "cantilever_projection_chargeable_area": projection_chargeable,
            "guard_room_area": guard_room_area,
            "meter_room_area": meter_room_area,
            "mumty_area": mumty_area,
            "stairs_area": stairs_area,
            "fire_stairs_area": fire_stairs_area,
            "shaft_area": shaft_area,
            "lift_area": lift_area,
            "pump_room_area": pump_room_area,
            "ac_room_area": ac_room_area,
            "substation_area": substation_area,
            "watchman_booth_area": watchman_booth_area,
            "total_ancillary_exempt_area": ancillary_exempt_area,
        },
    }


# ---------------------------------------------------------------------------
# Building Height calculation
# ---------------------------------------------------------------------------

def calculate_building_height(
    model: CADModel,
    floor_areas: dict[str, float],
    building_type: str = "",
    terrain: str = "",
    stilt_height: float = 0.0,
    stilt_qualifies: bool = True,
    second_stilt_height: float = 0.0,
    second_stilt_used_for_parking: bool = True,
    service_floor_height: float = 0.0,
    basement_height_above_ground: float = 0.0,
    terrace_ratio_within_limit: bool = True,
    roof_feature_height: float = 0.0,
) -> dict[str, Any]:
    """
    Compute Building Height from a CADModel, applying every height
    relaxation clause in Section 3 ("Building Height") of the SIDA /
    UGIDCR / UHUDA byelaws, and cross-check the result against the height
    the drawing already declares (color 151, "Height Of the Building after
    exemptions") so a mismatch between the architect's drawn value and the
    byelaw-computed value can be flagged.

    Building Height (measured from plinth top) = the floor-to-floor stack
    of ordinary levels + every height-contributing feature that does NOT
    qualify for exemption.

    Parameters
    ----------
    model : CADModel
    floor_areas : dict[str, float]
        Ground + numbered floor areas — drives the floor count multiplied
        by the typical floor-to-floor height (color 233).
    building_type : str
        Kept for context/messaging; the height thresholds below are not
        building-type specific (unlike the FAR balcony threshold).
    terrain : str
        "hill" or "plain".
        - Hilly areas: "No relaxation in building height for stilt floor
          or sloping roof" — a stilt floor is always counted, and a 2nd
          stilt floor is not permitted at all.
        - Plain areas: stilt floor exemption logic follows the same
          <= 2.4 m rule used for FAR.
    stilt_height : float
        Stilt floor clear height (color 21).
    stilt_qualifies : bool
        Whether the stilt floor otherwise qualifies as a byelaw "Stilt
        Floor" (open >= 3 sides, parking/services use only). Not
        derivable from 2D geometry alone.
    second_stilt_height : float
        Height of a 2nd stilt floor, if present. Always counted towards
        Building Height when used for parking (even though it remains
        FAR-exempt), and is invalid entirely in hilly areas.
    service_floor_height : float
        Service floor clear height (color 89). Exempt if <= 2.4 m.
    basement_height_above_ground : float
        Basement ceiling height above natural ground level. No dedicated
        CAD color exists for this measurement, so it is accepted as an
        explicit input (defaults to 0 = fully below ground = exempt).
        Exempt if <= 1.2 m; only the excess beyond 1.2 m counts.
    terrace_ratio_within_limit : bool
        Whether (mumty + lift room + roof tank + chimney + parapet +
        decoration features) / total terrace area is < 20% — the umbrella
        condition the byelaw attaches to every terrace-level relaxation.
        Defaults to True; if False, none of the terrace features below
        are exempt regardless of their individual height.
    roof_feature_height : float
        Combined roof-top water tank / parapet / chimney / decoration
        feature height, if tracked (no dedicated color per feature in the
        layer spec) — exempt up to 1.5 m, gated by
        ``terrace_ratio_within_limit``.

    Returns
    -------
    dict with keys: computed_building_height, drawn_building_height,
    height_mismatch (bool, > 0.05 m tolerance), and
    height_exempt_breakdown (every component + whether it was exempted).
    """
    is_hilly = (terrain or "").strip().lower().startswith("hill")

    # 1. Drawn / declared height (architect-computed, color 151) — kept for
    #    cross-validation, never blindly trusted as the final answer.
    drawn_building_height = _fmt(_length(model, BUILDING_HEIGHT_DRAWN_COLOR))

    # 2. Typical floor stack — floor-to-floor height x number of levels
    #    already extracted as ordinary (non-exempt) floor plates.
    floor_to_floor_height = _fmt(_length(model, FLOOR_TO_FLOOR_HEIGHT_COLOR))
    num_levels = len(floor_areas)
    floor_stack_height = _fmt(floor_to_floor_height * num_levels)

    # 3. Stilt floor — exempt from height only in PLAIN areas, height
    #    <= 2.4 m, and only if it otherwise qualifies. Hilly areas get
    #    "No relaxation in building height for stilt floor" — always counted.
    stilt_ok = (not is_hilly) and stilt_qualifies and 0 < stilt_height <= STILT_HEIGHT_LIMIT_M
    stilt_counted_height = 0.0 if stilt_ok else stilt_height

    # 4. 2nd stilt floor — not permitted at all in hilly areas; in plain
    #    areas it always counts towards height (parking use or not).
    second_stilt_not_permitted_in_hilly = is_hilly and second_stilt_height > 0
    second_stilt_counted_height = 0.0 if is_hilly else second_stilt_height

    # 5. Service floor — exempt from height if <= 2.4 m.
    service_floor_ok = 0 < service_floor_height <= SERVICE_FLOOR_HEIGHT_LIMIT_M
    service_floor_counted_height = 0.0 if service_floor_ok else service_floor_height

    # 6. Basement — exempt if <= 1.2 m above ground; only the excess beyond
    #    1.2 m counts towards Building Height.
    basement_counted_height = _fmt(max(0.0, basement_height_above_ground - BASEMENT_ABOVE_GROUND_LIMIT_M))

    # 7. Mumty — exempt <= 2.4 m, gated by the 20% terrace-area condition.
    mumty_height = _fmt(_length(model, MUMTY_HEIGHT_COLOR))
    mumty_ok = terrace_ratio_within_limit and 0 < mumty_height <= MUMTY_HEIGHT_LIMIT_M
    mumty_counted_height = 0.0 if mumty_ok else mumty_height

    # 8. Lift machine room — exempt <= 4.2 m, gated by the same condition.
    machine_room_height = _fmt(_length(model, MACHINE_ROOM_HEIGHT_COLOR))
    machine_room_ok = terrace_ratio_within_limit and 0 < machine_room_height <= MACHINE_ROOM_HEIGHT_LIMIT_M
    machine_room_counted_height = 0.0 if machine_room_ok else machine_room_height

    # 9. Roof-top water tank / parapet / chimney / decoration features —
    #    exempt <= 1.5 m each, same 20% gate. Tracked as one combined value
    #    since no per-feature color code exists in the layer spec.
    roof_feature_ok = terrace_ratio_within_limit and 0 < roof_feature_height <= ROOF_FEATURE_HEIGHT_LIMIT_M
    roof_feature_counted_height = 0.0 if roof_feature_ok else roof_feature_height

    computed_building_height = _fmt(
        floor_stack_height
        + stilt_counted_height
        + second_stilt_counted_height
        + service_floor_counted_height
        + basement_counted_height
        + mumty_counted_height
        + machine_room_counted_height
        + roof_feature_counted_height
    )

    height_mismatch = abs(computed_building_height - drawn_building_height) > 0.05

    return {
        "computed_building_height": computed_building_height,
        "drawn_building_height": drawn_building_height,
        "height_mismatch": height_mismatch,
        "height_exempt_breakdown": {
            "is_hilly": is_hilly,
            "floor_to_floor_height": floor_to_floor_height,
            "num_levels": num_levels,
            "floor_stack_height": floor_stack_height,
            "stilt_height": stilt_height,
            "stilt_exempt": stilt_ok,
            "stilt_counted_height": _fmt(stilt_counted_height),
            "second_stilt_height": second_stilt_height,
            "second_stilt_not_permitted_in_hilly": second_stilt_not_permitted_in_hilly,
            "second_stilt_counted_height": _fmt(second_stilt_counted_height),
            "service_floor_height": service_floor_height,
            "service_floor_exempt": service_floor_ok,
            "service_floor_counted_height": _fmt(service_floor_counted_height),
            "basement_height_above_ground": basement_height_above_ground,
            "basement_counted_height": basement_counted_height,
            "mumty_height": mumty_height,
            "mumty_exempt": mumty_ok,
            "mumty_counted_height": _fmt(mumty_counted_height),
            "machine_room_height": machine_room_height,
            "machine_room_exempt": machine_room_ok,
            "machine_room_counted_height": _fmt(machine_room_counted_height),
            "roof_feature_height": roof_feature_height,
            "roof_feature_exempt": roof_feature_ok,
            "roof_feature_counted_height": _fmt(roof_feature_counted_height),
            "terrace_ratio_within_limit": terrace_ratio_within_limit,
        },
    }


# ---------------------------------------------------------------------------
# Public metric derivation
# ---------------------------------------------------------------------------

def derive_metrics(
    model: CADModel,
    building_type: str,
    subtype: str,
    terrain: str,
    location: str = "",
) -> dict[str, Any]:
    """
    Derive all SIDA architectural metrics from a CADModel.

    Operates directly on CADModel indexes — no CSV, no DataFrame.
    Returns the same flat dict shape as the original derive_metrics(df).

    Parameters
    ----------
    model : CADModel
        Output of parse_dxf_to_cad_model().
    building_type : str
        "Residential" | "Commercial" | "Industrial" | "Mall" |
        "Institutional" | "Other". Drives the FAR balcony/projection
        exemption threshold (1.2 m for Industrial, 1.8 m otherwise).
    subtype : str
        e.g. "Multiple Units", "Group Housing", "Group Housing Flatted",
        "Affordable Housing", "Pharmaceutical" … Only affects reporting
        (e.g. pharma multi-service-floor context); free-form since the
        byelaw subtype list is long and building-type specific.
    terrain : str
        "Hill" | "Plain". Governs the stilt-floor / 2nd-stilt-floor
        Building Height exemption rules (Section 3 of the byelaws) —
        NOT the same field as ``location``.
    location : str
        "Rural" | "Urban". Not yet used in the geometry/exemption
        arithmetic (kept for future rule.json matching and for
        echoing back in the report); accepted so callers can pass it
        through without it being silently dropped.

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

    ground_coverage  = _fmt(_area(model, 10))


    # heights
    building_height = _fmt(_length(model, 151))  #height of building after excemption
    plinth_height = _fmt(_length(model, 105))
    mumty_height    = _fmt(_length(model, 45))
    stilth_floor_height = _fmt(_length(model, 21))
    machine_room_height = _fmt(_length(model, 46))

    # NON FAR (also recomputed inside calculate_far() for the FAR breakdown;
    # kept here too since total_ground_floor_area / chargable_area need them)
    guard_room_area             = _fmt(_area(model, 182))
    meter_room_area             = _fmt(_area(model, 192))
    mumty_area             = _fmt(_area(model, 9))
    stairs_area            = _fmt(_sum_area(model, 115))
    fire_stairs            = _fmt(_sum_area(model, 116))

    # --- Parking ---
    open_parking_area       = _fmt(_sum_area(model, 20))
    car_parking_area        = _fmt(_sum_area(model, 140))
    mechanical_parking_area = _fmt(_sum_area(model, 213))
    stilt_parking_area      = _fmt(_sum_area(model, 15))
    basement_parking_area   = _fmt(_sum_area(model, 31))

    # --- Ancillary ---
    
    landscape_area             = _fmt(_sum_area(model, 60))
    canopy_area            = _fmt(_sum_area(model, 184))
    
    loading_unloading_area = _fmt(_sum_area(model, 221))
    rain_water_harvesting  = _fmt(_sum_area(model, RWH_AREA_COLOR))
    rwh_height              = _fmt(_length(model, RWH_HEIGHT_COLOR))
    rwh_volume              = _fmt(rain_water_harvesting * rwh_height)
    required_rwh_volume     = calculate_required_rwh_volume(ground_coverage)

    # --- Derived totals ---
    ground_area             = floor_areas.get("ground", 0.0)

    total_ground_floor_area = _fmt(ground_area + guard_room_area + meter_room_area)

    total_floor_area     = _fmt(sum(floor_areas.values()))

    # --- FAR (handles stilt / basement / service floor / balcony-projection
    #     / ancillary-room exemptions — see calculate_far()) ---
    far_result = calculate_far(
        model=model,
        floor_areas=floor_areas,
        plot_area=plot_area,
        building_type=building_type,
        subtype=subtype,
        terrain=terrain,
        stilt_height=stilth_floor_height,
        service_floor_height=_fmt(_length(model, SERVICE_FLOOR_HEIGHT_COLOR)),
    )
    far_area  = far_result["far_area"]
    far_value = far_result["far_value"]

    required_loading_unloading_area = calculate_required_loading_unloading_area(far_area)

    # --- Building Height (handles stilt / 2nd-stilt / service floor /
    #     basement / mumty / lift-machine-room / roof-feature exemptions
    #     and hilly-area restrictions — see calculate_building_height()) ---
    height_result = calculate_building_height(
        model=model,
        floor_areas=floor_areas,
        building_type=building_type,
        terrain=terrain,
        stilt_height=stilth_floor_height,
    )
    computed_building_height = height_result["computed_building_height"]
    building_height_mismatch = height_result["height_mismatch"]

    ground_coverage_percentage = _fmt(ground_coverage / plot_area * 100) if plot_area else 0.0

    open_area               = _fmt(plot_area - total_ground_floor_area)

    chargable_area          = _fmt(sum(floor_areas.values()) + mumty_area + guard_room_area + meter_room_area)

    covered_area            = chargable_area

    # --- Parking permissible ---
    plot_usage = 0.3 if plot_area < 1000 else 0.5
    ecs        = (far_area * plot_usage) / 100
    permissible_open_parking       = _fmt(ecs * 23)
    permissible_stilt_parking      = _fmt(ecs * 28)
    permissible_basement_parking   = _fmt(ecs * 32)
    permissible_mechanical_parking = _fmt(ecs * 64)
    
    return {
        # Request context (echoed back for reporting/debugging)
        "building_type": building_type,
        "subtype":       subtype,
        "terrain":       terrain,
        "location":      location,
        # Plot
        "plot_area":               plot_area,
        # Floors
        "floor_areas":             floor_areas,
        "total_floor_builtup":     total_floor_area,

        "total_ground_floor_area": total_ground_floor_area,
        # "total_stair_case_area":   total_stair_case_area,
        # Setbacks
        "front_set_back":              front_set_back,
        "front_set_back_length":          front_set_back_len,
        "rear_set_back":               rear_set_back,
        "rear_set_back_length":           rear_set_back_len,
        "side_setback_distance1":      side_setback_distance1,
        "side_setback_distance1_length":  side_setback_distance1_len,
        "side_setback_distance2":      side_setback_distance2,
        "side_setback_distance2_length":  side_setback_distance2_len,

        # Road / height
        "road_width":      road_width,
        "building_height": building_height,
        "computed_building_height": computed_building_height,
        "building_height_mismatch": building_height_mismatch,
        "height_exempt_breakdown":  height_result["height_exempt_breakdown"],
        "mumty_height":    mumty_height,
        "plinth_height": plinth_height,
        "stilth_floor_height": stilth_floor_height,
        "machine_room_height": machine_room_height,


        # Coverage / FAR
        "ground_coverage":          ground_coverage,
        "ground_coverage_percentage": ground_coverage_percentage,
        "far_area":                far_area,
        "far_value":               far_value,
        "far_exempt_breakdown":    far_result["far_exempt_breakdown"],
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
        "guard_room_area":              guard_room_area,
        "meter_room_area":              meter_room_area,
        "mumty_area":              mumty_area,
        "landscape_area":              landscape_area,
        "canopy_area":             canopy_area,
        "stairs_area":             stairs_area,
        "fire_stairs":             fire_stairs,
        "loading_unloading_area":          loading_unloading_area,
        "required_loading_unloading_area": required_loading_unloading_area,
        "rain_water_harvesting":   rain_water_harvesting,
        "rwh_height":              rwh_height,
        "rwh_volume":              rwh_volume,
        "required_rwh_volume":     required_rwh_volume,
    }
