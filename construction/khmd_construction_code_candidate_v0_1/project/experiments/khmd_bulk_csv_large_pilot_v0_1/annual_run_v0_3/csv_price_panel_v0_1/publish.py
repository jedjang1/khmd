"""Validate new monetary aggregates and bind an external R-readable release."""
import pipeline as p
import os,sys,json,csv,time,hashlib,sqlite3
from pathlib import Path
from collections import Counter,defaultdict
from fractions import Fraction
from decimal import Decimal,localcontext,ROUND_HALF_EVEN
def direct_q(values):
 if not values:return (None,None,None)
 v=sorted(values);answers=[]
 for k in (1,2,3):
  numerator=(len(v)-1)*k;j,remainder=divmod(numerator,4)
  x=(v[j]*(4-remainder)+v[min(j+1,len(v)-1)]*remainder)/4
  with localcontext() as context:context.prec=50;context.rounding=ROUND_HALF_EVEN;answers.append(format(Decimal(x.numerator)/Decimal(x.denominator),'f'))
 return tuple(answers)
def sample_check(stage,prices,out,g):
 # Deterministic bounded sample: first nontrivial ratio groups and RENT cross-file groups.
 samples=prices.execute("select grid_id,quarter,transaction_family from statistics where metric='sale_amount_m2' and rent_subtype='ALL' and n_obs between 5 and 50 order by grid_id,quarter limit 6").fetchall()
 samples+=prices.execute("select grid_id,quarter,transaction_family from statistics where metric='monthly_rent' and rent_subtype='ALL' and n_obs between 5 and 50 order by grid_id desc,quarter limit 6").fetchall()
 stage.set_progress_handler(lambda:(g.checkpoint('bounded_cross_file_sample_search') and 0),1000000)
 cross_samples=stage.execute('select grid_id,quarter,family from facts group by grid_id,quarter,family having min(file_id)!=max(file_id) and count(*)<=500 limit 2').fetchall()
 samples+= [k for k in cross_samples if k not in samples]
 reports=[];source_cache={};compared_source=0;cross=0
 for key in samples:
  records=stage.execute('select file_id,ordinal,subtype,subtype_raw,subtype_state,v1,v2,e1,e2,cancel_state from facts where grid_id=? and quarter=? and family=? order by file_id,ordinal',key).fetchall()
  cross+=int(len({r[0] for r in records})>1)
  direct=[]
  for fid,ordinal,sub,sr,ss,v1,v2,e1,e2,cs in records:
   if fid not in source_cache:
    sha,store=stage.execute('select f.sha,x.store from files f join source_files x on f.id=x.id where f.id=?',(fid,)).fetchone();con=p.db(store,True);meta=json.loads(con.execute('select metadata from files where sha=?',(sha,)).fetchone()[0]);source_cache[fid]=(con,sha,meta['columns'])
   con,sha,cols=source_cache[fid];raw,states,derived=con.execute('select raw_values,states,derived from observations where file_sha=? and ordinal=?',(sha,ordinal)).fetchone();raw=json.loads(raw);states=json.loads(states);derived=json.loads(derived);compared_source+=1
   field=p.MONEY[key[2]];original=[derived['numeric'].get(x) for x in field]
   assert original==[v1,v2] and all(states[cols.index(x)] in ('VALUE','EXPLICIT_ZERO') for x in field)
   if key[2]=='RENT':assert raw[cols.index('전월세구분')]==sr and states[cols.index('전월세구분')]==ss
   direct.append((sub,original))
  for row in prices.execute('select rent_subtype,metric,n_obs,n_valid,q25,median,q75 from statistics where grid_id=? and quarter=? and transaction_family=?',key):
   level,metric,nobs,nvalid,*actual=row;chosen=[values for sub,values in direct if level=='ALL' or sub==level];vals=[]
   for a,b in chosen:
    if metric=='sale_amount_m2':vals.append(Fraction(Decimal(a))/Fraction(Decimal(b)))
    else:vals.append(Fraction(Decimal(b if metric=='monthly_rent' else a)))
   assert nobs==len(chosen) and nvalid==len(vals) and tuple(actual)==direct_q(vals)
  reports.append({'grid_id':key[0],'quarter':key[1],'family':key[2],'observations':len(records),'distinct_source_files':len({r[0] for r in records}),'status':'DIRECT_NORMALIZED_SOURCE_AND_INDEPENDENT_RATIONAL_PASS'})
  g.checkpoint('independent_actual_sample_'+str(len(reports)))
 for con,_,_ in source_cache.values():con.close()
 p.write(out/'direct_sample_validation.json',{'status':'PASS','groups':len(reports),'source_rows_read':compared_source,'cross_file_groups_in_sample':cross,'selection':'six SALE and six RENT n_obs5..50 plus first two cross-file groups <=500 if present; not random accuracy estimate','groups_checked':reports,'cross_file_synthetic_test':'small_tests/results.json'})
def publish(work,out,g):
 out.mkdir();start=time.monotonic();m=p.binding();cfg=p.read(work/'config.json');assert p.sha(p.__file__)==cfg['code_sha256'];assert p.sha(cfg['quantile_source']['path'])==cfg['quantile_source']['sha256']
 c=p.db(work/'price.sqlite');stage=p.db(work/'stage.sqlite');g.reserve_output(2*1024**3)
 # The file registry linkage is metadata only and does not reread observations nationally.
 stage.execute('create table if not exists source_files(id primary key,store)')
 release=p.read(m['source_release']['path']);stores={x['file_sha256']:x['store'] for x in release['active_files']}
 with stage:
  for fid,sha in stage.execute('select id,sha from files'):stage.execute('insert or ignore into source_files values(?,?)',(fid,stores[sha]))
 assert stage.execute('select count(*),sum(expected),sum(processed),sum(assigned),sum(complete) from files').fetchone()==(480,20916100,20916100,20403079,480)
 c.set_progress_handler(lambda:(g.checkpoint('publication_SQL_progress') and 0),1000000)
 c.execute('ATTACH DATABASE ? AS counts',(str(p.COUNT.parent/'panel.sqlite'),))
 assert c.execute("select count(*) from statistics where n_obs != n_valid+n_excluded or (n_valid=0 and (q25 is not null or median is not null or q75 is not null)) or (n_valid>0 and (q25 is null or median is null or q75 is null))").fetchone()[0]==0
 assert c.execute("select count(*) from counts.panel p left join statistics s on s.grid_id=p.grid_id and s.quarter=p.quarter and s.transaction_family=p.transaction_family and s.rent_subtype='ALL' and s.metric=case p.transaction_family when 'SALE' then 'sale_amount' else 'deposit' end where s.n_obs is null or s.n_obs!=p.n_obs").fetchone()[0]==0
 assert c.execute("select count(*) from statistics s left join counts.panel p on s.grid_id=p.grid_id and s.quarter=p.quarter and s.transaction_family=p.transaction_family where p.grid_id is null").fetchone()[0]==0
 assert c.execute("select count(*) from statistics s join statistics t using(grid_id,quarter,transaction_family,rent_subtype) where (s.metric='sale_amount' and t.metric='sale_amount_m2' or s.metric='deposit' and t.metric='monthly_rent') and s.n_obs!=t.n_obs").fetchone()[0]==0
 assert c.execute("select count(*) from (select grid_id,quarter,transaction_family,metric,sum(case when rent_subtype='ALL' then n_obs else -n_obs end) delta,sum(case when rent_subtype='ALL' then n_valid else -n_valid end) dv,sum(case when rent_subtype='ALL' then n_excluded else -n_excluded end) de from statistics where transaction_family='RENT' group by 1,2,3,4 having delta!=0 or dv!=0 or de!=0)").fetchone()[0]==0
 c.execute('DETACH DATABASE counts')
 c.execute('create table metric_totals as select transaction_family,rent_subtype,metric,unit,count(*) n_groups,sum(n_obs) n_obs,sum(n_valid) n_valid,sum(n_excluded) n_excluded,sum(n_explicit_zero) n_explicit_zero,sum(n_negative) n_negative,sum(cancellation_date_observed_n) cancellation_date_observed_n,sum(subtype_amount_discordance_n) subtype_amount_discordance_n from statistics group by transaction_family,rent_subtype,metric,unit')
 totals=c.execute('select * from metric_totals order by transaction_family,rent_subtype,metric').fetchall();columns=[x[1] for x in c.execute('pragma table_info(metric_totals)')];p.table(out/'metric_totals.csv',columns,totals)
 denom={(r[0],r[1],r[2]):r[5] for r in totals};assert denom[('SALE','ALL','sale_amount')]==8098310 and denom[('RENT','ALL','deposit')]==12304769
 sample_check(stage,c,out,g)
 reasons=Counter()
 for i,(metric,level,payload,nv,nz,neg,q25,median,q75) in enumerate(c.execute('select metric,rent_subtype,exclusion_reasons,n_valid,n_explicit_zero,n_negative,q25,median,q75 from statistics')):
  assert nz+neg<=nv
  if nv:assert Decimal(q25)<=Decimal(median)<=Decimal(q75)
  for reason,n in json.loads(payload).items():reasons[(metric,level,reason)]+=n
  if i%10000==0:g.checkpoint('quantile_order_checked_'+str(i))
 p.table(out/'exclusion_totals.csv',['metric','rent_subtype','reason','n'],[(*key,n) for key,n in sorted(reasons.items())])
 p.table(out/'raw_state_totals_assigned.csv',['family','field','state','raw_literal','n_obs'],stage.execute('select f.family,s.field,s.raw_state,s.raw_literal,sum(s.n) from states s join files f on s.file_id=f.id group by 1,2,3,4 order by 1,2,3,4'))
 p.table(out/'processed_files.csv',['file_id','sha256','query_region','family','input_n','assigned_n','unassigned_n','complete'],stage.execute('select id,sha,province,family,processed,assigned,processed-assigned,complete from files order by id'))
 p.table(out/'r_expected_sample.csv',p.HEADER,c.execute("select "+','.join(p.HEADER)+" from statistics where metric='sale_amount_m2' and quarter='2025Q1' and transaction_family='SALE' and rent_subtype='ALL' order by grid_id,quarter,transaction_family,rent_subtype,metric limit 5"))
 # Compare newly read subset states with existing registration summaries for visibility; no imputation.
 meta={'schema':'KHMD_PRICE_PANEL_V1','unit':'reported_observation_value_statistics','grid_version':m['grid_version'],'source_release_sha256':m['source_release']['sha256'],'spatial_manifest_sha256':m['spatial_result']['sha256'],'count_release_sha256':p.sha(p.COUNT)}
 with c:
  for k,v in meta.items():c.execute('insert into metadata values(?,?)',(k,v))
 nrows=c.execute('select count(*) from statistics').fetchone()[0];c.commit();c.close();stage.close()
 # Published database is already completed; exclusive manifest publishes only after all checks.
 path=work/'price.sqlite';blocks=[];whole=hashlib.sha256()
 with path.open('rb') as f:
  for i,block in enumerate(iter(lambda:f.read(1024*1024),b'')):
   whole.update(block);blocks.append(hashlib.sha256(block).hexdigest());g.checkpoint('sealed_DB_block_'+str(i))
 manifest={**meta,'source_release':m['source_release'],'spatial_result':m['spatial_result'],'count_release':cfg['count_release'],'grid':m['grid'],'reference_snapshot':m['reference_snapshot'],'regional_reference_sources':m['regional_reference_sources'],'database':str(path.resolve()),'database_sha256':whole.hexdigest(),'database_integrity':{'algorithm':'sha256','bytes':path.stat().st_size,'chunk_bytes':1048576,'chunk_sha256':blocks},'statistics_rows':nrows,'base_groups':571310,'input_occurrences':20916100,'assigned':20403079,'unassigned':513021,'metric_totals':[dict(zip(columns,r)) for r in totals],'metric_policy':cfg,'aggregation_levels':'ALL is pooled; JEONSE/MONTHLY_RENT/UNKNOWN partition RENT and overlap ALL. Metric denominators also overlap; never sum all rows as population.','source_identity':'file SHA + ordinal retained in stage facts; source raw fields and states unchanged','quantile_serialization':'decimal text, exact rational HF7 before Decimal50 HALF_EVEN; R numeric conversion optional precision loss','source_integrity_scope':'Source SHA/metadata selection, existing spatial SHA and per-file demand weights verified; normalized stores read-only transactions; new selected-field chunk digests. No repeated byte hash of all original CSVs/stores.','limitations':['2026 reference parcels, not contract-time location verification','reported observation distributions, not quality-adjusted price index','Seoul PILOT_PARTIAL; Cheongju PARTIAL_MATCH; population completeness unproven','no inflation adjustment, capitalization, trimming or event deduplication']}
 validation={'status':'PASS','input':20916100,'assigned':20403079,'unassigned':513021,'base_groups':571310,'statistics_rows':nrows,'source_rows_raw_reparsed':0,'national_spatial_rerun':0,'count_panel_key_denominator_comparison':'ALL_GROUPS_PASS','subtype_partition_conservation':'ALL_GROUPS_PASS','valid_excluded_conservation':'ALL_METRIC_ROWS_PASS','independent_sample':'direct_sample_validation.json','elapsed_seconds':time.monotonic()-start}
 p.write(out/'validation.json',validation);g.publication_gate();p.write(out/'release_manifest.json',manifest)
 return validation
if __name__=='__main__':
 if len(sys.argv)>1:
  g=p.resource.ReferenceGuard(p.ROOT);g.admit();r=publish(p.H/'work',p.H/'panel',g);w=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY']);p.write(w/'result.json',r);p.write(w/'worker_resource_receipt.json',g.publication_gate());g.reader.close()
 else:print(p.dump(p.resource.supervise([sys.executable,'-B','-X','utf8',__file__,'worker'],str(p.ROOT),dict(os.environ),p.H/'publish_supervisor')))
