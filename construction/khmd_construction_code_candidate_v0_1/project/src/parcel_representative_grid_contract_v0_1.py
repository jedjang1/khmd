"""Final parcel-representative grid definition; never a production assignment.

Only saved diagnostic JSON is read to build the contract. The optional POS helper
accepts caller-supplied synthetic geometry and is not used by the artifact build.
No collector, raw geometry reader, repair, reprojection or network path exists.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path


GRID_VERSION = "KHMD_GRID_1KM_EPSG5186_V0_1"
CANDIDATE_PATH = "metadata/khmd_fixed_1km_grid_spec_v0_1_candidate.json"
OBSERVATIONS_PATH = "data/interim/spatial_representation_diagnostics_v0_1/observations.json"
CRS_EVIDENCE_PATH = "metadata/spatial_representation_crs_and_engine_evidence_v0_1.json"
BOUNDARY_CLASSES = (
    "PARCEL_SINGLE_GRID",
    "PARCEL_CROSS_GRID_POS_DOMINANT_AGREE",
    "PARCEL_CROSS_GRID_POS_DOMINANT_DIFFER",
    "PARCEL_CROSS_GRID_DOMINANT_TIE",
)


def _coordinate_ratio(value, name):
    # Actual geometry-engine coordinates are binary floats. Retaining their
    # exact ratio avoids rounding a quotient across an edge or underflow to -0.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite native integer or float")
    if isinstance(value, int):
        return value, 1
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value.as_integer_ratio()


def grid_index(x, y) -> tuple[int, int]:
    """Exact mathematical floor for supplied coordinates on the fixed lattice.

    This is the same definition as floor(x/1000), floor(y/1000), evaluated using
    the exact represented coordinate rather than a rounded floating quotient.
    Negative values immediately below zero consequently belong to index -1.
    There is no configurable origin, cell size, snapping or epsilon.
    """
    nx, dx = _coordinate_ratio(x, "x")
    ny, dy = _coordinate_ratio(y, "y")
    return nx // (1000 * dx), ny // (1000 * dy)


def grid_id(i: int, j: int) -> str:
    if isinstance(i, bool) or isinstance(j, bool) or not isinstance(i, int) or not isinstance(j, int):
        raise ValueError("grid indices must be integers")
    return f"G1K_5186_{i}_{j}"


def boundary_class(crosses, pos_equals_dominant, dominant_tied=False) -> str | None:
    """Classify supplied diagnostics without changing the selected POS cell.

    A dominant-area tie has no uniquely selected dominant cell: its comparison
    must be null. Unknown comparison on a crossing parcel stays unclassified.
    Positive-area crossing, not zero-area boundary contact, supplies ``crosses``.
    """
    if type(crosses) is not bool or type(dominant_tied) is not bool:
        raise ValueError("crosses and dominant_tied must be booleans")
    if pos_equals_dominant is not None and type(pos_equals_dominant) is not bool:
        raise ValueError("pos_equals_dominant must be boolean or null")
    if dominant_tied:
        if not crosses or pos_equals_dominant is not None:
            raise ValueError("a dominant tie requires crossing and a null comparison")
        return BOUNDARY_CLASSES[3]
    if not crosses:
        return BOUNDARY_CLASSES[0]
    if pos_equals_dominant is None:
        return None
    return BOUNDARY_CLASSES[1] if pos_equals_dominant else BOUNDARY_CLASSES[2]


def saved_pos_grid_regression(observations) -> dict:
    """Compare arithmetic on already saved POS coordinates; no geometry calls.

    The old floating division is checked alongside the exact mathematical floor
    against every saved valid parcel POS grid. Fail closed if evidence is absent
    or if any cell would change. This is not a coordinate or grid materialization.
    """
    rows = observations.get("parcel_observations")
    if not isinstance(rows, list) or not rows:
        raise ValueError("saved parcel POS arithmetic evidence is missing")
    usable = 0
    old_new_changes = 0
    saved_mismatches = 0
    for row in rows:
        diagnostic = row["geometry"]
        if diagnostic.get("status") != "GEOMETRY_VALID" or diagnostic.get("computation_status") != "OK":
            continue
        xy = diagnostic.get("point_on_surface_xy")
        if not isinstance(xy, list) or len(xy) != 2:
            raise ValueError("saved valid POS coordinate must contain x and y")
        exact = grid_index(*xy)
        old = tuple(math.floor(v / 1000) for v in xy)
        old_new_changes += exact != old
        saved_mismatches += grid_id(*exact) != diagnostic.get("point_on_surface_grid")
        usable += 1
    if not usable or old_new_changes or saved_mismatches:
        raise ValueError("saved POS grid arithmetic regression failed")
    return {
        "evidence_role": "Saved-coordinate arithmetic regression only; no geometry recomputation",
        "saved_parcels": len(rows),
        "saved_valid_POS_coordinates_checked": usable,
        "old_float_division_vs_exact_floor_cell_changes": old_new_changes,
        "saved_POS_grid_mismatches": saved_mismatches,
        "geometry_computations": 0,
        "production_assignments": 0,
        "status": "passed",
    }


def _read_json(root, relative_path):
    return json.loads((Path(root) / relative_path).read_text(encoding="utf-8"))


def _source_evidence(root, relative_path):
    return {"path": relative_path, "sha256": hashlib.sha256((Path(root) / relative_path).read_bytes()).hexdigest()}


def finalized_grid_spec(root) -> dict:
    """Return a final definition using preserved evidence, without writing files.

    The candidate file remains an unchanged historical diagnostic. The runtime
    is copied from the actual completed diagnostic loader, never inferred from
    the Python process building or testing this contract.
    """
    candidate = _read_json(root, CANDIDATE_PATH)
    observations = _read_json(root, OBSERVATIONS_PATH)
    crs_evidence = _read_json(root, CRS_EVIDENCE_PATH)
    expected = {
        "version": GRID_VERSION + "_CANDIDATE", "CRS": "EPSG:5186",
        "origin_x": 0, "origin_y": 0, "cell_size_x": 1000, "cell_size_y": 1000,
        "boundary_epsilon": 0, "coordinate_swap": False, "raw_reprojection": False,
        "snapping": False, "production_assignment": False, "diagnostic_only": True,
        "Pilot_extent_dependent": False, "region_specific_origin": False,
        "grid_id_formula": "G1K_5186_<signed_decimal_i>_<signed_decimal_j>",
        "index_formula": "i=floor((x-0)/1000);j=floor((y-0)/1000)",
    }
    for key, value in expected.items():
        if type(candidate.get(key)) is not type(value) or candidate[key] != value:
            raise ValueError(f"preserved candidate grid contract differs: {key}")
    runtime = observations.get("runtime")
    required = ("python", "executable", "shapely", "GEOS", "OGR_GEOS", "GDAL", "pyproj", "PROJ", "local_runtime_sha256")
    if not isinstance(runtime, dict) or any(not runtime.get(key) for key in required):
        raise ValueError("actual saved diagnostic runtime evidence is incomplete")
    if runtime.get("PROJ_network_enabled") is not False:
        raise ValueError("saved diagnostic runtime must record PROJ networking disabled")
    if runtime["executable"] not in runtime["local_runtime_sha256"]:
        raise ValueError("saved runtime executable fingerprint is missing")
    xy = crs_evidence["crs_and_xy_interpretation"]
    if xy.get("source_computational_xy") != "x=easting,y=northing":
        raise ValueError("native computational XY evidence differs")
    result = deepcopy(candidate)
    result.update({
        "version": GRID_VERSION,
        "diagnostic_only": False,
        "definition_only": True,
        "grid_definition_approved": True,
        "production_assignment": False,
        "production_coordinates_created": False,
        "product_target": "PARCEL_REPRESENTATIVE_GRID",
        "representative_method": "POINT_ON_SURFACE",
        "preserved_candidate": _source_evidence(root, CANDIDATE_PATH),
        "crs_evidence": _source_evidence(root, CRS_EVIDENCE_PATH),
        "computational_xy_convention": "Native geometry-engine x=easting, y=northing in metres; no axis swap from formal EPSG northing/easting labels",
        "numeric_implementation": {
            "formula_unchanged": True,
            "previous_diagnostic_implementation": "math.floor(x / 1000), math.floor(y / 1000) using binary floating division",
            "final_contract_implementation": "For finite native float coordinates use as_integer_ratio and integer floor division by 1000 times the denominator; native integers remain exact",
            "reason": "Preserve mathematical floor at represented boundaries, including negative subnormal coordinates whose floating quotient could underflow to -0",
            "origin_changed": False,
            "epsilon": 0,
            "saved_coordinate_regression": saved_pos_grid_regression(observations),
        },
        "point_on_surface_contract": {
            "method": "POINT_ON_SURFACE",
            "engine_call": "shapely geometry.representative_point() / GEOS PointOnSurface",
            "usable_geometry": "Nonempty, valid, finite-coordinate Polygon or MultiPolygon with positive area",
            "multipart_rule": "Use the complete unchanged MultiPolygon; do not choose the largest component or reorder components",
            "holes_rule": "Preserve every interior ring; POS must be covered by and strictly inside usable polygonal geometry",
            "source_geometry_rule": "Use identical preserved source WKB with identical component/ring order; no normalize, repair, buffer, snap, simplify or reprojection",
            "determinism_scope": "Same WKB bytes and frozen actual Python/Shapely/GEOS runtime; no promise across engine versions or equivalent geometry with different byte/component order",
            "failure_rule": "Keep unusable geometry or computation failure unresolved; no centroid or dominant-area fallback",
            "centroid_role": "Diagnostic only; it may lie outside a concave polygon, in a hole or between components",
            "dominant_area_role": "Sensitivity diagnostic only; never replaces the POS representative cell",
            "dominant_tie_selected_grid": None,
            "dominant_tie_comparison": None,
            "dominant_tie_automatic_choice": False,
            "boundary_classes": list(BOUNDARY_CLASSES),
            "actual_transaction_building_identified": False,
            "production_assignment": False,
        },
        "preserved_runtime": deepcopy(runtime),
        "runtime_evidence": {
            **_source_evidence(root, OBSERVATIONS_PATH),
            "json_pointer": "/runtime",
            "role": "Actual completed diagnostic runtime; frozen future POS reproducibility contract",
            "current_contract_builder_runtime_is_production_engine": False,
            "production_execution_performed": False,
            "live_runtime_revalidated": False,
            "future_execution_requirement": "Before an authorized production phase, verify actual loaded Python/Shapely/GEOS and source WKB against this frozen runtime and hashes; mismatch blocks execution",
            "Shapely_GEOS_and_OGR_GEOS_are_distinct": runtime["GEOS"] != ".".join(map(str, runtime["OGR_GEOS"])),
            "prior_local_import_authoritative_final_audit_engine": crs_evidence["local_engine_observation"]["authoritative_final_audit_engine"],
        },
    })
    return result


def representative_point_synthetic(geometry):
    """Run POS only on caller-supplied synthetic geometry for contract tests.

    This helper has no raw I/O and does not certify the calling process as the
    frozen production runtime. No intersection/dominant-area audit is invoked.
    """
    import spatial_representation_geometry_v0_1 as kernel

    if kernel.geometry_status(geometry) != "GEOMETRY_VALID":
        raise ValueError("synthetic POS requires valid usable polygonal geometry")
    point = geometry.representative_point()
    grid_index(point.x, point.y)  # Finite-coordinate validation, no assignment.
    if not geometry.covers(point) or not geometry.contains(point):
        raise ValueError("synthetic POS is not inside the polygonal geometry")
    return point
