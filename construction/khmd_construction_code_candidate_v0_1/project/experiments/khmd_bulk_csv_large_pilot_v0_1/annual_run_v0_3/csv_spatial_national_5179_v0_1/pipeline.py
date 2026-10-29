"""Sequential demand-scoped nationwide spatial continuation, offline and guarded."""
import os,sys
from pathlib import Path
DLL=None
if Path(sys.executable).parent.name=='Python312':DLL=os.add_dll_directory(str(Path(sys.executable).parents[2]/'bin'))
import argparse,csv,hashlib,json,math,re,sqlite3,time,traceback,zipfile
from collections import defaultdict,Counter
from datetime import datetime,timezone
H=Path(__file__).resolve().parent;ROOT=H.parents[3];P=H.parent/'csv_regional_demand_v0_1';V=H.parent/'csv_spatial_5179_busan_v0_2';B=H.parent/'csv_spatial_5179_busan_v0_3'
sys.path.insert(0,str(V));import run as old
b=old.b;s=old.s;d=old.d;grid=old.grid
def db(path,ro=False):return d.database(path,ro)
def table(path,header,rows,g=None):
    with path.open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(header)
        for i,row in enumerate(rows,1):
            w.writerow(row)
            if g and i%1000==0:g.checkpoint('exported_rows_'+str(i))
def config(g=None):
    c=b.read(H/'config.json')
    for x in c['code_bindings']:b.need(b.lane.sha(Path(x['path']),g)==x['sha256'],'CODE_OR_POLICY_DRIFT:'+x['path'])
    return c
def verify_final(path,g=None):
    m=b.read(path)
    for x in m['artifacts']:b.need(b.lane.sha(Path(x['path']),g)==x['sha256'],'COMPLETED_ARTIFACT_DRIFT')
    return m
def object_dir(oid):return H/'objects'/oid
def region_dir(region,cfg):return H/'regions'/cfg['region_ids'][region]
def route(code,prefixes):return prefixes.get(code[:2],[])
def initialize(out,g):
    cfg=config(g)
    for x in cfg['input_bindings']:b.need(b.lane.sha(Path(x['path']),g)==x['sha256'],'INPUT_BINDING_DRIFT')
    verify_final(B/'busan_run/final_manifest.json',g)
    source=db(P/'national_demand/demand.sqlite',True);c=db(H/'routing.sqlite')
    c.executescript('create table keys(id primary key,province,region_literal,lot,legal_codes,status,n);create table routes(id,object_id,primary key(id,object_id));create index region_keys on keys(province);create index object_routes on routes(object_id);')
    counts=Counter();prefixmap=cfg['prefix_objects'];unresolved=Counter();cross=0
    for row in source.execute("select * from keys where province!='부산광역시' order by id"):
        aid,province,region,lot,codes,status,n=row;c.execute('insert into keys values(?,?,?,?,?,?,?)',row);counts[province]+=n
        if status=='EXACT_KEY_ELIGIBLE':
            codes=json.loads(codes);b.need(len(codes)==1,'LEGAL_CODE_CARDINALITY');objects=route(codes[0],prefixmap)
            if len(objects)!=1:unresolved[province]+=n
            else:
                c.execute('insert into routes values(?,?)',(aid,objects[0]));cross+=int(cfg['objects'][objects[0]]['region_name']!=province)
        if sum(counts.values())%10000<100:g.checkpoint('inherited_address_keys_routed_'+aid[:8])
    c.commit();b.need(sum(counts.values())==19588294 and len(counts)==15,'REMAINING_SCOPE')
    b.need(c.execute('select count(*) from keys').fetchone()[0]==42556,'KEY_SCOPE')
    c.close();source.close()
    # Small changed-link tests; no source regeneration.
    b.need(route('2712345678',{'27':['D'],'47':['K']})==['D'],'QUERY_REGION_MUST_NOT_OVERRIDE_REFERENCE_CODE')
    b.need(route('9912345678',{})==[],'UNKNOWN_ROUTE_NOT_GUESSED')
    test=db(out/'regression.sqlite');test.executescript('create table t(region,k,n,primary key(region,k));')
    test.executemany('insert into t values(?,?,?)',[('A','G:Q:RENT',2),('B','G:Q:RENT',3)]);test.commit()
    b.need(test.execute('select k,sum(n) from t group by k').fetchall()==[('G:Q:RENT',5)],'CROSS_REGION_MERGE')
    try:
        with test:test.execute('insert into t values(?,?,?)',('C','X',4));test.execute('insert into t values(?,?,?)',('A','G:Q:RENT',2))
    except sqlite3.IntegrityError:pass
    b.need(test.execute('select sum(n) from t').fetchone()[0]==5,'TRANSACTION_DUPLICATE_ROLLBACK');test.close()
    return dict(status='INITIALIZED',input_occurrences=sum(counts.values()),address_keys=42556,regions=dict(counts),routing_uncertain_occurrences=dict(unresolved),query_reference_region_different_keys=cross,tests=['query_not_reference','unknown_route_explicit','cross_region_grid_merge','duplicate_transaction_rollback','prior_Busan_axis_POS_restart_tests_reused'],address_keys_regenerated=0)
def ensure_members(obj,work,g):
    existing=work/'members.json'
    if existing.exists():return b.read(existing)['sets']
    sets=[]
    if obj['existing_sets']:
        for rec in obj['existing_sets']:
            sets.append(rec)
    else:
        raw=ROOT/obj['raw_path'];before=b.identity(raw);b.need(b.lane.sha(raw,g)==obj['sha256'],'RAW_OBJECT_SHA')
        with zipfile.ZipFile(raw) as z:
            needed=[i for i in z.infolist() if Path(i.filename).suffix.lower() in ('.shp','.dbf','.shx','.prj','.cpg')]
            b.need({i.filename for i in needed}==set(obj['members']),'ARCHIVE_MEMBER_DRIFT');g.reserve_output(sum(i.file_size for i in needed)+64*1024**2)
            folder=work/'extracted';folder.mkdir(exist_ok=True);by_stem={}
            for info in needed:
                name=Path(info.filename).name;b.need(name==info.filename and '..' not in name,'MEMBER_ESCAPE');p=folder/name
                recpath=folder/(name+'.receipt.json')
                if recpath.exists():
                    m=b.read(recpath);b.need(b.lane.sha(p,g)==m['sha256'],'EXTRACTED_MEMBER_DRIFT')
                else:
                    b.need(not p.exists(),'UNCOMMITTED_MEMBER_REVIEW_REQUIRED');sha=hashlib.sha256();n=0
                    with z.open(info) as a,p.open('xb') as dst:
                        while True:
                            chunk=a.read(256*1024)
                            if not chunk:break
                            dst.write(chunk);sha.update(chunk);n+=len(chunk);g.checkpoint('extracted_member_bytes_'+name+'_'+str(n))
                    b.need(n==info.file_size,'EXTRACT_SIZE');m=dict(path=str(p),sha256=sha.hexdigest(),bytes=n);b.write(recpath,m)
                by_stem.setdefault(p.stem,{})[p.suffix]=m
            for stem,members in sorted(by_stem.items()):
                b.need(set(members)=={'.dbf','.shp','.shx','.prj','.cpg'},'MEMBER_SET_INCOMPLETE');sets.append(dict(set_id=obj['file_no']+':'+stem,members=members,source_archive_sha256=obj['sha256'],region=obj['region_name']))
        b.need(b.identity(raw)==before,'RAW_CHANGED')
    b.write(existing,dict(sets=sets,source_archive_sha256=obj['sha256'],source_snapshot='2026-09-08'));return sets
def candidates(oid,out,g):
    cfg=config(g);obj=cfg['objects'][oid];work=object_dir(oid);work.mkdir(parents=True,exist_ok=True);sets=ensure_members(obj,work,g)
    rt=db(H/'routing.sqlite',True);wanted=defaultdict(list)
    for aid,codes,lot in rt.execute('select k.id,k.legal_codes,k.lot from keys k join routes r on k.id=r.id where r.object_id=?',(oid,)):wanted[(json.loads(codes)[0],lot)].append(aid)
    rt.close();c=db(work/'candidates.sqlite');c.executescript('create table if not exists candidates(address_id,set_id,pnu,ordinal,dbf_sha,code,lot,eligibility,primary key(address_id,set_id,ordinal));create index if not exists candidate_address on candidates(address_id);create table if not exists done(set_id primary key,rows);')
    exceptions={x['PNU']:x for x in csv.DictReader((ROOT/cfg['exceptions']).open(encoding='utf-8-sig'))}
    def store(sid,ordinal,raw,h):
        values=s.rawfields(raw,h);key=(values['A2'],values['A4']);ids=wanted.get(key,())
        if not ids:return
        pnu=values['A1'];b.need(len(pnu)==19 and pnu.isascii() and pnu.isdigit() and pnu[:10]==key[0],'PNU_IDENTITY');eligibility='EXACT_REFERENCE_CANDIDATE'
        if pnu in exceptions:eligibility='QUARANTINED_REFERENCE' if exceptions[pnu]['quarantine_flag']=='True' else 'HISTORICAL_REFERENCE_CODE_FLAG'
        for aid in ids:c.execute('insert into candidates values(?,?,?,?,?,?,?,?)',(aid,sid,pnu,ordinal,hashlib.sha256(raw).hexdigest(),key[0],key[1],eligibility))
    scanned=0;indexed=0
    ix=db(ROOT/cfg['index_path'],True) if obj['existing_sets'] else None
    for rec in sets:
        sid=rec['set_id']
        if c.execute('select 1 from done where set_id=?',(sid,)).fetchone():continue
        path=Path(rec['members']['.dbf']['path']);b.need(b.lane.sha(path,g)==rec['members']['.dbf']['sha256'],'DBF_MEMBER_SHA')
        with path.open('rb') as f:
            h=s.inputs._dbf_header(f)
            with c:
                if ix:
                    for (code,lot) in wanted:
                        for index_sid,ordinal,pnu in ix.execute('select set_id,row_ordinal,pnu from parcels indexed by parcels_K2V2 where a2 COLLATE BINARY=? and jibun COLLATE BINARY=? order by pnu',(code,lot)):
                            if index_sid!=sid:continue
                            f.seek(h['header_length']+(ordinal-1)*h['record_length']);raw=f.read(h['record_length']);values=s.rawfields(raw,h);b.need((values['A1'],values['A2'],values['A4'])==(pnu,code,lot),'EXISTING_INDEX_RAW_BINDING');store(sid,ordinal,raw,h);indexed+=1
                        g.checkpoint('indexed_lookup_completed_'+code+'_'+lot)
                else:
                    f.seek(h['header_length']);fields={x['name']:x for x in h['fields']}
                    for ordinal in range(1,h['record_count']+1):
                        raw=f.read(h['record_length']);b.need(len(raw)==h['record_length'] and raw[:1]==b' ','DBF_SHORT_OR_DELETED')
                        code=raw[fields['A2']['offset']:fields['A2']['offset']+10].decode('ascii');lot=raw[fields['A4']['offset']:fields['A4']['offset']+fields['A4']['width']].decode('euc_kr').rstrip(' ')
                        if (code,lot) in wanted:store(sid,ordinal,raw,h)
                        scanned+=1
                        if ordinal%2048==0:g.checkpoint('DBF_records_completed_'+sid+'_'+str(ordinal))
                    b.need(f.read() in (b'',b'\x1a'),'DBF_TRAILER')
                c.execute('insert into done values(?,?)',(sid,h['record_count']))
        g.checkpoint('reference_member_committed_'+sid)
    if ix:ix.close()
    total=c.execute('select sum(rows) from done').fetchone()[0];b.need(total==int(obj['total_geometry_rows']),'REGION_MEMBER_COVERAGE')
    matched=c.execute('select count(*) from candidates').fetchone()[0];c.close()
    return dict(status='CANDIDATES_COMPLETE',object_id=oid,source_region=obj['region_name'],members=len(sets),covered_reference_rows=total,rows_scanned_this_attempt=scanned,reused_index_hits=indexed,wanted_literal_keys=len(wanted),candidate_rows=matched,query_region_not_used_as_reference_code=True)
class Saved:
    def __init__(self,cfg,g):
        self.config=b.read(ROOT/cfg['bridge_config']);self.g=g
        self.partition_bindings={x['path']:x['sha256'] for x in b.read(ROOT/self.config['pos_manifest'])['partitions']};self.partition_rows={};self.verified_partitions={}
        self.ix=db(ROOT/self.config['saved_pos_index'],True)
        self.extra=db(H.parent/'csv_spatial_supply_v0_1/supply_run_v0_4/generated_points.sqlite',True)
    def get(self,pnu,sid,ordinal):
        extra=self.extra.execute('select payload from points where pnu=?',(pnu,)).fetchone()
        if extra:
            x=json.loads(extra[0]);q=x['point'];b.need(x['source']['set_id']==sid and x['source']['row_ordinal']==ordinal and q['CRS']=='EPSG:5186' and q['representative_method']=='POINT_ON_SURFACE','EXTRA_POS_LOCATOR')
            return q
        row=self.ix.execute('select payload from crosswalk where pnu=?',(pnu,)).fetchone()
        if not row:return None
        x=json.loads(row[0]);b.need(x['matched_physical_set_id']==sid and int(x['matched_source_row_ordinal'])==ordinal,'SAVED_POS_LOCATOR')
        return b.Linker.saved(self,x)
    def close(self):self.ix.close();self.extra.close()
def geometry(rec,source,cache,eng,transforms):
    aid,n,sid,pnu,ordinal,sha,code,lot,eligibility=rec
    base=dict(address_id=aid,occurrences=n,pnu=pnu,set_id=sid,ordinal=ordinal,dbf_record_sha256=sha,reference_snapshot='2026-09-08',source_CRS='EPSG:5186',target_CRS='EPSG:5179',historical_location_verified=False)
    if eligibility=='QUARANTINED_REFERENCE':return dict(base,status='QUARANTINED_REFERENCE')
    dataset,layer,stream,h=source;_,_,pp,shapely,_=eng
    stream.seek(h['header_length']+(ordinal-1)*h['record_length']);raw=stream.read(h['record_length']);values=s.rawfields(raw,h)
    b.need(hashlib.sha256(raw).hexdigest()==sha and (values['A1'],values['A2'],values['A4'])==(pnu,code,lot),'PARCEL_BINDING')
    wkb=s.inputs._verify_record(layer,stream,h,ordinal,pnu,'A1')
    if wkb is None:return dict(base,status='GEOMETRY_FAILED',reason='GEOMETRY_MISSING')
    geom=shapely.from_wkb(wkb);wh=hashlib.sha256(wkb).hexdigest();base['geometry_wkb_sha256']=wh
    if geom.is_empty or geom.geom_type not in ('Polygon','MultiPolygon') or not geom.is_valid or not math.isfinite(geom.area) or geom.area<=0:
        from shapely.validation import explain_validity
        return dict(base,status='GEOMETRY_FAILED',reason=explain_validity(geom))
    saved=cache.get(pnu,sid,ordinal)
    if saved:
        b.need(saved['geometry_wkb_sha256']==wh,'SAVED_POS_GEOMETRY_SHA');point=shapely.Point(saved['x'],saved['y']);method='REUSED_VERIFIED_POS'
    else:
        try:point=grid.point(geom);method='GENERATED_SOURCE_POINT_ON_SURFACE'
        except ValueError as e:return dict(base,status='GEOMETRY_FAILED',reason=str(e))
    b.need(geom.contains(point),'SOURCE_POS_INSIDE')
    fw,bw,geo,area=transforms
    try:
        lon,lat=geo.transform(point.x,point.y,errcheck=True)
        if not(area.west<=lon<=area.east and area.south<=lat<=area.north):return dict(base,status='CRS_OUTSIDE_AREA',longitude=lon,latitude=lat)
        x,y=fw.transform(point.x,point.y,errcheck=True)
        from shapely.ops import transform
        tg=transform(fw.transform,geom)
        if not tg.is_valid or not tg.contains(shapely.Point(x,y)):return dict(base,status='TRANSFORM_FAILED',reason='TRANSFORMED_GEOMETRY_OR_POS_INSIDE')
        xx,yy=bw.transform(x,y,errcheck=True)
        if math.hypot(xx-point.x,yy-point.y)>1e-5:return dict(base,status='TRANSFORM_FAILED',reason='ROUNDTRIP_ABOVE_10_MICROMETRES')
        gid=grid.identifier(x,y)
    except (pp.exceptions.ProjError,ValueError) as e:return dict(base,status='TRANSFORM_FAILED',reason=str(e))
    return dict(base,status='ASSIGNED',grid_id=gid,grid_version=grid.VERSION,x=x,y=y,source_x=point.x,source_y=point.y,longitude=lon,latitude=lat,source_inside=True,target_inside=True,representative_method=method,reference_code_semantics=eligibility)
def regional(region,out,g):
    cfg=config(g);work=region_dir(region,cfg);work.mkdir(parents=True,exist_ok=True);g.reserve_output(128*1024**2)
    c=db(work/'regional.sqlite');c.executescript('create table if not exists meta(binding);create table if not exists results(id primary key,status,n,payload);create table if not exists candidate_links(id,set_id,pnu,ordinal,sha,code,lot,eligibility,primary key(id,set_id,ordinal));create table if not exists counts(grid_id,quarter,family,status,n,primary key(grid_id,quarter,family,status));create table if not exists done(sha primary key);')
    binding=b.lane.sha(H/'config.json');oldbind=c.execute('select binding from meta').fetchone()
    if oldbind:b.need(oldbind[0]==binding,'REGION_RESTART_BINDING')
    else:c.execute('insert into meta values(?)',(binding,));c.commit()
    routing=db(H/'routing.sqlite',True);keys=routing.execute('select * from keys where province=? order by id',(region,)).fetchall();expected=sum(x[6] for x in keys);objects={x[0] for x in routing.execute('select distinct r.object_id from routes r join keys k on k.id=r.id where k.province=?',(region,))}
    sets={};sources={}
    for oid in objects:
        verify_final(object_dir(oid)/'final_manifest.json',g)
        members=b.read(object_dir(oid)/'members.json')['sets'];sets.update({x['set_id']:x for x in members});sources[oid]=db(object_dir(oid)/'candidates.sqlite',True)
    with c:
        for aid,province,region_literal,lot,codes,key_status,n in keys:
            if c.execute('select 1 from results where id=?',(aid,)).fetchone():continue
            routeids=[x[0] for x in routing.execute('select object_id from routes where id=?',(aid,))];matches=[]
            for oid in routeids:matches.extend(sources[oid].execute('select * from candidates where address_id=?',(aid,)).fetchall())
            for match in matches:c.execute('insert or ignore into candidate_links values(?,?,?,?,?,?,?,?)',match)
            if key_status!='EXACT_KEY_ELIGIBLE':status='AMBIGUOUS_LEGAL_NAME' if key_status=='AMBIGUOUS_LEGAL_NAME' else 'UNLINKED_NAME_OR_JIBUN'
            elif len(routeids)!=1:status='REFERENCE_ROUTING_UNRESOLVED'
            elif not matches:status='UNLINKED_PARCEL'
            elif len(matches)>1:status='AMBIGUOUS_PARCEL'
            else:continue
            payload=dict(address_id=aid,status=status,occurrences=n,candidate_count=len(matches),source_name=region_literal,lot_literal=lot,query_province=province,reference_objects=routeids,key_status=key_status)
            c.execute('insert into results values(?,?,?,?)',(aid,status,n,b.dump(payload)))
    for x in sources.values():x.close()
    routing.close();weights={x[0]:x[6] for x in keys};del keys
    runtime,eng=s.captured_runtime(b.read(H.parent/'csv_spatial_supply_v0_1/supply_config_v0_4.json'),g);gd,ogr,pp,shapely,_=eng;gd.SetCacheMax(1024*1024)
    target=pp.CRS.from_epsg(5179);transforms=(pp.Transformer.from_crs(5186,5179,always_xy=True),pp.Transformer.from_crs(5179,5186,always_xy=True),pp.Transformer.from_crs(5186,target.geodetic_crs,always_xy=True),target.area_of_use)
    cache=Saved(cfg,g);opened=None;current_sid=None;source_identities={};facts=[];new=0
    # Only unique unmatched keys, ordered by physical member to avoid reopen loops.
    query='select l.* from candidate_links l left join results r on r.id=l.id where r.id is null order by l.set_id,l.ordinal,l.id'
    for aid,sid,pnu,ordinal,sha,code,lot,elig in c.execute(query):
        if sid!=current_sid:
            if opened:opened[2].close();opened=None;dataset=None;layer=None
            rec=sets[sid]
            for ext,m in rec['members'].items():
                p=Path(m['path']);b.need(b.lane.sha(p,g)==m['sha256'],'GEOMETRY_SOURCE_MEMBER_SHA');source_identities[str(p)]=b.identity(p)
            path=Path(rec['members']['.dbf']['path']);dataset=ogr.Open(str(path.with_suffix('.shp')),0);b.need(dataset is not None,'ASSET_GEOMETRY_MISSING');layer=dataset.GetLayer(0)
            fact=s.inputs._crs_facts(path.with_suffix('.prj'),layer,pp);b.need(fact['effective_authority']==['EPSG','5186'],'SOURCE_CRS_UNCONFIRMED');facts.append(dict(set_id=sid,**fact))
            stream=path.open('rb');header=s.inputs._dbf_header(stream);b.need(layer.GetFeatureCount()==header['record_count'],'SHP_DBF_ROW_ALIGNMENT');opened=(dataset,layer,stream,header);current_sid=sid
        result=geometry((aid,weights[aid],sid,pnu,ordinal,sha,code,lot,elig),opened,cache,eng,transforms)
        with c:c.execute('insert into results values(?,?,?,?)',(aid,result['status'],result['occurrences'],b.dump(result)))
        new+=1
        if new%16==0:g.checkpoint('regional_geometry_keys_committed_'+str(new))
    if opened:opened[2].close();opened=None;dataset=None;layer=None
    cache.close();b.need(all(b.identity(p)==v for p,v in source_identities.items()),'GEOMETRY_INPUT_CHANGED');g.checkpoint('regional_geometry_complete')
    b.need(c.execute('select count(*),sum(n) from results').fetchone()==(len(weights),expected),'KEY_CONSERVATION')
    src=db(P/'national_demand/demand.sqlite',True);files=src.execute('select sha,family,input_rows,complete from files where province=? order by sha',(region,)).fetchall();b.need(len(files)==30 and sum(x[2] for x in files)==expected and all(x[3] for x in files),'REGION_FILE_SCOPE')
    for sha,family,n,_ in files:
        if c.execute('select 1 from done where sha=?',(sha,)).fetchone():continue
        total=0
        with c:
            for aid,quarter,row_status,weight in src.execute('select key_id,quarter,row_status,n from weights where file_sha=?',(sha,)):
                status,payload=c.execute('select status,payload from results where id=?',(aid,)).fetchone();gid=''
                if status=='ASSIGNED':
                    if quarter=='UNASSIGNABLE_PERIOD' or row_status!='PARSED':status='OBSERVATION_NOT_AGGREGATABLE'
                    else:gid=json.loads(payload)['grid_id']
                c.execute('insert into counts values(?,?,?,?,?) on conflict(grid_id,quarter,family,status) do update set n=n+excluded.n',(gid,quarter,family,status,weight));total+=weight
            b.need(total==n,'FILE_WEIGHT_CONSERVATION');c.execute('insert into done values(?)',(sha,))
        g.checkpoint('regional_quarter_file_committed_'+sha[:8])
    src.close();status=dict(c.execute('select status,sum(n) from counts group by status'));b.need(sum(status.values())==expected,'REGION_TOTAL_CONSERVATION')
    table(out/'grid_quarter_counts.csv',['grid_id','quarter','family','observation_occurrences'],c.execute("select grid_id,quarter,family,n from counts where status='ASSIGNED' order by 1,2,3"),g)
    table(out/'quarter_status_counts.csv',['quarter','family','status','observation_occurrences'],c.execute('select quarter,family,status,sum(n) from counts group by 1,2,3 order by 1,2,3'),g)
    table(out/'address_results.csv',['address_id','status','occurrences','payload'],c.execute('select * from results order by 1'),g)
    b.write(out/'source_CRS.json',facts)
    result=dict(status='REGION_COMPLETE',region=region,cells=30,input_occurrences=expected,address_keys=len(weights),status_occurrences=status,assigned=status.get('ASSIGNED',0),unassigned=expected-status.get('ASSIGNED',0),grid_groups=c.execute("select count(*) from counts where status='ASSIGNED'").fetchone()[0],key_status=dict(c.execute('select status,count(*) from results group by status')),point_methods=dict(c.execute("select json_extract(payload,'$.representative_method'),count(*) from results where status='ASSIGNED' group by 1")),new_geometry_keys=new,reused_POS_partitions=cache.verified_partitions,reference_objects=sorted(objects),query_region_is_not_historical_boundary=True,reference_snapshot='2026-09-08',historical_location_verified=False)
    c.close();return result
def merge(out,g):
    cfg=config(g);c=db(out/'national.sqlite');c.executescript('create table grid(grid_id,quarter,family,n,primary key(grid_id,quarter,family));create table sources(region primary key,input,assigned,unassigned,manifest_sha);create table statuses(region,status,n,primary key(region,status));')
    allregions=[]
    bus=verify_final(B/'busan_run/final_manifest.json',g);allregions.append(('부산광역시',bus['result'],B/'full_attempt',B/'busan_run/final_manifest.json'))
    for region in cfg['regions']:
        m=verify_final(region_dir(region,cfg)/'final_manifest.json',g);allregions.append((region,m['result'],Path(m['out']),region_dir(region,cfg)/'final_manifest.json'))
    per_region_grid_groups=0
    for region,result,folder,manifest in allregions:
        with c:
            total=0
            with (folder/'grid_quarter_counts.csv').open(encoding='utf-8-sig',newline='') as f:
                for row in csv.DictReader(f):
                    gid=row['grid_id'];b.need(gid.startswith(grid.VERSION+':'),'MIXED_GRID_VERSION');n=int(row['observation_occurrences']);total+=n;per_region_grid_groups+=1
                    c.execute('insert into grid values(?,?,?,?) on conflict(grid_id,quarter,family) do update set n=n+excluded.n',(gid,row['quarter'],row['family'],n))
            b.need(total==result['assigned'],'REGION_EXPORTED_GRID_SUM');c.execute('insert into sources values(?,?,?,?,?)',(region,result.get('input_occurrences'),total,result['unassigned'],b.lane.sha(manifest)))
            for status,n in result['status_occurrences'].items():c.execute('insert into statuses values(?,?,?)',(region,status,n))
        g.checkpoint('national_region_merge_committed_'+region)
    total,assigned,unassigned=c.execute('select sum(input),sum(assigned),sum(unassigned) from sources').fetchone();b.need(total==20916100 and assigned+unassigned==total,'NATIONAL_CONSERVATION');b.need(c.execute('select sum(n) from grid').fetchone()[0]==assigned,'NATIONAL_GRID_SUM')
    table(out/'national_grid_quarter_counts.csv',['grid_id','quarter','transaction_family','observation_occurrences'],c.execute('select * from grid order by 1,2,3'),g)
    table(out/'query_region_status_counts.csv',['query_region','status','observation_occurrences'],c.execute('select * from statuses order by 1,2'),g)
    table(out/'query_region_totals.csv',['query_region','input_occurrences','assigned','unassigned','manifest_sha256'],c.execute('select * from sources order by 1'),g)
    result=dict(status='NATIONAL_SPATIAL_COMPLETE',regions=16,cells=480,input_occurrences=total,assigned=assigned,unassigned=unassigned,status_occurrences=dict(c.execute('select status,sum(n) from statuses group by status')),grid_groups=c.execute('select count(*) from grid').fetchone()[0],regional_grid_groups=per_region_grid_groups,merged_cross_region_groups=per_region_grid_groups-c.execute('select count(*) from grid').fetchone()[0],same_value_occurrences_not_deduplicated=True,grid_version=grid.VERSION)
    c.close();return result
def worker(stage,key,out):
    g=b.lane.resource.ReferenceGuard(ROOT);wd=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY']);start=time.monotonic()
    try:
        g.admit();result=initialize(out,g) if stage=='initialize' else candidates(key,out,g) if stage=='candidates' else regional(key,out,g) if stage=='region' else merge(out,g)
        result['elapsed_seconds']=time.monotonic()-start;b.write(wd/'worker_resource_receipt.json',g.publication_gate());b.write(out/'result.json',result)
    except BaseException as e:
        b.write(wd/'primary_exception.json',dict(error=str(e),type=type(e).__name__,traceback=traceback.format_exc()))
        if not (wd/'worker_resource_receipt.json').exists():b.write(wd/'worker_resource_receipt.json',g.receipt())
        raise
    finally:g.reader.close()
def execute(stage,key,work,cfg):
    final=work/'final_manifest.json'
    if final.exists():return verify_final(final)['result']
    work.mkdir(parents=True,exist_ok=True);out=work/('attempt_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ'));out.mkdir()
    runtime=ROOT/cfg['captured_runtime_root']/'apps/Python312/python.exe' if stage=='region' else Path(sys.executable)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',PROJ_NETWORK='OFF',GDAL_PAM_ENABLED='NO');env.pop('PYTHONHOME',None);env.pop('PYTHONPATH',None)
    sup=b.lane.resource.supervise([str(runtime),'-B','-X','utf8',str(Path(__file__).resolve()),'worker','--stage',stage,'--key',key,'--out',str(out)],str(ROOT),env,out/'supervised')
    if sup['status']!='COMPLETE' or sup['returncode']!=0:
        b.write(out/'HOLD.json',dict(stage=stage,key=key,supervisor=sup));raise RuntimeError('STOPPED_ON_HOLD:'+str(out))
    result=b.read(out/'result.json');b.write(out/'completion.json',dict(supervisor=sup,result=result))
    paths=[out/'completion.json',out/'result.json']
    if stage=='initialize':paths+=[H/'routing.sqlite']
    elif stage=='candidates':paths+=[work/'members.json',work/'candidates.sqlite']
    elif stage=='region':paths+=[work/'regional.sqlite',out/'grid_quarter_counts.csv',out/'quarter_status_counts.csv',out/'address_results.csv',out/'source_CRS.json']
    else:paths+=[out/'national.sqlite',out/'national_grid_quarter_counts.csv',out/'query_region_status_counts.csv',out/'query_region_totals.csv']
    b.write(final,dict(status=result['status'],config_sha256=b.lane.sha(H/'config.json'),out=str(out),result=result,artifacts=[dict(path=str(p),sha256=b.lane.sha(p)) for p in paths]))
    print(b.dump(dict(stage=stage,key=key,status=result['status'],input=result.get('input_occurrences'),assigned=result.get('assigned'),states=result.get('status_occurrences'),seconds=sup['elapsed_seconds'],current=sup['observed_max_enforcement_metric'],peak=sup['diagnostic_peak_value'])),flush=True)
    return result
def run_all():
    import msvcrt
    cfg=config()
    with (H/'coordinator.lock').open('a+b') as lock:
        if lock.tell()==0:lock.write(b'1');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        try:
            execute('initialize','',H/'initialization',cfg)
            rt=db(H/'routing.sqlite',True)
            for region in cfg['regions']:
                for oid, in rt.execute('select distinct r.object_id from routes r join keys k on k.id=r.id where k.province=? order by r.object_id',(region,)):
                    execute('candidates',oid,object_dir(oid),cfg)
                execute('region',region,region_dir(region,cfg),cfg)
            rt.close();execute('merge','',H/'national',cfg)
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['run','worker']);p.add_argument('--stage');p.add_argument('--key',default='');p.add_argument('--out',type=Path);a=p.parse_args()
    if a.mode=='run':run_all()
    else:worker(a.stage,a.key,a.out.resolve())
