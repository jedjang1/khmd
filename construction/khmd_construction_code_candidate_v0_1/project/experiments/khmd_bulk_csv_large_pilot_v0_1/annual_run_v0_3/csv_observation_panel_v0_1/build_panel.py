"""Read-only mountain review and sparse panel publication from completed aggregates.
No observation reaggregation, candidate reassignment or raw CSV reparsing.
"""
import os, sys, json, csv, re, sqlite3, hashlib, time, traceback
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone
H=Path(__file__).resolve().parent; BASE=H.parent; ROOT=H.parents[3]
O=BASE/'csv_spatial_national_5179_v0_1'; N=BASE/'csv_spatial_name_normalization_v0_1'
Q=BASE/'csv_spatial_target_quality_v0_2'; D=BASE/'csv_regional_demand_v0_1'
sys.path.insert(0,str(O)); import pipeline as p
b=p.b; db=p.db
VERSION='KHMD_UTMK_1KM_V1'
def put(path,x): b.write(path,x)
def sha(path,g=None): return b.lane.sha(Path(path),g)
def notation(value):
    if value is None: return 'FIELD_ABSENT'
    if value=='': return 'EMPTY'
    if re.fullmatch(r'산[0-9]+(?:-[0-9]+)?',value): return 'EXPLICIT_SAN'
    if re.fullmatch(r'[0-9]+(?:-[0-9]+)?',value): return 'NUMERIC_SAN_NOT_DISPLAYED'
    return 'SPECIAL_OR_WHITESPACE_PRESERVED'
def narrow(candidates,raw,source_rule=None):
    # A numeric display is NOT a proof of general land. An externally verified,
    # source-specific display rule would be required; this release supplies none.
    if source_rule is not None: raise ValueError('UNAPPROVED_SOURCE_RULE')
    return list(candidates)
def mountain(out,g):
    c=db(Q/'quality.sqlite',True); d=db(D/'national_demand/demand.sqlite',True)
    rows=[]; evidence=[]; total=0
    selected=c.execute("select r.id,r.n,r.payload from results r join selected s using(id) where s.category='AMBIGUOUS_PARCEL' order by r.n desc,r.id").fetchall()
    assert len(selected)==20
    for aid,n,payload in selected:
        x=json.loads(payload); raw_name,lot=d.execute('select region_literal,lot from keys where id=?',(aid,)).fetchone()
        file_sha=c.execute('select file_sha from weights where key_id=? order by n desc,file_sha limit 1',(aid,)).fetchone()[0]
        store=d.execute('select store from files where sha=?',(file_sha,)).fetchone()[0]; cc=db(store,True)
        meta=json.loads(cc.execute('select metadata from files where sha=?',(file_sha,)).fetchone()[0]); idx=meta['columns'].index('번지')
        # Stored normalized evidence only, stop at the first source observation.
        cc.set_progress_handler(lambda:(g.checkpoint('bounded_sample_lookup_'+aid[:8]) or 0),100000)
        obs=cc.execute("select obs_id,ordinal,byte_start,byte_end,raw_values,states,derived from observations where file_sha=? and json_extract(derived,'$.csv_region_literal')=? and json_extract(raw_values,?)=? limit 1",(file_sha,raw_name,'$['+str(idx)+']',lot)).fetchone()
        assert obs is not None; vals=json.loads(obs[4]); states=json.loads(obs[5]); cc.close()
        assert vals[idx]==lot
        paths=[Path(meta[k]) for k in ('path','snapshot_path','original_path') if meta.get(k)]
        path=next((z for z in paths if z.is_file()),None)
        assert path is not None, ('ORIGINAL_PATH_MISSING',list(meta))
        with path.open('rb') as f: f.seek(obs[2]); raw=f.read(obs[3]-obs[2])
        actual=list(csv.reader(raw.decode(meta['encoding'],errors='strict').splitlines()))
        assert len(actual)==1 and actual[0]==vals,'SOURCE_BYTE_RANGE_MISMATCH'
        candidates=c.execute('select pnu,set_id,ordinal,sha,code,lot from candidates where id=? order by pnu',(aid,)).fetchall()
        assert len(candidates)==2 and len({z[0] for z in candidates})==2
        kept=narrow(candidates,vals[idx]); assert kept==candidates
        rec=dict(key_id=aid,occurrences=n,source_file_sha256=file_sha,source_path=str(path),store=store,obs_id=obs[0],ordinal=obs[1],byte_start=obs[2],byte_end=obs[3],record_byte_sha256=hashlib.sha256(raw).hexdigest(),raw_address=vals[meta['columns'].index('시군구')],raw_lot=vals[idx],stored_lot=lot,raw_observability=states[idx],notation=notation(vals[idx]),source_conditions=meta['conditions'],acquisition_time_status=meta['acquisition_time_status'],candidates=[dict(pnu=z[0],pnu_digit11=z[0][10],set_id=z[1],ordinal=z[2],dbf_sha=z[3],legal_code=z[4],reference_A4=z[5]) for z in candidates],decision='RETAIN_AMBIGUOUS_NO_SOURCE_DISPLAY_RULE',source_bytes_equal_stored_values=True)
        evidence.append(rec); total+=n
        rows.append([aid,n,file_sha,obs[0],rec['raw_address'],lot,states[idx],rec['notation'],'|'.join(z[0] for z in candidates),'|'.join(z[0][10] for z in candidates),rec['decision']]);g.checkpoint('raw_sample_completed_'+aid[:8])
    assert total==69625
    # No national demand regeneration: classify the already frozen 47,676 keys.
    inventory=defaultdict(lambda:[0,0])
    for lot,n in d.execute('select lot,n from keys'):
        z=inventory[notation(lot)];z[0]+=1;z[1]+=n
    tests=[]
    for value,expected in [('산13','EXPLICIT_SAN'),('13','NUMERIC_SAN_NOT_DISPLAYED'),('','EMPTY'),(None,'FIELD_ABSENT'),('BL-1','SPECIAL_OR_WHITESPACE_PRESERVED'),(' 13','SPECIAL_OR_WHITESPACE_PRESERVED'),('0','NUMERIC_SAN_NOT_DISPLAYED')]:
        assert notation(value)==expected; assert narrow(['PNU1','PNU2'],value)==['PNU1','PNU2']; tests.append([repr(value),expected,'NO_CANDIDATE_SELECTION'])
    try: narrow(['1','2'],'13',{'general':1})
    except ValueError: tests.append(['unapproved source rule','REJECT','PASS'])
    else: raise AssertionError('RULE_BYPASS')
    p.table(out/'mountain_top20.csv',['key_id','affected_occurrences','file_sha256','observation_id','raw_address','lot_literal','observability','notation','candidate_PNUs','PNU_digit11','decision'],rows,g)
    put(out/'mountain_evidence.json',evidence)
    put(out/'mountain_review.json',dict(status='NO_SAFE_ADDITIONAL_ASSIGNMENT',top_keys=20,affected_occurrences=total,raw_records_checked=20,full_raw_reparse=0,new_assignments=0,remaining_ambiguous=232482,notation_inventory={k:dict(keys=v[0],occurrences=v[1]) for k,v in inventory.items()},tests=tests,source_trace=dict(selector='src/rent_k2v2_route_audit_v0_1.py:transaction_jibun',behavior='Identity-only numeric/explicit-san grammar; no trim, no inferred mountain flag',candidate='csv_spatial_national_5179_v0_1/pipeline.py:candidates',candidate_key='verified legal code + literal A4; digit11 not used to narrow'),limitations=['Top20 are bounded raw examples, not all 69,625 source rows reread','PNU digit11 semantics do not establish CSV missing-marker semantics','No equivalence assumed for other 0/1 code systems']))
    c.close();d.close();return dict(keys=20,occurrences=total,new_assignments=0)
def panel(out,g):
    fm=b.read(Q/'final_manifest.json'); source_manifest=ROOT/b.read(D/'demand_config.json')['release']
    assert fm['assigned']==20403079 and fm['input_occurrences']==20916100
    national=Path(fm['national_database']); expected=next(z['sha256'] for z in fm['artifacts'] if z['path']==str(national))
    assert sha(national,g)==expected,'NATIONAL_BINDING'
    source_sha=sha(source_manifest,g); spatial_sha=sha(Q/'final_manifest.json',g)
    source_doc=b.read(source_manifest); assert len(source_doc['active_files'])==480
    c=db(out/'panel.sqlite');src=db(national,True)
    c.executescript('create table panel(grid_id text,quarter text,transaction_family text,n_obs integer not null check(n_obs>0),primary key(grid_id,quarter,transaction_family));create table quality(query_region text,quarter text,transaction_family text,input_n integer,assigned_n integer,unassigned_n integer,name_lot_n integer,no_parcel_n integer,ambiguous_n integer,geometry_failed_n integer,other_unassigned_n integer,assignment_rate real,primary key(query_region,quarter,transaction_family));create table metadata(key text primary key,value text);')
    count=0; n=0
    for row in src.execute('select grid_id,quarter,family,n from grid order by grid_id,quarter,family'):
        assert row[0].startswith(VERSION+':') and re.fullmatch(r'20\d\dQ[1-4]',row[1]) and row[2] in ('SALE','RENT') and row[3]>0
        c.execute('insert into panel values(?,?,?,?)',row);count+=1;n+=row[3]
        if count%2000==0:g.checkpoint('panel_groups_copied_'+str(count))
    assert count==571310 and n==20403079
    quality=defaultdict(Counter);sources=[];region_ids=b.read(O/'config.json')['region_ids']
    for region,rid in sorted(region_ids.items()):
        path=Q/'publish_v0_3/daegu_regional.sqlite' if rid=='R09' else N/'regions'/rid/'regional.sqlite'
        if not path.exists():path=O/'regions'/rid/'regional.sqlite'
        regional=db(path,True)
        for quarter,family,status,num in regional.execute('select quarter,family,status,sum(n) from counts group by quarter,family,status'):
            quality[(region,quarter,family)][status]+=num
        regional.close();sources.append(dict(query_region=region,aggregate_source=str(path),sha256=sha(path,g),reference_snapshot='2026-09-08'));g.checkpoint('quality_region_'+rid)
    path=BASE/'csv_spatial_5179_busan_v0_3/full_attempt/quarter_status_counts.csv'
    with path.open(encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):quality[('부산광역시',row['quarter'],row['family'])][row['status']]+=int(row['observation_occurrences'])
    sources.append(dict(query_region='부산광역시',aggregate_source=str(path),sha256=sha(path,g),reference_snapshot='2026-09-08'))
    allstatus=Counter();regionstatus=Counter()
    for (region,quarter,family),v in sorted(quality.items()):
        inp=sum(v.values());assigned=v['ASSIGNED'];others=sum(k for s,k in v.items() if s not in ['ASSIGNED','UNLINKED_NAME_OR_JIBUN','UNLINKED_PARCEL','AMBIGUOUS_PARCEL','GEOMETRY_FAILED'])
        c.execute('insert into quality values(?,?,?,?,?,?,?,?,?,?,?,?)',(region,quarter,family,inp,assigned,inp-assigned,v['UNLINKED_NAME_OR_JIBUN'],v['UNLINKED_PARCEL'],v['AMBIGUOUS_PARCEL'],v['GEOMETRY_FAILED'],others,assigned/inp if inp else None))
        allstatus.update(v)
        for s,k in v.items():regionstatus[(region,s)]+=k
    assert regionstatus==Counter({(r,s):num for r,s,num in src.execute('select * from statuses')}),'REGIONAL_STATUS_DRIFT'
    assert allstatus==Counter(ASSIGNED=20403079,UNLINKED_NAME_OR_JIBUN=37680,UNLINKED_PARCEL=215426,AMBIGUOUS_PARCEL=232482,GEOMETRY_FAILED=27433),allstatus
    assert sum(allstatus.values())==20916100
    # Independent panel vs quality conservation for every quarter and family.
    ps=c.execute('select quarter,transaction_family,sum(n_obs) from panel group by quarter,transaction_family order by 1,2').fetchall()
    qs=c.execute('select quarter,transaction_family,sum(assigned_n) from quality group by quarter,transaction_family order by 1,2').fetchall();assert ps==qs
    meta=dict(schema='KHMD_OBSERVATION_PANEL_V1',grid_version=VERSION,source_release_sha256=source_sha,spatial_manifest_sha256=spatial_sha,reference_snapshot='2026-09-08',unit='observation_occurrence',sparse='true')
    c.executemany('insert into metadata values(?,?)',meta.items());c.commit()
    p.table(out/'query_region_quarter_quality.csv',[z[0] for z in c.execute('select * from quality limit 0').description],c.execute('select * from quality order by query_region,quarter,transaction_family'),g)
    p.table(out/'panel_counts.csv',['grid_id','quarter','transaction_family','n_obs'],c.execute('select * from panel order by grid_id,quarter,transaction_family'),g)
    c.close();src.close()
    manifest=dict(**meta,panel_id='KHMD_OBSERVATION_PANEL_20261028_V1',database='panel.sqlite',database_sha256=sha(out/'panel.sqlite',g),source_release=dict(path=str(source_manifest),sha256=source_sha,selected_files=480,input_occurrences=20916100),spatial_result=dict(path=str(Q/'final_manifest.json'),sha256=spatial_sha),grid=dict(version=VERSION,CRS='EPSG:5179',xy='easting,northing',origin=[0,0],spacing_metres=1000),regional_reference_sources=sources,panel_groups=count,quality_groups=len(quality),assigned=n,unassigned=513021,input_occurrences=20916100,spatial_changes=0,missing_group_semantics='UNOBSERVED_NOT_AUTOMATIC_ZERO',query_region_semantics='Acquisition query unit; not historical jurisdiction',quality_denominator='query_region x quarter x family input observations; never grid completeness',limitations=['2026 reference parcels, not contract-time location verification','Unassigned observations excluded from grid counts but included in query-region quality denominator','Occurrence multiplicity preserved; not unique transactions','Seoul PILOT_PARTIAL; Cheongju PARTIAL_MATCH; population completeness unproven','Reference snapshot dates are inherited asset declarations, not acquisition dates'])
    put(out/'panel_release_manifest.json',manifest)
    return dict(panel_groups=count,quality_groups=len(quality),assigned=n,unassigned=513021,input=20916100,checks=['PK_UNIQUE','SPARSE_POSITIVE_COUNTS','NATIONAL_CONSERVATION','REGION_STATUS_EQUAL_PRIOR','QUARTER_FAMILY_CONSERVATION','480_EXPLICIT_SELECTED_SOURCE_FILES'],seconds=None)
def worker(stage,out):
    g=b.lane.resource.ReferenceGuard(ROOT); wd=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY']);t=time.monotonic()
    try:
        g.admit();g.reserve_output(256*1024**2)
        result=mountain(out,g) if stage=='mountain' else panel(out,g)
        result['elapsed_seconds']=time.monotonic()-t;put(out/'result.json',result);put(wd/'worker_resource_receipt.json',g.publication_gate())
    except BaseException as e:
        put(wd/'primary_exception.json',dict(error=str(e),traceback=traceback.format_exc()));put(wd/'worker_resource_receipt.json',g.receipt());raise
    finally:g.reader.close()
if __name__=='__main__':
    if sys.argv[1]=='worker':worker(sys.argv[2],Path(sys.argv[3]))
    else:
        stage=sys.argv[1];out=H/stage;out.mkdir()
        sup=b.lane.resource.supervise([sys.executable,'-B','-X','utf8',__file__,'worker',stage,str(out)],str(ROOT),dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),out/'supervised')
        put(out/'supervisor.json',sup);print(json.dumps(sup,ensure_ascii=False));assert sup['status']=='COMPLETE' and sup['returncode']==0
