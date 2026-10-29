"""Extracted real seed prefix and next prepare, with explicit immutable handoff."""
import csv,json,hashlib,sqlite3
from pathlib import Path
from collections import defaultdict
from binding import *
from runtime import load
from guji_contract import seed_check,prepare_check,validate_seed
p=load('national_base',ANNUAL/'csv_spatial_national_5179_v0_1/pipeline.py')
b=p.b;s=p.s;d=p.d;db=p.db

def seed(bound,out,work,g):
    cfg,inputs=seed_check(bound,g);H=work;N=inputs['mapping'].parent
    need(not(work/'quality.sqlite').exists(),'SEED_INITIAL_OUTPUT_EXISTS_USE_NEW_WORK_OR_COMPLETED_MANIFEST')
    c=db(H/'quality.sqlite');c.executescript('create table results(id primary key,region,status,n,payload,source_db);create table selected(id primary key,category,selection);create table weights(file_sha,key_id,quarter,row_status,n,primary key(file_sha,key_id,quarter,row_status));create table candidates(id,set_id,pnu,ordinal,sha,code,lot,eligibility,primary key(id,set_id,ordinal));create table guji(id primary key,source,lot,old_code,new_code,old_name,new_name,n,effective_date);')
    for region in cfg['regions']:
        path=inputs['region:'+region];r=db(path,True)
        with c:
            for aid,st,n,text in r.execute('select * from results'):c.execute('insert into results values(?,?,?,?,?,?)',(aid,region,st,n,text,str(path)))
        r.close()
    bus=db(inputs['busan_spatial'],True)
    with c:
        for aid,st,n,text in bus.execute('select * from results'):c.execute('insert into results values(?,?,?,?,?,?)',(aid,'부산광역시',st,n,text,str(inputs['busan_spatial'])))
    bus.close();b.need(c.execute('select count(*),sum(n) from results').fetchone()==(cfg['baseline_keys'],cfg['baseline_occurrences']),'BASELINE_SCOPE')
    demand=db(inputs['demand'],True);mapping=db(inputs['mapping'],True)
    selections=[]
    for status in ['UNLINKED_PARCEL','AMBIGUOUS_PARCEL']:
        top=c.execute('select id,n from results where status=? order by n desc,id limit 20',(status,)).fetchall()
        for aid,n in top:c.execute('insert into selected values(?,?,?)',(aid,status,'TOP20'));selections.append([status,'TOP20',aid,n])
    seed=20261028
    for rule in ['CITY_DISTRICT_FIELD_SPACING','SEJONG_UNIQUE_PARENT_OMITTED_IN_SOURCE']:
        rows=mapping.execute('select id,province,n from mapping where reason=? order by n desc,id',(rule,)).fetchall();b.need(len(rows)>=30,'INSUFFICIENT_RULE_SAMPLE:'+rule);top=rows[:10];used={x[0] for x in top}
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
    for line in inputs['legal_codes'].read_text(encoding='cp949').splitlines():
        x=line.split()
        if len(x)>=6 and x[1:3]==['대구광역시','달성군'] and x[3] in ('구지면','구지읍') and x[4].endswith('리'):
            (old if x[3]=='구지면' else new)[x[4]]=x
    b.need(len(old)==15 and set(old)==set(new),'GUJI_CODE_TABLE_COVERAGE')
    transition=[]
    change=inputs['official_change'].read_text(encoding='utf-8')
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
    c.commit();c.close();demand.close();mapping.close()
    result=validate_seed(work/'quality.sqlite',cfg)
    g.checkpoint('official_crosswalk_and_selected_weights_seed_complete')
    return dict(status='GUJI_SEED_READY',**result)

def prepare(bound,out,work,g):
    cfg,inputs=prepare_check(bound,work,g);H=work;c=db(work/'quality.sqlite');demand=db(inputs['demand'],True);mapping=db(inputs['mapping'],True)
    with c:c.execute('delete from candidates')
    ids={x[0] for x in c.execute('select id from selected')};seed=20261028
    b.need(len(ids)==109,'INHERITED_SELECTION')
    # Existing candidates are retained with full record identity; never dedup by value.
    for aid,category,selection in c.execute('select * from selected').fetchall():
        region,st,n,text,source=c.execute('select region,status,n,payload,source_db from results where id=?',(aid,)).fetchone()
        if category=='GUJI':continue
        if region=='부산광역시':
            cand=db(inputs['busan_candidates'],True)
            rows=cand.execute('select * from candidates where address_id=?',(aid,)).fetchall();cand.close()
            # Busan set locator resolved below from source payload or materialization.
            sid='4724:'+Path(b.read(inputs['busan_extraction'])['members']['.dbf']['path']).stem
            with c:c.executemany('insert into candidates values(?,?,?,?,?,?,?,?)',[(r[0],sid,*r[1:]) for r in rows])
        else:
            cand=db(source,True);rows=cand.execute('select * from candidate_links where id=?',(aid,)).fetchall();cand.close()
            if not rows and Path(source)!=inputs['base_region:'+region]:
                cand=db(inputs['base_region:'+region],True);rows=cand.execute('select * from candidate_links where id=?',(aid,)).fetchall();cand.close()
            with c:c.executemany('insert into candidates values(?,?,?,?,?,?,?,?)',rows)
    # Guji uses prior code and exact unchanged lot against existing complete index.
    ix=db(inputs['parcel_index'],True);sets=b.read(inputs['members'])['sets_by_id']
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
    b.write(out/'selection.json',dict(seed=seed,top20=summary,rule_sample='each top10 + disjoint seeded20, round-robin regions, periods described not claimed representative',keys=len(ids),guji_keys=9,guji_occurrences=cfg['guji_occurrences']))
    b.write(H/'sets.json',sets);c.close();demand.close();mapping.close();g.checkpoint('target_selection_and_official_crosswalk_complete')
    return dict(status='PREPARED',selected_keys=len(ids),top20=summary)
