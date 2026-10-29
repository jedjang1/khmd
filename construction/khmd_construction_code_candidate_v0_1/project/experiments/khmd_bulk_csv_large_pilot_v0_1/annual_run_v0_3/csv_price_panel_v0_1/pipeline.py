"""Versioned CSV reported-value statistics. No raw CSV or geometry reads."""
import sys,os,json,csv,hashlib,sqlite3,time,itertools,traceback
from pathlib import Path
from collections import Counter,defaultdict
from decimal import Decimal,InvalidOperation
from fractions import Fraction
H=Path(__file__).resolve().parent;B=H.parent;ROOT=H.parents[3]
sys.path.insert(0,str(ROOT/'src'))
import khmd_reference_resource_monitor_v0_2 as resource
from khmd_aggregation_metric_contract_v0_1 import _quantile_fraction,_decimal_fraction,metric_small_n_status
COUNT=B/'csv_observation_panel_v0_1/panel/release_manifest.json'
DEMAND=B/'csv_regional_demand_v0_1/national_demand/demand.sqlite'
MONEY={'SALE':['거래금액(만원)','전용면적(㎡)'],'RENT':['보증금(만원)','월세금(만원)']}
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,x):
 with Path(p).open('x',encoding='utf8') as f:json.dump(x,f,ensure_ascii=False,indent=2)
def sha(p,g=None):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for i,v in enumerate(iter(lambda:f.read(1024*1024),b'')):
   h.update(v)
   if g and i%32==0:g.checkpoint('sha_'+Path(p).name+'_'+str(i))
 return h.hexdigest()
def dump(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def db(p,ro=False):
 c=sqlite3.connect(Path(p).resolve().as_uri()+'?mode=ro' if ro else str(p),uri=ro)
 c.execute('pragma cache_size=-2048');c.execute('pragma mmap_size=0');c.execute('pragma temp_store=FILE')
 if not ro:c.execute('pragma synchronous=FULL');c.execute('pragma journal_mode=DELETE')
 return c
def table(p,header,rows):
 with Path(p).open('x',encoding='utf-8-sig',newline='') as f:w=csv.writer(f);w.writerow(header);w.writerows(rows)
def binding():
 m=read(COUNT);assert sha(COUNT)=='9bd282046282d6d1e304e793291f1c63f81de0332781ad2b0123c4f94f49ad96'
 for k in ('source_release','spatial_result'):assert sha(m[k]['path'])==m[k]['sha256']
 return m
def initialize(out,g):
 m=binding();out.mkdir();g.reserve_output(20*1024**3)
 paths=[];maps=db(out/'spatial_lookup.sqlite');maps.execute('create table mapping(province,region_literal,lot,id primary key,status,grid_id,n)');maps.execute('create unique index address on mapping(province,region_literal,lot)')
 d=db(DEMAND,True)
 for rec in m['regional_reference_sources']:
  province=rec['query_region'];path=Path(rec['aggregate_source'])
  if province=='부산광역시':
   path=B/'csv_spatial_5179_busan_v0_2/busan_run/spatial.sqlite'
   bm=read(B/'csv_spatial_5179_busan_v0_3/busan_run/final_manifest.json');pin=next(x for x in bm['artifacts'] if Path(x['path'])==path)['sha256']
  else:pin=rec['sha256']
  assert sha(path,g)==pin,('SPATIAL_SHA',path);paths.append({'path':str(path),'sha256':pin,'query_region':province})
  s=db(path,True);identifier='address_id' if province=='부산광역시' else 'id'
  for aid,status,n,payload in s.execute('select '+identifier+',status,n,payload from results'):
   old=d.execute('select province,region_literal,lot,n from keys where id=?',(aid,)).fetchone();assert old and old[0]==province and old[3]==n
   gid=json.loads(payload).get('grid_id','') if status=='ASSIGNED' else ''
   assert status!='ASSIGNED' or gid.startswith(m['grid_version']+':')
   maps.execute('insert into mapping values(?,?,?,?,?,?,?)',(*old[:3],aid,status,gid,n))
  s.close();maps.commit();g.checkpoint('inherited_spatial_'+province)
 assert maps.execute('select count(*),sum(n) from mapping').fetchone()==(47676,20916100)
 assert maps.execute("select sum(n) from mapping where status='ASSIGNED'").fetchone()[0]==20403079
 maps.close();d.close()
 cfg={'schema':'KHMD_CSV_PRICE_POLICY_V1','source_release':m['source_release'],'spatial_result':m['spatial_result'],'count_release':{'path':str(COUNT),'sha256':sha(COUNT)},'spatial_sources':paths,'lookup_sha256':sha(out/'spatial_lookup.sqlite'),'code_sha256':sha(__file__),'quantile_source':{'path':str(ROOT/'src/khmd_aggregation_metric_contract_v0_1.py'),'sha256':sha(ROOT/'src/khmd_aggregation_metric_contract_v0_1.py')},'grid_version':m['grid_version'],'unit':'reported_observation_value_statistics','money_unit':'KRW_10K_NOMINAL','sale_ratio_unit':'KRW_10K_PER_M2','quantile':'HF7 exact rational interpolation, final Decimal50 ROUND_HALF_EVEN','cancellation_policy':'RETAIN_ALL_REPORTED_OCCURRENCES; observed flag/date not a correction linkage','rent_subtype':'exact CSV literal 전세=JEONSE; 월세=MONTHLY_RENT; all others UNKNOWN with raw literal/state retained','missing':'no zero imputation; finite money includes signed and explicit zero; area finite>0 for ratio','sparse':True,'scope':'Current user authorization for CSV descriptive statistics, not historical API execution authority'}
 write(out/'config.json',cfg);return {'status':'INITIALIZED','keys':47676}
def valid(value,state):
 if state not in ('VALUE','EXPLICIT_ZERO'):return None,('MISSING_'+str(state))
 if value is None:return None,'INVALID_PARSE'
 try:d=Decimal(str(value))
 except (InvalidOperation,ValueError):return None,'INVALID_PARSE'
 if not d.is_finite():return None,'INVALID_NONFINITE'
 return str(d),'VALID'
def subtype(raw):return 'JEONSE' if raw=='전세' else 'MONTHLY_RENT' if raw=='월세' else 'UNKNOWN'
def stage_schema(c):
 c.executescript('''create table if not exists files(id integer primary key,sha text unique,province,family,expected integer,last_ordinal integer default 0,processed integer default 0,assigned integer default 0,complete integer default 0,metadata_sha);
 create table if not exists facts(file_id integer,ordinal integer,grid_id text,quarter text,family text,subtype text,subtype_raw text,subtype_state text,v1 text,v2 text,e1 text,e2 text,cancel_state text,primary key(file_id,ordinal));
 create table if not exists chunks(file_id,first_ordinal,last_ordinal,n,assigned,digest,primary key(file_id,first_ordinal));
 create table if not exists weights(file_id,key_id,quarter,row_status,n,primary key(file_id,key_id,quarter,row_status));
 create table if not exists states(file_id,field,raw_state,raw_literal,n,primary key(file_id,field,raw_state,raw_literal));
 create table if not exists meta(key primary key,value);''')
def ingest(out,g,pause=None):
 cfg=read(out/'config.json');assert sha(__file__)==cfg['code_sha256'];m=binding();assert sha(out/'spatial_lookup.sqlite',g)==cfg['lookup_sha256'];release=read(m['source_release']['path'])
 c=db(out/'stage.sqlite');stage_schema(c);pin=sha(out/'config.json');old=c.execute("select value from meta where key='binding'").fetchone()
 if old:assert old[0]==pin
 else:c.execute('insert into meta values(?,?)',('binding',pin));c.commit()
 d=db(DEMAND,True);maps=db(out/'spatial_lookup.sqlite',True);new=0;region=None;lookup={};beg=time.monotonic()
 for item in sorted(release['active_files'],key=lambda x:(x['query']['province'],x['query']['family'],x['query']['date_from'])):
  digest=item['file_sha256'];q=item['query'];assert item['selected'];family=q['family'];file=c.execute('select * from files where sha=?',(digest,)).fetchone()
  if file and file[8]:continue
  if region!=q['province']:
   region=q['province'];lookup={(r,l):(aid,s,gid) for r,l,aid,s,gid in maps.execute('select region_literal,lot,id,status,grid_id from mapping where province=?',(region,))}
  src=db(item['store'],True);src.execute('BEGIN');meta,expected,good,errors=src.execute('select metadata,input_rows,good_rows,error_rows from files where sha=?',(digest,)).fetchone();meta_hash=hashlib.sha256(meta.encode()).hexdigest();prior=d.execute('select metadata_sha,input_rows,complete from files where sha=?',(digest,)).fetchone();assert prior==(meta_hash,expected,1) and good==expected and errors==0
  metadata=json.loads(meta);cols=metadata['columns'];idx={k:i for i,k in enumerate(cols)}
  assert all(k in idx for k in MONEY[family]+['번지'])
  if not file:
   with c:c.execute('insert into files(sha,province,family,expected,metadata_sha) values(?,?,?,?,?)',(digest,region,family,expected,meta_hash))
   file=c.execute('select * from files where sha=?',(digest,)).fetchone()
  assert file[9]==meta_hash;fid=file[0];last=file[5]
  while True:
   batch=src.execute('select ordinal,obs_id,raw_values,states,derived,row_status from observations where file_sha=? and ordinal>? order by ordinal limit 1000',(digest,last)).fetchall()
   if not batch:break
   facts=[];weights=Counter();states=Counter();h=hashlib.sha256();first=last+1
   for ordinal,oid,rv,st,der,rowstatus in batch:
    assert ordinal==last+1;last=ordinal;raw=json.loads(rv);state=json.loads(st);derived=json.loads(der);ym=derived.get('contract_month');quarter=ym[:4]+'Q'+str((int(ym[4:])-1)//3+1) if ym and len(ym)==6 and 1<=int(ym[4:])<=12 else 'UNASSIGNABLE_PERIOD'
    aid,status,gid=lookup[(derived['csv_region_literal'],raw[idx['번지']])];weights[(fid,aid,quarter,rowstatus)]+=1
    h.update((dump([ordinal,oid,rv,st,der,rowstatus])+'\n').encode())
    if status!='ASSIGNED' or quarter=='UNASSIGNABLE_PERIOD' or rowstatus!='PARSED':continue
    numeric=derived['numeric'];vals=[valid(numeric.get(k),state[idx[k]]) for k in MONEY[family]]
    sr=raw[idx['전월세구분']] if family=='RENT' else '';ss=state[idx['전월세구분']] if family=='RENT' else 'NOT_APPLICABLE';sub=subtype(sr) if family=='RENT' else 'NOT_APPLICABLE';cancel=state[idx['해제사유발생일']] if family=='SALE' else 'NOT_APPLICABLE'
    facts.append((fid,ordinal,gid,quarter,family,sub,sr,ss,vals[0][0],vals[1][0],vals[0][1],vals[1][1],cancel))
    for k in MONEY[family]:states[(fid,k,state[idx[k]],'')]+=1
    states[(fid,'전월세구분',ss,sr)]+=1;states[(fid,'해제사유발생일',cancel,'')]+=1
   commit_chunk(c,fid,first,last,len(batch),facts,weights,states,h.hexdigest())
   new+=len(batch);g.checkpoint('committed_'+digest[:8]+'_'+str(last))
   if pause and new>=pause:src.close();maps.close();d.close();c.close();return {'status':'INTENTIONAL_PAUSE','new_rows':new}
  assert c.execute('select processed from files where id=?',(fid,)).fetchone()[0]==expected
  got={(a,b,c0):n for a,b,c0,n in c.execute('select key_id,quarter,row_status,n from weights where file_id=?',(fid,))};want={(a,b,c0):n for a,b,c0,n in d.execute('select key_id,quarter,row_status,n from weights where file_sha=?',(digest,))};assert got==want,'SPATIAL_WEIGHT_MISMATCH'
  with c:c.execute('update files set complete=1 where id=?',(fid,))
  src.close();print(dump({'file_complete':digest,'region':region,'family':family,'period':q['date_from'],'rows':expected,'new_rows':new,'elapsed':time.monotonic()-beg}),flush=True)
 assert c.execute('select count(*),sum(processed),sum(assigned),sum(complete) from files').fetchone()==(480,20916100,20403079,480)
 c.set_progress_handler(lambda:(g.checkpoint('building_global_group_index') and 0),1000000)
 c.execute('create index if not exists group_index on facts(grid_id,quarter,family)');c.commit();c.close();maps.close();d.close()
 return {'status':'INGEST_COMPLETE','new_rows':new,'elapsed_seconds':time.monotonic()-beg}
def commit_chunk(c,fid,first,last,n,facts,weights,states,digest,fail=False):
 try:
  c.execute('BEGIN IMMEDIATE');c.executemany('insert into facts values('+','.join('?'*13)+')',facts)
  c.executemany('insert into weights values(?,?,?,?,?) on conflict(file_id,key_id,quarter,row_status) do update set n=n+excluded.n',[(*k,v) for k,v in weights.items()])
  c.executemany('insert into states values(?,?,?,?,?) on conflict(file_id,field,raw_state,raw_literal) do update set n=n+excluded.n',[(*k,v) for k,v in states.items()])
  c.execute('insert into chunks values(?,?,?,?,?,?)',(fid,first,last,n,len(facts),digest));c.execute('update files set last_ordinal=?,processed=processed+?,assigned=assigned+? where id=?',(last,n,len(facts),fid))
  if fail:raise RuntimeError('INJECTED_BEFORE_COMMIT')
  c.commit()
 except BaseException:c.rollback();raise
def quantiles(values):
 if not values:return (None,None,None)
 ordered=sorted(values);n=len(ordered);ans=[]
 for p0 in (Fraction(1,4),Fraction(1,2),Fraction(3,4)):
  h=(n-1)*p0;j=h.numerator//h.denominator;v=ordered[j]+(h-j)*(ordered[min(j+1,n-1)]-ordered[j]);ans.append(format(_decimal_fraction(v),'f'))
 return tuple(ans)
def metric_rows(key,records):
 gid,q,fam=key;levels={'ALL':records}
 if fam=='RENT':
  for subtype0 in sorted(set(r[0] for r in records)):levels[subtype0]=[r for r in records if r[0]==subtype0]
 for level,recs in levels.items():
  metrics=['sale_amount','sale_amount_m2'] if fam=='SALE' else ['deposit','monthly_rent']
  for mi,metric in enumerate(metrics):
   values=[];excluded=Counter();explicit0=negative=cancel=conflict=0
   for sub,rawsub,substate,v1,v2,e1,e2,cstate in recs:
    cancel+=int(cstate=='VALUE')
    if fam=='RENT' and e2=='VALID':conflict+=int((sub=='JEONSE' and Decimal(v2)!=0) or (sub=='MONTHLY_RENT' and Decimal(v2)==0))
    if fam=='SALE':
     if e1!='VALID':excluded['amount:'+e1]+=1;continue
     value=Fraction(Decimal(v1))
     if mi==1:
      if e2!='VALID':excluded['area:'+e2]+=1;continue
      if Decimal(v2)<=0:excluded['area:NONPOSITIVE']+=1;continue
      value/=Fraction(Decimal(v2))
    else:
     value0,error=(v1,e1) if mi==0 else (v2,e2)
     if error!='VALID':excluded['value:'+error]+=1;continue
     value=Fraction(Decimal(value0))
    values.append(value);explicit0+=int(value==0);negative+=int(value<0)
   nv=len(values);assert len(recs)==nv+sum(excluded.values())
   yield (gid,q,fam,level,metric,'KRW_10K_PER_M2' if metric=='sale_amount_m2' else 'KRW_10K_PER_MONTH' if metric=='monthly_rent' else 'KRW_10K',len(recs),nv,len(recs)-nv,explicit0,negative,*quantiles(values),metric_small_n_status(nv),dump(dict(excluded)),cancel,conflict)
HEADER=['grid_id','quarter','transaction_family','rent_subtype','metric','unit','n_obs','n_valid','n_excluded','n_explicit_zero','n_negative','q25','median','q75','small_n_status','exclusion_reasons','cancellation_date_observed_n','subtype_amount_discordance_n']
def aggregate(out,g,pause=None):
 cfg=read(out/'config.json');assert sha(__file__)==cfg['code_sha256'];src=db(out/'stage.sqlite',True);assert src.execute('select count(*),sum(complete) from files').fetchone()==(480,480)
 target=out/'price.sqlite';new=not target.exists();c=db(target)
 if new:
  c.execute('create table statistics('+','.join(x+(' integer' if x.startswith('n_') or x.endswith('_n') else ' text') for x in HEADER)+',primary key(grid_id,quarter,transaction_family,rent_subtype,metric))');c.execute('create table metadata(key primary key,value)');c.execute('create table checkpoint(id integer primary key check(id=1),last_grid,last_quarter,last_family,groups_n)');c.execute("insert into metadata values('binding',?)",(sha(out/'config.json'),));c.commit()
 assert c.execute("select value from metadata where key='binding'").fetchone()[0]==sha(out/'config.json')
 cp=c.execute('select last_grid,last_quarter,last_family,groups_n from checkpoint').fetchone();last=cp[:3] if cp else ('','','');n=cp[3] if cp else 0;newgroups=0;buffer=[]
 cur=src.execute('select grid_id,quarter,family,subtype,subtype_raw,subtype_state,v1,v2,e1,e2,cancel_state from facts where (grid_id,quarter,family)>(?,?,?) order by grid_id,quarter,family',last)
 for key,iterator in itertools.groupby(cur,lambda r:r[:3]):
  records=[r[3:] for r in iterator];assert len(records)<=100000,'GROUP_RESOURCE_REVIEW';buffer.extend(metric_rows(key,records));n+=1;newgroups+=1
  if newgroups%250==0:
   with c:
    c.executemany('insert into statistics values('+','.join('?'*len(HEADER))+')',buffer);c.execute('insert or replace into checkpoint values(1,?,?,?,?)',(*key,n))
   buffer=[];g.checkpoint('global_groups_committed_'+str(n));print('GROUPS='+str(n),flush=True) if n%25000==0 else None
   if pause and newgroups>=pause:c.close();src.close();return {'status':'INTENTIONAL_PAUSE','groups':n}
 if buffer:
  with c:c.executemany('insert into statistics values('+','.join('?'*len(HEADER))+')',buffer);c.execute('insert or replace into checkpoint values(1,?,?,?,?)',(*key,n))
 assert n==571310;c.close();src.close();return {'status':'AGGREGATE_COMPLETE','groups':n}
def execute(stage,work,pause=None):
 attempt=H/'runs'/(stage+'_'+time.strftime('%Y%m%dT%H%M%S'));attempt.parent.mkdir(exist_ok=True)
 cmd=[sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'worker',stage,str(work)]
 if pause:cmd.append(str(pause))
 r=resource.supervise(cmd,str(ROOT),dict(os.environ),attempt);print(dump(r));return r
if __name__=='__main__':
 if sys.argv[1]=='worker':
  g=resource.ReferenceGuard(ROOT);g.admit();stage=sys.argv[2];out=Path(sys.argv[3]);pause=int(sys.argv[4]) if len(sys.argv)>4 else None
  result=initialize(out,g) if stage=='init' else ingest(out,g,pause) if stage=='ingest' else aggregate(out,g,pause)
  work=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY']);write(work/'result.json',result);write(work/'worker_resource_receipt.json',g.publication_gate());g.reader.close()
 else:sys.exit(0 if execute(sys.argv[1],Path(sys.argv[2]),int(sys.argv[3]) if len(sys.argv)>3 else None)['status']=='COMPLETE' else 1)
