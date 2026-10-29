"""Only affected handoffs. Synthetic fixtures never stand in for external inputs."""
import os,sys
import runtime  # captured Windows DLL directories before sqlite3 import
import argparse,ast,csv,json,socket,sqlite3,struct,time,traceback
from pathlib import Path
from datetime import datetime,timezone
from binding import *
import runtime
import khmd_reference_resource_monitor_v0_2 as monitor

def db(path):
    c=sqlite3.connect(path);c.execute('pragma cache_size=-2048');return c

def make_dbf(path,records):
    fields=[('A1',19),('A2',10),('A4',10)];head=bytearray(32)
    head[0]=3;head[1:4]=bytes([126,9,8]);struct.pack_into('<IHH',head,4,len(records),129,40)
    with path.open('xb') as f:
        f.write(head)
        for name,width in fields:
            field=bytearray(32);field[:len(name)]=name.encode();field[11]=ord('C');field[16]=width;f.write(field)
        f.write(b'\r')
        for row in records:f.write(b' '+b''.join(str(v).encode('euc_kr').ljust(w,b' ') for v,(_,w) in zip(row,fields)))
        f.write(b'\x1a')

def produce(out,g):
    from runtime import load
    r=load('fixture_real_geometry',ANNUAL/'csv_spatial_5179_busan_v0_2/run.py')
    finish=load('fixture_old_finish',ANNUAL/'csv_spatial_5179_busan_v0_3/finish.py')
    from completion import geometry_ready
    import shapely,pyproj
    from shapely.geometry import Polygon
    root=out/'inputs';root.mkdir();cw=root/'candidate';cw.mkdir()
    policy={'grid_version':'KHMD_UTMK_1KM_V1','area_of_use':{'west':122.71,'east':134.28,'south':28.6,'north':40.27}}
    write(root/'policy.json',policy);write(root/'geometry_config.json',{'scope':'SYNTHETIC','source_CRS':'EPSG:5186','candidate_sha256':'set below in stage manifest'})
    c=db(cw/'candidates.sqlite');c.executescript('create table key_results(address_id primary key,candidate_count,match_status,occurrences,cached_POS_available);create table candidates(address_id,pnu,ordinal,dbf_sha,raw_A2,raw_A4,eligibility);')
    c.executemany('insert into key_results values(?,?,?,?,?)',[('a',1,'UNIQUE_PARCEL_CRS_PENDING',5,0),('b',2,'AMBIGUOUS_PARCEL',2,0)])
    c.execute('insert into candidates values(?,?,?,?,?,?,?)',('a','2611010100100010000',1,'a'*64,'2611010100','1','EXACT_REFERENCE_CANDIDATE'));c.commit();c.close()
    c=db(cw/'candidates.sqlite');c.executemany('insert into candidates values(?,?,?,?,?,?,?)',[
        ('b','2611010100100020000',2,'b'*64,'2611010100','2','EXACT_REFERENCE_CANDIDATE'),
        ('b','2611010100200020000',3,'c'*64,'2611010100','2','EXACT_REFERENCE_CANDIDATE')]);c.commit();c.close()
    poly=Polygon([(200000,500000),(200100,500000),(200100,500100),(200000,500100)])
    pt=r.grid.point(poly);tf=pyproj.Transformer.from_crs(5186,5179,always_xy=True);x,y=tf.transform(pt.x,pt.y,errcheck=True)
    lon,lat=pyproj.Transformer.from_crs(5186,4326,always_xy=True).transform(pt.x,pt.y)
    target=shapely.ops.transform(tf.transform,poly) if hasattr(shapely,'ops') else None
    # Same strict-inside checks as the actual producer, on fabricated geometry.
    from shapely.ops import transform
    target=transform(tf.transform,poly);need(poly.contains(pt) and target.contains(shapely.Point(x,y)),'SYNTHETIC_POINT_INSIDE')
    payload=dict(address_id='a',status='ASSIGNED',occurrences=5,pnu='2611010100100010000',source_ordinal=1,source_dbf_record_sha='a'*64,
        source_inside=True,target_inside=True,source_CRS='EPSG:5186',target_CRS='EPSG:5179',x=x,y=y,longitude=lon,latitude=lat,grid_id=r.grid.identifier(x,y),representative_method='SYNTHETIC_POINT_ON_SURFACE')
    c=db(root/'spatial.sqlite');c.executescript('create table meta(binding);create table results(address_id primary key,status,n,payload);')
    c.execute('insert into meta values(?)',(r.b.digest(dict(config=sha(root/'geometry_config.json'),policy=sha(root/'policy.json'))),));c.commit()
    r.commit(c,[payload,dict(address_id='b',status='AMBIGUOUS_PARCEL',occurrences=2)]);c.close()
    c=db(root/'busan_demand.sqlite');c.executescript('create table files(sha primary key,family,query_json,input_rows,complete,province);create table weights(file_sha,key_id,quarter,row_status,n);')
    c.executemany('insert into files values(?,?,?,?,?,?)',[('f1','RENT','{}',3,1,'부산광역시'),('f2','RENT','{}',4,1,'부산광역시')])
    c.executemany('insert into weights values(?,?,?,?,?)',[('f1','a','2025Q1','PARSED',3),('f2','a','2025Q1','PARSED',2),('f2','b','2025Q1','PARSED',2)]);c.commit();c.close()
    write(cw/'input_manifest.json',{'scope':'SYNTHETIC','not_real_cadastral_data':True})
    candidate=dict(status='SYNTHETIC_CANDIDATES_CREATED',scope='SYNTHETIC',keys=2,occurrences=7)
    write(cw/'candidate_manifest.json',dict(result=candidate,input_manifest_sha256=sha(cw/'input_manifest.json'),database_sha256=sha(cw/'candidates.sqlite')))
    geometry=geometry_ready(root/'spatial.sqlite',cw/'candidates.sqlite',root/'geometry_config.json',root/'policy.json',2,7,'SYNTHETIC',g)
    need(r.grid.index(-0.1,0)==(-1,0) and r.grid.identifier(x,y)==payload['grid_id'],'GRID_POLICY_TEST')
    regression=finish.tests(out)
    # Guji is a separate branch: preceding national normalization fixture, not Busan -> Guji.
    gg=root/'guji';gg.mkdir();regional=db(gg/'regional.sqlite');regional.executescript('create table results(id primary key,status,n,payload);create table candidate_links(id,set_id,pnu,ordinal,sha,code,lot,eligibility);')
    dm=db(gg/'demand.sqlite');dm.executescript('create table keys(id primary key,province,region_literal,lot,legal_codes,status,n);create table weights(file_sha,key_id,quarter,row_status,n,primary key(file_sha,key_id,quarter,row_status));create table files(sha primary key,family);');dm.execute("insert into files values('gfile','RENT')")
    mapping=db(gg/'mapping.sqlite');mapping.execute('create table mapping(id primary key,province,n,source,lot,reason)')
    rows=[]
    for status in ('UNLINKED_PARCEL','AMBIGUOUS_PARCEL'):
        rows += [(status+str(i),status,1,'경기도 가상시 시험동','1',None) for i in range(20)]
    for rule in ('CITY_DISTRICT_FIELD_SPACING','SEJONG_UNIQUE_PARENT_OMITTED_IN_SOURCE'):
        rows += [(rule+str(i),'ASSIGNED',1,'가상 원문 주소','1',rule) for i in range(30)]
    records=[];codes=[];change=[]
    for i in range(1,16):
        ri='가상'+str(i)+'리';old=f'277103{i:04d}';new=f'277106{i:04d}'
        codes += [f'{old} 대구광역시 달성군 구지면 {ri} 20260930',f'{new} 대구광역시 달성군 구지읍 {ri} 20260930'];change += [old[5:],new[5:]]
        if i<=9:
            rows.append(('guji'+str(i),'UNLINKED_NAME_OR_JIBUN',2,'대구광역시 달성군 구지읍 '+ri,str(i),'CURRENT_MASTER_NO_PROVEN_ALIAS'))
            records.append((old+'1'+f'{i:04d}'+'0000',old,str(i)))
    for aid,status,n,address,lot,rule in rows:
        regional.execute('insert into results values(?,?,?,?)',(aid,status,n,'{}'))
        dm.execute('insert into keys values(?,?,?,?,?,?,?)',(aid,'대구광역시',address,lot,'[]','SYNTHETIC',n));dm.execute('insert into weights values(?,?,?,?,?)',('gfile',aid,'2025Q1','PARSED',n))
        if rule:mapping.execute('insert into mapping values(?,?,?,?,?,?)',(aid,'대구광역시',n,address,lot,rule))
    for cc in (regional,dm,mapping):cc.commit();cc.close()
    bc=db(gg/'empty_busan.sqlite');bc.execute('create table results(address_id primary key,status,n,payload)');bc.close()
    (gg/'legal_codes.txt').write_text('\n'.join(codes),encoding='cp949');(gg/'official_change.txt').write_text('SYNTHETIC TEST ONLY\n'+'\n'.join(change),encoding='utf-8')
    make_dbf(gg/'parcels.dbf',records)
    ix=db(gg/'index.sqlite');ix.executescript('create table parcels(set_id,row_ordinal,pnu,a2,jibun);create index parcels_K2V2 on parcels(a2,jibun);')
    for i,(pnu,code,lot) in enumerate(records,1):ix.execute('insert into parcels values(?,?,?,?,?)',('synthetic-set',i,pnu,code,lot))
    ix.commit();ix.close()
    write(gg/'members.json',{'sets_by_id':{'synthetic-set':{'set_id':'synthetic-set','members':{'.dbf':{'path':str(gg/'parcels.dbf'),'sha256':sha(gg/'parcels.dbf')}}}}})
    write(gg/'baseline.json',dict(scope='SYNTHETIC',result={'status':'SYNTHETIC_BASELINE_READY'},artifacts=[dict(path=str(p),sha256=sha(p)) for p in (gg/'regional.sqlite',gg/'empty_busan.sqlite')]))
    g.checkpoint('synthetic_inputs_created')
    return dict(candidate=candidate,geometry=geometry,policy={'status':'POLICY_TESTS_PASS','scope':'SYNTHETIC'},regression={'status':'RESTART_TESTS_PASS','tests':regression,'scope':'SYNTHETIC'})

def descriptor(role,path,time='SYNTHETIC'):
    return dict(role=role,path=str(path),expected_sha256=sha(path),schema='SYNTHETIC_TYPED_FIXTURE',source='generated_by_validate_links.py',version='v2',reference_time=time,acquisition_time_status='SYNTHETIC_NOT_ACQUIRED')

def config(out,name,stage,roles,parameters):
    path=out/(name+'.json');write(path,dict(schema='KHMD_CONSTRUCTION_INPUTS_V2',scope='SYNTHETIC',stage=stage,inputs=[descriptor(k,v,'2026-09-30' if k in ('legal_codes','official_change') else 'SYNTHETIC') for k,v in roles.items()],parameters=parameters));return path

def worker(out,mode):
    g=monitor.ReferenceGuard(PROJECT);wd=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY'])
    try:
        g.admit()
        def denied(*a,**k):raise RuntimeError('NETWORK_FORBIDDEN')
        socket.create_connection=socket.socket.connect=socket.socket.connect_ex=denied
        if mode=='produce':result=produce(out,g)
        elif mode=='bind':
            result=bind(out/'request.json',out/'bound.json',g)
        else:result=reject_tests(out,g)
        runtime.audit_loaded_modules(out)
        write(out/'result.json',result);write(wd/'worker_resource_receipt.json',g.publication_gate())
    except BaseException as e:
        write(wd/'primary_exception.json',dict(error=str(e),traceback=traceback.format_exc()))
        if not(wd/'worker_resource_receipt.json').exists():write(wd/'worker_resource_receipt.json',g.receipt())
        raise
    finally:g.reader.close()

def supervise(out,mode,python):
    out.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PROJ_NETWORK='OFF')
    rr=Path(python).parents[2];env.update(PROJ_DATA=str(rr/'share/proj'),GDAL_DATA=str(rr/'apps/gdal/share'))
    sup=monitor.supervise([str(python),'-B','-X','utf8',__file__,'worker',str(out),mode],str(PROJECT),env,out/'supervisor')
    write(out/'supervisor.json',sup);need(sup['status']=='COMPLETE' and sup['returncode']==0,'TEST_HOLD:'+str(out));return sup

def bound_config(root,name,stage,roles,params,python):
    folder=root/name;folder.mkdir();source=config(folder,'request',stage,roles,params);supervise(folder,'bind',python);return folder/'bound.json'

def reject_tests(out,g):
    request=read(out/'cases.json');checks=[]
    def rejects(name,fn,match):
        try:fn()
        except (ValueError,FileNotFoundError) as e:
            need(match in str(e),'WRONG_REJECTION:'+name+':'+str(e));checks.append(name)
        else:raise AssertionError('ACCEPTED:'+name)
    original=read(request['config'])
    for label,mutator,match in [
        ('missing_file',lambda x:x['inputs'][0].update(path=str(out/'absent')), 'absent'),
        ('wrong_SHA',lambda x:x['inputs'][0].update(expected_sha256='0'*64),'INPUT_SHA_MISMATCH'),
        ('missing_metadata',lambda x:x['inputs'][0].pop('version'),'REQUIRED_METADATA'),
        ('missing_role',lambda x:x['inputs'].pop(),'MISSING_INPUT_ROLES')]:
        c=json.loads(json.dumps(original));mutator(c);path=out/(label+'.json');write(path,c)
        rejects(label,lambda:bind(path,out/(label+'_bound.json'),g),match)
    from guji_contract import validate_seed,prepare_check
    cfg=request['seed_parameters'];src=sqlite3.connect(Path(request['seed']).as_uri()+'?mode=ro',uri=True);bad=out/'bad_seed.sqlite';dst=db(bad);src.backup(dst);src.close();dst.execute("delete from weights where key_id='guji1'");dst.commit();dst.close()
    rejects('seed_missing_weight',lambda:validate_seed(bad,cfg),'SEED_WEIGHT_CONSERVATION')
    write(out/'fake_stage.json',{'schema':'KHMD_CONSTRUCTION_STAGE_V2','scope':'SYNTHETIC','status':'FAILED'})
    rejects('failed_seed_not_inherited',lambda:verify_stage(out/'fake_stage.json','GUJI_SEED_READY','SYNTHETIC',g),'STAGE_NOT_COMPLETE')
    from completion import geometry_ready
    src=sqlite3.connect(Path(request['spatial']).as_uri()+'?mode=ro',uri=True);badgeo=out/'bad_geometry.sqlite';dst=db(badgeo);src.backup(dst);src.close();dst.execute("delete from results where address_id='b'");dst.commit();dst.close()
    rejects('incomplete_geometry_not_complete',lambda:geometry_ready(badgeo,Path(request['candidate']),Path(request['geometry_config']),Path(request['policy']),2,7,'SYNTHETIC',g),'GEOMETRY_CHECKPOINT_INCOMPLETE')
    # An unowned work DB cannot be silently used as seed or resume.
    unowned=out/'unowned';unowned.mkdir();db(unowned/'quality.sqlite').close()
    rejects('unowned_seed_database',lambda:prepare_check(Path(request['prepare_bound']),unowned,g),'UNOWNED_QUALITY_DATABASE')
    rejects('synthetic_seed_not_external',lambda:verify_stage(Path(request['seed']).parent/'final_manifest.json','GUJI_SEED_READY','EXTERNAL',g),'STAGE_SCOPE_SCHEMA')
    import guji
    altered=read(request['seed_config']);legal=next(x for x in altered['inputs'] if x['role']=='legal_codes')
    badlegal=out/'wrong_date_codes.txt';badlegal.write_text(Path(legal['path']).read_text(encoding='cp949').replace('20260930','20260929'),encoding='cp949')
    legal.update(path=str(badlegal),expected_sha256=sha(badlegal));write(out/'wrong_date_config.json',altered)
    bind(out/'wrong_date_config.json',out/'wrong_date_bound.json',g)
    wrongwork=out/'wrong_date_work';wrongwork.mkdir();wrongout=out/'wrong_date_out';wrongout.mkdir()
    rejects('official_date_not_inferred',lambda:guji.seed(out/'wrong_date_bound.json',wrongout,wrongwork,g),'GUJI_DATE')
    resumed=out/'prepare_interrupted';resumed.mkdir()
    prepare_check(Path(request['prepare_bound']),resumed,g)
    # A genuine partial candidate state is recomputed from bound inputs, never
    # treated as a completed audit or inherited success.
    c=db(resumed/'quality.sqlite');c.execute("insert into candidates values('guji1','partial','untrusted',1,'partial','partial','1','INCOMPLETE')");c.commit();c.close()
    rop=out/'prepare_resume_out';rop.mkdir();again=guji.prepare(Path(request['prepare_bound']),rop,resumed,g)
    c=db(resumed/'quality.sqlite');need(c.execute('select count(*) from candidates').fetchone()[0]==9,'PREPARE_RESUME_EXACT_ONCE');need(not c.execute("select 1 from candidates where set_id='partial'").fetchone(),'PARTIAL_NOT_ACCEPTED');c.close();checks.append('prepare_interrupted_resume_9_candidates')
    c=db(resumed/'quality.sqlite');c.execute("update results set payload='altered' where id='guji1'");c.commit();c.close()
    rejects('resume_immutable_seed_drift',lambda:prepare_check(Path(request['prepare_bound']),resumed,g),'SEED_IMMUTABLE_STATE_DRIFT')
    import aggregate_consumer
    merged=out/'downstream_aggregate';merged.mkdir()
    result=aggregate_consumer.merge(merged,g,[('부산광역시',request['busan_final'])],'SYNTHETIC',7,2)
    need(result['assigned']==5 and result['unassigned']==2 and result['grid_groups']==1,'DOWNSTREAM_MERGE_CONSERVATION');checks.append('actual_national_merge_body_input_7_assigned_5')
    rejects('same_region_double_merge',lambda:aggregate_consumer.checked_inputs([('부산광역시',request['busan_final'])]*2,'SYNTHETIC',g),'DUPLICATE_REGION_OR_MANIFEST')
    return {'status':'TARGETED_REJECTIONS_PASS','checks':checks}

def main(python,output_root=None):
    import run_stage
    os.environ['KHMD_QGIS_ROOT']=str(Path(python).parents[2])
    out=(Path(output_root).resolve() if output_root else HERE/'validation')/('run_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ'));out.mkdir(parents=True)
    for path in HERE.glob('*.py'):compile(ast.parse(path.read_text(encoding='utf-8-sig')),str(path),'exec')
    fixture=out/'fixture';sup=supervise(fixture,'produce',python);result=read(fixture/'result.json');inputs=fixture/'inputs';cw=inputs/'candidate'
    for key,path in [('candidate',cw/'completion.json'),('geometry',inputs/'geometry_completion.json'),('policy',inputs/'policy_completion.json'),('regression',inputs/'regression_completion.json')]:
        receipt=dict(supervisor=sup,result=result[key],producer_result=str(fixture/'result.json'),producer_result_sha256=sha(fixture/'result.json'))
        if key=='policy':receipt['policy_sha256']=sha(inputs/'policy.json')
        write(path,receipt)
    # Actual unchanged candidate publication gate, not a made-up PASS record.
    from runtime import load
    publication=load('real_candidate_publication',ANNUAL/'csv_regional_demand_v0_1/candidate_publication.py')
    write(cw/'publication_receipt.json',publication.verify(cw,cw))
    roles={'spatial':inputs/'spatial.sqlite','candidates':cw/'candidates.sqlite','candidate_input':cw/'input_manifest.json','candidate_manifest':cw/'candidate_manifest.json','candidate_publication':cw/'publication_receipt.json','candidate_completion':cw/'completion.json','geometry_completion':inputs/'geometry_completion.json','geometry_config':inputs/'geometry_config.json','grid_policy':inputs/'policy.json','policy_completion':inputs/'policy_completion.json','regression_completion':inputs/'regression_completion.json','demand':inputs/'busan_demand.sqlite'}
    bound=bound_config(out,'busan_binding','busan_finish',roles,dict(address_keys=2,input_cells=2,input_occurrences=7),python)
    pause=run_stage.run(bound,out/'busan_resumed',out/'busan_pause',python,1)
    need(pause['status']=='AGGREGATION_INTENTIONAL_PAUSE' and not(out/'busan_resumed/final_manifest.json').exists(),'PAUSE_NOT_FINAL')
    resumed=run_stage.run(bound,out/'busan_resumed',out/'busan_finish',python)
    continuous=run_stage.run(bound,out/'busan_continuous',out/'busan_continuous_attempt',python)
    def counts(path):
        c=sqlite3.connect(path);x=c.execute('select * from counts order by 1,2,3,4').fetchall();c.close();return x
    need(counts(out/'busan_resumed/aggregate.sqlite')==counts(out/'busan_continuous/aggregate.sqlite'),'RESUME_EQUIVALENCE')
    need(resumed['result']['assigned']==5 and resumed['result']['unassigned']==2 and resumed['result']['grid_quarter_family_groups']==1,'BUSAN_CONSERVATION')
    reused=run_stage.run(bound,out/'busan_resumed',out/'must_not_create',python);need(reused['status']=='REUSED_COMPLETE_NO_REPROCESSING' and not(out/'must_not_create').exists(),'NO_REPROCESS')
    # Use the actual national downstream manifest reader, without running initialize.
    p=load('national_consumer',ANNUAL/'csv_spatial_national_5179_v0_1/pipeline.py');p.verify_final(out/'busan_resumed/final_manifest.json')
    gg=inputs/'guji';params=dict(baseline_keys=109,baseline_occurrences=118,guji_occurrences=18,regions=['대구광역시'],reference_date='2026-09-08')
    sr={'baseline_manifest':gg/'baseline.json','busan_spatial':gg/'empty_busan.sqlite','region:대구광역시':gg/'regional.sqlite','demand':gg/'demand.sqlite','mapping':gg/'mapping.sqlite','legal_codes':gg/'legal_codes.txt','official_change':gg/'official_change.txt'}
    sb=bound_config(out,'guji_seed_binding','guji_seed',sr,params,python)
    seed=run_stage.run(sb,out/'guji_seed',out/'guji_seed_attempt',python)
    pr={'seed_manifest':out/'guji_seed/final_manifest.json','seed_database':out/'guji_seed/quality.sqlite','seed_crosswalk':out/'guji_seed_attempt/guji_ri_crosswalk.csv','demand':gg/'demand.sqlite','mapping':gg/'mapping.sqlite','members':gg/'members.json','parcel_index':gg/'index.sqlite','dbf':gg/'parcels.dbf','region:대구광역시':gg/'regional.sqlite','base_region:대구광역시':gg/'regional.sqlite'}
    pb=bound_config(out,'guji_prepare_binding','guji_prepare',pr,params,python)
    prepared=run_stage.run(pb,out/'guji_prepare',out/'guji_prepare_attempt',python)
    c=sqlite3.connect(out/'guji_prepare/quality.sqlite');need(c.execute('select count(*) from candidates').fetchone()[0]==9,'GUJI_EXACT_CANDIDATES');need(c.execute('select sum(n) from weights').fetchone()[0]==118,'GUJI_WEIGHT_SUM');c.close()
    re=run_stage.run(pb,out/'guji_prepare',out/'must_not_prepare_again',python);need(re['status']=='REUSED_COMPLETE_NO_REPROCESSING','GUJI_COMPLETED_RESUME')
    rejects=out/'rejections';rejects.mkdir();write(rejects/'cases.json',dict(busan_final=str(out/'busan_resumed/final_manifest.json'),config=str(out/'busan_binding/request.json'),seed=str(out/'guji_seed/quality.sqlite'),seed_config=str(out/'guji_seed_binding/request.json'),seed_parameters=params,spatial=str(inputs/'spatial.sqlite'),candidate=str(cw/'candidates.sqlite'),geometry_config=str(inputs/'geometry_config.json'),policy=str(inputs/'policy.json'),prepare_bound=str(pb)))
    supervise(rejects,'reject',python)
    summary=dict(status='TARGETED_EXECUTION_LINKS_PASS',scope='SYNTHETIC',busan=resumed['result'],guji_seed=seed['result'],guji_prepare=prepared['result'],rejections=read(rejects/'result.json'),national_manifest_reader='PASS',full_national_reproduction=False,guji_geometry_audit_and_national_publish='NOT_RUN',output=str(out))
    write(out/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='worker':worker(Path(sys.argv[2]),sys.argv[3])
    else:
        p=argparse.ArgumentParser();p.add_argument('--python',type=Path,required=True);p.add_argument('--output-root',type=Path);a=p.parse_args();main(a.python,a.output_root)
