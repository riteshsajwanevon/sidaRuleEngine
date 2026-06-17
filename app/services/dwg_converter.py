# -*- coding: utf-8 -*-
"""
DWG Converter Service  (Placeholder)
--------------------------------------
DWG files cannot be parsed directly by ezdxf because DWG is a proprietary
binary format owned by Autodesk.  Conversion to DXF requires an external
tool such as the ODA File Converter (formerly Teigha File Converter).

This module is a placeholder that documents the intended integration point.

TODO: ODA File Converter Integration
--------------------------------------
1. Download ODA File Converter from:
   https://www.opendesign.com/guestfiles/oda_file_converter

2. Install it on the server (Linux/Windows/macOS).

3. Implement convert_dwg_to_dxf() below using subprocess to call:
   ODAFileConverter <input_dir> <output_dir> ACAD2018 DXF 0 1

   Example CLI call:
       ODAFileConverter /tmp/input /tmp/output ACAD2018 DXF 0 1

4. Verify the output DXF exists and return its path.

5. Remove the NotImplementedError and wire this service into upload.py.

Alternative: Use LibreCAD, FreeCAD, or a cloud conversion API (e.g., Aspose).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class DWGConversionNotImplementedError(NotImplementedError):
    """Raised when DWG conversion is attempted before ODA integration."""


def convert_dwg_to_dxf(dwg_path: str, output_dir: str) -> str:
    """
    Convert a DWG file to DXF using the ODA File Converter.

    Args:
        dwg_path:   Absolute path to the input .dwg file.
        output_dir: Directory where the converted .dxf will be written.

    Returns:
        Absolute path to the converted .dxf file.

    Raises:
        DWGConversionNotImplementedError: Always, until ODA is integrated.

    TODO:
        - Install ODA File Converter on the server.
        - Locate the ODA binary (e.g., /usr/bin/ODAFileConverter).
        - Replace the raise below with the subprocess call.
        - Add error handling for conversion failures.
        - Add timeout handling for large files.
    """
    # TODO: Replace this block with actual ODA subprocess call
    # -------------------------------------------------------
    # oda_binary = "/usr/bin/ODAFileConverter"   # adjust path
    # input_dir  = str(Path(dwg_path).parent)
    # stem       = Path(dwg_path).stem
    # Path(output_dir).mkdir(parents=True, exist_ok=True)
    #
    # result = subprocess.run(
    #     [oda_binary, input_dir, output_dir, "ACAD2018", "DXF", "0", "1"],
    #     capture_output=True,
    #     text=True,
    #     timeout=120,
    # )
    #
    # if result.returncode != 0:
    #     raise RuntimeError(f"ODA conversion failed: {result.stderr}")
    #
    # dxf_path = str(Path(output_dir) / f"{stem}.dxf")
    # if not Path(dxf_path).exists():
    #     raise FileNotFoundError(f"Converted DXF not found: {dxf_path}")
    #
    # return dxf_path
    # -------------------------------------------------------

    raise DWGConversionNotImplementedError(
        "DWG conversion is not yet implemented. "
        "See services/dwg_converter.py for ODA integration instructions."
    )
