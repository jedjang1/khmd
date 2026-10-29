"""Demand-scoped reference supply; existing guard/geometry kernel unchanged.

One bounded regional DBF pass for 33 exact address keys, not a national index.
Frozen originals are read-only. Only prior NOT_AGGREGATABLE rows can change.
"""
import os as _khmd_path_env  # candidate-only path configuration
import os,sys
from pathlib import Path
# The captured QGIS sqlite extension depends on its preserved bin directory.
# Establish the DLL search directory before importing sqlite3 or the bridge.
_bootstrap_dll=None
if Path(sys.executable).parent.name=='Python312':
    _bootstrap_root=Path(sys.executable).parents[2]
    _bootstrap_dll=os.add_dll_directory(str(_bootstrap_root/'bin'))
import argparse,copy,csv,hashlib,json,sqlite3,time,traceback,zipfile
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
H=Path(__file__).resolve().parent;ROOT=H.parents[3]
sys.path.insert(0,str(H.parent/'csv_spatial_bridge_v0_1'));import bridge as b
sys.path.insert(0,str(ROOT/'src'))
import spatial_representation_inputs_v0_1 as inputs

def js(path):return b.read(path)
def jsonl(path):return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
def output(path,rows):
    with path.open('x',encoding='utf-8') as f:
        for r in rows:f.write(b.dump(r)+'\n')
def pin(cfg,g):
    for p in cfg['bindings']:b.need(b.lane.sha(ROOT/p['path'],g)==p['sha256'],'BINDING_DRIFT:'+p['path'])
def captured_runtime(cfg,g):
    """Exact archived engine bytes, explicit relocation; original spec unchanged."""
    root=ROOT/cfg['captured_runtime_root'];expected=js(ROOT/'metadata/khmd_parcel_spatial_crosswalk_geometry_runtime_spec_v0_1.json')['expected']
    oldroot=Path(_khmd_path_env.environ['KHMD_QGIS_ROOT']);checked={}
    for source,sha in expected['local_runtime_sha256'].items():
        path=root/Path(source).relative_to(oldroot)
        b.need(b.lane.sha(path,g)==sha,'CAPTURED_ENGINE_SHA:'+str(path));checked[str(path)]=sha
    b.need(Path(sys.executable).resolve()==(root/'apps/Python312/python.exe').resolve(),'CAPTURED_EXECUTABLE')
    handle=os.add_dll_directory(str(root/'bin'))
    os.environ['PROJ_NETWORK']='OFF';os.environ['PROJ_DATA']=str(root/'share/proj');os.environ['GDAL_DATA']=str(root/'apps/gdal/share')
    from osgeo import gdal,ogr
    import shapely,pyproj
    pyproj.network.set_network_enabled(False);gdal.SetConfigOption('GDAL_PAM_ENABLED','NO');gdal.SetConfigOption('PROJ_NETWORK','OFF');gdal.UseExceptions();ogr.UseExceptions()
    actual=dict(python=sys.version,executable=sys.executable,shapely=shapely.__version__,GEOS=shapely.geos_version_string,GDAL=gdal.VersionInfo(),OGR_GEOS=[ogr.GetGEOSVersionMajor(),ogr.GetGEOSVersionMinor(),ogr.GetGEOSVersionMicro()],pyproj=pyproj.__version__,PROJ=pyproj.proj_version_str)
    for k in ('python','shapely','GEOS','GDAL','OGR_GEOS','pyproj','PROJ'):b.need(actual[k]==expected[k],'FROZEN_ENGINE_VERSION:'+k)
    b.need(str(Path(shapely.__file__).resolve()) in checked and str(Path(shapely.lib.__file__).resolve()) in checked,'LOADED_ENGINE_PATH')
    actual.update(relocation='IDENTICAL_PINNED_BYTES_IN_EXISTING_CAPTURE',checked_runtime_files=checked)
    return actual,(gdal,ogr,pyproj,shapely,handle)
def rawfields(raw,header):
    b.need(len(raw)==header['record_length'] and raw[:1]==b' ','SOURCE_DBF_DELETED_OR_SHORT')
    return {x['name']:raw[x['offset']:x['offset']+x['width']].decode('euc_kr').rstrip(' ') for x in header['fields']}

def extract_busan(cfg,out,g):
    obj=cfg['busan'];raw=ROOT/obj['raw_path'];before=b.identity(raw)
    b.need(raw.stat().st_size==int(obj['bytes']),'BUSAN_BYTES')
    # Only newly consumed regional archive, not all held archives.
    b.need(b.lane.sha(raw,g)==obj['sha256'],'BUSAN_SOURCE_SHA')
    scratch=out/'scratch';scratch.mkdir();members={}
    with zipfile.ZipFile(raw) as z:
        needed=[i for i in z.infolist() if Path(i.filename).suffix.lower() in ('.dbf','.shp','.shx','.prj','.cpg')]
        b.need(len(needed)==5 and len({Path(i.filename).stem for i in needed})==1,'BUSAN_MEMBER_SCOPE')
        total=sum(i.file_size for i in needed);g.reserve_output(total+16*1024*1024)
        for info in needed:
            p=scratch/Path(info.filename).name;b.lane.safe(p);h=hashlib.sha256();n=0
            with z.open(info) as src,p.open('xb') as dst:
                while True:
                    chunk=src.read(256*1024)
                    if not chunk:break
                    dst.write(chunk);h.update(chunk);n+=len(chunk)
                    g.checkpoint('regional_member_bytes_completed_'+str(n))
            b.need(n==info.file_size,'ZIP_MEMBER_SIZE')
            members[p.suffix]=dict(path=str(p),sha256=h.hexdigest(),bytes=n,source_member=info.filename,source_archive_sha256=obj['sha256'])
    b.need(b.identity(raw)==before,'RAW_CHANGED_DURING_READ')
    b.write(out/'regional_extraction.json',dict(source=obj,members=members,scratch_bytes=total,CRC_verified_by_zipfile=True))
    return members,total

def build_target_index(cfg,targets,members,out,g):
    wanted={}
    for a in targets:
        if a['reason']=='PARCEL_REFERENCE_REGION_NOT_MATERIALIZED':
            b.need(a['csv_region_literal'].startswith('부산광역시 ') and len(a['legal_codes'])==1 and a['jibun_status']=='JIBUN_IDENTITY_VALID','TARGET_SCOPE')
            wanted[(a['legal_codes'][0],a['jibun_literal'])]=a['address_id']
    b.need(len(wanted)==33,'TARGET_KEY_COUNT')
    c=sqlite3.connect(out/'target_reference.sqlite');c.execute('PRAGMA cache_size=-1024');c.execute('PRAGMA temp_store=FILE')
    c.execute('CREATE TABLE parcels(address_id TEXT,pnu TEXT,legal_code TEXT,jibun TEXT,ordinal INTEGER,dbf_record_sha256 TEXT,source_archive_sha256 TEXT,PRIMARY KEY(address_id,pnu,ordinal))')
    candidates=defaultdict(list)
    p=Path(members['.dbf']['path'])
    with p.open('rb') as f:
        header=inputs._dbf_header(f);b.need(header['record_count']==705940,'REGIONAL_ROW_COUNT')
        b.need([(x['name'],x['type'],x['width']) for x in header['fields']]==[('A0','N',9),('A1','C',19),('A2','C',10),('A3','C',254),('A4','C',10),('A5','C',200),('A6','D',8),('A7','C',5)],'SOURCE_SCHEMA')
        fields={x['name']:x for x in header['fields']}
        f.seek(header['header_length'])
        for ordinal in range(1,header['record_count']+1):
            raw=f.read(header['record_length']);b.need(len(raw)==header['record_length'] and raw[:1]==b' ','DBF_SHORT_OR_DELETED')
            code=raw[fields['A2']['offset']:fields['A2']['offset']+10].decode('ascii')
            lot=raw[fields['A4']['offset']:fields['A4']['offset']+10].decode('euc_kr').rstrip(' ')
            aid=wanted.get((code,lot))
            if aid:
                values=rawfields(raw,header);pnu=values['A1'];b.need(len(pnu)==19 and pnu.isascii() and pnu.isdigit() and pnu[:10]==code,'PNU_SOURCE_CODE')
                rec=dict(pnu=pnu,legal_code=code,jibun=lot,row_ordinal=ordinal,dbf_record_sha256=hashlib.sha256(raw).hexdigest(),dbf_path=str(p),set_id='4724:'+p.stem,raw_archive_sha256_recorded=cfg['busan']['sha256'])
                candidates[aid].append(rec)
                c.execute('insert into parcels values(?,?,?,?,?,?,?)',(aid,pnu,code,lot,ordinal,rec['dbf_record_sha256'],cfg['busan']['sha256']))
            if ordinal%2048==0:g.checkpoint('regional_DBF_records_completed_'+str(ordinal))
        b.need(f.read() in (b'',b'\x1a'),'DBF_TRAILER')
    c.execute('CREATE INDEX exact_address ON parcels(legal_code COLLATE BINARY,jibun COLLATE BINARY)');c.commit();c.close()
    b.write(out/'index_manifest.json',dict(scope='ONLY_33_EXPLICIT_ADDRESS_KEYS',negative_match_scope='Entire_busAN_DBF_705940_records_scanned_for_these_keys',rows_scanned=705940,target_keys=33,matched_rows=sum(map(len,candidates.values())),source_archive_sha256=cfg['busan']['sha256'],dbf_sha256=members['.dbf']['sha256'],index_sha256=b.lane.sha(out/'target_reference.sqlite'),national_authority=False))
    return candidates,header

class SupplyOverlay:
    """Consumed by the CSV bridge continuation; no transaction-row collapse."""
    def __init__(self,manifest_path):
        self.manifest=js(manifest_path);p=manifest_path.parent/self.manifest['address_file']
        b.need(b.lane.sha(p)==self.manifest['address_sha256'],'SUPPLY_PAYLOAD_SHA')
        self.items={r['address_id']:r for r in jsonl(p)}
    def apply(self,row,release_sha):
        b.need(release_sha==self.manifest['release_sha256'],'SUPPLY_RELEASE_BINDING')
        item=self.items.get(row['address_id'])
        if item is None:return copy.deepcopy(row)
        b.need(row['status']=='NOT_AGGREGATABLE','SUPPLY_PRIOR_STATUS')
        b.need((row['csv_region_literal'],row['jibun_literal'],row['reference_legal_codes'])==(item['csv_region_literal'],item['jibun_literal'],item['legal_codes']),'SUPPLY_ADDRESS_BINDING')
        new=copy.deepcopy(row);new['prior_status']=row['status'];new['status']=item['status'];new['reason']=item['reason'];new['supply_manifest']=str(self.manifest['supply_id'])
        if item['status']=='UNIQUE_REFERENCE_ASSIGNED':
            b.need(item['candidate_count']==1 and len(item['spatial_candidates'])==1,'SUPPLY_NOT_UNIQUE')
            p=item['spatial_candidates'][0]
            for k in ('pnu','x','y','grid_id'):new[k]=p[k]
        return new

def continuation(cfg,out,supplied,g):
    prior=ROOT/cfg['prior']/'sample_run_v0_1';rows=jsonl(prior/'observations.jsonl')
    output(out/'supplied_addresses.jsonl',supplied)
    b.write(out/'supply_manifest.json',dict(supply_id=str(out.relative_to(ROOT)),address_file='supplied_addresses.jsonl',address_sha256=b.lane.sha(out/'supplied_addresses.jsonl'),release_sha256=cfg['release_sha256'],prior_completion_sha256=b.lane.sha(prior/'completion.json'),point_file='generated_points.jsonl',point_sha256=b.lane.sha(out/'generated_points.jsonl'),no_historical_location_claim=True))
    overlay=SupplyOverlay(out/'supply_manifest.json');new=[overlay.apply(x,cfg['release_sha256']) for x in rows]
    b.need(len(new)==len({x['observation_id'] for x in new})==330,'OBSERVATION_CONSERVATION')
    unchanged=[(x,y) for x,y in zip(rows,new) if x['status']!='NOT_AGGREGATABLE']
    b.need(len(unchanged)==264 and all(x==y for x,y in unchanged),'PRIOR_RESULT_CHANGED')
    b.need(Counter((x['file_sha256'],x['raw_content_digest']) for x in new)==Counter((x['file_sha256'],x['raw_content_digest']) for x in rows),'MULTIPLICITY_CHANGED')
    grid=Counter((x['family'],x['quarter'],x['grid_id']) for x in new if x['status']=='UNIQUE_REFERENCE_ASSIGNED')
    statuses=Counter(x['status'] for x in new);quarters=Counter((x['family'],x['quarter'],x['status']) for x in new)
    b.need(sum(grid.values())==statuses['UNIQUE_REFERENCE_ASSIGNED'] and sum(quarters.values())==330,'GRID_CONSERVATION')
    output(out/'observations.jsonl',new)
    b.table(out/'grid_quarter_counts.csv',[dict(family=f,quarter=q,grid_id=gid,observation_occurrences=n,scope='SAMPLE_ONLY') for (f,q,gid),n in sorted(grid.items())])
    b.table(out/'quarter_status_counts.csv',[dict(family=f,quarter=q,status=s,occurrences=n) for (f,q,s),n in sorted(quarters.items())])
    tests=[]
    def reject(name,fn):
        try:fn()
        except Exception as e:tests.append(dict(name=name,result='PASS',error=str(e)));return
        raise AssertionError('NOT_REJECTED:'+name)
    target=next(x for x in rows if x['status']=='NOT_AGGREGATABLE')
    reject('wrong_release',lambda:overlay.apply(target,'0'*64))
    wrong=copy.deepcopy(target);wrong['jibun_literal']='FOREIGN'
    reject('wrong_literal_address',lambda:overlay.apply(wrong,cfg['release_sha256']))
    wrong=copy.deepcopy(target);wrong['status']='UNIQUE_REFERENCE_ASSIGNED'
    reject('cannot_replace_prior_success',lambda:overlay.apply(wrong,cfg['release_sha256']))
    for name in ['330_unique_source_IDs','264_prior_results_unchanged','repeated_occurrence_multiset_unchanged','grid_and_quarter_conservation']:tests.append(dict(name=name,result='PASS'))
    b.write(out/'regression.json',tests);g.checkpoint('bridge_continuation_and_regressions_complete')
    return dict(status_counts={k:statuses[k] for k in b.STATUSES},occurrences=330,reused_unchanged_occurrences=264,affected_occurrences=66,assigned_grid_occurrences=sum(grid.values()),unassigned_occurrences=330-sum(grid.values()),grid_groups=len(grid),quarter_conservation=sum(quarters.values())==330,regressions=len(tests))

def worker(config,out):
    t=time.monotonic();g=b.lane.resource.ReferenceGuard(ROOT);work=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY']);timings={}
    try:
        g.admit();cfg=js(config);b.need(cfg['mode']=='TARGETED_EXISTING_ASSET_SUPPLY' and not cfg['full_national_execution'],'SCOPE')
        pin(cfg,g);targets=js(ROOT/cfg['targets']);b.need(len(targets)==cfg['max_target_addresses']==35,'TARGET_COUNT')
        st=time.monotonic();members,scratch=extract_busan(cfg,out,g);timings['regional_extraction_seconds']=time.monotonic()-st
        st=time.monotonic();found,header=build_target_index(cfg,targets,members,out,g);timings['target_index_seconds']=time.monotonic()-st
        from parcel_spatial_crosswalk_geometry_v0_1 import compute
        st=time.monotonic();runtime,engines=captured_runtime(cfg,g);gdal,ogr,pyproj,shapely,dll=engines
        gdal.SetCacheMax(1024*1024);g.checkpoint('frozen_geometry_runtime_verified')
        b.write(out/'runtime.json',runtime);timings['runtime_seconds']=time.monotonic()-st
        points=[];supplied=[];sources={};crs=[];input_ids={}
        exceptions=list(csv.DictReader((ROOT/'metadata/khmd_nationwide_reference_row_exception_registry_v0_1.csv').open(encoding='utf-8-sig')))
        quarantined_pnu=str(cfg.get('quarantined_reference_pnu',''))
        b.need(hashlib.sha256(quarantined_pnu.encode('ascii')).hexdigest()=='7443a594cba325a0621be34e5c56d460ad061537e1b97bbda231c28dfcfcbfa4','EXTERNAL_QUARANTINE_IDENTITY_REQUIRED')
        b.write(out/'row_exception_gate.json',dict(source='metadata/khmd_nationwide_reference_row_exception_registry_v0_1.csv',rows=len(exceptions),quarantined_pnu=quarantined_pnu,exact_targets_outside_known_exceptions=True))
        st=time.monotonic()
        for original in targets:
            a=copy.deepcopy(original)
            if original['reason']=='PARCEL_REFERENCE_REGION_NOT_MATERIALIZED':a['parcel_candidates']=found.get(a['address_id'],[])
            a['candidate_count']=len(a['parcel_candidates'])
            if a['candidate_count']!=1:
                a.update(status='UNLINKED' if not a['candidate_count'] else 'AMBIGUOUS_REFERENCE',reason='TARGET_SOURCE_NO_EXACT_PARCEL' if not a['candidate_count'] else 'MULTIPLE_PARCELS_NO_AUTOMATIC_CHOICE');supplied.append(a);continue
            rec=a['parcel_candidates'][0];pnu=rec['pnu'];b.need(pnu!=quarantined_pnu,'QUARANTINED_REFERENCE_PNU')
            path=Path(rec['dbf_path']);path=path if path.is_absolute() else ROOT/path
            key=str(path)
            if key not in sources:
                dataset=ogr.Open(str(path.with_suffix('.shp')),0);b.need(dataset is not None,'GEOMETRY_SOURCE_MISSING')
                layer=dataset.GetLayer(0);facts=inputs._crs_facts(path.with_suffix('.prj'),layer,pyproj)
                b.need(facts['effective_authority']==['EPSG','5186'] and not facts['reprojection_performed'],'CRS_GATE')
                f=path.open('rb');h=inputs._dbf_header(f);b.need(layer.GetFeatureCount()==h['record_count'],'GEOMETRY_DBF_ROW_COUNT')
                sources[key]=(dataset,layer,f,h);crs.append(dict(path=key,**facts))
                for suffix in ('.dbf','.shp','.shx','.prj'):input_ids[str(path.with_suffix(suffix))]=b.identity(path.with_suffix(suffix))
            dataset,layer,f,h=sources[key];ordinal=rec['row_ordinal']
            f.seek(h['header_length']+(ordinal-1)*h['record_length']);raw=f.read(h['record_length']);fields=rawfields(raw,h)
            b.need(hashlib.sha256(raw).hexdigest()==rec['dbf_record_sha256'],'DBF_RECORD_SHA')
            b.need((fields['A1'],fields['A2'],fields['A4'])==(pnu,a['legal_codes'][0],a['jibun_literal']),'EXACT_PARCEL_BINDING')
            wkb=inputs._verify_record(layer,f,h,ordinal,pnu,'A1');b.need(wkb is not None,'GEOMETRY_MISSING')
            geom=shapely.from_wkb(wkb)
            # No repairs or substitutions; kernel throws on invalid/empty/nonfinite.
            derived=compute(geom);g.checkpoint('verified_POS_and_grid_completed_'+pnu)
            point=dict(pnu=pnu,x=derived['representative_x'],y=derived['representative_y'],grid_id=derived['parcel_representative_grid_id'],CRS='EPSG:5186',grid_version=cfg['grid_version'],representative_method='POINT_ON_SURFACE',geometry_wkb_sha256=hashlib.sha256(wkb).hexdigest(),geometry_derivation='UNCHANGED_VALID_SOURCE',boundary_class=derived['parcel_boundary_class'])
            points.append(dict(point=point,kernel=derived,source=rec,source_snapshot=cfg['snapshot'],runtime=runtime,grid_sha256=cfg['grid_sha256'],historical_location_verified=False))
            a.update(status='UNIQUE_REFERENCE_ASSIGNED',reason='TARGETED_SOURCE_GEOMETRY_VERIFIED_POS',spatial_candidates=[point]);supplied.append(a)
        for dataset,layer,f,h in sources.values():f.close()
        sources.clear();dataset=None;layer=None
        timings['geometry_seconds']=time.monotonic()-st
        b.need(all(b.identity(p)==i for p,i in input_ids.items()),'GEOMETRY_INPUT_CHANGED')
        output(out/'generated_points.jsonl',points);b.write(out/'crs_checks.json',crs)
        c=sqlite3.connect(out/'generated_points.sqlite');c.execute('create table points(pnu TEXT PRIMARY KEY,payload TEXT NOT NULL)');c.executemany('insert into points values(?,?)',[(p['point']['pnu'],b.dump(p)) for p in points]);c.commit();c.close()
        result=continuation(cfg,out,supplied,g);pin(cfg,g)
        result.update(status='TARGET_SUPPLY_SAMPLE_COMPLETE',generated_points=len(points),target_addresses=len(targets),scratch_bytes=scratch,elapsed_seconds=time.monotonic()-t,timings=timings,network=0,geometry_repair=0,coordinate_transform=0,national_execution=0,CSV_raw_reparse=0,full_SQL_count=0,release_changed=0,guard_changed=0,Seoul='PILOT_PARTIAL',Cheongju='PARTIAL_MATCH',completeness='UNPROVEN')
        b.write(work/'worker_resource_receipt.json',g.publication_gate());b.write(out/'result.json',result)
    except BaseException as e:
        b.write(work/'primary_exception.json',dict(error=str(e),type=type(e).__name__,traceback=traceback.format_exc()))
        if not (work/'worker_resource_receipt.json').exists():b.write(work/'worker_resource_receipt.json',g.receipt())
        raise
    finally:g.reader.close()

def run(config,out):
    b.need(not out.exists(),'OUTPUT_EXISTS_NO_REPLACE');out.mkdir(parents=True)
    cfg=js(config);b.need(cfg['mode']=='TARGETED_EXISTING_ASSET_SUPPLY','SCOPE')
    runtime=str(ROOT/cfg['captured_runtime_root']/'apps/Python312/python.exe')
    b.write(out/'invocation.json',dict(started_utc=datetime.now(timezone.utc).isoformat(),config_sha256=b.lane.sha(config),source_sha256=b.lane.sha(Path(__file__)),mode='ISOLATED_TARGETED_SAMPLE_NOT_PRODUCTION'))
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',PROJ_NETWORK='OFF',GDAL_PAM_ENABLED='NO')
    for key in ('PYTHONHOME','PYTHONPATH'):env.pop(key,None)
    sup=b.lane.resource.supervise([runtime,'-B','-X','utf8',str(Path(__file__).resolve()),'worker','--config',str(config),'--out',str(out)],str(ROOT),env,out/'supervised')
    b.need(sup['status']=='COMPLETE','RESOURCE_OR_WORKER_HOLD:'+str(out/'supervised'))
    b.write(out/'completion.json',dict(status='TARGET_SUPPLY_SUPERVISED_PASS',result=js(out/'result.json'),supervisor=sup,artifacts=[dict(path=p.name,sha256=b.lane.sha(p)) for p in out.iterdir() if p.is_file()]))
    print(b.dump(js(out/'completion.json')))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['run','worker']);p.add_argument('--config',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    (run if a.mode=='run' else worker)(a.config.resolve(),a.out.resolve())
