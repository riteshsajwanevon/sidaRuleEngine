# SIDA — AutoCAD DXF Validation API

A production-ready FastAPI backend that processes AutoCAD DXF files and validates
architectural drawings against SIDA building regulations defined in `New_rules.json`.

---

## Architecture

```
backend/
├── New_rules.json              ← Building regulation rules (Python-literal JSON)
├── demo_sidaproject.py         ← Original Colab notebook (source of all logic)
├── requirements.txt
├── README.md
└── app/
    ├── main.py                 ← FastAPI app, CORS, startup, health check
    ├── api/
    │   ├── upload.py           ← POST /upload
    │   └── validate.py         ← POST /validate
    ├── services/
    │   ├── dxf_service.py      ← DXF → CSV (reused from demo_sidaproject.py)
    │   ├── csv_service.py      ← CADData, geometry, metric derivation (reused)
    │   ├── new_json_service.py ← New_rules.json loader + option extractor (reused)
    │   ├── validation_service.py ← Full validation pipeline (reused)
    │   └── dwg_converter.py    ← DWG placeholder (ODA TODO)
    ├── models/
    │   └── schemas.py          ← Pydantic request/response models
    ├── utils/
    │   └── file_utils.py       ← Path helpers, job ID, extension validation
    ├── uploads/                ← Uploaded DXF/DWG files (per job_id)
    ├── outputs/                ← Generated CSV files (per job_id)
    └── reports/                ← Validation reports (per job_id)
```

---

## Reused Files from demo_sidaproject.py

| Original Function/Block | Extracted Into |
|---|---|
| `get_entity_color()` | `services/dxf_service.py` |
| `extract_entity_data()` | `services/dxf_service.py` |
| `dxf_to_csv_in_memory()` | `services/dxf_service.py` |
| `extract_points()`, `polygon_area()`, `dist()` | `services/csv_service.py` |
| `CADData` class | `services/csv_service.py` |
| `calculate()`, `safe_calc()` | `services/csv_service.py` |
| Floor codes, metric derivation block | `services/csv_service.py` |
| `RULES` loading (`ast.literal_eval`) | `services/new_json_service.py` |
| `location_matches()`, `area_type_matches()` | `services/validation_service.py` |
| `get_applicable_rule()`, `get_required_setbacks()` | `services/validation_service.py` |
| `validate()` function | `services/validation_service.py` |
| Report generation block | `services/validation_service.py` |

**Zero logic was rewritten.** All functions were lifted directly from the notebook
and adapted only for file I/O (removing Google Colab dependencies).

---

## DXF → CSV Workflow

```
POST /upload (multipart .dxf)
        │
        ▼
  Save to uploads/<job_id>/filename.dxf
        │
        ▼
  dxf_service.dxf_to_csv_file()
    └─ ezdxf.readfile()          ← open DXF
    └─ doc.modelspace()          ← iterate all entities
    └─ extract_entity_data()     ← per-entity: type, layer, color, coords, details
    └─ csv.DictWriter            ← write to outputs/<job_id>/filename.csv
        │
        ▼
  csv_service.derive_metrics()
    └─ CADData(df)               ← wrap DataFrame
    └─ calculate("area"|"length"|"parallel_distance"|"sum_area", ...)
    └─ floor_areas, setbacks, FAR, coverage, parking, etc.
        │
        ▼
  new_json_service.get_available_area_types()
  new_json_service.get_available_locations()
        │
        ▼
  Response: { job_id, status, csv_path, available_area_types, available_locations }
```

---

## New_JSON Integration

`New_rules.json` contains a list of rule objects. Each rule defines:

| Field | Description |
|---|---|
| `area_type` | Building type (e.g. "Industrial Unit", "Cottage/Micro/Household") |
| `location` | "Urban", "Rural", or "Urban/Rural" |
| `plot_min` / `plot_max` | Plot area range (Sq.M) |
| `road_min` / `road_max` | Road width range (M) |
| `FAR` | Maximum Floor Area Ratio |
| `coverage_percent` | Maximum ground coverage (%) |
| `max_building_height` | Maximum building height (M) |
| `height_bands` | List of setback requirements per height band |

**Matching logic** (`validation_service.get_applicable_rule`):
1. Filter by `area_type` (supports "/" compound types like "Cottage/Micro/Household")
2. Filter by `location` (supports "Urban/Rural" wildcard)
3. Filter by `plot_area` within `[plot_min, plot_max]`
4. Filter by `road_width >= road_min` and `< road_max` (if set)
5. Return the first matching rule

**Checks performed:**
- FAR ≤ allowed FAR
- Ground coverage % ≤ allowed coverage
- Rain water harvesting volume ≥ minimum required
- Loading/unloading area ≥ minimum required
- Building height ≤ maximum allowed
- Parking areas (open, stilt, basement, mechanical) ≥ permissible minimums
- Front/rear/side setbacks ≥ height-band requirements
- Green area ≥ 25% of total setback area

---

## Quick Start

### 1. Install dependencies

```bash
cd /home/ritesh/SIDA/backend
pip install -r requirements.txt
```

### 2. Start the server

```bash
uvicorn app.main:app --reload
```

### 3. Open API docs

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc:       http://127.0.0.1:8000/redoc
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json

---

## API Reference

### POST /upload

Upload a DXF or DWG file.

**Request** — multipart/form-data:
```
file: <your_drawing.dxf>
```

**Response (DXF)**:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "converted",
  "csv_path": "/home/ritesh/SIDA/backend/app/outputs/550e8400.../drawing.csv",
  "available_area_types": ["Cottage", "Industrial Flatted Units", "Industrial Unit", "IT Unit", "Micro", "Household"],
  "available_locations": ["Rural", "Urban"]
}
```

**Response (DWG)**:
```json
{
  "status": "pending_conversion",
  "message": "DWG conversion will be implemented later."
}
```

---

### POST /validate

Validate a processed job against building rules.

**Request**:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "area_type": "Industrial Unit",
  "location": "Urban"
}
```

**Response (PASS)**:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "success",
  "validation_status": "PASS",
  "report": {
    "file_name": "drawing",
    "fetched_details": [
      { "label": "Plot Area", "value": 1500.0, "unit": "Sq.M" },
      { "label": "FAR", "value": 1.45, "unit": "" }
    ],
    "passed_checks": [
      "FAR : In Map = 1.45, Allowed ≤ 1.6",
      "Building Height : In Map = 18.0 m, Allowed ≤ 30 m"
    ],
    "failed_checks": [],
    "validation_status": "PASS"
  }
}
```

**Response (FAIL)**:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "success",
  "validation_status": "FAIL",
  "report": { "..." },
  "errors": [
    "FAR : Allowed ≤ 1.6, In Map = 1.85",
    "Front Setback : Allowed ≥ 5 m, In Map = 3.2 m"
  ]
}
```

---

## Error Responses

All errors follow this format:
```json
{
  "status": "error",
  "message": "Human-readable description"
}
```

| HTTP Code | Cause |
|---|---|
| 400 | Unsupported file type, invalid/corrupt DXF |
| 404 | job_id not found, no CSV for job |
| 422 | No file provided |
| 500 | Internal processing error |

---

## DWG Support (Future)

See `app/services/dwg_converter.py` for full ODA File Converter integration
instructions. The placeholder is ready — install ODA and uncomment the
subprocess block to enable DWG conversion.
