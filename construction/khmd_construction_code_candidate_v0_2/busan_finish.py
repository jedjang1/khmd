"""Normal Busan finalization; original finish.process validation and aggregation."""
import csv,json,sqlite3
from pathlib import Path
from binding import verify, read, sha, need, ANNUAL
from runtime import load
r=load('busan_base_run',ANNUAL/'csv_spatial_5179_busan_v0_2/run.py')
b=r.b;d=r.d

def check(bound,g):
    m,inputs=verify(bound,'busan_finish',g);cfg=m['parameters']
    for k in ('address_keys','input_cells','input_occurrences'):
        need(isinstance(cfg.get(k),int) and cfg[k]>0,'MISSING_SCOPE:'+k)
    if m['scope']=='EXTERNAL':
        need((cfg['address_keys'],cfg['input_cells'],cfg['input_occurrences'])==(5120,30,1327806),'BUSAN_FROZEN_SCOPE')
    cw=inputs['candidates'].parent
    for role,name in [('candidate_input','input_manifest.json'),('candidate_manifest','candidate_manifest.json'),('candidate_publication','publication_receipt.json')]:
        need(inputs[role]==cw/name,'CANDIDATE_LAYOUT:'+role)
    receipt=read(inputs['candidate_publication'])
    need(Path(receipt['supervised_completion']).resolve()==inputs['candidate_completion'],'CANDIDATE_COMPLETION_PATH')
    r.publication.check(cw) # unchanged candidate SHA/supervisor gate
    geometry=read(inputs['geometry_completion']); sup=geometry['supervisor']
    need(sup['status']=='COMPLETE' and sup['returncode']==0 and not sup.get('hold_reason'),'GEOMETRY_SUPERVISOR')
    result=geometry['result']
    need(result['status']=='BUSAN_GEOMETRY_CHECKPOINT_READY','GEOMETRY_STAGE_INCOMPLETE')
    need(result['spatial_sha256']==sha(inputs['spatial'],g),'GEOMETRY_SHA')
    need(result['config_sha256']==sha(inputs['geometry_config'],g) and result['policy_sha256']==sha(inputs['grid_policy'],g),'GEOMETRY_INPUT_BINDING')
    need(result['candidate_sha256']==sha(inputs['candidates'],g),'GEOMETRY_CANDIDATE_BINDING')
    need((result['address_keys'],result['input_occurrences'])==(cfg['address_keys'],cfg['input_occurrences']),'GEOMETRY_SCOPE')
    need(result.get('scope')==m['scope'],'GEOMETRY_SCOPE_KIND')
    policy=read(inputs['policy_completion']); regression=read(inputs['regression_completion'])
    for receipt in (policy,regression):
        need(receipt['supervisor']['status']=='COMPLETE' and receipt['supervisor']['returncode']==0,'PREREQUISITE_SUPERVISOR')
    need(policy['result']['status']=='POLICY_TESTS_PASS' and policy['policy_sha256']==sha(inputs['grid_policy'],g),'POLICY_TESTS_BINDING')
    need(regression['result']['status']=='RESTART_TESTS_PASS','RESTART_TESTS')
    return cfg,inputs

def table(path,columns,rows):
    with path.open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(columns);w.writerows(rows)

def transaction(c,sha,rows,fail=False):
    with c:
        for gid,q,f,z,n in rows:
            c.execute('insert into counts values(?,?,?,?,?) on conflict(grid_id,quarter,family,status) do update set n=n+excluded.n',(gid,q,f,z,n))
        c.execute('insert into done values(?)',(sha,))
        if fail:raise ValueError('TEST_INTERRUPTION_BEFORE_COMMIT')

def process(bound,out,work,g,pause=0):
    cfg,inputs=check(bound,g);g.reserve_output(64*1024**2)
    test_results=[] # prior regression tests are bound separately; not repeated here
    source=d.database(inputs['spatial'],True);cand=d.database(inputs['candidates'],True)
    expected_binding=b.digest(dict(config=b.lane.sha(inputs['geometry_config']),policy=b.lane.sha(inputs['grid_policy'])))
    b.need(source.execute('select binding from meta').fetchone()[0]==expected_binding,'GEOMETRY_CHECKPOINT_BINDING')
    b.need(source.execute('select count(*),sum(n) from results').fetchone()==(cfg['address_keys'],cfg['input_occurrences']),'GEOMETRY_CHECKPOINT_COMPLETE')
    keys={};reasons={}
    for aid,status,n,payload in source.execute('select * from results order by address_id'):
        x=json.loads(payload);b.need((x['address_id'],x['status'],x['occurrences'])==(aid,status,n),'PAYLOAD_ROW_BINDING')
        k=cand.execute('select candidate_count,match_status,occurrences from key_results where address_id=?',(aid,)).fetchone();b.need(k and k[2]==n,'KEY_SOURCE_WEIGHT')
        if status=='ASSIGNED':
            pnu,ordinal,sha=cand.execute('select pnu,ordinal,dbf_sha from candidates where address_id=?',(aid,)).fetchone()
            b.need(k[0]==1 and (x['pnu'],x['source_ordinal'],x['source_dbf_record_sha'])==(pnu,ordinal,sha),'UNIQUE_PARCEL_BINDING')
            b.need(x['source_inside'] and x['target_inside'] and x['source_CRS']=='EPSG:5186' and x['target_CRS']=='EPSG:5179' and r.grid.identifier(x['x'],x['y'])==x['grid_id'],'GEOMETRY_TARGET_BINDING')
            a=b.read(inputs['grid_policy'])['area_of_use'];b.need(a['west']<=x['longitude']<=a['east'] and a['south']<=x['latitude']<=a['north'],'AREA_CHECKPOINT')
        elif k[1]=='UNIQUE_PARCEL_CRS_PENDING':b.need(status in ('GEOMETRY_FAILED','TRANSFORM_FAILED','OUTSIDE_TARGET_CRS_AREA','REFERENCE_INELIGIBLE'),'UNIQUE_STATUS')
        else:b.need(status==k[1],'UNASSIGNED_STATUS_CHANGED')
        keys[aid]=(status,x.get('grid_id',''))
        if 'reason' in x:reasons[x['reason']]=reasons.get(x['reason'],0)+n
    cand.close();source.close();g.checkpoint('all_bound_geometry_checkpoint_bindings_verified')
    c=d.database(work/'aggregate.sqlite');c.executescript('create table if not exists meta(binding);create table if not exists counts(grid_id,quarter,family,status,n,primary key(grid_id,quarter,family,status));create table if not exists done(sha primary key);')
    binding=b.lane.sha(bound);old=c.execute('select binding from meta').fetchone()
    if old:b.need(old[0]==binding,'AGG_RESTART_BINDING')
    else:c.execute('insert into meta values(?)',(binding,));c.commit()
    src=d.database(inputs['demand'],True)
    files=src.execute("select sha,family,query_json,input_rows,complete from files where province='부산광역시' order by sha").fetchall()
    b.need(len(files)==cfg['input_cells'] and sum(x[3] for x in files)==cfg['input_occurrences'] and all(x[4] for x in files),'FROZEN_FILE_SCOPE')
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
    total=c.execute('select sum(n) from counts').fetchone()[0];b.need(total==cfg['input_occurrences'] and c.execute('select count(*) from done').fetchone()[0]==cfg['input_cells'],'FINAL_CONSERVATION')
    statuses=dict(c.execute('select status,sum(n) from counts group by status'))
    assigned=c.execute("select coalesce(sum(n),0) from counts where status='ASSIGNED'").fetchone()[0];b.need(assigned==statuses.get('ASSIGNED',0),'GRID_SUM')
    table(out/'grid_quarter_counts.csv',['grid_id','quarter','family','observation_occurrences'],c.execute("select grid_id,quarter,family,n from counts where status='ASSIGNED' order by 1,2,3"))
    table(out/'quarter_status_counts.csv',['quarter','family','status','observation_occurrences'],c.execute('select quarter,family,status,sum(n) from counts group by 1,2,3 order by 1,2,3'))
    original=d.database(inputs['spatial'],True)
    table(out/'address_results.csv',['address_id','status','occurrences','payload'],original.execute('select * from results order by 1'))
    point_counts=dict(original.execute("select json_extract(payload,'$.representative_method'),count(*) from results where status='ASSIGNED' group by 1"))
    key_counts=dict(original.execute('select status,count(*) from results group by status'))
    coordinate_extent=original.execute("select min(json_extract(payload,'$.longitude')),max(json_extract(payload,'$.longitude')),min(json_extract(payload,'$.latitude')),max(json_extract(payload,'$.latitude')) from results where status='ASSIGNED'").fetchone()
    groups=c.execute("select count(*) from counts where status='ASSIGNED'").fetchone()[0];original.close();src.close();c.close()
    return dict(status='BUSAN_5179_SPATIAL_COMPLETE',input_cells=cfg['input_cells'],input_occurrences=total,status_occurrences=statuses,key_counts=key_counts,assigned=assigned,unassigned=total-assigned,grid_quarter_family_groups=groups,new_files=new,skipped_files=skipped,point_methods=point_counts,failure_reasons=reasons,longitude_latitude_extent=coordinate_extent,tests=test_results,geometry_recomputed_this_resume=0,normal_completion=True,reference_snapshot='2026-09-08',historical_location_verified=False)
