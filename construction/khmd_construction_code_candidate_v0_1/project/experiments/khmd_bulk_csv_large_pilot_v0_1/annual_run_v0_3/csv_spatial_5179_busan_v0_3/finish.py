"""Resume after committed geometry results; use a separate read-only demand connection.

The v0_2 failure was ATTACH URI handling, after all 5120 keys committed.
No geometry/address recomputation and no in-place amendment of prior evidence.
"""
import os,sys,csv,json,sqlite3,time,traceback,hashlib
from pathlib import Path
H=Path(__file__).resolve().parent;ROOT=H.parents[3];V=H.parent/'csv_spatial_5179_busan_v0_2';P=H.parent/'csv_regional_demand_v0_1'
sys.path.insert(0,str(V));import run as r
b=r.b;d=r.d
def check(g):
    cfg=b.read(H/'config.json')
    for x in cfg['bindings']:b.need(b.lane.sha(Path(x['path']),g)==x['sha256'],'INPUT_SHA:'+x['path'])
    r.bind(g);r.publication.check(P/'busan_candidates')
    b.need(b.read(V/'policy_attempt/completion.json')['result']['status']=='POLICY_TESTS_PASS','POLICY_TESTS')
    b.need(b.read(V/'regression_attempt/completion.json')['result']['status']=='RESTART_TESTS_PASS','RESTART_TESTS')
    prior=b.read(V/'full_attempt/supervised/primary_exception.json')
    b.need(prior['error'].startswith('unable to open database: file:///') and 'attach database ? as demand' in prior['traceback'],'RECOVERY_FAILURE_SCOPE')
    return cfg
def table(path,columns,rows):
    with path.open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(columns);w.writerows(rows)
def transaction(c,sha,rows,fail=False):
    with c:
        for gid,q,f,z,n in rows:
            c.execute('insert into counts values(?,?,?,?,?) on conflict(grid_id,quarter,family,status) do update set n=n+excluded.n',(gid,q,f,z,n))
        c.execute('insert into done values(?)',(sha,))
        if fail:raise ValueError('TEST_INTERRUPTION_BEFORE_COMMIT')
def tests(out):
    p=out/'aggregation_tests.sqlite';c=d.database(p)
    c.executescript('create table counts(grid_id,quarter,family,status,n,primary key(grid_id,quarter,family,status));create table done(sha primary key);')
    a=[('G','2025Q1','RENT','ASSIGNED',2),('G','2025Q1','RENT','ASSIGNED',3)];z=[('','2025Q1','RENT','AMBIGUOUS_PARCEL',4)]
    transaction(c,'a',a)
    try:transaction(c,'b',z,True)
    except ValueError:pass
    b.need(c.execute('select sum(n) from counts').fetchone()[0]==5,'AGG_ROLLBACK')
    c.close();c=d.database(p);transaction(c,'b',z)
    try:transaction(c,'a',a);raise AssertionError('REPEAT_ACCEPTED')
    except sqlite3.IntegrityError:pass
    b.need(c.execute('select sum(n) from counts').fetchone()[0]==9 and c.execute('select count(*) from done').fetchone()[0]==2,'RESTART_EXACT_ONCE')
    expected=sorted([('G','2025Q1','RENT','ASSIGNED',5),('','2025Q1','RENT','AMBIGUOUS_PARCEL',4)])
    b.need(sorted(c.execute('select * from counts').fetchall())==expected,'CONTINUOUS_EQ');c.close()
    return ['file_transaction_rollback','close_reopen_resume','duplicate_file_rollback','multiset_5_plus_4_preserved']
def process(out,work,g,pause):
    cfg=check(g);g.reserve_output(64*1024**2)
    test_results=tests(out)
    source=d.database(V/'busan_run/spatial.sqlite',True);cand=d.database(P/'busan_candidates/candidates.sqlite',True)
    expected_binding=b.digest(dict(config=b.lane.sha(V/'config.json'),policy=b.lane.sha(V/'grid_policy.json')))
    b.need(source.execute('select binding from meta').fetchone()[0]==expected_binding,'GEOMETRY_CHECKPOINT_BINDING')
    b.need(source.execute('select count(*),sum(n) from results').fetchone()==(5120,1327806),'GEOMETRY_CHECKPOINT_COMPLETE')
    keys={};reasons={}
    for aid,status,n,payload in source.execute('select * from results order by address_id'):
        x=json.loads(payload);b.need((x['address_id'],x['status'],x['occurrences'])==(aid,status,n),'PAYLOAD_ROW_BINDING')
        k=cand.execute('select candidate_count,match_status,occurrences from key_results where address_id=?',(aid,)).fetchone();b.need(k and k[2]==n,'KEY_SOURCE_WEIGHT')
        if status=='ASSIGNED':
            pnu,ordinal,sha=cand.execute('select pnu,ordinal,dbf_sha from candidates where address_id=?',(aid,)).fetchone()
            b.need(k[0]==1 and (x['pnu'],x['source_ordinal'],x['source_dbf_record_sha'])==(pnu,ordinal,sha),'UNIQUE_PARCEL_BINDING')
            b.need(x['source_inside'] and x['target_inside'] and x['source_CRS']=='EPSG:5186' and x['target_CRS']=='EPSG:5179' and r.grid.identifier(x['x'],x['y'])==x['grid_id'],'GEOMETRY_TARGET_BINDING')
            a=b.read(V/'grid_policy.json')['area_of_use'];b.need(a['west']<=x['longitude']<=a['east'] and a['south']<=x['latitude']<=a['north'],'AREA_CHECKPOINT')
        elif k[1]=='UNIQUE_PARCEL_CRS_PENDING':b.need(status in ('GEOMETRY_FAILED','TRANSFORM_FAILED','OUTSIDE_TARGET_CRS_AREA','REFERENCE_INELIGIBLE'),'UNIQUE_STATUS')
        else:b.need(status==k[1],'UNASSIGNED_STATUS_CHANGED')
        keys[aid]=(status,x.get('grid_id',''))
        if 'reason' in x:reasons[x['reason']]=reasons.get(x['reason'],0)+n
    cand.close();source.close();g.checkpoint('all_5120_geometry_checkpoint_bindings_verified')
    c=d.database(work/'aggregate.sqlite');c.executescript('create table if not exists meta(binding);create table if not exists counts(grid_id,quarter,family,status,n,primary key(grid_id,quarter,family,status));create table if not exists done(sha primary key);')
    binding=b.lane.sha(H/'config.json');old=c.execute('select binding from meta').fetchone()
    if old:b.need(old[0]==binding,'AGG_RESTART_BINDING')
    else:c.execute('insert into meta values(?)',(binding,));c.commit()
    src=d.database(P/'national_demand/demand.sqlite',True)
    files=src.execute("select sha,family,query_json,input_rows,complete from files where province='부산광역시' order by sha").fetchall()
    b.need(len(files)==30 and sum(x[3] for x in files)==1327806 and all(x[4] for x in files),'FROZEN_FILE_SCOPE')
    new=0;skipped=0
    for sha,family,query,expected,_ in files:
        if c.execute('select 1 from done where sha=?',(sha,)).fetchone():skipped+=1;continue
        def weighted():
            total=0
            for aid,q,state,n in src.execute('select key_id,quarter,row_status,n from weights where file_sha=?',(sha,)):
                status,gid=keys[aid]
                if status=='ASSIGNED' and (state!='PARSED' or q=='UNASSIGNABLE_PERIOD'):status='OBSERVATION_NOT_AGGREGATABLE';gid=''
                total+=n;yield gid,q,family,status,n
            b.need(total==expected,'FILE_WEIGHT_CONSERVATION')
        transaction(c,sha,weighted());new+=1;g.checkpoint('weighted_file_committed_'+sha[:12])
        if pause and new>=pause:
            c.close();src.close();return dict(status='AGGREGATION_INTENTIONAL_PAUSE',new_files=new,skipped_files=skipped,tests=test_results)
    total=c.execute('select sum(n) from counts').fetchone()[0];b.need(total==1327806 and c.execute('select count(*) from done').fetchone()[0]==30,'FINAL_CONSERVATION')
    statuses=dict(c.execute('select status,sum(n) from counts group by status'))
    assigned=c.execute("select sum(n) from counts where status='ASSIGNED'").fetchone()[0];b.need(assigned==statuses['ASSIGNED'],'GRID_SUM')
    table(out/'grid_quarter_counts.csv',['grid_id','quarter','family','observation_occurrences'],c.execute("select grid_id,quarter,family,n from counts where status='ASSIGNED' order by 1,2,3"))
    table(out/'quarter_status_counts.csv',['quarter','family','status','observation_occurrences'],c.execute('select quarter,family,status,sum(n) from counts group by 1,2,3 order by 1,2,3'))
    original=d.database(V/'busan_run/spatial.sqlite',True)
    table(out/'address_results.csv',['address_id','status','occurrences','payload'],original.execute('select * from results order by 1'))
    point_counts=dict(original.execute("select json_extract(payload,'$.representative_method'),count(*) from results where status='ASSIGNED' group by 1"))
    key_counts=dict(original.execute('select status,count(*) from results group by status'))
    coordinate_extent=original.execute("select min(json_extract(payload,'$.longitude')),max(json_extract(payload,'$.longitude')),min(json_extract(payload,'$.latitude')),max(json_extract(payload,'$.latitude')) from results where status='ASSIGNED'").fetchone()
    groups=c.execute("select count(*) from counts where status='ASSIGNED'").fetchone()[0];original.close();src.close();c.close()
    return dict(status='BUSAN_5179_SPATIAL_COMPLETE',input_cells=30,input_occurrences=total,status_occurrences=statuses,key_counts=key_counts,assigned=assigned,unassigned=total-assigned,grid_quarter_family_groups=groups,new_files=new,skipped_files=skipped,point_methods=point_counts,failure_reasons=reasons,longitude_latitude_extent=coordinate_extent,tests=test_results,geometry_recomputed_this_resume=0,old_HOLD_preserved=True,reference_snapshot='2026-09-08',historical_location_verified=False)
def worker(work,out,pause):
    g=b.lane.resource.ReferenceGuard(ROOT);wd=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY']);t=time.monotonic()
    try:
        g.admit();result=process(out,work,g,pause);result['elapsed_seconds']=time.monotonic()-t
        b.write(wd/'worker_resource_receipt.json',g.publication_gate());b.write(out/'result.json',result)
    except BaseException as e:
        b.write(wd/'primary_exception.json',dict(error=str(e),traceback=traceback.format_exc()))
        if not (wd/'worker_resource_receipt.json').exists():b.write(wd/'worker_resource_receipt.json',g.receipt())
        raise
    finally:g.reader.close()
def run(work,out,pause):
    import msvcrt
    work.mkdir(parents=True,exist_ok=True)
    with (work/'coordinator.lock').open('a+b') as lock:
        if lock.tell()==0:lock.write(b'1');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        try:
            if (work/'final_manifest.json').exists():
                m=b.read(work/'final_manifest.json');b.need(b.lane.sha(H/'config.json')==m['config_sha256'],'FINAL_CONFIG')
                for x in m['artifacts']:b.need(b.lane.sha(Path(x['path']))==x['sha256'],'FINAL_ARTIFACT')
                print('REUSED_COMPLETE_NO_REPROCESSING');return
            b.need(not out.exists(),'ATTEMPT_NO_REPLACE');out.mkdir(parents=True)
            sup=b.lane.resource.supervise([sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'worker','--work',str(work),'--out',str(out),'--pause',str(pause)],str(ROOT),dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),out/'supervised')
            b.need(sup['status']=='COMPLETE' and sup['returncode']==0,'HOLD:'+str(out));result=b.read(out/'result.json');b.write(out/'completion.json',dict(supervisor=sup,result=result))
            if result['status']=='BUSAN_5179_SPATIAL_COMPLETE':
                paths=[work/'aggregate.sqlite',out/'grid_quarter_counts.csv',out/'quarter_status_counts.csv',out/'address_results.csv',out/'completion.json',V/'grid_policy.json',V/'busan_run/spatial.sqlite']
                b.write(work/'final_manifest.json',dict(status=result['status'],config_sha256=b.lane.sha(H/'config.json'),artifacts=[dict(path=str(p),sha256=b.lane.sha(p)) for p in paths],result=result))
            print(b.dump(dict(status=result['status'],result=result.get('status_occurrences'),seconds=sup['elapsed_seconds'])))
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
if __name__=='__main__':
    import argparse
    a=argparse.ArgumentParser();a.add_argument('mode',choices=['run','worker']);a.add_argument('--work',type=Path,required=True);a.add_argument('--out',type=Path,required=True);a.add_argument('--pause',type=int,default=0);v=a.parse_args();(run if v.mode=='run' else worker)(v.work.resolve(),v.out.resolve(),v.pause)
