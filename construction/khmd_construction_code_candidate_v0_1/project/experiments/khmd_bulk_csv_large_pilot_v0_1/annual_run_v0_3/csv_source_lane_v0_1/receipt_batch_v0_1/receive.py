"""Bounded new CSV receipt shard. Reuses csv_lane unchanged; prior store read-only."""
import os as _khmd_path_env  # candidate-only path configuration
import argparse,csv,hashlib,importlib.util,json,os,sqlite3,sys,time,traceback
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
OUT=Path(__file__).resolve().parent;BASE=OUT.parent;ROOT=BASE.parents[3]
sys.path.insert(0,str(BASE));import csv_lane as lane
R=lane.resource
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(name,value):lane.writej(OUT/name,value)
def csvout(name,rows):
    with (OUT/name).open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,list(rows[0]));w.writeheader()
        for x in rows:w.writerow({k:lane.dump(v) if isinstance(v,(dict,list)) else v for k,v in x.items()})
def header(p):
    pre=[]
    with p.open(encoding='cp949',newline='') as f:
        rr=csv.reader(f,strict=True)
        for row in rr:
            if row and row[0]=='NO':break
            lane.need(len(pre)<100 and len(row)==1,'HEADER_SCHEMA');pre.append(row[0])
        else:raise ValueError('HEADER_MISSING')
    conditions={x.split(' : ',1)[0]:x.split(' : ',1)[1] for x in pre if ' : ' in x}
    return conditions,row
def last_no(p,columns):
    # Bounded tail inspection supplies a provisional expected NO. Actual ingest
    # independently checks every sequence number and count; this is not a total-population claim.
    with p.open('rb') as f:f.seek(max(0,p.stat().st_size-65536));tail=f.read()
    final=tail.rstrip(b'\r\n').split(b'\n')[-1].decode('cp949')
    row=next(csv.reader([final],strict=True))
    lane.need(len(row)==len(columns) and row[0].isdigit(),'FINAL_RECORD_NOT_BOUNDED_READABLE')
    return int(row[0])
def prior():
    c=sqlite3.connect((BASE/'observations.sqlite').as_uri()+'?mode=ro&immutable=1',uri=True)
    rows={s:dict(metadata=json.loads(m),input_rows=n,good_rows=g,error_rows=e) for s,m,n,g,e in c.execute('select sha,metadata,input_rows,good_rows,error_rows from files')}
    c.close();return rows
def prepare():
    cfg=read(BASE/'config.json');policy=BASE/'download_policy_v0_2'
    release=read(policy/'analysis_release_manifest.json');olds=prior()
    lane.need(len(olds)==11 and sum(x['input_rows'] for x in olds.values())==299169,'PRIOR_REGISTRY_DRIFT')
    inputs=[];skips=[];discovery=[]
    def add(path,expected_sha,id,evidence,proposal=False):
        p=Path(path)
        if expected_sha in olds:
            skips.append(dict(path=str(p),sha256=expected_sha,reason='ALREADY_COMPLETE_SHA_NOT_REPROCESSED'));return
        if not p.exists():discovery.append(dict(path=str(p),status='FILE_ABSENT'));return
        cond,cols=header(p);lo,hi=cond['계약일자'].split(' ~ ')
        family='SALE' if cond['실거래구분']=='아파트(매매)' else 'RENT'
        inputs.append(dict(id=id,path=str(p),sha256=expected_sha,expected_rows=last_no(p,cols),expected_rows_basis='LAST_RECORD_NO_PROVISIONAL; full sequential check in actual ingestion',
          encoding='cp949',columns=cols,conditions=cond,query=dict(family=family,province=cond['시도'],district=cond['시군구'],date_from=lo,date_to=hi),
          source_url='https://rt.molit.go.kr/pt/xls/xls.do?mobileAt=',download_started_at=None,download_completed_at=None,
          acquisition_time_status='NOT_PROVIDED; filename/mtime not acquisition times',source_evidence=evidence,
          prior_validation='HEADER_SCOPE_AND_SHA_AUDIT' if expected_sha else 'NEW_BUNDLE_HEADER_ONLY',
          prior_API_comparison_scope='NOT_RUN; no new API comparison',selected=False,selection_reason='Pending receipt; prior exact-SHA proposal may activate only after clean ingestion',
          proposed_exact_sha_selection=proposal,spatial_status='NOT_RUN'))
    for x in read(policy/'four_cell_audit.json'):
        if (x['province'],x['year'],x['family']) not in [('경기도',2019,'SALE'),('서울특별시',2021,'SALE'),('서울특별시',2024,'RENT')]:continue
        rx=next(v for v in release['files'] if v['file_sha256']==x['sha256'])
        add(x['path'],x['sha256'],f'HELD_{x["family"]}_{x["year"]}_{x["sha256"][:12]}',str(policy/'four_cell_audit.json'),rx.get('proposed_for_next_release',False))
    bundle=read(policy/'first_download_bundle.json');found={x['cell_id']:[] for x in bundle}
    known={str(Path(x['path'])) for x in read(BASE/'held_file_planning_inventory.json')}
    # Only apartment CSV header candidates in Downloads; never recursively scan user folders.
    for p in Path(_khmd_path_env.environ['KHMD_DOWNLOADS']).glob('아파트*.csv'):
        if str(p) in known:continue
        cond,cols=header(p)
        for target in bundle:
            fam='아파트(매매)' if target['family']=='SALE' else '아파트(전월세)'
            if cond.get('실거래구분')==fam and cond.get('시도')==target['province'] and cond.get('시군구')=='전체' and cond.get('계약일자')==target['date_from']+' ~ '+target['date_to']:
                filters={k:v for k,v in cond.items() if k not in ('실거래구분','시도','시군구','계약일자','주소구분')}
                lane.need(all(v=='전체' for v in filters.values()) and cond['주소구분']=='지번주소','BUNDLE_FILTER_RESTRICTED')
                found[target['cell_id']].append(str(p));add(p,None,target['cell_id']+'_'+p.stem[-14:],str(policy/'first_download_bundle.json'))
    # Also recognize exact bundle scopes already in registered store; do not reparse them.
    for sha,x in olds.items():
        q=x['metadata']['query']
        for target in bundle:
            if (q['family'],q['province'],q['district'],q['date_from'],q['date_to'])==(target['family'],target['province'],'전체',target['date_from'],target['date_to']):
                found[target['cell_id']].append(x['metadata']['path'])
    for target in bundle:discovery.append(dict(cell_id=target['cell_id'],family=target['family'],year=target['year'],paths=found[target['cell_id']],status='RECEIVED' if found[target['cell_id']] else 'NOT_RECEIVED'))
    cfg=dict(cfg,output=str(OUT),started_utc='2026-10-27T04:42:35+00:00',inputs=inputs)
    cfg['bindings'] += [dict(path=str(p.relative_to(ROOT)),sha256=lane.sha(p)) for p in [BASE/'csv_lane.py',BASE/'qualification.json',policy/'analysis_release_manifest.json',policy/'first_download_bundle.json',policy/'qualification.json']]
    write('input_config.json',cfg);write('discovery.json',dict(prior_complete_files=len(olds),prior_rows=299169,skipped=skips,cells=discovery,scope='3 held cells plus exact first Busan8 only',directory_scan='nonrecursive apartment CSV header candidates only'))
    print(lane.dump(dict(new_files=len(inputs),provisional_rows=sum(x['expected_rows'] for x in inputs),busan_received=sum(bool(v) for v in found.values()),busan_missing=[k for k,v in found.items() if not v])))
def worker():
    work=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY']);cfg=read(OUT/'input_config.json');g=R.ReferenceGuard(ROOT)
    g.admit();start=time.perf_counter();old=prior();old_shas=set(old)
    try:
        tmp=OUT/'tmp';tmp.mkdir();rawdir=OUT/'raw_snapshots';rawdir.mkdir()
        for k in ('TMP','TEMP','SQLITE_TMPDIR'):os.environ[k]=str(tmp)
        g.reserve_output(2147483648)
        for b in cfg['bindings']:lane.need(lane.sha(ROOT/b['path'],g)==b['sha256'],'SOURCE_OR_POLICY_BINDING_DRIFT')
        func=lane.reused_functions(cfg);db=lane.db_open(OUT/'observations.sqlite');resolved=[];results=[];failed=[]
        for original in cfg['inputs']:
            s=dict(original)
            if s['sha256'] is None:s['sha256']=lane.sha(Path(s['path']),g)
            if s['sha256'] in old_shas:
                results.append(dict(id=s['id'],sha256=s['sha256'],status='ALREADY_COMPLETE_SHA_NOT_REPROCESSED',input_rows=0,good_rows=0,error_rows=0));continue
            if any(z['sha256']==s['sha256'] for z in resolved):
                results.append(dict(id=s['id'],sha256=s['sha256'],status='DUPLICATE_ALIAS_NOT_REPROCESSED',input_rows=0,good_rows=0,error_rows=0));continue
            try:
                result=lane.ingest(s,db,rawdir,g,func);results.append(result);resolved.append(s)
                print(lane.dump(result),flush=True)
            except (ValueError,csv.Error,UnicodeError) as e:
                failed.append(dict(id=s['id'],sha256=s['sha256'],status='PARSING_FAILURE',reason=str(e)));print(lane.dump(failed[-1]),flush=True)
        lane.writej(work/'resolved_inputs.json',resolved);lane.writej(work/'parse_failures.json',failed)
        new=[]
        for sha,m,n,good,err in db.execute('SELECT sha,metadata,input_rows,good_rows,error_rows FROM files'):
            meta=json.loads(m);meta['duplicate_groups'],meta['duplicate_extra_occurrences']=db.execute('SELECT count(*),COALESCE(SUM(n-1),0) FROM raw_multiplicity WHERE file_sha=? AND n>1',(sha,)).fetchone()
            meta['truncation_observation']=dict(expected_sequence_end=meta['expected_rows'],actual_rows=n,errors=err,
                query_scope_checked=err==0,round_count_indicator=(n>0 and n%10000==0),
                independent_UI_total=None,same_snapshot_official_total=None,population_completeness='UNPROVEN',
                split_observation='Header claims entire planned year and province; no filename-part union used; provider export truncation still cannot be ruled out')
            new.append(meta)
        prior_release=read(BASE/'download_policy_v0_2/analysis_release_manifest.json')
        active=[dict(x,store=str(BASE/'observations.sqlite')) for x in prior_release['files'] if x['selected']]
        pending=[]
        for m in new:
            proposal=next((x for x in prior_release['files'] if x['file_sha256']==m['sha256'] and x.get('proposed_for_next_release')),None)
            chosen=bool(proposal and m['error_rows']==0)
            rec=dict(file_sha256=m['sha256'],path=m['path'],query=m['query'],selected=chosen,store=str(OUT/'observations.sqlite'),
                reason='Prior exact-SHA conditional selection, receipt passed' if chosen else 'No prior exact-SHA selection or alternative snapshot; retain pending/not selected',
                state='SELECTED_AFTER_RECEIPT' if chosen else 'REGISTERED_NOT_SELECTED')
            (active if chosen else pending).append(rec)
        selectors=[dict(id=x['file_sha256'],sha256=x['file_sha256'],selected=True,query=x['query']) for x in active]
        lane.check_selection(selectors)
        release_sha=hashlib.sha256(lane.dump(active+pending).encode()).hexdigest()
        for m in new:
            a=next((x for x in active if x['file_sha256']==m['sha256']),None)
            db.execute('INSERT INTO selections VALUES(?,?,?,?,?)',(release_sha,m['sha256'],m['id'],bool(a),'Prior SHA proposal after validation' if a else 'NOT_SELECTED_PENDING_OR_ALTERNATIVE'))
        db.commit();db.close()
        counts={s:x['input_rows'] for s,x in old.items()};counts.update({m['sha256']:m['input_rows'] for m in new})
        selected_count=sum(counts[x['file_sha256']] for x in active)
        lane.writej(work/'analysis_release_manifest.json',dict(version='RECEIPT_BATCH_RELEASE_V0_1',selection_sha=release_sha,active_files=active,unselected_new_files=pending,
            active_rows=selected_count,prior_active_rows=298972,auto_latest=False,scope_overlap_check='PASS',
            old_store_read_only=True,new_store=str(OUT/'observations.sqlite'),API_rows_merged=0,
            read_instruction='Read each active file_sha256 only from its specified store; do not union all stored snapshots or selection versions'))
        lane.writej(work/'file_coverage_manifest.json',new)
        cumulative=dict(prior_files=len(old),prior_rows=sum(x['input_rows'] for x in old.values()),new_files=len(new),new_rows=sum(m['input_rows'] for m in new),
          cumulative_files=len(old)+len(new),cumulative_rows=sum(counts.values()),new_good_rows=sum(m['good_rows'] for m in new),new_error_rows=sum(m['error_rows'] for m in new),
          new_repeated_extra_occurrences=sum(m['duplicate_extra_occurrences'] for m in new),selected_files=len(active),selected_rows=selected_count,
          unselected_new_files=len(pending),parse_failures=failed,elapsed_seconds=time.perf_counter()-start,
          db_bytes=(OUT/'observations.sqlite').stat().st_size,raw_bytes=sum(p.stat().st_size for p in rawdir.iterdir()),
          comparison_reruns=0,spatialization=0,API_calls=0,prior_store_modified=False)
        lane.writej(work/'processing_candidate.json',cumulative)
        receipt=g.publication_gate();lane.writej(work/'worker_resource_receipt.json',receipt)
    except BaseException as e:
        lane.writej(work/'primary_exception.json',dict(type=type(e).__name__,reason=str(e),traceback=traceback.format_exc()))
        if not (work/'worker_resource_receipt.json').exists():lane.writej(work/'worker_resource_receipt.json',g.receipt())
        raise
    finally:g.reader.close()
def supervise():
    env=dict(os.environ);env['PYTHONDONTWRITEBYTECODE']='1'
    work=OUT/'supervised';cmd=[sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'worker']
    result=R.supervise(cmd,str(ROOT),env,work)
    if result['status']=='COMPLETE':write('qualification.json',dict(status='RECEIPT_PROCESSING_COMPLETE_NOT_POPULATION_COMPLETENESS',supervisor=result,result=read(work/'processing_candidate.json'),source_sha=lane.sha(Path(__file__)),processor_sha=lane.sha(BASE/'csv_lane.py')))
    print(lane.dump(result));raise SystemExit(0 if result['status']=='COMPLETE' else 1)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['prepare','run','worker']);args=ap.parse_args()
    {'prepare':prepare,'run':supervise,'worker':worker}[args.mode]()
