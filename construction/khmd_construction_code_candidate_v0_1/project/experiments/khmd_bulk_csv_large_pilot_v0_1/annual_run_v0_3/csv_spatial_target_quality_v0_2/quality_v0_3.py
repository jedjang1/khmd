"""Targeted provenance audit, explicit Guji code transition, immutable delta."""
import os,sys
from pathlib import Path
DLL=None
if Path(sys.executable).parent.name=='Python312':DLL=os.add_dll_directory(str(Path(sys.executable).parents[2]/'bin'))
import csv,json,sqlite3,hashlib,time,random,math,traceback,argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
H=Path(__file__).resolve().parent;BASE=H.parent;N=BASE/'csv_spatial_name_normalization_v0_1';O=BASE/'csv_spatial_national_5179_v0_1';EVID=BASE/'csv_spatial_target_quality_v0_1/evidence'
sys.path.insert(0,str(O));import pipeline as p
b=p.b;s=p.s;d=p.d;ROOT=p.ROOT;db=p.db

def current_region(region,cfg):
    path=N/'regions'/cfg['region_ids'][region]/'regional.sqlite'
    return path if path.exists() else O/'regions'/cfg['region_ids'][region]/'regional.sqlite'
def member_sets(cfg):
    sets={}
    for oid,obj in cfg['objects'].items():
        path=N/'objects'/oid/'members.json'
        if not path.exists():path=O/'objects'/oid/'members.json'
        if path.exists():records=b.read(path)['sets']
        elif oid=='NRC_4724':
            # Busan source is already materialized and bound by the demand stage.
            rec=b.read(BASE/'csv_spatial_supply_v0_1/supply_run_v0_4/regional_extraction.json')
            records=[dict(set_id='4724:'+Path(rec['members']['.dbf']['path']).stem,members=rec['members'],source_archive_sha256=rec['source']['sha256'])]
        else:continue
        for x in records:sets[x['set_id']]=x
    return sets

def prepare(out,g):
    cfg=p.config(g);c=db(H/'quality.sqlite');demand=db(p.P/'national_demand/demand.sqlite',True);mapping=db(N/'normalization.sqlite',True)
    with c:c.execute('delete from candidates')
    ids={x[0] for x in c.execute('select id from selected')};seed=20261028
    b.need(len(ids)==109,'INHERITED_SELECTION')
    # Existing candidates are retained with full record identity; never dedup by value.
    for aid,category,selection in c.execute('select * from selected').fetchall():
        region,st,n,text,source=c.execute('select region,status,n,payload,source_db from results where id=?',(aid,)).fetchone()
        if category=='GUJI':continue
        if region=='부산광역시':
            cand=db(p.P/'busan_candidates/candidates.sqlite',True)
            rows=cand.execute('select * from candidates where address_id=?',(aid,)).fetchall();cand.close()
            # Busan set locator resolved below from source payload or materialization.
            sid='4724:'+Path(b.read(BASE/'csv_spatial_supply_v0_1/supply_run_v0_4/regional_extraction.json')['members']['.dbf']['path']).stem
            with c:c.executemany('insert into candidates values(?,?,?,?,?,?,?,?)',[(r[0],sid,*r[1:]) for r in rows])
        else:
            cand=db(source,True);rows=cand.execute('select * from candidate_links where id=?',(aid,)).fetchall();cand.close()
            if not rows and Path(source)!=O/'regions'/cfg['region_ids'][region]/'regional.sqlite':
                cand=db(O/'regions'/cfg['region_ids'][region]/'regional.sqlite',True);rows=cand.execute('select * from candidate_links where id=?',(aid,)).fetchall();cand.close()
            with c:c.executemany('insert into candidates values(?,?,?,?,?,?,?,?)',rows)
    # Guji uses prior code and exact unchanged lot against existing complete index.
    ix=db(ROOT/cfg['index_path'],True);sets=member_sets(cfg)
    with c:
        for aid,source,lot,oc,nc,on,nn,n,date in c.execute('select * from guji').fetchall():
            for sid,ordinal,pnu in ix.execute('select set_id,row_ordinal,pnu from parcels indexed by parcels_K2V2 where a2 COLLATE BINARY=? and jibun COLLATE BINARY=?',(oc,lot)):
                rec=sets[sid];path=Path(rec['members']['.dbf']['path'])
                with path.open('rb') as f:
                    hdr=s.inputs._dbf_header(f);f.seek(hdr['header_length']+(ordinal-1)*hdr['record_length']);raw=f.read(hdr['record_length']);v=s.rawfields(raw,hdr)
                b.need((v['A1'],v['A2'],v['A4'])==(pnu,oc,lot),'GUJI_INDEX_RAW_BINDING');c.execute('insert into candidates values(?,?,?,?,?,?,?,?)',(aid,sid,pnu,ordinal,hashlib.sha256(raw).hexdigest(),oc,lot,'EXACT_REFERENCE_CANDIDATE'))
    ix.close()
    selection_rows=[]
    for aid,cat,selection in c.execute('select * from selected'):
        key=demand.execute('select * from keys where id=?',(aid,)).fetchone();region=key[1];lo,hi=c.execute('select min(quarter),max(quarter) from weights where key_id=?',(aid,)).fetchone()
        status=c.execute('select status from results where id=?',(aid,)).fetchone()[0];selection_rows.append([cat,selection,aid,region,key[2],key[3],key[6],status,lo,hi])
    p.table(out/'selected_keys.csv',['category','selection','id','query_region','source_address','lot','occurrences','prior_status','first_quarter','last_quarter'],selection_rows)
    summary={st:dict(keys=20,occurrences=c.execute('select sum(r.n) from results r join selected s using(id) where s.category=?',(st,)).fetchone()[0],denominator=c.execute('select sum(n) from results where status=?',(st,)).fetchone()[0]) for st in ['UNLINKED_PARCEL','AMBIGUOUS_PARCEL']}
    for x in summary.values():x['share']=x['occurrences']/x['denominator']
    b.write(out/'selection.json',dict(seed=seed,top20=summary,rule_sample='each top10 + disjoint seeded20, round-robin regions, periods described not claimed representative',keys=len(ids),guji_keys=9,guji_occurrences=8629))
    b.write(H/'sets.json',sets);c.close();demand.close();mapping.close();g.checkpoint('target_selection_and_official_crosswalk_complete')
    return dict(status='PREPARED',selected_keys=len(ids),top20=summary)

def audit(out,g):
    cfg=p.config(g);c=db(H/'quality.sqlite');demand=db(p.P/'national_demand/demand.sqlite',True);mapping=db(N/'normalization.sqlite',True);sets=b.read(H/'sets.json')
    c.executescript('create table if not exists record_evidence(id,set_id,ordinal,payload,primary key(id,set_id,ordinal));create table if not exists audit_keys(id primary key,payload);create table if not exists updates(id primary key,status,n,payload);')
    master={}
    with (ROOT/b.read(p.P/'demand_config.json')['legal_master']).open(encoding='utf-8-sig',newline='') as f:
        for x in csv.DictReader(f):master[x['법정동코드']]=[x[k] for k in ['시도명','시군구명','읍면동명','리명']]
    runtime,eng=s.captured_runtime(b.read(BASE/'csv_spatial_supply_v0_1/supply_config_v0_4.json'),g);gd,ogr,pp,sh,_=eng;gd.SetCacheMax(1024*1024)
    target=pp.CRS.from_epsg(5179);tf=pp.Transformer.from_crs(5186,5179,always_xy=True);trans=(tf,pp.Transformer.from_crs(5179,5186,always_xy=True),pp.Transformer.from_crs(5186,target.geodetic_crs,always_xy=True),target.area_of_use)
    cache=p.Saved(cfg,g);opened=None;sidnow=None;facts=[]
    for aid,sid,pnu,ordinal,sha,code,lot,elig in c.execute('select * from candidates order by set_id,ordinal').fetchall():
        if c.execute('select 1 from record_evidence where id=? and set_id=? and ordinal=?',(aid,sid,ordinal)).fetchone():continue
        if sid!=sidnow:
            if opened:opened[2].close();opened=None;layer=None;dataset=None
            rec=sets[sid];path=Path(rec['members']['.dbf']['path']);dataset=ogr.Open(str(path.with_suffix('.shp')),0);b.need(dataset is not None,'SOURCE_GEOMETRY_UNAVAILABLE');layer=dataset.GetLayer(0)
            fact=s.inputs._crs_facts(path.with_suffix('.prj'),layer,pp);b.need(fact['effective_authority']==['EPSG','5186'],'SOURCE_CRS');facts.append(dict(set_id=sid,**fact));f=path.open('rb');hdr=s.inputs._dbf_header(f);opened=(dataset,layer,f,hdr);sidnow=sid
        f=opened[2];hdr=opened[3];f.seek(hdr['header_length']+(ordinal-1)*hdr['record_length']);raw=f.read(hdr['record_length']);v=s.rawfields(raw,hdr)
        b.need(hashlib.sha256(raw).hexdigest()==sha and (v['A1'],v['A2'],v['A4'])==(pnu,code,lot),'RAW_CANDIDATE_IDENTITY')
        wkb=s.inputs._verify_record(layer,f,hdr,ordinal,pnu,'A1');geom=sh.from_wkb(wkb) if wkb else None;wh=hashlib.sha256(wkb).hexdigest() if wkb else None
        evidence=dict(pnu=pnu,set_id=sid,ordinal=ordinal,raw_A2=code,raw_A4=lot,DBF_record_sha256=sha,geometry_sha256=wh,geometry_valid=bool(geom is not None and geom.is_valid),PNU_land_type=pnu[10],PNU_main=int(pnu[11:15]),PNU_sub=int(pnu[15:19]),source_CRS='EPSG:5186',reference_date='2026-09-08')
        region,status,n,text,source=c.execute('select region,status,n,payload,source_db from results where id=?',(aid,)).fetchone();cat,selection=c.execute('select category,selection from selected where id=?',(aid,)).fetchone()
        if cat=='GUJI':
            b.need(c.execute('select count(*) from candidates where id=?',(aid,)).fetchone()[0]==1,'GUJI_NOT_UNIQUE')
            result=p.geometry((aid,n,sid,pnu,ordinal,sha,code,lot,elig),opened,cache,eng,trans)
            result['official_code_transition']=dict(zip(['source','lot','old_code','new_code','reference_name','source_name','occurrences','effective_date'],c.execute('select source,lot,old_code,new_code,old_name,new_name,n,effective_date from guji where id=?',(aid,)).fetchone()));result['contract_date_filter_applied']=False
            with c:c.execute('insert into updates values(?,?,?,?)',(aid,result['status'],n,b.dump(result)))
        elif cat in ['CITY_DISTRICT_FIELD_SPACING','SEJONG_UNIQUE_PARENT_OMITTED_IN_SOURCE']:
            key=demand.execute('select * from keys where id=?',(aid,)).fetchone();fields=master[code];actual=key[2].split();prov,county,dong,ri=fields
            if cat=='CITY_DISTRICT_FIELD_SPACING':
                leaf=[dong]+([ri] if ri else []);b.need(actual[0]==prov and actual[-len(leaf):]==leaf,'INDEPENDENT_LEAF_HIERARCHY');b.need(''.join(actual[1:-len(leaf)])==county,'INDEPENDENT_CITY_DISTRICT_CHARACTERS')
            else:b.need(fields[0]=='세종특별자치시' and county=='세종시' and code.startswith('36110') and actual==[prov,dong]+([ri] if ri else []),'INDEPENDENT_SEJONG_PARENT_LEAF')
            b.need(code==pnu[:10] and key[3]==lot,'MASTER_PNU_LOT_CHAIN');evidence['master_fields']=fields;evidence['source_address']=key[2]
            if status=='ASSIGNED':
                old=json.loads(text);b.need(old['geometry_wkb_sha256']==wh and geom.is_valid,'SAVED_GEOMETRY_SHA_VALID');point=sh.Point(old['source_x'],old['source_y']);b.need(geom.contains(point),'INDEPENDENT_SOURCE_CONTAINS')
                x,y=tf.transform(point.x,point.y,errcheck=True);b.need(abs(x-old['x'])<1e-7 and abs(y-old['y'])<1e-7,'INDEPENDENT_COORDINATE_CHAIN')
                gid='KHMD_UTMK_1KM_V1:'+str(math.floor(x/1000))+':'+str(math.floor(y/1000));b.need(gid==old['grid_id'],'INDEPENDENT_GRID_FLOOR')
                evidence.update(grid_id=gid,source_point_inside=True,stored_grid_reconciled=True)
        with c:c.execute('insert into record_evidence values(?,?,?,?)',(aid,sid,ordinal,b.dump(evidence)))
        g.checkpoint('raw_geometry_evidence_completed_'+aid[:10]+'_'+str(ordinal))
    if opened:opened[2].close();opened=None;dataset=None;layer=None
    cache.close();master.clear()
    for aid,cat,selection in c.execute('select * from selected').fetchall():
        if c.execute('select 1 from audit_keys where id=?',(aid,)).fetchone():continue
        key=demand.execute('select * from keys where id=?',(aid,)).fetchone();region,status,n,text,source=c.execute('select region,status,n,payload,source_db from results where id=?',(aid,)).fetchone();ev=[json.loads(x[0]) for x in c.execute('select payload from record_evidence where id=?',(aid,))];pnus={x['pnu'] for x in ev}
        item=dict(id=aid,category=cat,selection=selection,source_address=key[2],lot=key[3],occurrences=n,prior_status=status,candidate_rows=len(ev),distinct_PNUs=len(pnus),source_reference='2026-09-08',historical_location_verified=False)
        if cat=='AMBIGUOUS_PARCEL':
            item['classification']='DISTINCT_PNU_NOT_DUPLICATE_INDEX' if len(pnus)>1 else 'SAME_PNU_RECORDS_REQUIRE_SOURCE_AND_GEOMETRY_REVIEW';item['land_types']=sorted({x['PNU_land_type'] for x in ev});item['distinct_geometry_sha']=len({x['geometry_sha256'] for x in ev});item['automatic_choice']=False
            b.need(len(pnus)>1,'SAME_PNU_DUPLICATION_REQUIRES_REVIEW')
        elif cat=='UNLINKED_PARCEL':
            b.need(not ev,'UNLINKED_CANDIDATES_CONTRADICTION');payload=json.loads(text);code=json.loads(key[4])
            if not code:
                row=mapping.execute('select code from mapping where id=?',(aid,)).fetchone();code=[row[0]] if row else []
            objects=p.route(code[0],cfg['prefix_objects']) if len(code)==1 else [];b.need(len(objects)==1,'UNLINKED_REFERENCE_SCOPE_UNRESOLVED')
            oid=objects[0];base=N/'objects'/oid
            # Existing completed raw scan/index evidence; no inferred physical history.
            if not (base/'final_manifest.json').exists():base=O/'objects'/oid
            m=p.verify_final(base/'final_manifest.json',g);cand=db(base/'candidates.sqlite',True);hits=cand.execute('select count(*) from candidates where code=?',(code[0],)).fetchone()[0];cand.close()
            item.update(classification='EXACT_CODE_LOT_ABSENT_IN_VALIDATED_REFERENCE_SCAN',reference_object=oid,reference_complete_manifest=str(base/'final_manifest.json'),same_legal_code_other_candidate_records=hits,master_code=code[0],underlying_reason='UNCONFIRMED_PARCEL_CHANGE_OR_SOURCE_TIME_OR_ABSENCE',supply_missing=False,automatic_address_change=False)
        elif cat=='GUJI':item.update(classification='OFFICIAL_RI_CODE_TRANSITION',new_status=c.execute('select status from updates where id=?',(aid,)).fetchone()[0])
        else:item.update(classification='RAW_MASTER_PNU_GEOMETRY_CHAIN_VERIFIED' if status=='ASSIGNED' else 'MASTER_AND_CANDIDATE_CHAIN_ONLY_GRID_NOT_AVAILABLE',grid_verified=status=='ASSIGNED')
        with c:c.execute('insert into audit_keys values(?,?)',(aid,b.dump(item)))
    p.table(out/'target_quality.csv',['id','evidence'],c.execute('select * from audit_keys order by id'),g)
    p.table(out/'raw_parcel_evidence.csv',['id','set_id','ordinal','evidence'],c.execute('select * from record_evidence order by id,set_id,ordinal'),g)
    p.table(out/'guji_results.csv',['id','status','occurrences','payload'],c.execute('select * from updates order by id'),g);b.write(out/'source_CRS.json',facts)
    result=dict(status='TARGET_AUDIT_COMPLETE',keys=c.execute('select count(*) from audit_keys').fetchone()[0],guji_states=dict(c.execute('select status,sum(n) from updates group by status')),rule_sample_states=[list(x) for x in c.execute("select s.category,r.status,count(*),sum(r.n) from selected s join results r using(id) where s.category like '%FIELD%' or s.category like 'SEJONG%' group by 1,2")],ambiguous_distinct_PNU_keys=20,source_or_geometry_systematic_mismatch_detected=False)
    c.close();demand.close();mapping.close();return result

def publish(out,g):
    cfg=p.config(g);c=db(H/'quality.sqlite',True);base=p.verify_final(N/'national/final_manifest.json',g);before=base['result'];folder=Path(base['out'])
    b.need(c.execute('select count(*),sum(n) from updates').fetchone()==(9,8629),'ONLY_GUJI_UPDATES')
    # Verify the two sample keys with no candidate at the independent master level.
    dm=db(p.P/'national_demand/demand.sqlite',True);maps=db(N/'normalization.sqlite',True)
    master={}
    with (ROOT/b.read(p.P/'demand_config.json')['legal_master']).open(encoding='utf-8-sig') as f:
        for x in csv.DictReader(f):
            if x['읍면동명']:master[x['법정동코드']]=[x[k] for k in ['시도명','시군구명','읍면동명','리명']]
    missing_sample=[]
    for aid, in c.execute("select s.id from selected s join results r using(id) where s.category='CITY_DISTRICT_FIELD_SPACING' and r.status='UNLINKED_PARCEL'"):
        k=dm.execute('select * from keys where id=?',(aid,)).fetchone();code=maps.execute('select code from mapping where id=?',(aid,)).fetchone()[0];prov,county,dong,ri=master[code];leaf=[dong]+([ri] if ri else []);a=k[2].split();b.need(a[0]==prov and a[-len(leaf):]==leaf and ''.join(a[1:-len(leaf)])==county,'EMPTY_CANDIDATE_MASTER_CHAIN');missing_sample.append(dict(id=aid,master_code=code,source=k[2],master_fields=master[code],grid_verification='NOT_AVAILABLE_NO_CANDIDATE'))
    master.clear();maps.close();dm.close();b.write(out/'no_candidate_rule_sample_checks.json',missing_sample)
    g.reserve_output(160*1024**2)
    source=db(folder/'national.sqlite',True);target=db(out/'national.sqlite');source.backup(target,pages=256,progress=lambda a,bv,cv:g.checkpoint('national_baseline_backup_pages_'+str(cv-bv)));source.close()
    oldrd=current_region('대구광역시',cfg);old=db(oldrd,True);regional=db(out/'daegu_regional.sqlite');old.backup(regional,pages=128);old.close()
    def add(conn,table,values,columns):
        conn.execute('insert into '+table+' values('+','.join('?' for _ in values)+') on conflict('+columns+') do update set n=n+excluded.n',values)
    transitions=Counter()
    with target,regional:
        for aid,status,n,text in c.execute('select * from updates'):
            b.need(status=='ASSIGNED','NON_ASSIGNED_GUJI_REVIEW');oldrow=regional.execute('select status,n,payload from results where id=?',(aid,)).fetchone();b.need(oldrow[0]=='UNLINKED_NAME_OR_JIBUN' and oldrow[1]==n,'PRIOR_GUJI_STATUS');new=json.loads(text);gid=new['grid_id'];total=0
            for sha,quarter,rowstatus,weight in c.execute('select file_sha,quarter,row_status,n from weights where key_id=?',(aid,)):
                b.need(quarter!='UNASSIGNABLE_PERIOD' and rowstatus=='PARSED','GUJI_PERIOD');family=db_file_family(sha);total+=weight
                regional.execute("update counts set n=n-? where grid_id='' and quarter=? and family=? and status='UNLINKED_NAME_OR_JIBUN'",(weight,quarter,family))
                add(regional,'counts',(gid,quarter,family,'ASSIGNED',weight),'grid_id,quarter,family,status');add(target,'grid',(gid,quarter,family,weight),'grid_id,quarter,family')
            b.need(total==n,'GUJI_WEIGHT_CONSERVATION');regional.execute('update results set status=?,payload=? where id=?',(status,text,aid));transitions[(oldrow[0],status)]+=n
        regional.execute('delete from counts where n=0');b.need(regional.execute('select count(*) from counts where n<0').fetchone()[0]==0,'NEGATIVE_COUNT')
        target.execute("update statuses set n=n-8629 where region='대구광역시' and status='UNLINKED_NAME_OR_JIBUN'")
        target.execute("update statuses set n=n+8629 where region='대구광역시' and status='ASSIGNED'")
        target.execute("update sources set assigned=assigned+8629,unassigned=unassigned-8629,manifest_sha=? where region='대구광역시'",('DELTA_BOUND:'+b.lane.sha(H/'quality.sqlite',g),));target.execute('delete from statuses where n=0')
    n,assigned,unassigned=target.execute('select sum(input),sum(assigned),sum(unassigned) from sources').fetchone();b.need(n==20916100 and assigned+unassigned==n,'NATIONAL_CONSERVATION');b.need(target.execute('select sum(n) from grid').fetchone()[0]==assigned,'GRID_SUM');b.need(target.execute('select sum(n) from statuses').fetchone()[0]==n,'STATUSES_SUM')
    # Ensure every unchanged Daegu result remains byte-for-byte equal, not rerun.
    old=db(oldrd,True);unchanged=0
    for row in old.execute('select * from results'):
        if c.execute('select 1 from updates where id=?',(row[0],)).fetchone():continue
        b.need(row==regional.execute('select * from results where id=?',(row[0],)).fetchone(),'NON_TARGET_PAYLOAD_DRIFT');unchanged+=1
    old.close()
    p.table(out/'national_grid_quarter_counts.csv',['grid_id','quarter','transaction_family','observation_occurrences'],target.execute('select * from grid order by 1,2,3'),g)
    p.table(out/'query_region_status_counts.csv',['query_region','status','occurrences'],target.execute('select * from statuses order by 1,2'),g)
    p.table(out/'query_region_totals.csv',['query_region','input','assigned','unassigned','evidence_binding'],target.execute('select * from sources order by 1'),g)
    # Reuse completed per-region/year/family counts, apply just the 9-key delta.
    totals=Counter()
    prior=N/'validation/region_year_family_unassigned_reasons.csv'
    with prior.open(encoding='utf-8-sig',newline='') as f:
        for x in csv.DictReader(f):totals[(x['query_region'],x['contract_year'],x['family'],x['status'])]=int(x['after'])
    for aid, in c.execute('select id from updates'):
        for sha,quarter,n in c.execute('select file_sha,quarter,n from weights where key_id=?',(aid,)):
            family=db_file_family(sha);totals[('대구광역시',quarter[:4],family,'UNLINKED_NAME_OR_JIBUN')]-=n;totals[('대구광역시',quarter[:4],family,'ASSIGNED')]+=n
    b.need(sum(totals.values())==20916100 and min(totals.values())>=0,'PERIOD_COUNTS')
    p.table(out/'region_year_family_status.csv',['query_region','year','family','status','occurrences'],[(*k,v) for k,v in sorted(totals.items()) if v],g)
    rates=[]
    for reg,y,f in sorted({k[:3] for k in totals}):
        alln=sum(v for k,v in totals.items() if k[:3]==(reg,y,f));an=totals[(reg,y,f,'ASSIGNED')];rates.append([reg,y,f,alln,an,alln-an,an/alln])
    p.table(out/'region_year_family_rates.csv',['query_region','year','family','input','assigned','unassigned','assignment_rate'],rates,g)
    p.table(out/'largest_relative_gaps.csv',['query_region','year','family','input','assigned','unassigned','assignment_rate'],sorted(rates,key=lambda x:(x[-1],-x[-2]))[:20],g)
    p.table(out/'largest_absolute_gaps.csv',['query_region','year','family','input','assigned','unassigned','assignment_rate'],sorted(rates,key=lambda x:-x[-2])[:20],g)
    states=dict(target.execute('select status,sum(n) from statuses group by status'));groups=target.execute('select count(*) from grid').fetchone()[0];target.close();regional.close();c.close()
    return dict(status='TARGET_QUALITY_REVIEW_AND_GUJI_DELTA_COMPLETE',input=sum(states.values()),assigned=assigned,unassigned=unassigned,states=states,grid_groups=groups,newly_assigned=8629,changed_keys=9,other_keys_unchanged=47667,daegu_other_keys_verified=unchanged,baseline_manifest=str(N/'national/final_manifest.json'),baseline_manifest_sha=b.lane.sha(N/'national/final_manifest.json'),grid_version='KHMD_UTMK_1KM_V1',reference_date='2026-09-08',historical_location_verified=False)

_families=None
def db_file_family(sha):
    global _families
    if _families is None:
        dbase=db(p.P/'national_demand/demand.sqlite',True);_families=dict(dbase.execute('select sha,family from files'));dbase.close()
    return _families[sha]

def worker(stage,out):
    g=b.lane.resource.ReferenceGuard(ROOT);wd=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY']);t=time.monotonic()
    try:
        g.admit();result=prepare(out,g) if stage=='prepare' else audit(out,g) if stage=='audit' else publish(out,g)
        result['seconds']=time.monotonic()-t;b.write(out/'result.json',result);b.write(wd/'worker_resource_receipt.json',g.publication_gate())
    except BaseException as e:
        b.write(wd/'primary_exception.json',dict(error=str(e),traceback=traceback.format_exc()));b.write(wd/'worker_resource_receipt.json',g.receipt());raise
    finally:g.reader.close()

def execute(stage):
    out=H/(stage+'_v0_3');out.mkdir();cfg=p.config();runtime=ROOT/cfg['captured_runtime_root']/'apps/Python312/python.exe' if stage=='audit' else Path(sys.executable)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',PROJ_NETWORK='OFF',GDAL_PAM_ENABLED='NO');env.pop('PYTHONHOME',None);env.pop('PYTHONPATH',None)
    sup=b.lane.resource.supervise([str(runtime),'-B','-X','utf8',__file__,'worker',stage,str(out)],str(ROOT),env,out/'supervised');b.write(out/'supervisor.json',sup);print(b.dump(sup),flush=True);b.need(sup['status']=='COMPLETE' and sup['returncode']==0,'STOP_ON_HOLD')
if __name__=='__main__':
    if sys.argv[1]=='worker':worker(sys.argv[2],Path(sys.argv[3]))
    else:execute(sys.argv[1])
