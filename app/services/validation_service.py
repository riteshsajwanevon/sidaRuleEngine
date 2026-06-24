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
# Core validation logic
# ---------------------------------------------------------------------------

def _run_validation(
    metrics: dict[str, Any],
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Validate derived metrics against the hierarchical rule.json schema.
    Returns {"status", "failures", "details", "applicable_rule"}.
    """
    plot_area          = metrics["plot_area"]
    road_width         = metrics["road_width"]
    far_value          = metrics["far_value"]
    max_ground_cov_pct = metrics["max_ground_coverage_pre"]
    building_height    = metrics["building_height"]

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
            ],
            "details": [],
            "applicable_rule": None,
        }

    pass_list: list[str] = []
    fail_list: list[str] = []
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
        if max_ground_cov_pct > float(allowed_cov):
            fail_list.append(
                f"Ground Coverage Percent : Allowed <= {float(allowed_cov):.2f}%, "
                f"In Map = {max_ground_cov_pct}%"
            )
        else:
            pass_list.append(
                f"Ground Coverage Percent : In Map = {max_ground_cov_pct}%, "
                f"Allowed <= {float(allowed_cov):.2f}%"
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
        {"label": "Building Height",  "value": metrics["building_height"],        "unit": "M"},
        {"label": "Loading and Unloading Area", "value": metrics["loading_unloading_area"], "unit": "Sq.M"},
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
         "value": round(metrics["guard_room"] + metrics["meter_room"], 2), "unit": "Sq.M"},
        {"label": "Mumty Area",           "value": metrics["mumty_area"],            "unit": "Sq.M"},
        {"label": "Covered Area",         "value": metrics["covered_area"],          "unit": "Sq.M"},
        {"label": "Ground Coverage",      "value": metrics["max_ground_cov"],
         "unit": f"Sq.M ({metrics['max_ground_coverage_pre']}%)"},
        {"label": "Open Area",            "value": metrics["open_area"],             "unit": "Sq.M"},
        {"label": "Total Staircase Area", "value": metrics["total_stair_case_area"], "unit": "Sq.M"},
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
    location: str = "test",
    file_name: str = "Uploaded DXF",
    
) -> dict[str, Any]:
    """
    Full validation pipeline: CADModel → metrics → rules → report.

    Parameters
    ----------
    model     : CADModel produced by parse_dxf_to_cad_model()
    rules     : Parsed rule_json list (hierarchical schema)
    file_name : Used as report.file_name

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

    metrics           = derive_metrics(model , building_type, subtype, location)
    validation_result = _run_validation(metrics, rules)
    report            = _build_report(metrics, validation_result, file_name)

    result: dict[str, Any] = {
        "validation_status": validation_result["status"],
        "applicable_rule":   validation_result.get("applicable_rule"),
        "report":            report,
    }
    if validation_result["status"] == "FAIL":
        result["errors"] = validation_result["failures"]

    return result
