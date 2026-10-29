"""Versioned failed-key expression normalization; no raw parsing or fuzzy match."""
import os,sys
from pathlib import Path
DLL=None
if Path(sys.executable).parent.name=='Python312':DLL=os.add_dll_directory(str(Path(sys.executable).parents[2]/'bin'))
import csv,json,re,sqlite3,time,hashlib,argparse
from collections import Counter
from datetime import datetime,timezone
H=Path(__file__).resolve().parent;OLD=H.parent/'csv_spatial_national_5179_v0_1'
sys.path.insert(0,str(OLD));import pipeline as p
b=p.b;s=p.s;d=p.d;ROOT=p.ROOT;db=p.db
BASE_SAVED=p.Saved;BASE_CONFIG=p.config
p.H=H;p.__file__=__file__

def collapse(x):return ' '.join(x.split())
def aliases(row,unique_sejong_parent):
    prov,county,dong,ri=[row[k] for k in ['시도명','시군구명','읍면동명','리명']]
    if not dong:return []
    full=' '.join(x for x in [prov,county,dong,ri] if x)
    found=[(full,'HIERARCHY_SEPARATOR_WHITESPACE')]
    # Only explicit city+district boundary; preserve every character and leaf.
    m=re.fullmatch(r'([^\s]+시)([^\s]+구)',county)
    if m:found.append((' '.join(x for x in [prov,m[1],m[2],dong,ri] if x),'CITY_DISTRICT_FIELD_SPACING'))
    # Reference-master projection, NOT filling or editing the source empty field.
    if prov=='세종특별자치시' and county=='세종시' and unique_sejong_parent and row['법정동코드'].startswith('36110'):
        found.append((' '.join(x for x in [prov,dong,ri] if x),'SEJONG_UNIQUE_PARENT_OMITTED_IN_SOURCE'))
    return found

def lookup(c,source):
    matches=c.execute('select code,full,province,county,dong,ri,rule,master_row from aliases where alias=? order by code,rule',(collapse(source),)).fetchall()
    codes={x[0] for x in matches}
    return matches, sorted(codes)

def tests(c,lot):
    passed=[]
    def check(name,x):b.need(x,'REGRESSION:'+name);passed.append(name)
    check('city_district_explicit_boundary',lookup(c,'경기도 수원시 영통구 영통동')[1]==['4111710500'])
    check('other_parent_not_allowed',not lookup(c,'충청북도 수원시 영통구 영통동')[1])
    check('missing_district_not_inferred',not lookup(c,'경기도 수원시 영통동')[1])
    check('leaf_not_omitted',not lookup(c,'경기도 수원시 영통구')[1])
    check('sejong_unique_parent_projection',lookup(c,'세종특별자치시  종촌동')[1]==['3611011100'])
    check('arbitrary_county_not_inferred',not lookup(c,'경기도  영통동')[1])
    check('san_and_lot_preserved',lot('산12-3')[1]=='산12-3' and lot('12-3')[1]=='12-3')
    check('blank_and_BL_not_synthesized',lot('')[1] is None and lot('BL-1')[1] is None)
    check('lot_space_not_collapsed',lot('12 - 3')[1] is None)
    with c:
        for code in ['9900010100','9900020100']:c.execute('insert into aliases values(?,?,?,?,?,?,?,?,?)',('TEST 동',code,'TEST 동','TEST','A','동','','TEST',0))
    check('collision_not_resolved',len(lookup(c,'TEST 동')[1])==2)
    with c:c.execute("delete from aliases where province='TEST'")
    # Same transactional checkpoint contract as inherited pipeline.
    t=db(':memory:');t.execute('create table done(id primary key,n)');t.execute('insert into done values(1,2)');t.commit()
    try:
        with t:t.execute('insert into done values(2,3)');t.execute('insert into done values(1,9)')
    except sqlite3.IntegrityError:pass
    check('failed_unit_rolls_back_no_duplicate',t.execute('select sum(n) from done').fetchone()[0]==2);t.close()
    return passed

def initialize(out,g):
    cfg=p.config(g);oldcfg=b.read(OLD/'config.json');dc=b.read(p.P/'demand_config.json')
    master=ROOT/dc['legal_master'];binding=next(x for x in dc['bindings'] if x['path'].replace('\\','/')==dc['legal_master'].replace('\\','/'))
    b.need(b.lane.sha(master,g)==binding['sha256'],'LEGAL_MASTER_SHA')
    p.verify_final(OLD/'national/final_manifest.json',g)
    c=db(H/'normalization.sqlite');c.executescript('create table aliases(alias,code,full,province,county,dong,ri,rule,master_row);create index by_alias on aliases(alias);create table mapping(id primary key,province,source,lot,old_status,n,reason,lot_status,candidate_count,code,master_key,rule,payload);')
    parents=set()
    with master.open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['시도명']=='세종특별자치시' and r['읍면동명']:parents.add((r['시군구명'],r['법정동코드'][:5]))
    unique=parents=={('세종시','36110')};b.need(unique,'SEJONG_MASTER_PARENT_NOT_UNIQUE')
    with c,master.open(encoding='utf-8-sig',newline='') as f:
        for ordinal,r in enumerate(csv.DictReader(f),2):
            full=' '.join(r[k] for k in ['시도명','시군구명','읍면동명','리명'] if r[k])
            for alias,rule in aliases(r,unique):c.execute('insert into aliases values(?,?,?,?,?,?,?,?,?)',(alias,r['법정동코드'],full,r['시도명'],r['시군구명'],r['읍면동명'],r['리명'],rule,ordinal))
    lot=b.compile_pure(ROOT/dc['literal_selector'],{'transaction_jibun'})['transaction_jibun'];checks=tests(c,lot)
    src=db(p.P/'national_demand/demand.sqlite',True);rt=db(H/'routing.sqlite');rt.executescript('create table keys(id primary key,province,region_literal,lot,legal_codes,status,n);create table routes(id,object_id,primary key(id,object_id));create index region_keys on keys(province);create index object_routes on routes(object_id);')
    changed=Counter();reasons=Counter();failkeys=0;failn=0
    with c,rt:
        for row in src.execute('select * from keys order by id'):
            aid,prov,source,rawlot,codes,status,n=row;newrow=row
            if status!='EXACT_KEY_ELIGIBLE':
                failkeys+=1;failn+=n;ls,literal=lot(rawlot);matches,matchedcodes=lookup(c,source)
                reason='CURRENT_MASTER_NO_PROVEN_ALIAS';code='';full='';rule='';payload={'master_matches':matches,'derived_comparison_key':collapse(source),'source_preserved':True,'current_master_sha256':binding['sha256']}
                if not source:reason='MISSING_SOURCE_NAME'
                elif len(matchedcodes)>1:reason='NORMALIZED_CODE_COLLISION'
                elif len(matchedcodes)==1:
                    code=matchedcodes[0];chosen=matches[0];full=chosen[1];rule=chosen[6]
                    if literal is None:reason=ls
                    else:
                        reason=rule;objects=p.route(code,cfg['prefix_objects']);b.need(len(objects)==1,'NEW_REFERENCE_ROUTING_UNRESOLVED')
                        # Prior eligible keys never reach this branch; raw lot untouched.
                        b.need(status=='UNRESOLVED_LEGAL_NAME','UNEXPECTED_OLD_STATUS');b.need(prov!='부산광역시','BUSAN_NEW_ALIAS_REQUIRES_ADAPTER')
                        newrow=(aid,prov,source,rawlot,b.dump([code]),'EXACT_KEY_ELIGIBLE',n);rt.execute('insert into routes values(?,?)',(aid,objects[0]));changed[prov]+=n
                reasons[(reason,ls)]+=n
                c.execute('insert into mapping values(?,?,?,?,?,?,?,?,?,?,?,?,?)',(aid,prov,source,rawlot,status,n,reason,ls,len(matchedcodes),code,full,rule,b.dump(payload)))
            if prov!='부산광역시':rt.execute('insert into keys values(?,?,?,?,?,?,?)',newrow)
    b.need((failkeys,failn)==(7976,4785579),'FAILED_SCOPE_DRIFT')
    # Seed exact completed rows without touching payload, geometries or counts.
    reused=0;removed=0;points=db(H/'prior_points.sqlite');points.execute('create table points(pnu,set_id,ordinal,payload,primary key(pnu,set_id,ordinal))')
    for region in cfg['regions']:
        olddir=OLD/'regions'/cfg['region_ids'][region];work=p.region_dir(region,cfg);work.mkdir(parents=True,exist_ok=True)
        m=p.verify_final(olddir/'final_manifest.json',g)
        old=db(olddir/'regional.sqlite',True)
        with points:
            for text, in old.execute("select payload from results where status='ASSIGNED'"):
                x=json.loads(text);points.execute('insert or ignore into points values(?,?,?,?)',(x['pnu'],x['set_id'],x['ordinal'],text))
        if region not in changed:b.write(work/'final_manifest.json',m);old.close();continue
        target=db(work/'regional.sqlite')
        target.execute('create table results(id primary key,status,n,payload)')
        with target:
            for r in old.execute('select * from results'):
                if rt.execute('select 1 from routes where id=?',(r[0],)).fetchone():b.need(r[1]=='UNLINKED_NAME_OR_JIBUN','SUCCESS_REWRITE_FORBIDDEN');removed+=1
                else:target.execute('insert into results values(?,?,?,?)',r);reused+=1
        old.close();target.close();g.checkpoint('prior_results_seeded_'+region)
    for oid, in rt.execute('select distinct object_id from routes'):
        work=p.object_dir(oid);work.mkdir(parents=True,exist_ok=True);prior=OLD/'objects'/oid/'members.json'
        if prior.exists():b.write(work/'members.json',b.read(prior))
    p.table(out/'failure_diagnosis.csv',['reason','lot_status','address_keys','occurrences'],c.execute('select reason,lot_status,count(*),sum(n) from mapping group by 1,2 order by 4 desc'),g)
    p.table(out/'explicit_mapping.csv',['id','province','source','lot','old_status','occurrences','reason','lot_status','candidate_codes','code','master_key','rule','evidence'],c.execute('select * from mapping order by province,source,lot'),g)
    b.write(out/'tests.json',dict(passed=checks,master_parent_set=sorted(parents),raw_source_or_lot_mutated=False))
    count=rt.execute('select count(*) from routes').fetchone()[0];rt.close();src.close();c.close();points.close()
    artifacts=[dict(path=str(x),sha256=b.lane.sha(x,g)) for x in [H/'normalization.sqlite',H/'prior_points.sqlite',out/'tests.json',out/'explicit_mapping.csv',out/'failure_diagnosis.csv']]
    return dict(status='INITIALIZED',failed_keys=failkeys,failed_occurrences=failn,eligible_new_keys=count,eligible_new_occurrences=sum(changed.values()),changed_regions=dict(changed),old_results_reused=reused,only_failed_results_replaced=removed,tests_passed=len(checks),derived_artifacts=artifacts)

def config(g=None):
    cfg=BASE_CONFIG(g);final=H/'initialization/final_manifest.json'
    if final.exists():
        m=p.verify_final(final,g)
        for x in m['result']['derived_artifacts']:b.need(b.lane.sha(Path(x['path']),g)==x['sha256'],'DERIVED_BINDING_DRIFT')
    return cfg

class Saved(BASE_SAVED):
    def __init__(self,cfg,g):
        super().__init__(cfg,g);self.prior=db(H/'prior_points.sqlite',True)
    def get(self,pnu,sid,ordinal):
        # Restrict to matching region/set; old successful point remains source-bound.
        row=self.prior.execute('select payload from points where pnu=? and set_id=? and ordinal=?',(pnu,sid,ordinal)).fetchone()
        if row:
            x=json.loads(row[0]);return dict(x=x['source_x'],y=x['source_y'],CRS=x['source_CRS'],geometry_wkb_sha256=x['geometry_wkb_sha256'])
        return super().get(pnu,sid,ordinal)
    def close(self):
        self.prior.close()
        super().close()

p.initialize=initialize
p.Saved=Saved
p.config=config
if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('mode',choices=['run','worker']);q.add_argument('--stage');q.add_argument('--key',default='');q.add_argument('--out',type=Path);a=q.parse_args()
    if a.mode=='worker':p.worker(a.stage,a.key,a.out.resolve())
    else:p.run_all()
