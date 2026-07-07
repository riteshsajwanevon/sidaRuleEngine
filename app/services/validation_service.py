# -*- coding: utf-8 -*-
"""
Validation Service
------------------
Orchestrates metric extraction → rule matching → validation → report
for the POST /process-validate-dxf endpoint.

Pipeline:
    CADModel
        └── derive_metrics(model)           [metrics.py]
                └── _run_inline_rule_validation(metrics, rules)
                        └── build_report(metrics, result, file_name)
                                └── run_validation_from_cad_model() → response dict

Extension points for future geometry rules:
    Add validate_setbacks(), validate_intersections(), etc. as functions
    that accept a CADModel and return list[str] failures, then wire them
    into run_validation_from_cad_model() alongside the metric checks.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.cad_model import CADModel
from app.services.metrics import derive_metrics

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rule schema helpers
# ---------------------------------------------------------------------------

def _value_in_range(
    value: float,
    min_value: Any = None,
    max_value: Any = None,
) -> bool:
    if min_value is not None and value < float(min_value):
        return False
    if max_value is not None and value > float(max_value):
        return False
    return True


def _get_applicable_rule(
    plot_area: float,
    road_width: float,
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Match plot_area and road_width against the hierarchical rule.json schema.

    Returns one of:
        {"success": True,  "rule": ..., "road_rule": ...}
        {"success": False, "failed_at": "road_width", "rule": ..., ...}
        {"success": False, "failed_at": "plot_area",  ...}
    """
    for rule in rules:
        if not _value_in_range(plot_area, rule.get("plot_area_min"), rule.get("plot_area_max")):
            continue

        for road_rule in rule.get("road_rules", []):
            if _value_in_range(road_width, road_rule.get("road_width_min"), road_rule.get("road_width_max")):
                return {"success": True, "rule": rule, "road_rule": road_rule}

        return {
            "success": False,
            "failed_at": "road_width",
            "rule": rule,
            "road_width": road_width,
            "available_road_ranges": [
                {
                    "road_width_min": rr.get("road_width_min"),
                    "road_width_max": rr.get("road_width_max"),
                }
                for rr in rule.get("road_rules", [])
            ],
        }

    return {
        "success": False,
        "failed_at": "plot_area",
        "plot_area": plot_area,
        "available_plot_ranges": [
            {
                "plot_area_min": r.get("plot_area_min"),
                "plot_area_max": r.get("plot_area_max"),
            }
            for r in rules
        ],
    }


def _get_required_setbacks(road_rule: dict[str, Any], height: float) -> dict[str, Any] | None:
    """Return setback requirements for the matching height band."""
    for band in road_rule.get("height_bands", []):
        if _value_in_range(height, band.get("height_min"), band.get("height_max")):
            return band.get("setbacks", {})
    return None


# ---------------------------------------------------------------------------
# Exemption-breakdown diagnostics (calculate_far / calculate_building_height)
# ---------------------------------------------------------------------------

def _check_height_exemptions(metrics: dict[str, Any]) -> tuple[list[str], list[str]]:
    """
    Surface discrepancies between the drawn ("Height Of the Building after
    exemptions", color 151) and byelaw-computed building height, plus any
    individual exemption clause (stilt / 2nd stilt / service floor / mumty /
    lift machine room) that failed to qualify.

    Returns (pass_notes, fail_notes).
    """
    pass_list: list[str] = []
    fail_list: list[str] = []

    drawn    = metrics.get("building_height")
    computed = metrics.get("computed_building_height")
    if drawn is not None and computed is not None:
        if metrics.get("building_height_mismatch"):
            fail_list.append(
                f"Building Height Mismatch : Drawn (color 151) = {drawn} m, "
                f"Computed (post-exemption) = {computed} m — verify stilt / service floor / "
                f"mumty / lift-machine-room heights and basement depth used for exemptions."
            )
        else:
            pass_list.append(
                f"Building Height Check : Drawn = {drawn} m matches Computed (post-exemption) = {computed} m"
            )

    breakdown = metrics.get("height_exempt_breakdown") or {}
    if breakdown:
        if breakdown.get("second_stilt_not_permitted_in_hilly"):
            fail_list.append(
                "2nd Stilt Floor : Not permitted in hilly areas — its height has been counted "
                "towards Building Height."
            )

        if breakdown.get("stilt_height", 0) > 0 and not breakdown.get("stilt_exempt"):
            pass_list.append(
                f"Note — Stilt Floor Height Exemption not applied : height = {breakdown.get('stilt_height')} m "
                f"(needs <= 2.4 m, plain area, qualifying parking/services use); counted towards Building Height."
            )

        if breakdown.get("service_floor_height", 0) > 0 and not breakdown.get("service_floor_exempt"):
            pass_list.append(
                f"Note — Service Floor Height Exemption not applied : height = "
                f"{breakdown.get('service_floor_height')} m exceeds the 2.4 m limit; "
                f"counted towards Building Height."
            )

        if breakdown.get("mumty_height", 0) > 0 and not breakdown.get("mumty_exempt"):
            pass_list.append(
                f"Note — Mumty Height Exemption not applied : height = {breakdown.get('mumty_height')} m "
                f"(needs <= 2.4 m and terrace-feature ratio < 20%); counted towards Building Height."
            )

        if breakdown.get("machine_room_height", 0) > 0 and not breakdown.get("machine_room_exempt"):
            pass_list.append(
                f"Note — Lift Machine Room Height Exemption not applied : height = "
                f"{breakdown.get('machine_room_height')} m (needs <= 4.2 m and terrace-feature ratio < 20%); "
                f"counted towards Building Height."
            )

    return pass_list, fail_list


def _check_far_exemptions(metrics: dict[str, Any]) -> tuple[list[str], list[str]]:
    """
    Surface which FAR-relaxation clauses (stilt / service floor / balcony
    projections) did not qualify and were therefore added to the chargeable
    FAR area — informational, since `far_value` already reflects this.

    Returns (pass_notes, fail_notes).
    """
    pass_list: list[str] = []
    fail_list: list[str] = []

    breakdown = metrics.get("far_exempt_breakdown") or {}
    if not breakdown:
        return pass_list, fail_list

    if breakdown.get("stilt_floor_area_total", 0) > 0 and not breakdown.get("stilt_floor_qualifies"):
        pass_list.append(
            f"Note — Stilt Floor FAR Exemption not applied : "
            f"{breakdown.get('stilt_floor_chargeable_area')} Sq.M added to chargeable FAR area "
            f"(height/use does not qualify)."
        )

    if breakdown.get("service_floor_area_total", 0) > 0 and not breakdown.get("service_floor_qualifies"):
        pass_list.append(
            f"Note — Service Floor FAR Exemption not applied : "
            f"{breakdown.get('service_floor_chargeable_area')} Sq.M added to chargeable FAR area "
            f"(height > 2.4 m)."
        )

    total_projection_chargeable = round(
        (breakdown.get("balcony_chargeable_area") or 0)
        + (breakdown.get("chajja_chargeable_area") or 0)
        + (breakdown.get("cantilever_projection_chargeable_area") or 0),
        2,
    )
    if total_projection_chargeable > 0:
        pass_list.append(
            f"Note — Balcony/Projection FAR Exemption : {total_projection_chargeable} Sq.M beyond the "
            f"{breakdown.get('balcony_limit_m')} m relaxed width added to chargeable FAR area."
        )

    return pass_list, fail_list


# ---------------------------------------------------------------------------
# Core validation logic
# ---------------------------------------------------------------------------

def _run_validation(
    metrics: dict[str, Any],
    rules: list[dict[str, Any]],
    building_type: str,
    subtype: str,
    terrain: str,
    location: str,
) -> dict[str, Any]:
    """
    Validate derived metrics against the hierarchical rule.json schema.
    Returns {"status", "failures", "details", "applicable_rule"}.
    """
    plot_area          = metrics["plot_area"]
    road_width         = metrics["road_width"]
    far_value          = metrics["far_value"]
    ground_coverage_percentage = metrics["ground_coverage_percentage"]
    building_height    = metrics["building_height"]

    # Exemption-breakdown diagnostics — independent of rule.json matching,
    # so computed up front and merged into every return path below.
    height_exempt_pass, height_exempt_fail = _check_height_exemptions(metrics)
    far_exempt_pass,    far_exempt_fail    = _check_far_exemptions(metrics)
    exempt_pass_list = height_exempt_pass + far_exempt_pass
    exempt_fail_list = height_exempt_fail + far_exempt_fail

    match = _get_applicable_rule(plot_area, road_width, rules)

    # No plot area matched
    if not match["success"] and match.get("failed_at") == "plot_area":
        ranges = ", ".join(
            f"{r['plot_area_min']}–{r['plot_area_max']} Sq.M"
            for r in match["available_plot_ranges"]
        )
        return {
            "status": "FAIL",
            "failures": [
                f"Plot Area : In Map = {plot_area} Sq.M does not fall within any "
                f"defined plot area range. Available ranges: {ranges}."
            ] + exempt_fail_list,
            "details": exempt_pass_list,
            "applicable_rule": None,
        }

    pass_list: list[str] = list(exempt_pass_list)
    fail_list: list[str] = list(exempt_fail_list)
    rule = match["rule"]

    # Plot-level checks
    allowed_far = rule.get("far")
    if allowed_far is not None:
        if far_value > float(allowed_far):
            fail_list.append(f"FAR : Allowed <= {allowed_far}, In Map = {far_value}")
        else:
            pass_list.append(f"FAR : In Map = {far_value}, Allowed <= {allowed_far}")

    allowed_cov = rule.get("max_ground_coverage_percent")
    if allowed_cov is not None:
        if ground_coverage_percentage > float(allowed_cov):
            fail_list.append(
                f"Ground Coverage Percent : Allowed <= {float(allowed_cov):.2f}%, "
                f"In Map = {ground_coverage_percentage}%"
            )
        else:
            pass_list.append(
                f"Ground Coverage Percent : In Map = {ground_coverage_percentage}%, "
                f"Allowed <= {float(allowed_cov):.2f}%"
            )
    # Only for IT Industries (subtype != "IT Units") do we check the loading/unloading area requirement.
    # Loading/Unloading area: required = 26.25 Sq.M, scaled up by
    # (FAR area / 1000) once FAR area exceeds 1000 Sq.M — see
    # calculate_required_loading_unloading_area() in metrics.py.
    # rule.json may override the computed value via "min_loading_unloading_area".
    if building_type.lower() == "it_industries" and subtype.lower() != "it_units":
        required_loading_area = rule.get("min_loading_unloading_area")
        if required_loading_area is None:
            required_loading_area = metrics.get("required_loading_unloading_area")
        if required_loading_area is not None:
            loading_unloading_area = metrics.get("loading_unloading_area", 0.0)
            if loading_unloading_area < float(required_loading_area):
                fail_list.append(
                    f"Loading/Unloading Area : Allowed >= {required_loading_area} Sq.M, "
                    f"In Map = {loading_unloading_area} Sq.M"
                )
            else:
                pass_list.append(
                    f"Loading/Unloading Area : In Map = {loading_unloading_area} Sq.M, "
                    f"Allowed >= {required_loading_area} Sq.M"
                )

    # Rain Water Harvesting volume: required = 3.5 cu.m up to 400 Sq.M ground
    # coverage, scaling above that as ((coverage - 400) * 0.5 / 50) + 3.5 —
    # see calculate_required_rwh_volume() in metrics.py.
    required_rwh_volume = metrics.get("required_rwh_volume")
    if required_rwh_volume is not None:
        rwh_volume = metrics.get("rwh_volume", 0.0)
        if rwh_volume < float(required_rwh_volume):
            fail_list.append(
                f"Rain Water Harvesting Volume : Allowed >= {required_rwh_volume} Cu.M, "
                f"In Map = {rwh_volume} Cu.M"
            )
        else:
            pass_list.append(
                f"Rain Water Harvesting Volume : In Map = {rwh_volume} Cu.M, "
                f"Allowed >= {required_rwh_volume} Cu.M"
            )

    # Road width mismatch — diagnostic failure, no further checks possible
    if not match["success"]:
        ranges = ", ".join(
            f"{r['road_width_min']}–{r['road_width_max']} m"
            for r in match["available_road_ranges"]
        )
        fail_list.append(
            f"Road Width : In Map = {road_width} m does not match any defined "
            f"road width range for this plot area rule "
            f"({rule.get('plot_area_min')}–{rule.get('plot_area_max')} Sq.M). "
            f"Available road width ranges: {ranges}. "
            f"Building height and setback checks require a matching road rule."
        )
        return {
            "status": "FAIL",
            "failures": fail_list,
            "details": pass_list,
            "applicable_rule": {"rule": rule, "road_rule": None},
        }

    road_rule = match["road_rule"]

    # Road-level checks
    max_height = road_rule.get("max_building_height")
    if max_height is not None:
        if building_height > float(max_height):
            fail_list.append(
                f"Building Height : Allowed <= {max_height} m, In Map = {building_height} m"
            )
        else:
            pass_list.append(
                f"Building Height : In Map = {building_height} m, Allowed <= {max_height} m"
            )

    setbacks = _get_required_setbacks(road_rule, building_height)
    if setbacks:
        provided = {
            "front": metrics["front_set_back"],
            "rear":  metrics["rear_set_back"],
            "side1": metrics["side_setback_distance1"],
            "side2": metrics["side_setback_distance2"],
        }
        labels = {"front": "Front", "rear": "Rear", "side1": "Side 1", "side2": "Side 2"}
        for key, current in provided.items():
            req = setbacks.get(key)
            if req is None:
                continue
            if current < float(req):
                fail_list.append(
                    f"{labels[key]} Setback : Allowed >= {req} m, In Map = {current} m"
                )
            else:
                pass_list.append(
                    f"{labels[key]} Setback : In Map = {current} m, Allowed >= {req} m"
                )

        # Green/Landscape Area: required = 25% of total setback area, where
        # setback area is built from each side's drawn setback-line length
        # times the rule-required setback dimension for that side.
        required_front = setbacks.get("front")
        required_rear  = setbacks.get("rear")
        required_side1 = setbacks.get("side1")
        required_side2 = setbacks.get("side2")
        if None not in (required_front, required_rear, required_side1, required_side2):
            required_front = float(required_front)
            required_rear  = float(required_rear)
            required_side1 = float(required_side1)
            required_side2 = float(required_side2)

            all_set_back_area = (
                (metrics["front_set_back_length"] * required_front)
                + (metrics["rear_set_back_length"] * required_rear)
                + ((metrics["side_setback_distance1_length"] - (required_front + required_rear)) * required_side1)
                + ((metrics["side_setback_distance2_length"] - (required_front + required_rear)) * required_side2)
            )
            required_green_area = round(all_set_back_area * 0.25, 2)
            green_area = metrics.get("landscape_area", 0.0)
            # Byelaw Section 11 exemption: Industrial buildings on plots
            # < 500 Sq.M are exempted from maintaining Green Cover entirely.
            is_industrial_green_exempt = (
                building_type.strip().lower() == "industries" and plot_area < 500
            )
            if is_industrial_green_exempt:
                pass_list.append(
                    f"Green/Landscape Area : Exempted (Industrial, Plot Area = {plot_area} Sq.M < 500 Sq.M)"
                )
            elif green_area < required_green_area:
                fail_list.append(
                    f"Green/Landscape Area : Allowed >= {required_green_area} Sq.M "
                    f"(25% of setback area = {round(all_set_back_area, 2)} Sq.M), In Map = {green_area} Sq.M"
                )
            else:
                pass_list.append(
                    f"Green/Landscape Area : In Map = {green_area} Sq.M, Allowed >= {required_green_area} Sq.M "
                    f"(25% of setback area = {round(all_set_back_area, 2)} Sq.M)"
                )

    return {
        "status": "PASS" if not fail_list else "FAIL",
        "failures": fail_list,
        "details": pass_list,
        "applicable_rule": {"rule": rule, "road_rule": road_rule},
    }


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def _build_report(
    metrics: dict[str, Any],
    validation_result: dict[str, Any],
    file_name: str,
) -> dict[str, Any]:
    floor_areas = metrics["floor_areas"]

    fetched: list[dict[str, Any]] = [
        {"label": "Plot Area", "value": metrics["plot_area"], "unit": "Sq.M"},
    ]

    for key, label in {
        "ground": "Existing Ground Floor Area",
        "first":  "Existing First Floor Area",
        "second": "Existing Second Floor Area",
        "third":  "Existing Third Floor Area",
        "fourth": "Existing Fourth Floor Area",
        "fifth":  "Existing Fifth Floor Area",
        "sixth":  "Existing Sixth Floor Area",
    }.items():
        if key in floor_areas:
            fetched.append({"label": label, "value": floor_areas[key], "unit": "Sq.M"})

    fetched += [
        {"label": "Total Ground Coverage (incl. Non-FAR)", "value": metrics["total_ground_floor_area"], "unit": "Sq.M"},
        {"label": "Front Setback",    "value": metrics["front_set_back"],         "unit": "M"},
        {"label": "Rear Setback",     "value": metrics["rear_set_back"],          "unit": "M"},
        {"label": "Side Setback (1)", "value": metrics["side_setback_distance1"], "unit": "M"},
        {"label": "Side Setback (2)", "value": metrics["side_setback_distance2"], "unit": "M"},
        {"label": "Road Width",       "value": metrics["road_width"],             "unit": "M"},
        {"label": "FAR Area",         "value": metrics["far_area"],               "unit": "Sq.M"},
        {"label": "FAR",              "value": metrics["far_value"],              "unit": ""},
        {"label": "Building Height (Drawn)",          "value": metrics["building_height"],           "unit": "M"},
        {"label": "Building Height (Computed, post-exemption)",
         "value": metrics.get("computed_building_height"), "unit": "M"},
        {"label": "Loading and Unloading Area (Provided)", "value": metrics["loading_unloading_area"], "unit": "Sq.M"},
        {"label": "Loading and Unloading Area (Required)",
         "value": metrics.get("required_loading_unloading_area"), "unit": "Sq.M"},
        {"label": "Rain Water Harvesting Volume (Provided)", "value": metrics.get("rwh_volume"), "unit": "Cu.M"},
        {"label": "Rain Water Harvesting Volume (Required)",
         "value": metrics.get("required_rwh_volume"), "unit": "Cu.M"},
    ]

    for key, label in [
        ("open_parking_area",       "Open Area Parking"),
        ("stilt_parking_area",      "Stilt Area Parking"),
        ("basement_parking_area",   "Basement Area Parking"),
        ("mechanical_parking_area", "Mechanical Area Parking"),
    ]:
        if metrics.get(key, 0) > 0:
            fetched.append({"label": label, "value": metrics[key], "unit": "Sq.M"})

    fetched += [
        {"label": "Guard/Meter Room Area",
         "value": round(metrics["guard_room_area"] + metrics["meter_room_area"], 2), "unit": "Sq.M"},
        {"label": "Mumty Area",           "value": metrics["mumty_area"],            "unit": "Sq.M"},
        {"label": "Covered Area",         "value": metrics["covered_area"],          "unit": "Sq.M"},
        {"label": "Ground Coverage",      "value": metrics["ground_coverage"],
         "unit": f"Sq.M ({metrics['ground_coverage_percentage']}%)"},
        {"label": "Open Area",            "value": metrics["open_area"],             "unit": "Sq.M"},
        {"label": "Total Chargeable Area","value": metrics["chargable_area"],        "unit": "Sq.M"},
    ]

    return {
        "file_name":         file_name,
        "fetched_details":   fetched,
        "passed_checks":     validation_result["details"],
        "failed_checks":     validation_result["failures"],
        "validation_status": validation_result["status"],
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_validation_from_cad_model(
    model: CADModel,
    rules: list[dict[str, Any]],
    building_type: str = "test",
    subtype: str = "test",
    terrain: str = "test",
    location: str = "test",
    file_name: str = "Uploaded DXF",
) -> dict[str, Any]:
    """
    Full validation pipeline: CADModel → metrics → rules → report.

    Parameters
    ----------
    model         : CADModel produced by parse_dxf_to_cad_model()
    rules         : Parsed rule_json list (hierarchical schema)
    building_type : "Residential" | "Commercial" | "Industrial" | "Mall" |
                    "Institutional" | "Other"
    subtype       : e.g. "Multiple Units", "Group Housing",
                    "Group Housing Flatted", "Affordable Housing" …
    terrain       : "Hill" | "Plain" — drives stilt/building-height
                    exemption rules. NOT the same as ``location``.
    location      : "Rural" | "Urban"
    file_name     : Used as report.file_name

    Returns
    -------
    {
        "validation_status": "PASS" | "FAIL",
        "applicable_rule":   {...} | None,
        "report":            {...},
        "errors":            [...]   # only present on FAIL
    }
    """
    if not isinstance(rules, list) or not rules:
        raise ValueError("rules must be a non-empty list.")

    metrics           = derive_metrics(model, building_type, subtype, terrain, location)
    validation_result = _run_validation(metrics, rules, building_type, subtype, terrain, location)
    report            = _build_report(metrics, validation_result, file_name)

    result: dict[str, Any] = {
        "validation_status": validation_result["status"],
        "applicable_rule":   validation_result.get("applicable_rule"),
        "report":            report,
    }
    if validation_result["status"] == "FAIL":
        result["errors"] = validation_result["failures"]

    return result
