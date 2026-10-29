"""Read frozen parcel locators and exact-PNU GIS benchmark geometry, offline.

This module never reruns transaction linkage and never writes an artifact.  Its
output contains reference-level diagnostics and occurrence weights, not final
transaction coordinates or transaction-to-grid assignments.  The caller must
verify its immutable-input baseline before calling ``collect``.
"""
import os as _khmd_path_env  # candidate-only path configuration
from collections import Counter
from contextlib import ExitStack
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import struct
import sys


PRIMARY = 'data/interim/pilot_primary_parcel_linkage_v0_1/pilot_primary_parcel_linkage.csv'
PRIMARY_FREEZE = 'metadata/pilot_primary_parcel_linkage_freeze_v0_1.json'
PRIMARY_FREEZE_SHA = 'e0cd3da8d03af187c70c6fc6aafc5a5452391b395f9d806b2a900474020fcaab'
COVERAGE_FREEZE = 'metadata/pilot_parcel_linkage_coverage_policy_freeze_v0_1_candidate.json'
COVERAGE_FREEZE_SHA = 'd0b756962cd97a357c16fc94b695c767fc68fa667d09bad642a23d6a5ecf5416'
INDEX = 'data/interim/spatial_reference_bridge_v0_1/reference_indices.sqlite'
INDEX_SHA = '7ad707fab3f9e09190dd95dd850e3a7f2ddeac3fe9d02d5c060da23011dd08f2'
INDEX_BYTES = 3681910784
PHYSICAL = 'metadata/spatial_reference_physical_set_provenance_v0_1.csv'
RAW_FREEZE = 'metadata/spatial_reference_pilot_raw_release_freeze_v0_1.json'
EXACT = 'PRIMARY_EXACT_UNIQUE_CURRENT_REFERENCE'
QGIS_ROOT = Path(_khmd_path_env.environ['KHMD_QGIS_ROOT'])
EXPECTED_SETS = {
    '4722:AL_D002_11_20260908': ('cadastral', 896903),
    '4725:AL_D002_27_20260908': ('cadastral', 785263),
    '4731:AL_D002_43_20260908': ('cadastral', 1000000),
    '4731:AL_D002_43_20260908(2)': ('cadastral', 1000000),
    '4731:AL_D002_43_20260908(3)': ('cadastral', 415439),
    '4486:AL_D010_11_20260909': ('gis', 695754),
    '4489:AL_D010_27_20260909': ('gis', 382697),
    '4495:AL_D010_43_20260909': ('gis', 837345),
}
GIS_SQL = ('SELECT set_id,row_ordinal,A2_raw,deleted_flag FROM gis INDEXED BY gis_PNU '
           'WHERE A2_raw COLLATE BINARY=? ORDER BY set_id,row_ordinal')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def within(root, relative):
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and path.is_file(), 'input_missing_or_outside_workspace')
    return path


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def grouped_primary(root):
    """Aggregate existing assignments; never infer or construct a parcel key."""
    for relative, digest in ((PRIMARY_FREEZE, PRIMARY_FREEZE_SHA),
                             (COVERAGE_FREEZE, COVERAGE_FREEZE_SHA)):
        require(sha(within(root, relative)) == digest, 'authority_freeze_hash_mismatch')
    primary_freeze = read_json(root / PRIMARY_FREEZE)
    require(sha(within(root, PRIMARY)) == primary_freeze['artifacts_sha256'][PRIMARY],
            'primary_result_hash_mismatch')
    rows = read_csv(root / PRIMARY)
    require(len(rows) == 54697, 'transaction_universe_changed')
    ids = set()
    parcels = {}
    source_counts = Counter()
    unresolved = 0
    for row in rows:
        require(row['occurrence_id'] not in ids, 'duplicate_occurrence')
        ids.add(row['occurrence_id'])
        require(row['resolved_entity_level'] == 'PARCEL', 'entity_level_changed')
        if row['combined_primary_status'] != EXACT:
            unresolved += 1
            require(not row['reference_pnu'] and not row['matched_physical_set_id']
                    and not row['matched_source_row_ordinal'], 'unresolved_has_assignment')
            continue
        pnu = row['reference_pnu']
        require(re.fullmatch(r'[0-9]{19}', pnu) is not None, 'invalid_saved_pnu')
        ordinal = int(row['matched_source_row_ordinal'])
        require(ordinal > 0 and row['reference_match_count'] == '1', 'invalid_saved_locator')
        locator = (row['matched_physical_set_id'], ordinal, row['matched_reference_region'],
                   row['matched_fileNo'])
        if pnu not in parcels:
            parcels[pnu] = dict(pnu=pnu, set_id=locator[0], ordinal=ordinal,
                                region=locator[2], fileNo=locator[3], txn_weight=0,
                                weight_strata=Counter())
        parcel = parcels[pnu]
        require(locator == (parcel['set_id'], parcel['ordinal'], parcel['region'], parcel['fileNo']),
                'same_pnu_conflicting_frozen_locator')
        parcel['txn_weight'] += 1
        parcel['weight_strata'][(row['source'], row['source_region'], row['transaction_year'])] += 1
        source_counts[row['source']] += 1
    require(unresolved == 1598 and sum(source_counts.values()) == 53099,
            'primary_counts_changed')
    require(source_counts == {'SALE': 18110, 'RENT': 34989}, 'source_counts_changed')
    for parcel in parcels.values():
        parcel['weight_strata'] = [dict(source=s, region=r, year=y, count=n)
                                  for (s, r, y), n in sorted(parcel['weight_strata'].items())]
    return [parcels[pnu] for pnu in sorted(parcels)], {
        'transactions_total': len(rows), 'exact_occurrences': 53099,
        'unresolved_occurrences_excluded_from_geometry': unresolved,
        'distinct_matched_parcels': len(parcels), 'source_exact_occurrences': dict(source_counts),
    }


def _dbf_header(stream):
    stream.seek(0)
    header = stream.read(32)
    require(len(header) == 32, 'dbf_header_short')
    count, header_length, record_length = struct.unpack_from('<IHH', header, 4)
    fields = []
    offset = 1
    while stream.tell() < header_length:
        descriptor = stream.read(32)
        if descriptor[:1] == b'\r':
            break
        require(len(descriptor) == 32, 'dbf_descriptor_short')
        name = descriptor[:11].split(b'\0', 1)[0].decode('ascii')
        width = descriptor[16]
        fields.append(dict(name=name, offset=offset, width=width, type=chr(descriptor[11]),
                           decimals=descriptor[17]))
        offset += width
    require(offset == record_length, 'dbf_record_width_mismatch')
    return dict(record_count=count, header_length=header_length, record_length=record_length,
                fields=fields, LDID=header[29])


def _verify_record(layer, stream, schema, ordinal, pnu, field):
    require(1 <= ordinal <= schema['record_count'], 'ordinal_outside_source')
    stream.seek(schema['header_length'] + (ordinal - 1) * schema['record_length'])
    raw = stream.read(schema['record_length'])
    require(len(raw) == schema['record_length'] and raw[:1] == b' ', 'deleted_or_short_source_row')
    f = next(x for x in schema['fields'] if x['name'] == field)
    require(f['type'] == 'C' and f['width'] == 19, 'pnu_physical_schema_changed')
    slot = raw[f['offset']:f['offset'] + f['width']]
    require(slot == pnu.encode('ascii'), 'raw_dbf_pnu_locator_mismatch')
    feature = layer.GetFeature(ordinal - 1)
    require(feature is not None and feature.GetFID() == ordinal - 1, 'ogr_fid_mapping_mismatch')
    require(feature.GetField(field) == pnu, 'ogr_raw_dbf_pnu_mismatch')
    geometry = feature.GetGeometryRef()
    wkb = None if geometry is None else bytes(geometry.ExportToWkb())
    return wkb


def _runtime(kernel):
    engine = kernel.load_engine()
    os.environ['PROJ_NETWORK'] = 'OFF'
    os.environ['PROJ_DATA'] = str(QGIS_ROOT / 'share/proj')
    os.environ['GDAL_DATA'] = str(QGIS_ROOT / 'share/gdal')
    # Keep DLL directory handles alive through all geometry reads.
    dll_handle = os.add_dll_directory(str(QGIS_ROOT / 'bin')) if os.name == 'nt' else None
    qgis_site = str(QGIS_ROOT / 'apps/Python312/Lib/site-packages')
    if qgis_site not in sys.path:
        sys.path.append(qgis_site)
    from osgeo import gdal, ogr
    import pyproj
    import shapely
    pyproj.network.set_network_enabled(False)
    gdal.SetConfigOption('PROJ_NETWORK', 'OFF')
    gdal.SetConfigOption('GDAL_PAM_ENABLED', 'NO')
    gdal.UseExceptions()
    ogr.UseExceptions()
    return engine, gdal, ogr, pyproj, shapely, dll_handle


def _crs_facts(prj, layer, pyproj):
    from resolve_cadastral_na23_crs_v0_1 import definition_checks
    text = prj.read_text(encoding='utf-8-sig')
    source = pyproj.CRS.from_wkt(text)
    target = pyproj.CRS.from_epsg(5186)
    checks, parameters = definition_checks(source, target)
    require(all(checks.values()), 'actual_prj_definition_not_epsg5186')
    srs = layer.GetSpatialRef()
    require(srs is not None, 'ogr_spatial_reference_missing')
    ogr_crs = pyproj.CRS.from_wkt(srs.ExportToWkt())
    ogr_checks, _ = definition_checks(ogr_crs, target)
    require(all(ogr_checks.values()), 'ogr_crs_definition_mismatch')
    return dict(actual_PRJ_text=text, PRJ_sha256=sha(prj), initial_authority=source.to_authority(min_confidence=100),
                effective_authority=['EPSG', '5186'], definition_checks=checks, parameters=parameters,
                source_axes=[dict(name=a.name, direction=a.direction, unit=a.unit_name,
                                  unit_conversion_factor=a.unit_conversion_factor) for a in source.axis_info],
                source_xy_convention='x=easting,y=northing', coordinate_unit='metre',
                EPSG_axis_order='northing,easting',
                OGR_data_axis_to_SRS_axis_mapping=srs.GetDataAxisToSRSAxisMapping(),
                axis_reordering_performed=False, reprojection_performed=False,
                PROJ_network_enabled=pyproj.network.is_network_enabled())


def _gis_diagnostic(geometry, kernel):
    """Representative-point benchmark only; no GIS footprint/grid intersections."""
    status = kernel.geometry_status(geometry)
    rawvalid = None if geometry is None else bool(geometry.is_valid)
    if status != 'GEOMETRY_VALID':
        return dict(gstatus=status, rawvalid=rawvalid, representative_point=None,
                    grid=None, computation_status='NOT_APPLICABLE', computation_error=None)
    try:
        point = geometry.representative_point()
        require(not point.is_empty and math.isfinite(point.x) and math.isfinite(point.y),
                'gis_representative_point_nonfinite')
        inside = bool(geometry.covers(point))
        require(inside, 'gis_representative_point_outside')
        return dict(gstatus=status, rawvalid=True,
                    representative_point=dict(x=point.x, y=point.y, inside=inside),
                    grid=kernel.grid_id(*kernel.grid_index(point.x, point.y)),
                    computation_status='OK', computation_error=None)
    except Exception as error:
        return dict(gstatus=status, rawvalid=True, representative_point=None,
                    grid=None, computation_status='ERROR', computation_error=type(error).__name__)


def collect(root):
    """Return JSON-serializable reference diagnostics without writing anything."""
    import spatial_representation_geometry_v0_1 as kernel
    root = Path(root).resolve()
    parcels, counts = grouped_primary(root)
    engine, gdal, ogr, pyproj, shapely, dll_handle = _runtime(kernel)
    input_paths = {PRIMARY, PRIMARY_FREEZE, COVERAGE_FREEZE, INDEX, PHYSICAL, RAW_FREEZE}
    require(within(root, INDEX).stat().st_size == INDEX_BYTES, 'reference_index_size_changed')
    index = sqlite3.connect((root / INDEX).as_uri() + '?mode=ro&immutable=1', uri=True)
    index.execute('PRAGMA query_only=ON')
    require(index.execute('PRAGMA query_only').fetchone() == (1,), 'reference_index_not_query_only')
    datasets = []
    warnings = Counter()
    def quiet(error_class, error_number, message):
        warnings[str(error_class) + ':' + str(error_number)] += 1
    gdal.PushErrorHandler(quiet)
    try:
        columns = [x[1] for x in index.execute('PRAGMA table_info(physical_sets)')]
        metadata = [dict(zip(columns, row)) for row in index.execute('SELECT * FROM physical_sets ORDER BY set_id')]
        require({x['set_id']: (x['source'], int(x['record_count'])) for x in metadata} == EXPECTED_SETS,
                'all_eight_physical_sets_required')
        csv_sets = {x['set_id']: x for x in read_csv(root / PHYSICAL)}
        require(len(csv_sets) == 8 and all({k: csv_sets[x['set_id']][k] for k in columns} == x for x in metadata),
                'physical_set_csv_sqlite_mismatch')
        plan = index.execute('EXPLAIN QUERY PLAN ' + GIS_SQL, ('0000000000000000000',)).fetchall()
        require(len(plan) == 1 and 'SEARCH gis USING INDEX gis_PNU' in plan[0][3],
                'gis_exact_lookup_not_indexed')
        sets = {}
        extracted_bindings = {}
        parcel_output = []
        gis_output = []
        matched_by_set = Counter(x['set_id'] for x in parcels)
        with ExitStack() as resources:
            for entry in metadata:
                sid = entry['set_id']
                dbf = within(root, entry['dbf_path'])
                shp, shx, prj = [dbf.with_suffix(suffix) for suffix in ('.shp', '.shx', '.prj')]
                require(shp.name == entry['shp_member'], 'shp_member_binding_mismatch')
                extraction_path = within(root, entry['extraction_manifest_path'])
                require(sha(extraction_path) == entry['extraction_manifest_sha'], 'extraction_manifest_changed')
                extraction = read_json(extraction_path)
                require(extraction['source_sha256'] == entry['raw_archive_sha'], 'archive_extraction_binding_mismatch')
                require(extraction['files_sha256'][entry['dbf_path']] == entry['dbf_sha'], 'dbf_hash_binding_mismatch')
                input_paths.update(extraction['files_sha256'])
                input_paths.update([entry['extraction_manifest_path'], entry['raw_archive_path']])
                extracted_bindings.update(extraction['files_sha256'])
                for path in (shp, shx, prj):
                    require(path.is_file() and path.relative_to(root).as_posix() in extraction['files_sha256'],
                            'shape_member_missing_or_unbound')
                stream = resources.enter_context(dbf.open('rb'))
                schema = _dbf_header(stream)
                require(schema == json.loads(entry['schema_json']), 'physical_dbf_schema_changed')
                shx_bytes = shx.stat().st_size
                require(shx_bytes >= 100 and (shx_bytes - 100) % 8 == 0, 'invalid_shx_size')
                count = schema['record_count']
                require((shx_bytes - 100) // 8 == count == int(entry['record_count']), 'dbf_shx_count_mismatch')
                dataset = ogr.Open(str(shp), 0)
                require(dataset is not None and dataset.GetLayerCount() == 1, 'ogr_readonly_layer_open_failed')
                datasets.append(dataset)
                layer = dataset.GetLayer(0)
                require(layer.GetFeatureCount() == count, 'ogr_source_count_mismatch')
                crs = _crs_facts(prj, layer, pyproj)
                require(crs['PRJ_sha256'] == extraction['files_sha256'][prj.relative_to(root).as_posix()],
                        'actual_prj_hash_changed')
                entry.update(geometry_path=shp.relative_to(root).as_posix(), geometry_feature_count=count,
                             matched_parcel_count=matched_by_set[sid], CRS=crs)
                sets[sid] = dict(layer=layer, stream=stream, schema=schema, metadata=entry)
            for number, parcel in enumerate(parcels, 1):
                sid, ordinal, pnu = parcel['set_id'], parcel['ordinal'], parcel['pnu']
                require(sid in sets and sets[sid]['metadata']['source'] == 'cadastral', 'unknown_parcel_set')
                source = sets[sid]
                require((source['metadata']['region'], source['metadata']['fileNo']) == (parcel['region'], parcel['fileNo']),
                        'saved_parcel_source_provenance_mismatch')
                saved = index.execute('SELECT A1_raw,deleted_flag FROM cadastral WHERE set_id=? AND row_ordinal=?',
                                      (sid, ordinal)).fetchall()
                require(saved == [(pnu, 0)], 'saved_parcel_index_provenance_mismatch')
                wkb = _verify_record(source['layer'], source['stream'], source['schema'], ordinal, pnu, 'A1')
                geometry = None if wkb is None else shapely.from_wkb(wkb)
                diagnostic = kernel.analyze_geometry(geometry)
                diagnostic['wkb_sha256'] = None if wkb is None else hashlib.sha256(wkb).hexdigest()
                parcel_output.append(dict(parcel, geometry=diagnostic))
                gis_candidates = index.execute(GIS_SQL, (pnu,)).fetchall()
                for gis_sid, gis_ordinal, gis_pnu, deleted in gis_candidates:
                    require(gis_pnu == pnu and deleted == 0 and gis_sid in sets
                            and sets[gis_sid]['metadata']['source'] == 'gis', 'gis_candidate_provenance_mismatch')
                    source = sets[gis_sid]
                    wkb = _verify_record(source['layer'], source['stream'], source['schema'], gis_ordinal, pnu, 'A2')
                    geometry = None if wkb is None else shapely.from_wkb(wkb)
                    observation = _gis_diagnostic(geometry, kernel)
                    observation.update(pnu=pnu, set_id=gis_sid, ordinal=gis_ordinal,
                                       region=source['metadata']['region'], fileNo=source['metadata']['fileNo'],
                                       wkb_sha256=None if wkb is None else hashlib.sha256(wkb).hexdigest())
                    gis_output.append(observation)
                if number % 200 == 0:
                    print(json.dumps(dict(event='reference_geometry_diagnostics', parcels_complete=number,
                                          parcels_total=len(parcels), gis_features=len(gis_output))), flush=True)
        require(sum(x['txn_weight'] for x in parcel_output) == 53099, 'diagnostic_weight_loss')
        require(len({(x['set_id'], x['ordinal']) for x in gis_output}) == len(gis_output), 'duplicate_gis_physical_row')
        for entry in metadata:
            entry['benchmark_gis_features_read'] = sum(x['set_id'] == entry['set_id'] for x in gis_output)
        runtime_paths = [Path(sys.executable), Path(shapely.__file__), Path(shapely.lib.__file__),
                         Path(gdal.__file__), QGIS_ROOT / 'bin/gdal309.dll',
                         QGIS_ROOT / 'bin/geos_c.dll', QGIS_ROOT / 'bin/geos.dll',
                         Path(pyproj.datadir.get_data_dir()) / 'proj.db']
        runtime = dict(python=sys.version, executable=sys.executable, shapely=shapely.__version__,
                       GEOS=shapely.geos_version_string, GDAL=gdal.VersionInfo(),
                       OGR_GEOS=[ogr.GetGEOSVersionMajor(), ogr.GetGEOSVersionMinor(), ogr.GetGEOSVersionMicro()],
                       pyproj=pyproj.__version__, PROJ=pyproj.proj_version_str,
                       PROJ_network_enabled=pyproj.network.is_network_enabled(), GDAL_PAM_ENABLED=gdal.GetConfigOption('GDAL_PAM_ENABLED'),
                       local_runtime_sha256={str(p): sha(p) for p in runtime_paths if p.is_file()},
                       gdal_diagnostic_counts=dict(warnings))
        counts.update(gis_exact_pnu_queries=len(parcels), gis_features_read=len(gis_output),
                      parcel_geometry_reads=len(parcel_output), physical_sets_opened=len(metadata),
                      cadastral_sets_opened=5, gis_sets_opened=3,
                      saved_cadastral_locator_verifications=len(parcels),
                      raw_dbf_ogr_fid_pnu_verifications=len(parcel_output) + len(gis_output),
                      transaction_linkage_reruns=0, transaction_grid_assignments=0,
                      transaction_gis_assignments=0, unresolved_geometry_assignments=0,
                      geometry_repairs=0, reprojections=0, API_calls=0, downloads=0)
        return dict(parcel_observations=parcel_output, gis_features=gis_output,
                    physical_sets=metadata, runtime=runtime, counts=counts,
                    input_provenance=dict(primary_freeze_sha256=PRIMARY_FREEZE_SHA,
                                          coverage_freeze_sha256=COVERAGE_FREEZE_SHA,
                                          index_expected_sha256=INDEX_SHA, input_integrity_owner='caller immutable baseline',
                                          index_mode='mode=ro&immutable=1; query_only=ON', GIS_query=GIS_SQL,
                                          GIS_query_plan=[list(x) for x in plan],
                                          raw_DBF_and_OGR_FID_alignment='physical ordinal minus one, verified per geometry read',
                                          extracted_member_expected_sha256=extracted_bindings,
                                          source_scope='all eight declared physical sets; no region filter'),
                    input_paths=sorted(input_paths))
    finally:
        datasets.clear()
        index.close()
        gdal.PopErrorHandler()
        if dll_handle is not None:
            dll_handle.close()
