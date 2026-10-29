"""Pinned Busan candidate -> verified source POS -> 5179 grid, resumable per key."""
import os,sys
from pathlib import Path
DLL=None
if Path(sys.executable).parent.name=='Python312':DLL=os.add_dll_directory(str(Path(sys.executable).parents[2]/'bin'))
import argparse,csv,hashlib,json,math,sqlite3,time,traceback
from datetime import datetime,timezone
from binding import PROJECT, ANNUAL
H=Path(os.environ['KHMD_BUSAN_STAGE']).resolve();ROOT=PROJECT;P=H.parent/'csv_regional_demand_v0_1'
sys.path.insert(0,str(ANNUAL/'csv_regional_demand_v0_1'));import demand as d
import candidate_publication as publication
sys.path.insert(0,str(ANNUAL/'csv_spatial_supply_v0_1'));import supply_v0_4 as s
sys.path.insert(0,str(ANNUAL/'csv_spatial_5179_busan_v0_2'))
import grid
b=d.b
def db(p,ro=False):return d.database(p,ro)
def bind(g):
    cfg=b.read(H/'config.json')
    for x in cfg['bindings']:b.need(b.lane.sha(Path(x['path']),g)==x['sha256'],'BINDING_DRIFT:'+x['path'])
    return cfg
def setup(g):
    cfg=bind(g);runtime,engines=s.captured_runtime(b.read(H.parent/'csv_spatial_supply_v0_1/supply_config_v0_4.json'),g)
    engines[0].SetCacheMax(1024*1024)
    return cfg,runtime,engines
def crs_policy(g):
    cfg,runtime,eng=setup(g);_,_,pp,shapely,_=eng
    crs=pp.CRS.from_epsg(5179);area=crs.area_of_use
    policy=dict(grid_version=grid.VERSION,CRS='EPSG:5179',name=crs.name,unit='metre',coordinate_order='x=easting,y=northing',library_axis_info=[dict(name=a.name,direction=a.direction,unit=a.unit_name) for a in crs.axis_info],transform_always_xy=True,origin=[0,0],spacing=[1000,1000],index='i=floor(x/1000);j=floor(y/1000)',cell='[1000*i,1000*(i+1)) x [1000*j,1000*(j+1))',identifier='KHMD_UTMK_1KM_V1:{i}:{j}',definition='Projected-plane 1000m by 1000m square, not equal ground distance or area',alignment='Projection-coordinate alignment only; no claim of SGIS/national standard grid equivalence',area_of_use=dict(name=area.name,west=area.west,south=area.south,east=area.east,north=area.north),operation=crs.coordinate_operation.to_json_dict(),wkt=crs.to_wkt(),projjson=crs.to_json_dict(),local_EPSG_version=pp.database.get_database_metadata('EPSG.VERSION'),PROJ_database_sha256=b.lane.sha(Path(sys.executable).parents[2]/'share/proj/proj.db',g),authority='Explicit user instruction for new version, existing 5186 results retained',source_POS_method='POINT_ON_SURFACE in verified source CRS; transform the point, do not recompute in target CRS',reference_snapshot='2026-09-08',historical_location_verified=False)
    b.need(all(a.unit_name=='metre' for a in crs.axis_info),'UNIT')
    # Broad fixed geodetic sampling, not a national geometry pass or exact maxima.
    rows=[];proj=pp.Proj(crs)
    for lat in [33.0,33.5,34.0,34.5,35.0,35.5,36.0,36.5,37.0,37.5,38.0,38.5]:
        for lon in [124.5,125.0,125.5,126.0,126.5,127.0,127.5,128.0,128.5,129.0,129.5,130.0,130.5,131.0,131.5,132.0]:
            if area.west<=lon<=area.east and area.south<=lat<=area.north:
                f=proj.get_factors(lon,lat);rows.append(dict(label='regular_0.5_degree_screen_including_water',longitude=lon,latitude=lat,meridional_scale=f.meridional_scale,parallel_scale=f.parallel_scale,area_scale=f.areal_scale,ground_metres_per_projected_1000=1000/f.meridional_scale))
        g.checkpoint('national_factor_latitude_completed_'+str(lat))
    for name,lon,lat in [('Seoul',126.978,37.5665),('Busan',129.0756,35.1796),('Cheongju',127.489,36.642),('Jeju',126.531,33.499),('Ulleung',130.9,37.48),('Dokdo',131.87,37.24),('Baengnyeong',124.63,37.97),('Goseong',128.46,38.45),('Mara',126.27,33.12)]:
        f=proj.get_factors(lon,lat);rows.append(dict(label=name+'_illustrative_location_not_parcel',longitude=lon,latitude=lat,meridional_scale=f.meridional_scale,parallel_scale=f.parallel_scale,area_scale=f.areal_scale,ground_metres_per_projected_1000=1000/f.meridional_scale))
    tests=[]
    b.need(grid.index(-5e-324,0)==(-1,0),'SUBNORMAL_BOUNDARY');tests.append('negative_subnormal')
    for xy,expected in [((0,0),(0,0)),((1000,1000),(1,1)),((-0.1,-1000),(-1,-1)),((math.nextafter(1000,-math.inf),999.9),(0,0)),((math.nextafter(1000,math.inf),1000),(1,1))]:
        b.need(grid.index(*xy)==expected,'GRID_BOUNDARY');tests.append('boundary:'+str(xy))
    t=pp.Transformer.from_crs(crs.geodetic_crs,crs,always_xy=True)
    x,y=t.transform(127.5,38,errcheck=True);b.need(abs(x-1000000)<1e-6 and abs(y-2000000)<1e-6,'FALSE_ORIGIN')
    conventional=pp.Transformer.from_crs(crs.geodetic_crs,crs,always_xy=False)
    north,east=conventional.transform(38,127.5,errcheck=True);b.need(abs(north-y)<1e-6 and abs(east-x)<1e-6,'AXIS_ORDER')
    source=pp.CRS.from_epsg(5186);fw=pp.Transformer.from_crs(source,crs,always_xy=True);bw=pp.Transformer.from_crs(crs,source,always_xy=True)
    sx,sy=pp.Transformer.from_crs(source.geodetic_crs,source,always_xy=True).transform(129.0756,35.1796,errcheck=True)
    tx,ty=fw.transform(sx,sy,errcheck=True);xx,yy=bw.transform(tx,ty,errcheck=True)
    b.need(math.hypot(xx-sx,yy-sy)<1e-6 and math.hypot(tx-sx,ty-sy)>100000,'TRANSFORM_NOT_RELABEL')
    from shapely.geometry import Polygon
    geom=Polygon([(sx,sy),(sx+100,sy),(sx+100,sy+100),(sx,sy+100)])
    from shapely.ops import transform
    point=grid.point(geom);out=transform(fw.transform,geom);px,py=fw.transform(point.x,point.y,errcheck=True)
    b.need(out.contains(shapely.Point(px,py)),'TRANSFORMED_POS_INSIDE')
    tests+=['false_origin','native_axis_vs_always_xy','forward_inverse_1micrometre','transform_not_relabel','source_and_target_POS_inside']
    b.write(H/'grid_policy.json',policy);b.table(H/'distortion_samples.csv',rows)
    b.write(H/'CRS_review.json',dict(status='ACCEPTED_NEW_PROJECTED_PLANE_DEFINITION',sample_design='0.5 degree rectangular screen plus 9 named illustrative points; includes sea; not an administrative boundary census or rigorous national extrema',sample_points=len(rows),linear_scale_range=[min(min(r['meridional_scale'],r['parallel_scale']) for r in rows),max(max(r['meridional_scale'],r['parallel_scale']) for r in rows)],area_scale_range=[min(r['area_scale'] for r in rows),max(r['area_scale'] for r in rows)],ground_1000_range=[min(r['ground_metres_per_projected_1000'] for r in rows),max(r['ground_metres_per_projected_1000'] for r in rows)],tests=tests,runtime=runtime,old_5186_acceptance_not_reused=True))
    return dict(status='POLICY_TESTS_PASS',tests=len(tests),samples=len(rows))
def source_open(cfg,eng):
    _,ogr,pp,_,_=eng;m=cfg['members'];p=Path(m['.dbf']['path']);dataset=ogr.Open(str(Path(m['.shp']['path'])),0)
    b.need(dataset is not None,'GEOMETRY_SOURCE_MISSING');layer=dataset.GetLayer(0)
    facts=s.inputs._crs_facts(Path(m['.prj']['path']),layer,pp)
    b.need(facts['effective_authority']==['EPSG','5186'],'ACTUAL_SOURCE_CRS')
    stream=p.open('rb');header=s.inputs._dbf_header(stream)
    b.need(layer.GetFeatureCount()==header['record_count']==705940,'SOURCE_GEOMETRY_ROWS')
    return dataset,layer,stream,header,facts
def derive(row,source,cache,eng,policy):
    aid,n,status,pnu,ordinal,sha,code,lot,eligibility=row
    if status!='UNIQUE_PARCEL_CRS_PENDING':return dict(address_id=aid,status=status,occurrences=n)
    if eligibility!='EXACT_REFERENCE_CANDIDATE':return dict(address_id=aid,status='REFERENCE_INELIGIBLE',reason=eligibility,occurrences=n)
    ds,layer,f,h,_=source;_,_,pp,shapely,_=eng
    f.seek(h['header_length']+(ordinal-1)*h['record_length']);raw=f.read(h['record_length']);values=s.rawfields(raw,h)
    b.need(hashlib.sha256(raw).hexdigest()==sha and (values['A1'],values['A2'],values['A4'])==(pnu,code,lot),'PARCEL_IDENTITY_SHA')
    wkb=s.inputs._verify_record(layer,f,h,ordinal,pnu,'A1')
    base=dict(address_id=aid,occurrences=n,pnu=pnu,source_ordinal=ordinal,source_dbf_record_sha=sha,source_CRS='EPSG:5186',target_CRS='EPSG:5179',reference_snapshot='2026-09-08',historical_location_verified=False)
    try:
        if wkb is None:raise ValueError('GEOMETRY_MISSING')
        geom=shapely.from_wkb(wkb)
        # Validate raw geometry even when a cached POS exists.
        if geom.is_empty or geom.geom_type not in ('Polygon','MultiPolygon') or not geom.is_valid or not math.isfinite(geom.area) or geom.area<=0:raise ValueError('GEOMETRY_INVALID_EMPTY_OR_NONPOLYGON')
        wh=hashlib.sha256(wkb).hexdigest();cached=cache.execute('select payload from points where pnu=?',(pnu,)).fetchone()
        if cached:
            saved=json.loads(cached[0]);pt=saved['point'];b.need(pt['CRS']=='EPSG:5186' and pt['representative_method']=='POINT_ON_SURFACE' and pt['geometry_wkb_sha256']==wh and saved['source']['row_ordinal']==ordinal and saved['source']['dbf_record_sha256']==sha,'CACHED_POS_BINDING')
            point=shapely.Point(pt['x'],pt['y']);method='REUSED_VERIFIED_POS'
        else:point=grid.point(geom);method='GENERATED_SOURCE_POINT_ON_SURFACE'
        if not geom.contains(point):raise ValueError('POS_NOT_STRICTLY_INSIDE_SOURCE')
    except ValueError as e:
        if str(e)=='CACHED_POS_BINDING':raise
        return dict(base,status='GEOMETRY_FAILED',reason=str(e))
    sourcecrs=pp.CRS.from_epsg(5186);target=pp.CRS.from_epsg(5179)
    try:
        geo=pp.Transformer.from_crs(sourcecrs,target.geodetic_crs,always_xy=True);lon,lat=geo.transform(point.x,point.y,errcheck=True);a=target.area_of_use
        if not(a.west<=lon<=a.east and a.south<=lat<=a.north):return dict(base,status='OUTSIDE_TARGET_CRS_AREA',longitude=lon,latitude=lat)
        fw=pp.Transformer.from_crs(sourcecrs,target,always_xy=True);x,y=fw.transform(point.x,point.y,errcheck=True)
        from shapely.ops import transform
        transformed=transform(fw.transform,geom)
        if not transformed.is_valid or not transformed.contains(shapely.Point(x,y)):return dict(base,status='TRANSFORM_FAILED',reason='TARGET_GEOMETRY_OR_POS_INSIDE_CHECK')
        back=pp.Transformer.from_crs(target,sourcecrs,always_xy=True);xx,yy=back.transform(x,y,errcheck=True)
        if math.hypot(xx-point.x,yy-point.y)>1e-5:raise ValueError('ROUNDTRIP_ABOVE_10_MICROMETRES')
        gid=grid.identifier(x,y)
    except (pp.exceptions.ProjError,ValueError) as e:return dict(base,status='TRANSFORM_FAILED',reason=str(e))
    return dict(base,status='ASSIGNED',representative_method=method,source_x=point.x,source_y=point.y,x=x,y=y,longitude=lon,latitude=lat,geometry_wkb_sha256=wh,source_inside=True,target_inside=True,grid_id=gid,grid_version=grid.VERSION)
def commit(c,rows):
    with c:c.executemany('insert into results values(?,?,?,?)',[(r['address_id'],r['status'],r['occurrences'],b.dump(r)) for r in rows])
SQL="""select k.address_id,k.occurrences,k.match_status,c.pnu,c.ordinal,c.dbf_sha,c.raw_A2,c.raw_A4,c.eligibility from key_results k left join candidates c on c.address_id=k.address_id and k.candidate_count=1 order by k.address_id"""
def regression(work,g):
    cfg,runtime,eng=setup(g);source=source_open(cfg,eng);cache=db(cfg['prior_point_db'],True);cand=db(P/'busan_candidates/candidates.sqlite',True);actual=db(work/'spatial.sqlite',True)
    saved=actual.execute('select address_id,payload from results order by address_id').fetchall();b.need(len(saved)==17,'PAUSED_17_KEYS')
    policy=b.read(H/'grid_policy.json');continuous=[]
    for row in cand.execute(SQL+' limit 17'):
        continuous.append(derive(row,source,cache,eng,policy));g.checkpoint('continuous_spatial_regression_completed_'+row[0][:12])
    b.need(saved==[(r['address_id'],b.dump(r)) for r in continuous],'PAUSED_CONTINUOUS_RESULT_DIFFERENCE')
    source[2].close();cache.close();cand.close();actual.close()
    test=H/'restart_regression';test.mkdir();c=db(test/'atomic.sqlite');c.execute('create table results(address_id TEXT PRIMARY KEY,status TEXT,n INTEGER,payload TEXT)');c.commit()
    commit(c,continuous[:8])
    try:commit(c,continuous[8:]+continuous[:1]);raise AssertionError('DUPLICATE_ACCEPTED')
    except sqlite3.IntegrityError:pass
    b.need(c.execute('select count(*) from results').fetchone()[0]==8,'PARTIAL_TRANSACTION_NOT_ROLLED_BACK')
    c.close()
    # Close an uncommitted connection, then resume. Actual process-crash tests
    # are inherited from the demand checkpoint qualification, not spawned here.
    values=[(r['address_id'],r['status'],r['occurrences'],b.dump(r)) for r in continuous[8:]]
    b.write(test/'rows.json',values)
    for mode,expected in [('before',8),('after',17)]:
        c=db(test/'atomic.sqlite');c.executemany('insert into results values(?,?,?,?)',values)
        if mode=='after':c.commit()
        c.close();c=db(test/'atomic.sqlite');b.need(c.execute('select count(*) from results').fetchone()[0]==expected,'CLOSE_CHECKPOINT');c.close()
    c=db(test/'atomic.sqlite',True);b.need(c.execute('select address_id,payload from results order by address_id').fetchall()==saved,'RESUMED_EQ_CONTINUOUS');c.close()
    r=dict(status='RESTART_TESTS_PASS',actual_geometry_keys=17,tests=['paused_vs_continuous_exact_payload','duplicate_batch_rollback','close_before_commit_preserves_prior','close_after_commit_preserves_completed','resumed_equals_continuous'],source_reparse=0,actual_process_crash_tests_reused=str(P/'restart_tests/qualification.json'),worker_child_processes=0)
    b.write(test/'qualification.json',r);return r
def process(work,g,pause,regression=False):
    cfg,runtime,eng=setup(g);policy=b.read(H/'grid_policy.json');b.need(policy['grid_version']==grid.VERSION,'POLICY_VERSION')
    policy_receipt=b.read(H/'policy_attempt/completion.json');b.need(policy_receipt['policy_sha256']==b.lane.sha(H/'grid_policy.json'),'POLICY_BINDING')
    if not pause:b.need(b.read(H/'regression_attempt/completion.json')['result']['status']=='RESTART_TESTS_PASS','RESTART_TESTS_REQUIRED')
    g.reserve_output(128*1024**2);publication.check(P/'busan_candidates')
    source=source_open(cfg,eng);source_ids={m['path']:b.identity(m['path']) for m in cfg['members'].values()}
    candidates=db(P/'busan_candidates/candidates.sqlite',True);cache=db(cfg['prior_point_db'],True)
    c=db(work/'spatial.sqlite');binding=b.digest(dict(config=b.lane.sha(H/'config.json'),policy=b.lane.sha(H/'grid_policy.json')))
    c.executescript('create table if not exists meta(binding TEXT);create table if not exists results(address_id TEXT PRIMARY KEY,status TEXT,n INTEGER,payload TEXT);')
    old=c.execute('select binding from meta').fetchone()
    if old:b.need(old[0]==binding,'RESTART_BINDING')
    else:c.execute('insert into meta values(?)',(binding,));c.commit()
    new=0;reused=0;buffer=[]
    try:
        for row in candidates.execute(SQL):
            if c.execute('select 1 from results where address_id=?',(row[0],)).fetchone():reused+=1;continue
            buffer.append(derive(row,source,cache,eng,policy));new+=1
            if len(buffer)>=16 or (pause and new>=pause):
                commit(c,buffer);buffer=[];g.checkpoint('verified_spatial_keys_committed_'+str(new+reused))
            if pause and new>=pause:
                return dict(status='INTENTIONAL_PAUSE',new_keys=new,reused_keys=reused)
        if buffer:commit(c,buffer);g.checkpoint('final_spatial_keys_committed')
        b.need(c.execute('select count(*),sum(n) from results').fetchone()==(5120,1327806),'ALL_KEY_CONSERVATION')
        b.need(all(b.identity(p)==v for p,v in source_ids.items()),'SOURCE_CHANGED')
        b.write(work/'source_CRS.json',source[4]);c.commit();c.close()
        from completion import geometry_ready
        return geometry_ready(work/'spatial.sqlite',P/'busan_candidates/candidates.sqlite',H/'config.json',H/'grid_policy.json',5120,1327806,'EXTERNAL',g)
    finally:source[2].close();c.close();cache.close();candidates.close()
def worker(mode,work,attempt,pause):
    t=time.monotonic();g=b.lane.resource.ReferenceGuard(ROOT);wd=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY'])
    try:
        g.admit();r=crs_policy(g) if mode=='policy' else regression(work,g) if mode=='regression' else process(work,g,pause)
        r['elapsed_seconds']=time.monotonic()-t
        b.write(wd/'worker_resource_receipt.json',g.publication_gate());b.write(attempt/'result.json',r)
    except BaseException as e:
        b.write(wd/'primary_exception.json',dict(error=str(e),traceback=traceback.format_exc()))
        if not (wd/'worker_resource_receipt.json').exists():b.write(wd/'worker_resource_receipt.json',g.receipt())
        raise
    finally:g.reader.close()
def run(mode,work,attempt,pause):
    import msvcrt
    work.mkdir(parents=True,exist_ok=True)
    with (work/'coordinator.lock').open('a+b') as lock:
        if lock.tell()==0:lock.write(b'1');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        try:
            if (work/'final_manifest.json').exists():
                m=b.read(work/'final_manifest.json');b.need(m['config_sha256']==b.lane.sha(H/'config.json') and m['policy_sha256']==b.lane.sha(H/'grid_policy.json'),'COMPLETED_BINDING_DRIFT')
                for x in m['artifacts']:b.need(b.lane.sha(work/x['path'])==x['sha256'],'COMPLETED_ARTIFACT_DRIFT')
                print('REUSED_COMPLETE_NO_SOURCE_REPROCESSING');return
            b.need(not attempt.exists(),'ATTEMPT_NO_REPLACE');attempt.mkdir(parents=True)
            cfg=b.read(H/'config.json');runtime=ROOT/cfg['captured_runtime_root']/'apps/Python312/python.exe'
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',PROJ_NETWORK='OFF',GDAL_PAM_ENABLED='NO');env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
            command=[str(runtime),'-B','-X','utf8',str(Path(__file__).resolve()),'worker','--stage',mode,'--work',str(work),'--attempt',str(attempt),'--pause',str(pause)]
            sup=b.lane.resource.supervise(command,str(ROOT),env,attempt/'supervised')
            b.need(sup['status']=='COMPLETE' and sup['returncode']==0,'SUPERVISOR_HOLD:'+str(attempt))
            r=b.read(attempt/'result.json');b.write(attempt/'completion.json',dict(supervisor=sup,result=r,policy_sha256=b.lane.sha(H/'grid_policy.json')))
            if r['status']=='BUSAN_5179_COMPLETE':b.write(work/'final_manifest.json',dict(status=r['status'],config_sha256=b.lane.sha(H/'config.json'),policy_sha256=b.lane.sha(H/'grid_policy.json'),completion=str(attempt/'completion.json'),completion_sha256=b.lane.sha(attempt/'completion.json'),artifacts=[dict(path=p.name,sha256=b.lane.sha(p)) for p in work.iterdir() if p.is_file() and p.name!='coordinator.lock']))
            print(b.dump(dict(status=r['status'],elapsed=sup['elapsed_seconds'],result=r.get('status_occurrences'))))
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['run','worker']);p.add_argument('--stage',choices=['policy','spatial','regression'],default='spatial');p.add_argument('--work',type=Path,required=True);p.add_argument('--attempt',type=Path,required=True);p.add_argument('--pause',type=int,default=0);a=p.parse_args()
    (run if a.mode=='run' else worker)(a.stage,a.work.resolve(),a.attempt.resolve(),a.pause)
