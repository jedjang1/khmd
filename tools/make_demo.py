"""Deterministic, wholly synthetic five-occurrence example; no real data reads."""
import sqlite3,json,hashlib,sys
from pathlib import Path
def put(p,x):
 with p.open('x',encoding='utf8') as f:json.dump(x,f,indent=2,sort_keys=True)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def seal(p):
 with p.open('rb') as f:b=[hashlib.sha256(x).hexdigest() for x in iter(lambda:f.read(1048576),b'')]
 return {'algorithm':'sha256','bytes':p.stat().st_size,'chunk_bytes':1048576,'chunk_sha256':b}
def make(root,g=None):
 root=Path(root);root.mkdir();v='KHMD_UTMK_1KM_V1';gid=v+':1000:2000';grid={'version':v,'CRS':'EPSG:5179','xy':'easting,northing','origin':[0,0],'spacing_metres':1000}
 for n in ['source','spatial']:put(root/(n+'.json'),{'schema':'SYNTHETIC_EXAMPLE_ONLY','role':n,'actual_transactions':0})
 refs={n:{'path':name+'.json','sha256':digest(root/(name+'.json'))} for n,name in [('source_release','source'),('spatial_result','spatial')]}
 common={'grid_version':v,'grid':grid,**refs,'source_release_sha256':refs['source_release']['sha256'],'spatial_manifest_sha256':refs['spatial_result']['sha256'],'example_only':True,'input_occurrences':5,'assigned':5,'unassigned':0,'reference_snapshot':'SYNTHETIC_NO_REAL_GEOMETRY'}
 # Two repeated SALE observations; RENT: explicit JEONSE0, MONTHLY_RENT10, UNKNOWN missing.
 put(root/'synthetic_observations.json',{'synthetic':True,'records':[{'family':'SALE','amount':'100','area':'10'},{'family':'SALE','amount':'100','area':'20'},{'family':'RENT','subtype':'JEONSE','deposit':'1000','monthly':'0'},{'family':'RENT','subtype':'MONTHLY_RENT','deposit':'0','monthly':'10'},{'family':'RENT','subtype':'UNKNOWN','deposit':None,'monthly':None}],'not_unique_transaction_identifiers':True})
 doc={**common,'schema':'KHMD_OBSERVATION_PANEL_V1','unit':'observation_occurrence','sparse':'true','database':'counts.sqlite','panel_groups':2,'quality_groups':2}
 con=sqlite3.connect(root/'counts.sqlite');con.execute('create table metadata(key text primary key,value text)')
 for k in ['schema','unit','sparse','grid_version','source_release_sha256','spatial_manifest_sha256']:con.execute('insert into metadata values(?,?)',(k,doc[k]))
 con.execute('create table panel(grid_id text,quarter text,transaction_family text,n_obs integer,primary key(grid_id,quarter,transaction_family))')
 con.executemany('insert into panel values(?,?,?,?)',[(gid,'2025Q1','SALE',2),(gid,'2025Q1','RENT',3)])
 con.execute('create table quality(query_region text,quarter text,transaction_family text,input_n integer,assigned_n integer,unassigned_n integer,name_jibun_n integer,no_candidate_n integer,ambiguous_n integer,geometry_failure_n integer,other_n integer,assignment_rate real)')
 for fam,n in [('SALE',2),('RENT',3)]:con.execute('insert into quality values(?,?,?,?,?,?,?,?,?,?,?,?)',('Synthetic region','2025Q1',fam,n,n,0,0,0,0,0,0,1.0))
 con.commit();con.close();doc['database_integrity']=seal(root/'counts.sqlite');doc['database_sha256']=digest(root/'counts.sqlite');put(root/'count_release.json',doc)
 d={**common,'schema':'KHMD_PRICE_PANEL_V1','unit':'reported_observation_value_statistics','database':'price.sqlite','count_release':{'path':'count_release.json','sha256':digest(root/'count_release.json')},'count_release_sha256':digest(root/'count_release.json')}
 con=sqlite3.connect(root/'price.sqlite');con.execute('create table metadata(key text primary key,value text)')
 for k in ['schema','unit','grid_version','source_release_sha256','spatial_manifest_sha256','count_release_sha256']:con.execute('insert into metadata values(?,?)',(k,d[k]))
 con.execute('create table statistics(grid_id text,quarter text,transaction_family text,rent_subtype text,metric text,unit text,n_obs integer,n_valid integer,n_excluded integer,q25 text,median text,q75 text,primary key(grid_id,quarter,transaction_family,rent_subtype,metric))')
 rows=[('SALE','ALL','sale_amount','KRW_10K',2,2,0,'100','100','100'),('SALE','ALL','sale_amount_m2','KRW_10K_PER_M2',2,2,0,'6.25','7.5','8.75')]
 for sub,n,nv,dep,mon in [('ALL',3,2,('250','500','750'),('2.5','5','7.5')),('JEONSE',1,1,('1000',)*3,('0',)*3),('MONTHLY_RENT',1,1,('0',)*3,('10',)*3),('UNKNOWN',1,0,(None,)*3,(None,)*3)]:
  for metric,unit,qs in [('deposit','KRW_10K',dep),('monthly_rent','KRW_10K_PER_MONTH',mon)]:rows.append(('RENT',sub,metric,unit,n,nv,n-nv,*qs))
 con.executemany('insert into statistics values('+','.join('?'*12)+')',[(gid,'2025Q1',*r) for r in rows])
 con.execute('create table metric_totals as select transaction_family,rent_subtype,metric,unit,count(*) n_groups,sum(n_obs) n_obs,sum(n_valid) n_valid,sum(n_excluded) n_excluded from statistics group by 1,2,3,4');con.commit();con.close()
 d['database_integrity']=seal(root/'price.sqlite');d['database_sha256']=digest(root/'price.sqlite');put(root/'price_release.json',d)
 if g:g.checkpoint('synthetic_example_created')
if __name__=='__main__':make(sys.argv[1])
