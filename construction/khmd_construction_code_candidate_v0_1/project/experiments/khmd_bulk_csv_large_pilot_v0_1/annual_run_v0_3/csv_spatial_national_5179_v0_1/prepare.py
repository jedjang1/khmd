"""Catalog-only preparation: no CSV parsing, demand regeneration or geometry."""
import pipeline as p
from collections import defaultdict
b=p.b;ROOT=p.ROOT;H=p.H
mat=b.read(ROOT/'metadata/rent_k2v2_reference_materialization_v0_1.json');oldcfg=b.read(p.V/'config.json');bridge='experiments/khmd_bulk_csv_large_pilot_v0_1/annual_run_v0_3/csv_spatial_bridge_v0_1/sample_config.json'
bc=b.read(ROOT/bridge);objects={};prefix=defaultdict(set);existing=defaultdict(list);member_manifests=set()
for x in mat['physical_sets']:
    manifest=b.read(ROOT/x['extraction_manifest_path']);member_manifests.add(x['extraction_manifest_path']);path=ROOT/x['dbf_path'];members={}
    for ext in ('.dbf','.shp','.shx','.prj','.cpg'):
        target=path.with_suffix(ext);rel=target.relative_to(ROOT).as_posix();sha=manifest['files_sha256'][rel]
        members[ext]=dict(path=str(target),sha256=sha,bytes=target.stat().st_size)
    existing[x['fileNo']].append(dict(set_id=x['set_id'],members=members,source_archive_sha256=x['raw_archive_sha'],region=x['region']))
for x in p.csv.DictReader((ROOT/'metadata/khmd_nationwide_cadastral_reference_object_registry_v0_1.csv').open(encoding='utf-8-sig')):
    oid=x['reference_region_id'];x=dict(x);x['file_no']=oid.split('_')[-1];x['existing_sets']=existing[x['file_no']]
    raw=ROOT/x['raw_path'];b.need(raw.stat().st_size==int(x['bytes']),'RAW_CATALOG_BYTES')
    with p.zipfile.ZipFile(raw) as z:
        names=[i.filename for i in z.infolist() if p.Path(i.filename).suffix.lower() in ('.dbf','.shp','.shx','.prj','.cpg')]
        for n in names:
            b.need(p.Path(n).name==n and '..' not in n,'MEMBER_SAFETY');match=p.re.fullmatch(r'AL_D002_(\d{2})_20260908(?:\(\d+\))?\.(?:dbf|shp|shx|prj|cpg)',n);b.need(match is not None,'MEMBER_IDENTITY');prefix[match[1]].add(oid)
        x['members']=names
    objects[oid]=x
summary=list(p.csv.DictReader((p.P/'regional_demand_summary.csv').open(encoding='utf-8-sig')))
regions=[x['province'] for x in sorted(summary,key=lambda x:int(x['distinct_address_keys'])) if x['province']!='부산광역시']
b.need(sum(int(x['processed_occurrences']) for x in summary if x['province']!='부산광역시')==19588294,'REMAINING_COUNT')
codepaths=[H/'pipeline.py',H/'prepare.py',p.V/'grid.py',p.V/'grid_policy.json',p.P/'demand.py',p.old.s.Path(p.old.s.__file__),p.Path(b.__file__),ROOT/'src/spatial_representation_inputs_v0_1.py',ROOT/'src/khmd_reference_resource_monitor_v0_2.py',ROOT/'metadata/khmd_nationwide_reference_resource_monitor_contract_v0_2.json']
inputpaths=[ROOT/'metadata/khmd_nationwide_cadastral_reference_object_registry_v0_1.csv',ROOT/'metadata/khmd_nationwide_reference_row_exception_registry_v0_1.csv',ROOT/'metadata/khmd_nationwide_reference_region_validation_policy_v0_3.json',ROOT/'metadata/khmd_nationwide_reference_cross_object_pnu_uniqueness_summary_v0_1.json',ROOT/'metadata/rent_k2v2_reference_materialization_v0_1.json',ROOT/bridge,ROOT/bc['pos_manifest'],ROOT/bc['saved_pos_index'],ROOT/oldcfg['release'],p.P/'national_demand/final_manifest.json',p.B/'busan_run/final_manifest.json',H.parent/'csv_spatial_supply_v0_1/supply_run_v0_4/generated_points.sqlite']+[ROOT/x for x in member_manifests]
dm=b.read(p.P/'national_demand/final_manifest.json')
bindings=[dict(path=str(x),sha256=b.lane.sha(x)) for x in inputpaths]+[dict(path=str(p.P/'national_demand/demand.sqlite'),sha256=dm['database_sha256']),dict(path=str(ROOT/mat['index_path']),sha256=mat['index_sha256'])]
b.write(H/'config.json',dict(started_utc='2026-10-27T15:59:50.380776+00:00',mode='USER_AUTHORIZED_REMAINING_REGIONS_SEQUENTIAL',regions=regions,region_ids={v:'R'+str(i+1).zfill(2) for i,v in enumerate(regions)},objects=objects,prefix_objects={k:sorted(v) for k,v in prefix.items()},routing_basis='Inherited exact legal codes/current or approved historical-name bridge -> validated member code prefix; never query province -> historical boundary',index_path=mat['index_path'],bridge_config=bridge,exceptions='metadata/khmd_nationwide_reference_row_exception_registry_v0_1.csv',captured_runtime_root=oldcfg['captured_runtime_root'],code_bindings=[dict(path=str(x),sha256=b.lane.sha(x)) for x in codepaths],input_bindings=bindings,expected_remaining=19588294,expected_national=20916100,grid_version=p.grid.VERSION))
b.table(H/'scope.csv',[dict(query_region=x['province'],cells=x['source_files'],occurrences=x['processed_occurrences'],address_keys=x['distinct_address_keys'],action='REUSE_COMPLETED' if x['province']=='부산광역시' else 'SEQUENTIAL_PROCESS') for x in summary])
print(b.dump(dict(remaining_regions=regions,reference_prefixes={k:sorted(v) for k,v in prefix.items()},new_input=19588294)))
