# -*- coding: utf-8 -*-
"""
DXF Parser
----------
Single-pass ASCII DXF parser that produces a CADModel directly.

Why a custom parser (not ezdxf)?
    ezdxf.readfile() on a 119 MB DXF takes ~41 s just to load into memory.
    This streamer reads the same file in ~3-4 s by scanning only the
    TABLES and ENTITIES sections, building typed DxfEntity objects and
    CADModel indexes in one pass.

Public API
----------
    parse_dxf_to_cad_model(stream) -> CADModel
        Primary entry point.  Returns a fully-indexed CADModel ready for
        metric extraction and validation.  No CSV, no DataFrame.

    parse_dxf(stream) -> {"layer_colors": ..., "entities": [...]}
        Legacy dict-based wrapper kept for backward compatibility with any
        caller that still uses the old shape.

Flow
----
    stream
      └── _read_all_pairs()          reads (code, value) pairs once
              ├── _extract_layer_colors(pairs)   → dict[str, int]
              └── _extract_entities(pairs, colors) → list[DxfEntity]
                      └── CADModel(layer_colors, entities)
                              └── __post_init__ builds indexes
"""

from __future__ import annotations

import traceback
from typing import IO, Iterable

from app.models.cad_model import CADModel, DxfEntity, SUPPORTED_TYPES


# ---------------------------------------------------------------------------
# Low-level pair reader
# ---------------------------------------------------------------------------

def _read_all_pairs(stream: IO[bytes] | IO[str]) -> list[tuple[str, str]]:
    """
    Read every (group_code, value) pair from a seekable DXF stream into a
    list.  The stream is consumed exactly once.
    """
    stream.seek(0)
    pairs: list[tuple[str, str]] = []
    while True:
        code = stream.readline()
        if not code:
            break
        val = stream.readline()
        if not val:
            break
        if isinstance(code, bytes):
            code = code.decode("utf-8", errors="ignore")
        if isinstance(val, bytes):
            val = val.decode("utf-8", errors="ignore")
        pairs.append((code.strip(), val.rstrip("\r\n")))
    return pairs


# ---------------------------------------------------------------------------
# Attribute helpers (shared by layer-color and entity extraction)
# ---------------------------------------------------------------------------

def _last(attrs: dict[str, list[str]], code: str, default: str = "") -> str:
    vals = attrs.get(code)
    return vals[-1] if vals else default


def _f(attrs: dict[str, list[str]], code: str, default: float = 0.0) -> float:
    raw = _last(attrs, code)
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def _append(attrs: dict[str, list[str]], code: str, value: str) -> None:
    attrs.setdefault(code, []).append(value)


# ---------------------------------------------------------------------------
# Layer colour table
# ---------------------------------------------------------------------------

def _extract_layer_colors(pairs: Iterable[tuple[str, str]]) -> dict[str, int]:
    """
    Scan the TABLES/LAYER section and return {layer_name: color_int}.
    Stops as soon as ENDSEC is reached — does not read ENTITIES.
    """
    colors: dict[str, int] = {}
    in_tables      = False
    in_layer_table = False
    cur: dict[str, str] = {}

    for code, value in pairs:
        if code == "0":
            if value == "SECTION":
                in_tables      = False
                in_layer_table = False
            elif value == "ENDSEC" and in_tables:
                break
            elif value == "TABLE":
                cur = {}
            elif value == "LAYER" and in_layer_table:
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
    raw  = attrs.get("62", "")
    if name and raw:
        try:
            colors[name] = abs(int(raw))
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Colour resolution
# ---------------------------------------------------------------------------

def _resolve_color(
    attrs: dict[str, list[str]],
    layer: str,
    layer_colors: dict[str, int],
) -> int:
    """
    Resolve an entity's effective color code using the same fallback chain
    as the original demo_sidaproject.py:
        explicit group-62 color → layer color → default 7
    """
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
# Entity builder
# ---------------------------------------------------------------------------

def _build_entity(
    etype: str,
    attrs: dict[str, list[str]],
    layer_colors: dict[str, int],
    poly_points: list[tuple[float, float]] | None = None,
) -> DxfEntity | None:
    """
    Convert raw DXF attribute dict into a typed DxfEntity.

    The Details string is built in the same format as the original
    dxf_service.py so that CSV export (when requested) produces identical
    output.  The ``points`` list is populated natively so geometry helpers
    never need to re-parse the Details string.
    """
    layer = _last(attrs, "8")
    color = _resolve_color(attrs, layer, layer_colors)
    ent   = DxfEntity(entity_type=etype, layer=layer, color=color)

    try:
        if etype == "LINE":
            sx, sy, sz = _f(attrs, "10"), _f(attrs, "20"), _f(attrs, "30")
            ex, ey, ez = _f(attrs, "11"), _f(attrs, "21"), _f(attrs, "31")
            ent.start_x, ent.start_y, ent.start_z = sx, sy, sz
            ent.end_x,   ent.end_y,   ent.end_z   = ex, ey, ez
            ent.details = f"LINE from ({sx}, {sy}, {sz}) to ({ex}, {ey}, {ez})"

        elif etype == "CIRCLE":
            cx, cy, cz = _f(attrs, "10"), _f(attrs, "20"), _f(attrs, "30")
            r = _f(attrs, "40")
            ent.start_x, ent.start_y, ent.start_z = cx, cy, cz
            ent.details = f"center=({cx}, {cy}, {cz}), radius={r}"

        elif etype == "ARC":
            cx, cy, cz = _f(attrs, "10"), _f(attrs, "20"), _f(attrs, "30")
            r  = _f(attrs, "40")
            sa = _f(attrs, "50")
            ea = _f(attrs, "51")
            ent.start_x, ent.start_y, ent.start_z = cx, cy, cz
            ent.details = (
                f"center=({cx}, {cy}, {cz}), radius={r}, "
                f"start_angle={sa}, end_angle={ea}"
            )

        elif etype == "LWPOLYLINE":
            xs  = attrs.get("10", [])
            ys  = attrs.get("20", [])
            pts = [(float(x), float(y)) for x, y in zip(xs, ys)]
            ent.points = pts
            if pts:
                ent.start_x, ent.start_y = pts[0]
            ent.details = f"points={pts}"

        elif etype == "POLYLINE":
            pts = poly_points or []
            ent.points  = pts
            ent.start_z = 0.0
            if pts:
                ent.start_x, ent.start_y = pts[0]
            ent.details = f"points={pts}"

        elif etype == "TEXT":
            ent.start_x = _f(attrs, "10")
            ent.start_y = _f(attrs, "20")
            ent.start_z = _f(attrs, "30")
            ent.details = f"text={_last(attrs, '1')}"

        elif etype == "MTEXT":
            ent.start_x = _f(attrs, "10")
            ent.start_y = _f(attrs, "20")
            ent.start_z = _f(attrs, "30")
            text = "".join(attrs.get("3", [])) + _last(attrs, "1")
            ent.details = f"text={text}"

        elif etype == "INSERT":
            ent.start_x = _f(attrs, "10")
            ent.start_y = _f(attrs, "20")
            ent.start_z = _f(attrs, "30")
            ent.details = f"block_name={_last(attrs, '2')}"

        else:
            ent.details = "Unsupported entity type"

    except Exception:
        ent.details = "Error parsing entity"

    return ent


# ---------------------------------------------------------------------------
# ENTITIES section scanner
# ---------------------------------------------------------------------------

def _extract_entities(
    pairs: Iterable[tuple[str, str]],
    layer_colors: dict[str, int],
) -> list[DxfEntity]:
    """
    Scan the ENTITIES section and return one DxfEntity per supported entity.

    State machine mirrors dxf_service._stream_entities_from_pairs exactly,
    but produces DxfEntity objects instead of CSV rows.
    """
    entities:    list[DxfEntity]        = []
    in_entities: bool                   = False
    cur_type:    str | None             = None
    cur_attrs:   dict[str, list[str]]   = {}

    # POLYLINE accumulator (POLYLINE uses VERTEX sub-entities + SEQEND)
    in_polyline:  bool                        = False
    poly_attrs:   dict[str, list[str]]        = {}
    poly_points:  list[tuple[float, float]]   = []
    in_vertex:    bool                        = False
    vtx_attrs:    dict[str, list[str]]        = {}

    def flush_entity() -> None:
        nonlocal cur_type, cur_attrs
        if cur_type in SUPPORTED_TYPES:
            ent = _build_entity(cur_type, cur_attrs, layer_colors)
            if ent:
                entities.append(ent)
        cur_type  = None
        cur_attrs = {}

    for code, value in pairs:

        # Section markers
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

        # POLYLINE / VERTEX / SEQEND handling
        if in_polyline:
            if code == "0" and value == "VERTEX":
                if in_vertex and vtx_attrs:
                    poly_points.append((_f(vtx_attrs, "10"), _f(vtx_attrs, "20")))
                in_vertex = True
                vtx_attrs = {}
                continue

            if code == "0" and value == "SEQEND":
                if in_vertex and vtx_attrs:
                    poly_points.append((_f(vtx_attrs, "10"), _f(vtx_attrs, "20")))
                ent = _build_entity("POLYLINE", poly_attrs, layer_colors, poly_points)
                if ent:
                    entities.append(ent)
                in_polyline = False
                in_vertex   = False
                poly_attrs  = {}
                poly_points = []
                vtx_attrs   = {}
                cur_type    = None
                cur_attrs   = {}
                continue

            if in_vertex:
                _append(vtx_attrs, code, value)
            else:
                _append(poly_attrs, code, value)
            continue

        # Entity boundary
        if code == "0":
            flush_entity()
            if value == "POLYLINE":
                in_polyline = True
                poly_attrs  = {}
                poly_points = []
                in_vertex   = False
                vtx_attrs   = {}
            elif value in SUPPORTED_TYPES:
                cur_type  = value
                cur_attrs = {}
            continue

        if cur_type:
            _append(cur_attrs, code, value)

    return entities


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_dxf_to_cad_model(stream: IO[bytes] | IO[str]) -> CADModel:
    """
    Parse a seekable DXF stream and return a fully-indexed CADModel.

    This is the primary entry point for the validation pipeline.
    The stream is read exactly once into an in-memory pair list, then:
        1. Layer colours are extracted from the TABLES section.
        2. Entities are extracted from the ENTITIES section.
        3. A CADModel is constructed — indexes built automatically.

    No CSV is generated.  No pandas DataFrame is created.

    Raises ValueError on parse failure.
    """
    try:
        all_pairs = _read_all_pairs(stream)
        layer_colors = _extract_layer_colors(iter(all_pairs))
        entities     = _extract_entities(iter(all_pairs), layer_colors)
        return CADModel(layer_colors=layer_colors, entities=entities)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            f"DXF parsing failed: {exc}\n{traceback.format_exc()}"
        ) from exc
