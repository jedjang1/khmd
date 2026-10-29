"""Exact, read-only polygon diagnostics for the EPSG:5186 1 km pilot grid.

No geometry is repaired, projected, snapped, buffered, or assigned an epsilon.
Raw geometry validity and derived calculation failures are separate evidence.
The QGIS fallback uses only an existing local installation, without installation
or network access. Call ``load_engine`` before importing Shapely in a caller.
"""
from __future__ import annotations

import importlib
import math
import os
from pathlib import Path
import sys
from typing import Any


_DLL_HANDLES: list[Any] = []
QGIS_ROOT = Path(os.environ["KHMD_QGIS_ROOT"])
MAX_CANDIDATE_CELLS = 100_000


def load_engine():
    """Load installed Shapely, using the known local QGIS runtime if necessary."""
    try:
        return importlib.import_module("shapely")
    except ModuleNotFoundError as exc:
        if exc.name != "shapely":
            raise
        site = QGIS_ROOT / "apps/Python312/Lib/site-packages"
        binary = QGIS_ROOT / "bin"
        if not site.is_dir() or not binary.is_dir():
            raise RuntimeError("No installed Shapely or known QGIS runtime available") from exc
        if hasattr(os, "add_dll_directory"):
            _DLL_HANDLES.append(os.add_dll_directory(str(binary)))
        if str(site) not in sys.path:
            sys.path.insert(0, str(site))
        return importlib.import_module("shapely")


load_engine()
from shapely.geometry import box  # noqa: E402
from shapely.validation import explain_validity  # noqa: E402


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, (bool, str, bytes)):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _grid_parameters(origin, size):
    try:
        ox, oy = origin
    except (TypeError, ValueError) as exc:
        raise ValueError("origin must contain exactly two finite numbers") from exc
    ox = _finite_number(ox, "origin x")
    oy = _finite_number(oy, "origin y")
    size = _finite_number(size, "size")
    if size <= 0:
        raise ValueError("size must be positive")
    return ox, oy, size


def grid_index(x, y, origin=(0, 0), size=1000) -> tuple[int, int]:
    """Use mathematical floor: each point belongs to [left,right) x [bottom,top)."""
    ox, oy, size = _grid_parameters(origin, size)
    x = _finite_number(x, "x")
    y = _finite_number(y, "y")
    qx, qy = (x - ox) / size, (y - oy) / size
    if not math.isfinite(qx) or not math.isfinite(qy):
        raise ValueError("grid index arithmetic produced non-finite values")
    return math.floor(qx), math.floor(qy)


def grid_id(i: int, j: int) -> str:
    if isinstance(i, bool) or isinstance(j, bool) or not isinstance(i, int) or not isinstance(j, int):
        raise ValueError("grid indices must be integers")
    return f"G1K_5186_{i}_{j}"


def _all_coordinates(geometry):
    polygons = [geometry] if geometry.geom_type == "Polygon" else geometry.geoms
    for polygon in polygons:
        for ring in [polygon.exterior, *polygon.interiors]:
            yield from ring.coords


def _inspect_geometry(geometry) -> dict:
    result = {
        "status": "GEOMETRY_MISSING", "geom_type": None, "validity_reason": None,
        "raw_is_valid": None, "bounds": None, "area": None,
        "nonpositive_area": None, "inspection_error": None,
    }
    if geometry is None:
        return result
    try:
        result["geom_type"] = geometry.geom_type
        if geometry.is_empty:
            result["status"] = "GEOMETRY_EMPTY"
            return result
        if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            result["status"] = "GEOMETRY_NONPOLYGON"
            return result
        if not all(math.isfinite(v) for coord in _all_coordinates(geometry) for v in coord):
            result["status"] = "GEOMETRY_NONFINITE"
            return result
        bounds = list(geometry.bounds)
        if len(bounds) != 4 or not all(math.isfinite(v) for v in bounds):
            result["status"] = "GEOMETRY_NONFINITE"
            return result
        result["bounds"] = bounds
        area = float(geometry.area)
        if not math.isfinite(area):
            result["status"] = "GEOMETRY_NONFINITE"
            return result
        result["area"] = area
        result["nonpositive_area"] = area <= 0
        result["raw_is_valid"] = bool(geometry.is_valid)
        result["validity_reason"] = explain_validity(geometry)
        # Invalid zero-area polygons must remain visibly invalid raw geometry.
        if not result["raw_is_valid"]:
            result["status"] = "GEOMETRY_INVALID_RAW"
        elif area <= 0:
            result["status"] = "GEOMETRY_NONPOSITIVE_AREA"
        else:
            result["status"] = "GEOMETRY_VALID"
    except Exception as exc:
        result["status"] = "GEOMETRY_INSPECTION_ERROR"
        result["inspection_error"] = f"{type(exc).__name__}: {exc}"
    return result


def geometry_status(geometry) -> str:
    return _inspect_geometry(geometry)["status"]


def _point_fields(geometry, point, prefix, origin, size):
    xy = [_finite_number(point.x, f"{prefix} x"), _finite_number(point.y, f"{prefix} y")]
    return {
        f"{prefix}_xy": xy,
        f"{prefix}_inside": bool(geometry.covers(point)),
        f"{prefix}_strictly_inside": bool(geometry.contains(point)),
        f"{prefix}_grid": grid_id(*grid_index(*xy, origin=origin, size=size)),
    }


def analyze_geometry(geometry, origin=(0, 0), size=1000, *, max_candidate_cells=MAX_CANDIDATE_CELLS) -> dict:
    """Return JSON-safe raw diagnostics and, only when valid, spatial summaries.

    Cell intersections are closed polygons; zero-area line/point contact is kept
    separately from positive-area coverage. Exact maximum-area ties have a null
    dominant grid. ``area_delta`` is intersection-area sum minus raw area and is
    reported without tolerance classification. A computation error never changes
    GEOMETRY_VALID into an invalid-raw status, and publishes no partial assignment.
    """
    result = _inspect_geometry(geometry)
    result.update({
        "computation_status": "NOT_APPLICABLE", "computation_error": None,
        "grid_origin": None, "grid_size": None,
        "centroid_xy": None, "centroid_inside": None, "centroid_strictly_inside": None,
        "centroid_grid": None, "point_on_surface_xy": None,
        "point_on_surface_inside": None, "point_on_surface_strictly_inside": None,
        "point_on_surface_grid": None, "positive_area_cells": [], "touch_only_cells": [],
        "area_sum": None, "area_delta": None, "positive_area_cell_count": None,
        "touch_only_cell_count": None, "crosses_boundary": None,
        "dominant_grid": None, "dominant_share": None, "dominant_tie": [],
        "candidate_cell_count": None,
    })
    if result["status"] != "GEOMETRY_VALID":
        return result
    stage = "grid_parameters"
    try:
        ox, oy, size = _grid_parameters(origin, size)
        if isinstance(max_candidate_cells, bool) or not isinstance(max_candidate_cells, int) or max_candidate_cells < 1:
            raise ValueError("max_candidate_cells must be a positive integer")
        origin = (ox, oy)
        derived = {"grid_origin": list(origin), "grid_size": size}
        stage = "centroid"
        derived.update(_point_fields(geometry, geometry.centroid, "centroid", origin, size))
        stage = "point_on_surface"
        derived.update(_point_fields(geometry, geometry.representative_point(), "point_on_surface", origin, size))
        stage = "grid_intersections"
        xmin, ymin, xmax, ymax = result["bounds"]
        imin, jmin = grid_index(xmin, ymin, origin, size)
        imax, jmax = grid_index(xmax, ymax, origin, size)
        # One additional minimum-side cell admits exact lower-edge contact. The
        # maximum-edge cell is already included by floor; no epsilon is applied.
        imin, jmin = imin - 1, jmin - 1
        candidates = (imax - imin + 1) * (jmax - jmin + 1)
        if candidates > max_candidate_cells:
            raise ValueError(f"candidate cell limit exceeded: {candidates} > {max_candidate_cells}")
        positive, touches = [], []
        for i in range(imin, imax + 1):
            for j in range(jmin, jmax + 1):
                x0, y0 = ox + i * size, oy + j * size
                x1, y1 = ox + (i + 1) * size, oy + (j + 1) * size
                if not all(math.isfinite(v) for v in (x0, y0, x1, y1)) or x1 <= x0 or y1 <= y0:
                    raise ValueError("cell arithmetic is non-finite or loses positive cell extent")
                cell = box(x0, y0, x1, y1)
                intersection = geometry.intersection(cell)
                if intersection.is_empty:
                    continue
                area = float(intersection.area)
                if not math.isfinite(area) or area < 0:
                    raise ValueError("intersection area is non-finite or negative")
                record = {"grid_id": grid_id(i, j), "i": i, "j": j, "area": area}
                if area > 0:
                    positive.append(record)
                else:
                    touches.append(record)
        if not positive:
            raise ValueError("valid positive-area geometry yielded no positive-area cells")
        area_sum = math.fsum(cell["area"] for cell in positive)
        if not math.isfinite(area_sum):
            raise ValueError("intersection-area sum is non-finite")
        largest = max(cell["area"] for cell in positive)
        winners = [cell["grid_id"] for cell in positive if cell["area"] == largest]
        derived.update({
            "positive_area_cells": positive, "touch_only_cells": touches,
            "area_sum": area_sum, "area_delta": area_sum - result["area"],
            "positive_area_cell_count": len(positive), "touch_only_cell_count": len(touches),
            "crosses_boundary": len(positive) > 1, "candidate_cell_count": candidates,
            "dominant_grid": winners[0] if len(winners) == 1 else None,
            "dominant_share": largest / result["area"],
            "dominant_tie": winners if len(winners) > 1 else [],
        })
        result.update(derived)
        result["computation_status"] = "OK"
    except Exception as exc:
        result["computation_status"] = "ERROR"
        result["computation_error"] = f"{stage}: {type(exc).__name__}: {exc}"
    return result


def classify_gis(parcel_grid, feature_grids, total_features, invalid_features) -> dict:
    """Compare all selected-PNU building representative grids, never choose one.

    Missing/invalid feature evidence prevents an 'all' conclusion. SPAN_CELLS
    takes precedence when complete evidence contains more than one unique grid;
    the independent all-different flag remains available for such a set.
    """
    for name, value in (("total_features", total_features), ("invalid_features", invalid_features)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    if invalid_features > total_features:
        raise ValueError("invalid_features exceeds total_features")
    features = list(feature_grids)
    comparable = [value for value in features if isinstance(value, str) and value.strip()]
    unique = sorted(set(comparable))
    complete = (invalid_features == 0 and len(comparable) == total_features and len(features) == total_features)
    parcel_available = isinstance(parcel_grid, str) and bool(parcel_grid.strip())
    available = parcel_available and total_features > 0 and complete
    status = "GIS_UNAVAILABLE"
    if available:
        if len(unique) > 1:
            status = "GIS_SPAN_CELLS"
        elif unique[0] == parcel_grid:
            status = "GIS_ALL_EQUAL"
        else:
            status = "GIS_DIFFERS_ALL"
    return {
        "status": status, "parcel_grid": parcel_grid if parcel_available else None,
        "unique_feature_grids": unique, "comparable_feature_count": len(comparable),
        "total_features": total_features, "invalid_features": invalid_features,
        "incomplete_evidence": not complete,
        "observed_features_span_cells": len(unique) > 1,
        "all_comparable_features_differ": all(value != parcel_grid for value in comparable) if parcel_available and comparable else None,
        "actual_transaction_building_identified": False,
    }
