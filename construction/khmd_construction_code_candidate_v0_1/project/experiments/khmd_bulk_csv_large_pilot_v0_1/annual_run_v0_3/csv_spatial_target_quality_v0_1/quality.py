"""Targeted provenance audit, explicit Guji code transition, immutable delta."""
import os,sys
from pathlib import Path
DLL=None
if Path(sys.executable).parent.name=='Python312':DLL=os.add_dll_directory(str(Path(sys.executable).parents[2]/'bin'))
import csv,json,sqlite3,hashlib,time,random,math,traceback,argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
H=Path(__file__).resolve().parent;BASE=H.parent;N=BASE/'csv_spatial_name_normalization_v0_1';O=BASE/'csv_spatial_national_5179_v0_1'
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
            records=rec.get('sets',[])
            if not records:continue
        else:continue
        for x in records:sets[x['set_id']]=x
    return sets

def prepare(out,g):
    cfg=p.config(g);p.verify_final(N/'national/final_manifest.json',g)
    c=db(H/'quality.sqlite');c.executescript('create table results(id primary key,region,status,n,payload,source_db);create table selected(id primary key,category,selection);create table weights(file_sha,key_id,quarter,row_status,n,primary key(file_sha,key_id,quarter,row_status));create table candidates(id,set_id,pnu,ordinal,sha,code,lot,eligibility,primary key(id,set_id,ordinal));create table guji(id primary key,source,lot,old_code,new_code,old_name,new_name,n,effective_date);')
    for region in cfg['regions']:
        path=current_region(region,cfg);r=db(path,True)
        with c:
            for aid,st,n,text in r.execute('select * from results'):c.execute('insert into results values(?,?,?,?,?,?)',(aid,region,st,n,text,str(path)))
        r.close()
    bus=db(p.V/'busan_run/spatial.sqlite',True)
    with c:
        for aid,st,n,text in bus.execute('select * from results'):c.execute('insert into results values(?,?,?,?,?,?)',(aid,'부산광역시',st,n,text,str(p.V/'busan_run/spatial.sqlite')))
    bus.close();b.need(c.execute('select count(*),sum(n) from results').fetchone()==(47676,20916100),'BASELINE_SCOPE')
    demand=db(p.P/'national_demand/demand.sqlite',True);mapping=db(N/'normalization.sqlite',True)
    selections=[]
    for status in ['UNLINKED_PARCEL','AMBIGUOUS_PARCEL']:
        top=c.execute('select id,n from results where status=? order by n desc,id limit 20',(status,)).fetchall()
        for aid,n in top:c.execute('insert into selected values(?,?,?)',(aid,status,'TOP20'));selections.append([status,'TOP20',aid,n])
    seed=20261028
    for rule in ['CITY_DISTRICT_FIELD_SPACING','SEJONG_UNIQUE_PARENT_OMITTED_IN_SOURCE']:
        rows=mapping.execute('select id,province,n from mapping where reason=? order by n desc,id',(rule,)).fetchall();top=rows[:10];used={x[0] for x in top}
        buckets=defaultdict(list)
        for x in rows[10:]:buckets[x[1]].append(x)
        # Deterministic seeded hash ranking; round-robin region coverage before extras.
        for region,xs in buckets.items():xs.sort(key=lambda x:hashlib.sha256((str(seed)+rule+x[0]).encode()).hexdigest())
        sample=[]
        while len(sample)<20:
            for region in sorted(buckets):
                if buckets[region] and len(sample)<20:sample.append(buckets[region].pop(0))
        for group,xs in [('TOP10',top),('SEED20_REGION_STRATIFIED',sample)]:
            for aid,region,n in xs:c.execute('insert into selected values(?,?,?)',(aid,rule,group));selections.append([rule,group,aid,n])
    # Code table is the official text member, not inferred prefix substitution.
    old={};new={}
    for line in (H/'evidence/legal_code_table.txt').read_text(encoding='cp949').splitlines():
        x=line.split()
        if len(x)>=6 and x[1:3]==['대구광역시','달성군'] and x[3] in ('구지면','구지읍') and x[4].endswith('리'):
            (old if x[3]=='구지면' else new)[x[4]]=x
    b.need(len(old)==15 and set(old)==set(new),'GUJI_CODE_TABLE_COVERAGE')
    transition=[]
    change=(H/'evidence/change.hwpx.txt').read_text(encoding='utf-8')
    for ri in sorted(old):
        a,z=old[ri],new[ri];b.need(a[-1]=='20260930' and z[-1]=='20260930','GUJI_DATE');b.need(a[0][5:] in change and z[0][5:] in change,'GUJI_CHANGE_TABLE_CODES')
        transition.append([ri,a[0],z[0],'2026-09-30','2026-09-08', 'CURRENT_CSV_NAME_TO_PRE_EFFECTIVE_REFERENCE_CODE'])
    p.table(out/'guji_ri_crosswalk.csv',['ri','old_code','new_code','effective_date','reference_date','direction'],transition)
    guji=mapping.execute("select id,source,lot,n from mapping where reason='CURRENT_MASTER_NO_PROVEN_ALIAS'").fetchall()
    with c:
        for aid,source,lot,n in guji:
            parts=source.split();b.need(parts[:3]==['대구광역시','달성군','구지읍'] and len(parts)==4 and parts[3] in old,'GUJI_FULL_ADDRESS');ri=parts[3]
            c.execute('insert into guji values(?,?,?,?,?,?,?,?,?)',(aid,source,lot,old[ri][0],new[ri][0],'대구광역시 달성군 구지면 '+ri,source,n,'2026-09-30'));c.execute('insert into selected values(?,?,?)',(aid,'GUJI','ALL9'))
    # Copy only selected-key preaggregated weights, one pass of existing demand.
    ids={x[0] for x in c.execute('select id from selected')}
    with c:
        for row in demand.execute('select * from weights'):
            if row[1] in ids:c.execute('insert into weights values(?,?,?,?,?)',row)
    # Existing candidates are retained with full record identity; never dedup by value.
    for aid,category,selection in c.execute('select * from selected').fetchall():
        region,st,n,text,source=c.execute('select region,status,n,payload,source_db from results where id=?',(aid,)).fetchone()
        if category=='GUJI':continue
        if region=='부산광역시':
            cand=db(p.P/'busan_candidates/candidates.sqlite',True)
            rows=cand.execute('select * from candidates where address_id=?',(aid,)).fetchall();cand.close()
            # Busan set locator resolved below from source payload or materialization.
            b.need(not rows,'BUSAN_CANDIDATE_SCHEMA_REQUIRES_EXPLICIT_ADAPTER')
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
    b.write(out/'selection.json',dict(seed=seed,top20=summary,rule_sample='each top10 + disjoint seeded20, round-robin regions, periods described not claimed representative',keys=len(ids),guji_keys=len(guji),guji_occurrences=sum(x[3] for x in guji)))
    b.write(H/'sets.json',sets);c.close();demand.close();mapping.close();g.checkpoint('target_selection_and_official_crosswalk_complete')
    return dict(status='PREPARED',selected_keys=len(ids),top20=summary)

def worker(stage,out):
    g=b.lane.resource.ReferenceGuard(ROOT);wd=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY']);t=time.monotonic()
    try:
        g.admit();result=prepare(out,g) if stage=='prepare' else audit(out,g) if stage=='audit' else publish(out,g)
        result['seconds']=time.monotonic()-t;b.write(out/'result.json',result);b.write(wd/'worker_resource_receipt.json',g.publication_gate())
    except BaseException as e:
        b.write(wd/'primary_exception.json',dict(error=str(e),traceback=traceback.format_exc()));b.write(wd/'worker_resource_receipt.json',g.receipt());raise
    finally:g.reader.close()

def execute(stage):
    out=H/stage;out.mkdir();cfg=p.config();runtime=ROOT/cfg['captured_runtime_root']/'apps/Python312/python.exe' if stage=='audit' else Path(sys.executable)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',PROJ_NETWORK='OFF',GDAL_PAM_ENABLED='NO');env.pop('PYTHONHOME',None);env.pop('PYTHONPATH',None)
    sup=b.lane.resource.supervise([str(runtime),'-B','-X','utf8',__file__,'worker',stage,str(out)],str(ROOT),env,out/'supervised');b.write(out/'supervisor.json',sup);print(b.dump(sup),flush=True);b.need(sup['status']=='COMPLETE' and sup['returncode']==0,'STOP_ON_HOLD')
if __name__=='__main__':
    if sys.argv[1]=='worker':worker(sys.argv[2],Path(sys.argv[3]))
    else:execute(sys.argv[1])
