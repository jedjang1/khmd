"""Read existing aggregate CSVs only; immutable, exclusive new output directory."""
import csv,json,hashlib,sys,os,time,math,sqlite3
from pathlib import Path
from collections import Counter,defaultdict
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'src/khmd_reference_resource_monitor_v0_2.py').exists())
sys.path.insert(0,str(ROOT/'src'))
import khmd_reference_resource_monitor_v0_2 as resource
PANEL=HERE.parent/'csv_observation_panel_v0_1/panel'
FIELDS=['input_n','assigned_n','unassigned_n','name_lot_n','no_parcel_n','ambiguous_n','geometry_failed_n','other_unassigned_n']
LABELS={'강원특별자치도':'Gangwon','경기도':'Gyeonggi','경상남도':'Gyeongnam','경상북도':'Gyeongbuk','대구광역시':'Daegu','대전광역시':'Daejeon','서울특별시':'Seoul','세종특별자치시':'Sejong','부산광역시':'Busan','울산광역시':'Ulsan','인천광역시':'Incheon','전북특별자치도':'Jeonbuk','전라남도':'Jeonnam','전남광주통합특별시':'Jeonnam-Gwangju (query)','제주특별자치도':'Jeju','충청남도':'Chungnam','충청북도':'Chungbuk'}
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,v):
 with Path(p).open('x',encoding='utf8') as f:json.dump(v,f,ensure_ascii=False,indent=2)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def table(p,rows,fields=None):
 rows=iter(rows);first=next(rows,None)
 if fields is None:fields=list(first or {})
 with Path(p).open('x',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
  if first is not None:w.writerow(first)
  w.writerows(rows)
def quantile(hist,p):
 n=sum(hist.values());h=(n-1)*p;lo=math.floor(h);hi=math.ceil(h);a=b=None;s=0
 for v,c in sorted(hist.items()):
  if a is None and s+c>lo:a=v
  if s+c>hi:b=v;break
  s+=c
 return a+(b-a)*(h-lo)
def worker(out):
 start=time.monotonic();g=resource.ReferenceGuard(ROOT);g.admit();g.reserve_output(30000000)
 out.mkdir();m=read(PANEL/'release_manifest.json')
 expected={'release_manifest.json':'9bd282046282d6d1e304e793291f1c63f81de0332781ad2b0123c4f94f49ad96','panel_counts.csv':'cf4ee45415a0040d37ebe7a0c1a87293d7a2c8efda471ef0664f2f879245165b','query_region_quarter_quality.csv':'a273fc95d17efe56c80950b3e5999a38e2ae4c959959d7b300fccbb6daf189f0'}
 for name,digest in expected.items():assert sha(PANEL/name)==digest,name
 assert m['grid_version']=='KHMD_UTMK_1KM_V1'
 dims={'region_year_family':('query_region','year','transaction_family'),'region_family':('query_region','transaction_family'),'year_family':('year','transaction_family'),'family':('transaction_family',),'national':()}
 sums={k:defaultdict(lambda:[0]*len(FIELDS)) for k in dims};seen=set();quality_n=0;reasons=[]
 with (PANEL/'query_region_quarter_quality.csv').open(encoding='utf-8-sig',newline='') as f:
  for row in csv.DictReader(f):
   key=(row['query_region'],row['quarter'],row['transaction_family']);assert key not in seen;seen.add(key)
   row['year']=int(row['quarter'][:4]);v=[int(row[x]) for x in FIELDS]
   assert v[0]==v[1]+v[2] and v[2]==sum(v[3:]);quality_n+=1
   for name,columns in dims.items():
    target=sums[name][tuple(row[c] for c in columns)]
    for i,n in enumerate(v):target[i]+=n
   if quality_n%100==0:g.checkpoint('quality_rows_'+str(quality_n))
 for name,groups in sums.items():
  rows=[]
  for key,v in sorted(groups.items()):
   r=dict(zip(dims[name],key));r.update(zip(FIELDS,v));r['assignment_rate']=v[1]/v[0] if v[0] else 'NA';r['denominator_status']='POSITIVE_INPUT' if v[0] else 'ZERO_INPUT'
   if 'query_region' in r:r['region_label']=LABELS.get(r['query_region'],r['query_region'])
   rows.append(r)
  table(out/(name+'.csv'),rows)
 total=sums['national'][()];assert total==[20916100,20403079,513021,37680,215426,232482,27433,0],total
 assert quality_n==1920 and len(sums['region_year_family'])==480
 for name in ('national','family','region_year_family'):
  for key,v in sorted(sums[name].items()):
   for i,reason in enumerate(FIELDS[3:],3):
    r={'aggregation':name,**dict(zip(dims[name],key)),'reason':reason,'n_obs':v[i],'input_n':v[0],'unassigned_n':v[2],'share_of_input':v[i]/v[0] if v[0] else 'NA','share_of_unassigned':v[i]/v[2] if v[2] else 'NA'};reasons.append(r)
 table(out/'unassigned_reasons.csv',reasons,['aggregation','query_region','year','transaction_family','reason','n_obs','input_n','unassigned_n','share_of_input','share_of_unassigned'])
 hist=defaultdict(Counter);panel_n=0;panel_sum=0;previous=None
 # Existing panel is ordered by primary key; validate adjacent uniqueness without a large set.
 with (PANEL/'panel_counts.csv').open(encoding='utf-8-sig',newline='') as f:
  for row in csv.DictReader(f):
   key=(row['grid_id'],row['quarter'],row['transaction_family']);assert previous is None or key>previous,('PANEL_ORDER_OR_DUPLICATE',key);previous=key
   n=int(row['n_obs']);assert n>0
   hist[('ALL','ALL')][n]+=1;hist[(row['transaction_family'],'ALL')][n]+=1;hist[(row['transaction_family'],row['quarter'][:4])][n]+=1
   panel_n+=1;panel_sum+=n
   if panel_n%10000==0:g.checkpoint('panel_groups_'+str(panel_n))
 assert panel_n==571310 and panel_sum==total[1]
 summaries=[];freq=[]
 for (family,year),h in sorted(hist.items()):
  ng=sum(h.values());no=sum(k*v for k,v in h.items());small=sum(v for k,v in h.items() if k<5);smallobs=sum(k*v for k,v in h.items() if k<5)
  r=dict(transaction_family=family,year=year,n_groups=ng,n_obs=no,min_n=min(h),max_n=max(h),mean_n=no/ng,groups_n1=h[1],groups_n2_4=small-h[1],groups_n5plus=ng-small,groups_n_lt5=small,group_share_n_lt5=small/ng,n_obs_in_groups_lt5=smallobs,observation_share_in_groups_lt5=smallobs/no)
  for q in (.25,.5,.75,.9,.95,.99):r['p'+str(int(q*100))]=quantile(h,q)
  summaries.append(r)
  for n,count in sorted(h.items()):freq.append(dict(transaction_family=family,year=year,n_obs_per_group=n,n_groups=count,observations=n*count))
 table(out/'panel_distribution.csv',summaries);table(out/'panel_frequency.csv',freq)
 # Only registered file metadata (480 small records). Never read observations/raw CSV.
 source=read(m['source_release']['path']);assert sha(m['source_release']['path'])==m['source_release']['sha256'];schema=Counter();obs=Counter();files=[]
 for i,item in enumerate(source['active_files']):
  assert item['selected']
  with sqlite3.connect(Path(item['store']).as_uri()+'?mode=ro',uri=True) as con:
   con.execute('PRAGMA cache_size=-512');record=con.execute('SELECT metadata FROM files WHERE sha=?',(item['file_sha256'],)).fetchone()
  assert record is not None;meta=json.loads(record[0]);family=item['query']['family']
  for field in meta['columns']:schema[(family,field)]+=1
  for entry in meta.get('observability',[]):obs[(family,entry['field'],entry['state'])]+=entry['n']
  files.append({'file_sha256':item['file_sha256'],'transaction_family':family,'query_region':item['query']['province'],'metadata_store':item['store'],'columns':json.dumps(meta['columns'],ensure_ascii=False)})
  if i%20==0:g.checkpoint('metadata_records_'+str(i+1))
 table(out/'source_field_inventory.csv',[dict(transaction_family=f,field=k,selected_files_with_field=v) for (f,k),v in sorted(schema.items())])
 table(out/'source_field_observability.csv',[dict(transaction_family=f,field=k,state=s,n_obs=v) for (f,k,s),v in sorted(obs.items())])
 table(out/'selected_file_schema.csv',files)
 check=ROOT/'experiments/khmd_r_csv_release_v0_3/check_tools/user_run_20261028_080606_469/run_status.json';status=read(check);assert status['check_counts']=={'ERROR':0,'WARNING':0,'NOTE':0}
 provenance=[{'path':str(PANEL/n),'sha256':v,'role':'immutable existing aggregate/manifest'} for n,v in expected.items()]
 provenance.extend([{'path':str(check),'sha256':sha(check),'role':'reused successful khmd 0.0.3 nonadmin check; not rerun'},{'path':m['source_release']['path'],'sha256':m['source_release']['sha256'],'role':'selected CSV release, immutable'}])
 write(out/'input_manifest.json',{'inputs':provenance,'grid':m['grid'],'reference_snapshot':m['reference_snapshot'],'regional_reference_sources':m['regional_reference_sources'],'source_release':m['source_release'],'spatial_result':m['spatial_result'],'check_options':['--no-manual','--no-build-vignettes']})
 result={'status':'PASS','quality_rows':quality_n,'region_year_family_rows':480,'panel_groups':panel_n,'input_n':total[0],'assigned_n':total[1],'unassigned_n':total[2],'assignment_rate':total[1]/total[0],'absence_policy':'no absent combinations imputed; zero denominator NA','small_n':'n_obs<5 descriptive existing reporting band; not monetary-valid N or suppression','elapsed_seconds':time.monotonic()-start,'raw_reparse':0,'raw_SQL_aggregate':0,'price_calculation':0}
 write(out/'validation.json',result);receipt=g.publication_gate();write(Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY'])/'worker_resource_receipt.json',receipt);g.reader.close();print(json.dumps(result))
if __name__=='__main__':
 if sys.argv[1]=='worker':worker(Path(sys.argv[2]))
 else:
  out=Path(sys.argv[1]).resolve();r=resource.supervise([sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'worker',str(out)],str(ROOT),dict(os.environ),out.parent/(out.name+'_supervisor'));print(json.dumps(r));sys.exit(0 if r['status']=='COMPLETE' else 1)
