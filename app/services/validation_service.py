# -*- coding: utf-8 -*-
"""
Validation Service
------------------
Orchestrates CSV loading → metric derivation → rule matching → validation.

Responsibilities:
  - Load CSV for a given job_id
  - Derive metrics via csv_service
  - Apply New_JSON rules via new_json_service
  - Run the full validate() logic (reused from demo_sidaproject.py)
  - Generate a structured report dict

Original source: demo_sidaproject.py → validate(), location_matches(),
                 area_type_matches(), get_applicable_rule(),
                 get_required_setbacks(), report generation block.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from app.services.csv_service import derive_metrics, load_csv
from app.services.new_json_service import load_rules

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rule matching helpers  (reused verbatim from demo_sidaproject.py)
# ---------------------------------------------------------------------------

def location_matches(rule_location: str, input_location: str) -> bool:
    if rule_location == input_location:
        return True
    if rule_location == "Urban/Rural":
        return input_location in ("Urban", "Rural")
    return False


def area_type_matches(rule_area_type: str, input_area_type: str) -> bool:
    allowed_types = [t.strip().lower() for t in rule_area_type.split("/")]
    return input_area_type.strip().lower() in allowed_types


def get_applicable_rule(
    area_type: str,
    location: str,
    plot_area: float,
    road_width: float,
    rules: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Select the first matching rule for the given inputs."""
    for rule in rules:
        if not area_type_matches(rule["area_type"], area_type):
            continue
        if not location_matches(rule["location"], location):
            continue

        plot_max = rule["plot_max"]
        if not (rule["plot_min"] <= plot_area <= (plot_max if plot_max is not None else plot_area)):
            continue

        if road_width < rule["road_min"]:
            continue

        road_max = rule.get("road_max")
        if road_max is not None and road_width >= road_max:
            continue

        return rule

    return None


def get_required_setbacks(rule: dict[str, Any], height: float) -> dict[str, Any] | None:
    """Return the setback requirements for the applicable height band."""
    for band in rule.get("height_bands", []):
        if height <= band["h_max"]:
            return {
                "front": band["F"],
                "back": band["B"],
                "side1": band["S1"],
                "side2": band["S2"],
            }
    return None


# ---------------------------------------------------------------------------
# Core validation function  (reused from demo_sidaproject.py → validate())
# ---------------------------------------------------------------------------

def _run_validation(
    area_type: str,
    location: str,
    metrics: dict[str, Any],
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Run all validation checks against the applicable rule.

    Reused from demo_sidaproject.py → validate() function.
    Returns {"status": "PASS"|"FAIL", "failures": [...], "details": [...]}
    """
    plot_area = metrics["plot_area"]
    road_width = metrics["road_width"]
    far_value = metrics["far_value"]
    far_area = metrics["far_area"]
    max_ground_coverage_pre = metrics["max_ground_coverage_pre"]
    building_height = metrics["building_height"]
    floor_areas = metrics["floor_areas"]
    rain_water_harvesting = metrics["rain_water_harvesting"]
    loading_unloading_area = metrics["loading_unloading_area"]
    green_area = metrics["green_area"]
    front_set_back = metrics["front_set_back"]
    front_set_back_len = metrics["front_set_back_len"]
    rear_set_back = metrics["rear_set_back"]
    rear_set_back_len = metrics["rear_set_back_len"]
    side_setback_distance1 = metrics["side_setback_distance1"]
    side_setback_distance1_len = metrics["side_setback_distance1_len"]
    side_setback_distance2 = metrics["side_setback_distance2"]
    side_setback_distance2_len = metrics["side_setback_distance2_len"]
    open_parking_area = metrics["open_parking_area"]
    basement_parking_area = metrics["basement_parking_area"]
    stilt_parking_area = metrics["stilt_parking_area"]
    mechanical_parking_area = metrics["mechanical_parking_area"]
    permissible_open_parking = metrics["permissible_open_parking"]
    permissible_stilt_parking = metrics["permissible_stilt_parking"]
    permissible_basement_parking = metrics["permissible_basement_parking"]
    permissible_mechanical_parking = metrics["permissible_mechanical_parking"]

    rule = get_applicable_rule(area_type, location, plot_area, road_width, rules)

    if rule is None:
        return {
            "status": "FAIL",
            "failures": [
                f"No matching rule for plot_area={plot_area}, "
                f"location={location}, area_type={area_type}"
            ],
            "details": [],
        }

    pass_list: list[str] = []
    fail_list: list[str] = []

    # --- FAR ---
    if far_value > rule["FAR"]:
        fail_list.append(f"FAR : Allowed ≤ {rule['FAR']}, In Map = {far_value}")
    else:
        pass_list.append(f"FAR : In Map = {far_value}, Allowed ≤ {rule['FAR']}")

    # --- Ground coverage ---
    if rule["coverage_percent"] is not None:
        allowed_cov = rule["coverage_percent"]
        if max_ground_coverage_pre > allowed_cov:
            fail_list.append(
                f"Ground Coverage Percent : Allowed ≤ {allowed_cov:.2f}%, In Map = {max_ground_coverage_pre}%"
            )
        else:
            pass_list.append(
                f"Ground Coverage Percent : In Map = {max_ground_coverage_pre}%, Allowed ≤ {allowed_cov:.2f}%"
            )

    # --- Rain water harvesting ---
    ground_floor_area = floor_areas.get("ground", 0.0)
    min_req_har = ((ground_floor_area - 400) * 0.5 / 50) + 3.5 if ground_floor_area > 400 else 3.5
    depth = 6
    rwh_volume = rain_water_harvesting * depth
    if rwh_volume < min_req_har:
        fail_list.append(
            f"Rain Water Harvesting : Allowed ≥ {min_req_har:.2f} Cu.M, In Map = {rwh_volume:.2f} Cu.M"
        )
    else:
        pass_list.append(
            f"Rain Water Harvesting : In Map = {rwh_volume:.2f} Cu.M, Allowed ≥ {min_req_har:.2f} Cu.M"
        )

    # --- Loading / Unloading ---
    units = far_area / 1000
    required_lu = 26.25 if units <= 1 else 26.25 * units
    if loading_unloading_area < required_lu:
        fail_list.append(
            f"Loading/Unloading : Allowed ≥ {required_lu:.2f} Sq.M, In Map = {loading_unloading_area:.2f} Sq.M"
        )
    else:
        pass_list.append(
            f"Loading/Unloading : In Map = {loading_unloading_area} Sq.M, Allowed ≥ {required_lu:.2f} Sq.M"
        )

    # --- Building height ---
    max_h = rule["max_building_height"]
    if building_height > max_h:
        fail_list.append(f"Building Height : Allowed ≤ {max_h} m, In Map = {building_height} m")
    else:
        pass_list.append(f"Building Height : In Map = {building_height} m, Allowed ≤ {max_h} m")

    # --- Parking ---
    if open_parking_area > 0:
        if open_parking_area < permissible_open_parking:
            fail_list.append(
                f"Open Parking : Allowed ≥ {permissible_open_parking:.2f} Sq.M, In Map = {open_parking_area:.2f} Sq.M"
            )
        else:
            pass_list.append(
                f"Open Parking : In Map = {open_parking_area:.2f} Sq.M, Allowed ≥ {permissible_open_parking:.2f} Sq.M"
            )

    if basement_parking_area > 0:
        if basement_parking_area < permissible_basement_parking:
            fail_list.append(
                f"Basement Parking : Allowed ≥ {permissible_basement_parking:.2f} Sq.M, In Map = {basement_parking_area:.2f} Sq.M"
            )
        else:
            pass_list.append(
                f"Basement Parking : In Map = {basement_parking_area:.2f} Sq.M, Allowed ≥ {permissible_basement_parking:.2f} Sq.M"
            )

    if stilt_parking_area > 0:
        if stilt_parking_area < permissible_stilt_parking:
            fail_list.append(
                f"Stilt Parking : Allowed ≥ {permissible_stilt_parking:.2f} Sq.M, In Map = {stilt_parking_area:.2f} Sq.M"
            )
        else:
            pass_list.append(
                f"Stilt Parking : In Map = {stilt_parking_area:.2f} Sq.M, Allowed ≥ {permissible_stilt_parking:.2f} Sq.M"
            )

    if mechanical_parking_area > 0:
        if mechanical_parking_area < permissible_mechanical_parking:
            fail_list.append(
                f"Mechanical Parking : Allowed ≥ {permissible_mechanical_parking:.2f} Sq.M, In Map = {mechanical_parking_area:.2f} Sq.M"
            )
        else:
            pass_list.append(
                f"Mechanical Parking : In Map = {mechanical_parking_area:.2f} Sq.M, Allowed ≥ {permissible_mechanical_parking:.2f} Sq.M"
            )

    # --- Setbacks ---
    provided_setbacks = {
        "front": front_set_back,
        "back": rear_set_back,
        "side1": side_setback_distance1,
        "side2": side_setback_distance2,
    }

    if any(v > 0 for v in provided_setbacks.values()):
        required = get_required_setbacks(rule, building_height)
        if required:
            for key, label in {"front": "Front", "back": "Rear", "side1": "Side 1", "side2": "Side 2"}.items():
                current = provided_setbacks[key]
                req = required[key]
                if req is None:
                    continue
                if current < req:
                    fail_list.append(f"{label} Setback : Allowed ≥ {req} m, In Map = {current} m")
                else:
                    pass_list.append(f"{label} Setback : In Map = {current} m, Allowed ≥ {req} m")

            # --- Green area ---
            req_f = required["front"] or 0
            req_b = required["back"] or 0
            req_s1 = required["side1"] or 0
            req_s2 = required["side2"] or 0

            all_set_back_area = (
                (front_set_back_len * req_f)
                + (rear_set_back_len * req_b)
                + ((side_setback_distance1_len - (req_f + req_b)) * req_s1)
                + ((side_setback_distance2_len - (req_f + req_b)) * req_s2)
            ) * 0.25

            if green_area >= all_set_back_area:
                pass_list.append(
                    f"Green Area : In Map = {green_area} Sq.M, Allowed ≥ {all_set_back_area:.2f} Sq.M"
                )
            else:
                fail_list.append(
                    f"Green Area : Allowed ≥ {all_set_back_area:.2f} Sq.M, In Map = {green_area} Sq.M"
                )

    status = "PASS" if not fail_list else "FAIL"
    return {"status": status, "failures": fail_list, "details": pass_list}


# ---------------------------------------------------------------------------
# Report builder  (reused from demo_sidaproject.py → report generation block)
# ---------------------------------------------------------------------------

def build_report(
    metrics: dict[str, Any],
    validation_result: dict[str, Any],
    file_name: str = "Unknown",
) -> dict[str, Any]:
    """
    Build a structured report dict from metrics + validation result.

    Mirrors the text report from demo_sidaproject.py but returns structured data
    instead of a plain-text string.
    """
    floor_areas = metrics["floor_areas"]

    fetched_details: list[dict[str, Any]] = [
        {"label": "Plot Area", "value": metrics["plot_area"], "unit": "Sq.M"},
    ]

    for key, label in {
        "ground": "Existing Ground Floor Area",
        "first": "Existing First Floor Area",
        "second": "Existing Second Floor Area",
        "third": "Existing Third Floor Area",
        "fourth": "Existing Fourth Floor Area",
        "fifth": "Existing Fifth Floor Area",
        "sixth": "Existing Sixth Floor Area",
    }.items():
        if key in floor_areas:
            fetched_details.append({"label": label, "value": floor_areas[key], "unit": "Sq.M"})

    fetched_details += [
        {"label": "Total Ground Coverage (incl. Non-FAR)", "value": metrics["total_ground_floor_area"], "unit": "Sq.M"},
        {"label": "Front Setback", "value": metrics["front_set_back"], "unit": "M"},
        {"label": "Rear Setback", "value": metrics["rear_set_back"], "unit": "M"},
        {"label": "Side Setback (1)", "value": metrics["side_setback_distance1"], "unit": "M"},
        {"label": "Side Setback (2)", "value": metrics["side_setback_distance2"], "unit": "M"},
        {"label": "Road Width", "value": metrics["road_width"], "unit": "M"},
        {"label": "FAR Area", "value": metrics["far_area"], "unit": "Sq.M"},
        {"label": "FAR", "value": metrics["far_value"], "unit": ""},
        {"label": "Building Height", "value": metrics["building_height"], "unit": "M"},
        {"label": "Loading and Unloading Area", "value": metrics["loading_unloading_area"], "unit": "Sq.M"},
    ]

    for key, label in [
        ("open_parking_area", "Open Area Parking"),
        ("stilt_parking_area", "Stilt Area Parking"),
        ("basement_parking_area", "Basement Area Parking"),
        ("mechanical_parking_area", "Mechanical Area Parking"),
    ]:
        if metrics.get(key, 0) > 0:
            fetched_details.append({"label": label, "value": metrics[key], "unit": "Sq.M"})

    fetched_details += [
        {"label": "Guard/Meter Room Area", "value": round(metrics["guard_room"] + metrics["meter_room"], 2), "unit": "Sq.M"},
        {"label": "Mumty Area", "value": metrics["mumty_area"], "unit": "Sq.M"},
        {"label": "Covered Area", "value": metrics["covered_area"], "unit": "Sq.M"},
        {"label": "Ground Coverage", "value": metrics["max_ground_cov"], "unit": f"Sq.M ({metrics['max_ground_coverage_pre']}%)"},
        {"label": "Open Area", "value": metrics["open_area"], "unit": "Sq.M"},
        {"label": "Total Staircase Area", "value": metrics["total_stair_case_area"], "unit": "Sq.M"},
        {"label": "Total Chargeable Area", "value": metrics["chargable_area"], "unit": "Sq.M"},
    ]

    return {
        "file_name": file_name,
        "fetched_details": fetched_details,
        "passed_checks": validation_result["details"],
        "failed_checks": validation_result["failures"],
        "validation_status": validation_result["status"],
    }


# ---------------------------------------------------------------------------
# Public orchestration entry point
# ---------------------------------------------------------------------------

def run_validation_for_job(
    csv_path: str,
    area_type: str,
    location: str,
    rules_path: str | None = None,
) -> dict[str, Any]:
    """
    Full pipeline: load CSV → derive metrics → validate → build report.

    Args:
        csv_path:   Absolute path to the job's CSV file.
        area_type:  e.g. "Industrial Unit"
        location:   e.g. "Urban"
        rules_path: Optional override for New_rules.json path.

    Returns:
        {
            "validation_status": "PASS" | "FAIL",
            "report": { ... },
            "errors": [...]   # only present on FAIL
        }
    """
    # 1. Load CSV
    df: pd.DataFrame = load_csv(csv_path)

    # 2. Derive metrics
    metrics = derive_metrics(df)

    # 3. Load rules
    rules = load_rules(rules_path)

    # 4. Validate
    validation_result = _run_validation(area_type, location, metrics, rules)

    # 5. Build report
    file_name = Path(csv_path).stem
    report = build_report(metrics, validation_result, file_name=file_name)

    result: dict[str, Any] = {
        "validation_status": validation_result["status"],
        "report": report,
    }

    if validation_result["status"] == "FAIL":
        result["errors"] = validation_result["failures"]

    return result
