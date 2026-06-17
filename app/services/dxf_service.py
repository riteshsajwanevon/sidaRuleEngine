# -*- coding: utf-8 -*-
"""
DXF Service
-----------
Converts a DXF file to CSV using a fast line-by-line ASCII streamer.

Why not ezdxf?
  ezdxf.readfile() on a 119 MB DXF takes ~41 seconds just to load the file
  into memory before any entity is processed. The ASCII streamer below reads
  the same file in ~3-4 seconds by scanning only the ENTITIES section and
  writing CSV rows on the fly — no full object graph is built.

Output format:
  Identical to demo_sidaproject.py (ezdxf-based) so csv_service.py works
  without any changes. Specifically:
    - LWPOLYLINE Details: "points=[(x, y), ...]"   ← 2-tuples, plain floats
    - LINE Details:       "LINE from (x, y, z) to (x, y, z)"
    - CIRCLE Details:     "center=(x, y, z), radius=r"
    - ARC Details:        "center=(x, y, z), radius=r, start_angle=a, end_angle=b"
    - TEXT Details:       "text=<string>"
    - MTEXT Details:      "text=<string>"
    - INSERT Details:     "block_name=<name>"
"""

from __future__ import annotations

import csv
import traceback
from pathlib import Path
from typing import IO

FIELDNAMES = [
    "Type", "Layer", "ColorCode",
    "StartX", "StartY", "StartZ",
    "EndX", "EndY", "EndZ",
    "Details",
]

SUPPORTED = {"LINE", "CIRCLE", "ARC", "LWPOLYLINE", "POLYLINE", "TEXT", "MTEXT", "INSERT"}


# ---------------------------------------------------------------------------
# Low-level DXF pair iterator
# ---------------------------------------------------------------------------

def _iter_pairs(path: str):
    """Yield (group_code_str, value_str) pairs from an ASCII DXF file."""
    with open(path, encoding="utf-8", errors="ignore") as fh:
        while True:
            code = fh.readline()
            if not code:
                break
            value = fh.readline()
            if not value:
                break
            yield code.strip(), value.rstrip("\r\n")


# ---------------------------------------------------------------------------
# Layer color table  (scanned from TABLES section before ENTITIES)
# ---------------------------------------------------------------------------

def  _scan_layer_colors(path: str) -> dict[str, int]:
    """Return {layer_name: color_int} from the TABLES/LAYER section."""
    colors: dict[str, int] = {}
    in_tables = False
    in_layer_table = False
    cur: dict[str, str] = {}

    for code, value in _iter_pairs(path):
        if code == "0":
            if value == "SECTION":
                in_tables = False
                in_layer_table = False
            elif value == "ENDSEC" and in_tables:
                break
            elif value == "TABLE":
                cur = {}
            elif value == "LAYER" and in_layer_table:
                # flush previous layer entry
                _store_layer(cur, colors)
                cur = {}
            elif value == "ENDTAB":
                _store_layer(cur, colors)
                in_layer_table = False
            continue

        if code == "2":
            if value == "TABLES":
                in_tables = True
            elif value == "LAYER" and in_tables:
                in_layer_table = True

        if in_layer_table:
            cur[code] = value

    return colors


def _store_layer(attrs: dict[str, str], colors: dict[str, int]) -> None:
    name = attrs.get("2", "")
    raw = attrs.get("62", "")
    if name and raw:
        try:
            colors[name] = abs(int(raw))
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Color resolution  (mirrors demo_sidaproject.py get_entity_color logic)
# ---------------------------------------------------------------------------

def _resolve_color(attrs: dict[str, list[str]], layer: str, layer_colors: dict[str, int]) -> int:
    # true_color (group 420) → not used for ColorCode matching in csv_service,
    # but we replicate the demo's fallback chain: explicit color → layer color → 7
    raw = _last(attrs, "62")
    if raw:
        try:
            c = int(raw)
            if c not in (0, 256):
                return abs(c)
            if c == 256:
                return layer_colors.get(layer, 7)
        except ValueError:
            pass
    return layer_colors.get(layer, 7)


# ---------------------------------------------------------------------------
# Attribute helpers
# ---------------------------------------------------------------------------

def _last(attrs: dict[str, list[str]], code: str, default: str = "") -> str:
    vals = attrs.get(code)
    return vals[-1] if vals else default


def _f(attrs: dict[str, list[str]], code: str, default: float = 0.0) -> float:
    """Parse last value for code as float."""
    raw = _last(attrs, code)
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def _append(attrs: dict[str, list[str]], code: str, value: str) -> None:
    attrs.setdefault(code, []).append(value)


# ---------------------------------------------------------------------------
# Row builder — output matches demo_sidaproject.py format exactly
# ---------------------------------------------------------------------------

def _build_row(
    etype: str,
    attrs: dict[str, list[str]],
    layer_colors: dict[str, int],
    poly_points: list[tuple[float, float]] | None = None,
) -> dict | None:
    """Build one CSV row dict from collected entity attributes."""
    layer = _last(attrs, "8")
    color = _resolve_color(attrs, layer, layer_colors)

    row: dict = {
        "Type": etype,
        "Layer": layer,
        "ColorCode": color,
        "StartX": "", "StartY": "", "StartZ": "",
        "EndX": "", "EndY": "", "EndZ": "",
        "Details": "",
    }

    try:
        if etype == "LINE":
            sx, sy, sz = _f(attrs, "10"), _f(attrs, "20"), _f(attrs, "30")
            ex, ey, ez = _f(attrs, "11"), _f(attrs, "21"), _f(attrs, "31")
            row.update({"StartX": sx, "StartY": sy, "StartZ": sz,
                        "EndX": ex, "EndY": ey, "EndZ": ez})
            # Match demo: "LINE from (sx, sy, sz) to (ex, ey, ez)"
            row["Details"] = f"LINE from ({sx}, {sy}, {sz}) to ({ex}, {ey}, {ez})"

        elif etype == "CIRCLE":
            cx, cy, cz = _f(attrs, "10"), _f(attrs, "20"), _f(attrs, "30")
            r = _f(attrs, "40")
            row.update({"StartX": cx, "StartY": cy, "StartZ": cz})
            row["Details"] = f"center=({cx}, {cy}, {cz}), radius={r}"

        elif etype == "ARC":
            cx, cy, cz = _f(attrs, "10"), _f(attrs, "20"), _f(attrs, "30")
            r = _f(attrs, "40")
            sa, ea = _f(attrs, "50"), _f(attrs, "51")
            row.update({"StartX": cx, "StartY": cy, "StartZ": cz})
            row["Details"] = (
                f"center=({cx}, {cy}, {cz}), radius={r}, "
                f"start_angle={sa}, end_angle={ea}"
            )

        elif etype == "LWPOLYLINE":
            # Collect all X (code 10) and Y (code 20) values → 2-tuples
            xs = attrs.get("10", [])
            ys = attrs.get("20", [])
            pts = [(float(x), float(y)) for x, y in zip(xs, ys)]
            if pts:
                row["StartX"], row["StartY"] = pts[0]
            # Match demo: "points=[(x, y), ...]"
            row["Details"] = f"points={pts}"

        elif etype == "POLYLINE":
            pts = poly_points or []
            if pts:
                row["StartX"], row["StartY"] = pts[0]
                row["StartZ"] = 0.0
            row["Details"] = f"points={pts}"

        elif etype == "TEXT":
            ix, iy, iz = _f(attrs, "10"), _f(attrs, "20"), _f(attrs, "30")
            row.update({"StartX": ix, "StartY": iy, "StartZ": iz})
            row["Details"] = f"text={_last(attrs, '1')}"

        elif etype == "MTEXT":
            ix, iy, iz = _f(attrs, "10"), _f(attrs, "20"), _f(attrs, "30")
            # MTEXT content can span multiple group-3 records + one group-1
            text = "".join(attrs.get("3", [])) + _last(attrs, "1")
            row.update({"StartX": ix, "StartY": iy, "StartZ": iz})
            row["Details"] = f"text={text}"

        elif etype == "INSERT":
            ix, iy, iz = _f(attrs, "10"), _f(attrs, "20"), _f(attrs, "30")
            row.update({"StartX": ix, "StartY": iy, "StartZ": iz})
            row["Details"] = f"block_name={_last(attrs, '2')}"

        else:
            row["Details"] = "Unsupported entity type"

    except Exception:
        row["Details"] = "Error parsing entity"

    return row


# ---------------------------------------------------------------------------
# Main streaming converter
# ---------------------------------------------------------------------------

def _stream_entities(path: str, writer: csv.DictWriter, layer_colors: dict[str, int]) -> None:
    """
    Scan the ENTITIES section of the DXF and write one CSV row per entity.

    POLYLINE is handled specially: its VERTEX sub-entities are collected
    until SEQEND, then a single row is written with all points.
    """
    in_entities = False

    # Current entity state
    cur_type: str | None = None
    cur_attrs: dict[str, list[str]] = {}

    # POLYLINE accumulator
    in_polyline = False
    poly_attrs: dict[str, list[str]] = {}
    poly_points: list[tuple[float, float]] = []
    in_vertex = False
    vtx_attrs: dict[str, list[str]] = {}

    def flush_entity() -> None:
        nonlocal cur_type, cur_attrs
        if cur_type in SUPPORTED:
            row = _build_row(cur_type, cur_attrs, layer_colors)
            if row:
                writer.writerow(row)
        cur_type = None
        cur_attrs = {}

    for code, value in _iter_pairs(path):

        # ── Section markers ──────────────────────────────────────────────
        if code == "0" and value == "SECTION":
            in_entities = False
            continue
        if code == "2" and value == "ENTITIES" and not in_entities:
            in_entities = True
            continue
        if not in_entities:
            continue
        if code == "0" and value == "ENDSEC":
            flush_entity()
            break

        # ── Inside POLYLINE / VERTEX / SEQEND ────────────────────────────
        if in_polyline:
            if code == "0" and value == "VERTEX":
                # flush previous vertex
                if in_vertex and vtx_attrs:
                    x = _f(vtx_attrs, "10")
                    y = _f(vtx_attrs, "20")
                    poly_points.append((x, y))
                in_vertex = True
                vtx_attrs = {}
                continue

            if code == "0" and value == "SEQEND":
                # flush last vertex
                if in_vertex and vtx_attrs:
                    x = _f(vtx_attrs, "10")
                    y = _f(vtx_attrs, "20")
                    poly_points.append((x, y))
                row = _build_row("POLYLINE", poly_attrs, layer_colors, poly_points)
                if row:
                    writer.writerow(row)
                # reset polyline state
                in_polyline = False
                in_vertex = False
                poly_attrs = {}
                poly_points = []
                vtx_attrs = {}
                cur_type = None
                cur_attrs = {}
                continue

            if in_vertex:
                _append(vtx_attrs, code, value)
            else:
                _append(poly_attrs, code, value)
            continue

        # ── Entity boundary ───────────────────────────────────────────────
        if code == "0":
            flush_entity()
            if value == "POLYLINE":
                in_polyline = True
                poly_attrs = {}
                poly_points = []
                in_vertex = False
                vtx_attrs = {}
            elif value in SUPPORTED:
                cur_type = value
                cur_attrs = {}
            continue

        # ── Accumulate attributes ─────────────────────────────────────────
        if cur_type:
            _append(cur_attrs, code, value)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def dxf_to_csv_file(dxf_path: str, output_csv_path: str) -> str:
    """
    Convert a DXF file to CSV and write to output_csv_path.

    Uses the fast ASCII streamer — ~3-4s on a 119 MB file vs ~41s with ezdxf.
    Output format is identical to demo_sidaproject.py.

    Returns the output path.
    Raises ValueError on any parse failure.
    """
    try:
        layer_colors = _scan_layer_colors(dxf_path)
        out = Path(output_csv_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
            writer.writeheader()
            _stream_entities(dxf_path, writer, layer_colors)
        return output_csv_path
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"DXF parsing failed: {exc}\n{traceback.format_exc()}") from exc
