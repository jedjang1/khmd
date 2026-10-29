"""One explicit invocation, frozen scope, unchanged parser and resource supervisor.
No watcher, downloader, API access, latest-snapshot rule, or production authority.
All run directories are append-only. An unfinished run blocks the next invocation.
"""
import argparse,calendar,csv,hashlib,importlib.util,json,os,sqlite3,subprocess,sys,time,traceback
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent;BASE=HERE.parent;ROOT=BASE.parents[3]
sys.path.insert(0,str(BASE))
import csv_lane as lane
import discovery
import candidate_gate
loader=importlib.util.spec_from_file_location('prior_header_reader',BASE/'receipt_batch_v0_1/receive.py')
headers=importlib.util.module_from_spec(loader);loader.loader.exec_module(headers)
read=lane.readj;write=lane.writej;need=lane.need

def stamp():return datetime.now(timezone.utc).isoformat()
def csvout(p,rows):
    if not rows:return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with p.open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,keys);w.writeheader()
        for r in rows:w.writerow({k:lane.dump(v) if isinstance(v,(dict,list)) else v for k,v in r.items()})
def query(c):return dict(family=c['family'],province=c['province'],district='전체',date_from=c['date_from'],date_to=c['date_to'])
def pins_check(settings,g=None):
    for b in settings['pins']:need(lane.sha(Path(b['path']),g)==b['sha256'],'PIN_DRIFT:'+b['path'])
    # Prevent silently forking from a newer run made with the predecessor receiver.
    predecessor=Path(settings['predecessor_receiver'])
    predecessor_state=resolve_state(read(predecessor/'settings.json'),predecessor/'runs')
    need(predecessor_state['receipt_sha256']==settings['baseline_receipt_sha256'],'PREDECESSOR_RECEIPT_HEAD_CHANGED')
    code=read(HERE/'code_bindings.json')
    for b in code:need(lane.sha(HERE/b['path'],g)==b['sha256'],'RECEIVER_SOURCE_DRIFT:'+b['path'])

def classify(cond,cells):
    """Header facts only. Absent hidden UI controls are not invented."""
    family={'아파트(매매)':'SALE','아파트(전월세)':'RENT'}.get(cond.get('실거래구분'))
    region=[c for c in cells if c['family']==family and c['province']==cond.get('시도')]
    if not region:return [],'OUTSIDE_FROZEN_SCOPE'
    dates=cond.get('계약일자','').split(' ~ ')
    if len(dates)!=2:return [c['cell_id'] for c in region],'DATE_HEADER_UNREADABLE'
    lo,hi=dates
    try:
        datetime.strptime(lo,'%Y-%m-%d');datetime.strptime(hi,'%Y-%m-%d');need(lo<=hi,'DATE_ORDER')
    except ValueError:return [c['cell_id'] for c in region],'DATE_HEADER_UNREADABLE'
    matching=[c for c in region if max(lo,c['date_from'])<=min(hi,c['date_to'])]
    if not matching:return [],'OUTSIDE_FROZEN_SCOPE'
    ids=[c['cell_id'] for c in matching]
    exact=len(matching)==1 and lo==matching[0]['date_from'] and hi==matching[0]['date_to']
    required={'주소구분':'지번주소','시군구':'전체','읍면동':'전체','면적':'전체','금액선택':'전체'}
    # Some export headers name the locality control '읍면동/도로명'. No inferred synonyms.
    if '읍면동' not in cond and '읍면동/도로명' in cond:
        required.pop('읍면동');required['읍면동/도로명']='전체'
    known=set(required)|{'계약일자','실거래구분','시도'}
    filters_ok=all(cond.get(k)==v for k,v in required.items())
    filters_ok=filters_ok and all(v=='전체' for k,v in cond.items() if k not in known)
    return ids,('ELIGIBLE_FULL_YEAR' if exact and filters_ok else 'SPLIT_OR_FILTER_SCOPE_HOLD')

def choose(cell,seen,registered,active,blocked):
    """Snapshot uniqueness precedes selection; no arbitrary pairing or latest wins."""
    q=query(cell)
    pool=set(seen)
    pool.update(s for s,m in registered.items() if m['query']==q)
    prior=[x for x in active if lane.overlap(q,x['query'])]
    if blocked:return None,'HEADER_OR_SCOPE_CONFLICT_HOLD'
    if not pool:return None,'NOT_RECEIVED'
    if prior:
        if len(prior)==1 and prior[0]['query']==q and pool<= {prior[0]['file_sha256']}:
            return None,'ALREADY_SELECTED_UNCHANGED'
        return None,'EXISTING_SELECTION_PRESERVED_CONFLICT_HOLD'
    if not pool:return None,'NOT_RECEIVED'
    if len(pool)>1:return None,'MULTIPLE_SNAPSHOTS_SELECTION_PENDING'
    s=next(iter(pool));m=registered.get(s)
    if not m or m['error_rows'] or m['input_rows']!=m['good_rows']+m['error_rows']:
        return None,'PARSE_OR_CONSERVATION_HOLD'
    return dict(file_sha256=s,path=m['path'],query=q,selected=True,store=m['store'],cell_id=cell['cell_id'],state='SELECTED_AFTER_RECEIPT',reason='Direct user approval; unique verified SHA within explicit frozen 86-cell scope'), 'UNIQUE_CLEAN_SELECTED'

def baseline_state(settings):
    return dict(receipt_sha256=settings['baseline_receipt_sha256'],release=settings['baseline_release'],plan=settings['baseline_plan'],registry=settings['baseline_registry'])
def resolve_state(settings,runs):
    state=baseline_state(settings)
    pending=[]
    if runs.exists():
        for p in runs.iterdir():
            need(p.is_dir() and not p.is_symlink(),'UNEXPECTED_RUN_ENTRY')
            need((p/'final_receipt.json').exists(),'UNFINISHED_RUN_REQUIRES_INSPECTION:'+str(p))
            r=read(p/'final_receipt.json')
            need(r['status']=='COMPLETED_RECEIPT','INCOMPLETE_RECEIPT')
            for b in r['artifacts']:need(lane.sha(p/b['path'])==b['sha256'],'RUN_ARTIFACT_DRIFT:'+str(p/b['path']))
            pending.append((p,r))
    while pending:
        children=[x for x in pending if x[1]['parent_receipt_sha256']==state['receipt_sha256']]
        need(len(children)==1,'RECEIPT_CHAIN_BRANCH_OR_GAP')
        p,r=children[0];pending.remove(children[0])
        state=dict(receipt_sha256=lane.sha(p/'final_receipt.json'),release=str(p/'analysis_release_manifest.json'),plan=str(p/'national_cell_status.json'),registry=str(p/'registry_index.json'))
    return state

def load_registry(index,g):
    result={}
    bystore={}
    for s,r in index.items():bystore.setdefault(r['store'],{})[s]=r
    for path,expected in bystore.items():
        lane.safe(path);g.checkpoint('registry_metadata_before')
        with sqlite3.connect(Path(path).as_uri()+'?mode=ro&immutable=1',uri=True) as db:
            for s,m,n,good,e in db.execute('SELECT sha,metadata,input_rows,good_rows,error_rows FROM files'):
                need(s in expected,'UNREGISTERED_STORE_MUTATION')
                b=expected[s];need(hashlib.sha256(m.encode()).hexdigest()==b['metadata_sha256'],'REGISTERED_METADATA_DRIFT')
                need((n,good,e)==(b['input_rows'],b['good_rows'],b['error_rows']),'REGISTRY_COUNTS_DRIFT')
                need(s not in result,'DUPLICATE_REGISTRATION');result[s]=dict(json.loads(m),store=path)
        g.checkpoint('registry_metadata_completed')
    need(set(result)==set(index),'REGISTERED_FILE_MISSING')
    return result

def validate_scope_plan(settings, plan, cells):
    approved=set(settings['approved_additional_cell_ids'])
    need(len(approved)==settings['scope_count']==86,'APPROVED_SCOPE_COUNT')
    need(len(cells)==len({c['cell_id'] for c in cells}) and {c['cell_id'] for c in cells}<=approved,'UNAPPROVED_RECEIPT_SCOPE')
    byid={c['cell_id']:c for c in plan}
    need(len(plan)==len(byid)==480 and approved<=set(byid),'PLAN_SCOPE_IDENTITY')
    for c in cells:
        need(query(c)==query(byid[c['cell_id']]),'PLAN_QUERY_DRIFT')
        need(byid[c['cell_id']]['status'] in ('DOWNLOAD_READY','RECEIPT_PENDING','RECEIVED_PROCESSED_QUERY_SCOPE'),'CELL_NOT_ADMITTED')
    need({c['cell_id'] for c in plan if c['status']=='REQUIRES_REGION_OR_UI_CONFIRMATION'}==set(settings['held_cell_ids']),'HELD_SCOPE_CHANGED')

def process(out,settings,parent,cells,downloads,g,receipt_note=None):
    t=time.perf_counter();raw=out/'raw_snapshots';raw.mkdir();tmp=out/'tmp';tmp.mkdir()
    for k in ('TMP','TEMP','SQLITE_TMPDIR'):os.environ[k]=str(tmp)
    release=read(Path(parent['release']));plan=read(Path(parent['plan']));index=read(Path(parent['registry']))
    registered=load_registry(index,g);before=set(registered);config=read(BASE/'config.json');func=lane.reused_functions(config)
    need(len(plan)==len({c['cell_id'] for c in plan})==480,'PLAN_IDENTITY')
    held={c['cell_id'] for c in plan if c['status']=='REQUIRES_REGION_OR_UI_CONFIRMATION'}
    validate_scope_plan(settings, plan, cells)
    need(held==set(settings['held_cell_ids']) and not held & {c['cell_id'] for c in cells},'HELD_SCOPE_CHANGED')
    excluded=[];exclusions=read(HERE/'candidate_exclusions.json');outside_records=[];specs={};seen={c['cell_id']:set() for c in cells};issues=[];blocked=set();skips=[];outside=0
    byid={c['cell_id']:c for c in cells}
    notes=receipt_note or {'files':[]};noted={x['sha256']:x for x in notes['files']}
    for p in sorted(downloads.glob('*.csv')):
        g.checkpoint('header_before');lane.safe(p)
        item=discovery.inspect_file(p,cells,registered,headers.header,classify,lane.sha,g)
        status=item['status'];ids=item['cell_ids']
        exclusion=candidate_gate.is_excluded(item,exclusions)
        if exclusion:
            excluded.append(dict(item,exclusion=exclusion));continue
        if status in ('OUTSIDE_FROZEN_SCOPE','OUTSIDE_OTHER_CSV_SCHEMA'):
            outside+=1
            if status=='OUTSIDE_OTHER_CSV_SCHEMA':outside_records.append(item)
            continue
        if status=='REGISTERED_EXISTING_INPUT':
            skips.append(item)
            if item['scope_classification']=='ELIGIBLE_FULL_YEAR' and item['registered_query']==query(byid[ids[0]]):
                seen[ids[0]].add(item['sha256'])
            continue
        if status!='ELIGIBLE_FULL_YEAR':
            blocked.update(ids);issues.append(item);continue
        c=byid[ids[0]];s=item['sha256'];cond=item['conditions'];cols=item['columns']
        seen[c['cell_id']].add(s)
        if s in specs:continue
        try:n=headers.last_no(p,cols)
        except (ValueError,UnicodeError,csv.Error,OSError) as e:
            blocked.add(c['cell_id']);issues.append(dict(path=str(p),cell_ids=ids,status='TAIL_OR_ZERO_REVIEW_REQUIRED',reason=str(e)));continue
        note=noted.get(s,{})
        specs[s]=dict(id=c['cell_id']+'_'+s[:12],cell_id=c['cell_id'],path=str(p),sha256=s,expected_rows=n,encoding='cp949',columns=cols,conditions=cond,query=query(c),selected=False,
            source_url='https://rt.molit.go.kr/pt/xls/xls.do?mobileAt=',download_started_at=note.get('download_started_at'),download_completed_at=note.get('download_completed_at'),
            acquisition_time_status='USER_PROVIDED_NOT_INDEPENDENTLY_VERIFIED' if note.get('download_started_at') or note.get('download_completed_at') else 'UNKNOWN; filename/mtime are not acquisition times',
            hidden_conditions=dict(planned=dict(complex='전체',contract_type='전체' if c['family']=='RENT' else 'NOT_APPLICABLE',price_lower='',price_upper=''),provided=note.get('conditions',{}),evidence=note.get('evidence','UNKNOWN; not serialized in header; plan is not observation')),
            source_evidence=dict(frozen_cell=c,scope_sha256=lane.sha(HERE/'frozen_cells.json')),prior_API_comparison_scope='NOT_RUN',spatial_status='NOT_RUN')
        # Explicit contradictory sidecar statements cannot be ignored by a clean header.
        allowed=dict(complex='전체',contract_type='전체' if c['family']=='RENT' else 'NOT_APPLICABLE',price_lower='',price_upper='')
        if any(k not in allowed or v!=allowed[k] for k,v in note.get('conditions',{}).items()):blocked.add(c['cell_id'])
    write(out/'candidate_exclusions_applied.json',excluded)
    write(out/'discovery.json',dict(specs=list(specs.values()),issues=issues,existing_sha_skips=skips,outside_scope_headers=outside,outside_records=outside_records,receipt_note=notes))
    if settings.get('targeted_full_stream_preflight'):
        validation=[candidate_gate.validate(spec,lane,g,func) for spec in specs.values()]
        write(out/'target_stream_validation.json',validation)
        need(len(validation)<=1,'TARGET_MULTIPLE_NEW_SNAPSHOTS_HOLD')
        need(all(v['status']=='PASS' for v in validation),'TARGET_STREAM_VALIDATION_HOLD')
    new=[];failures=[];stores=[]
    for s,spec in specs.items():
        # One fresh DB per immutable snapshot, unchanged 2GiB per-DB budget/cache.
        store=out/(spec['cell_id']+'_'+s[:12]+'.sqlite');g.reserve_output(2147483648);db=lane.db_open(store);stores.append(str(store))
        try:
            r=lane.ingest(spec,db,raw,g,func)
            need(r['input_rows'] is not None,'SOURCE_NOT_INGESTED')
            stored=db.execute('SELECT metadata,input_rows,good_rows,error_rows FROM files WHERE sha=?',(s,)).fetchone()
            m=json.loads(stored[0]);m['store']=str(store)
            m['duplicate_groups'],m['duplicate_extra_occurrences']=db.execute('SELECT count(*),COALESCE(SUM(n-1),0) FROM raw_multiplicity WHERE file_sha=? AND n>1',(s,)).fetchone()
            index[s]=dict(store=str(store),input_rows=stored[1],good_rows=stored[2],error_rows=stored[3],metadata_sha256=hashlib.sha256(stored[0].encode()).hexdigest())
            registered[s]=m;new.append(m);print(lane.dump(r),flush=True)
        except (ValueError,UnicodeError,csv.Error,OSError) as e:
            blocked.add(spec['cell_id']);failures.append(dict(cell_id=spec['cell_id'],sha256=s,path=spec['path'],reason=str(e)))
        finally:db.close()
    active=list(release['active_files']);added=[];records=[]
    for c in cells:
        rec,status=choose(c,seen[c['cell_id']],registered,active,c['cell_id'] in blocked)
        if rec:
            trial=active+[rec]
            lane.check_selection([dict(id=x['file_sha256'],sha256=x['file_sha256'],selected=True,query=x['query']) for x in trial])
            active=trial;added.append(rec)
        known={s for s,m in registered.items() if m['query']==query(c)}
        selected=[x['file_sha256'] for x in active if x['query']==query(c)]
        records.append(dict(cell_id=c['cell_id'],status=status,received_sha256=sorted(seen[c['cell_id']]|known),registered_sha256=sorted(known),selected_sha256=selected))
    need({x['file_sha256'] for x in release['active_files']} <= {x['file_sha256'] for x in active},'PRIOR_SELECTION_REMOVED')
    byrecord={r['cell_id']:r for r in records}
    for c in plan:
        if c['cell_id'] not in byrecord:continue
        r=byrecord[c['cell_id']];good=[s for s in r['registered_sha256'] if registered[s]['error_rows']==0]
        c.update(received=bool(r['received_sha256']),processed=bool(good),analysis_selected=bool(r['selected_sha256']),received_file_sha256=r['received_sha256'],selected_file_sha256=r['selected_sha256'],received_snapshot_count=len(r['received_sha256']),receipt_detail=r['status'],population_complete=False)
        c['status']='RECEIVED_PROCESSED_QUERY_SCOPE' if good else ('RECEIPT_PENDING' if c['received'] else 'DOWNLOAD_READY')
    need(held=={c['cell_id'] for c in plan if c['status']=='REQUIRES_REGION_OR_UI_CONFIRMATION'},'HELD_CELLS_CHANGED')
    manifest=dict(release,version='MANUAL_REMAINING86_RECEIPT_RELEASE_V1',parent=dict(path=parent['release'],sha256=lane.sha(Path(parent['release']))),active_files=active,active_file_count=len(active),active_rows=sum(registered[x['file_sha256']]['good_rows'] for x in active),added_files=len(added),unresolved_cells=[r for r in records if 'HOLD' in r['status'] or 'PENDING' in r['status']],excluded_current_files=[],auto_latest=False,production_authority=False,selection_approval=settings['user_approval'])
    manifest['candidate_exclusions']=dict(path=str(HERE/'candidate_exclusions.json'),sha256=lane.sha(HERE/'candidate_exclusions.json'))
    write(out/'analysis_release_manifest.json',manifest);write(out/'national_cell_status.json',plan);csvout(out/'national_cell_status.csv',plan)
    write(out/'registry_index.json',index);write(out/'file_coverage_manifest.json',new);csvout(out/'cell_receipts.csv',records)
    write(out/'unresolved.json',dict(cells=manifest['unresolved_cells'],discovery_issues=issues,file_failures=failures,missing_cells=[r['cell_id'] for r in records if r['status']=='NOT_RECEIVED']))
    csvout(out/'file_processing_summary.csv',[dict(sha256=m['sha256'],path=m['path'],store=m['store'],input_rows=m['input_rows'],good_rows=m['good_rows'],error_rows=m['error_rows'],repeated_extra_occurrences=m['duplicate_extra_occurrences']) for m in new])
    target=None
    if added:
        m=registered[added[0]['file_sha256']];months=m['observed_month_counts']
        if months:
            ym=sorted(months)[0];year=int(ym[:4]);month=int(ym[4:])
            target=dict(family=m['query']['family'],province=m['query']['province'],start=f'{year:04}-{month:02}-01',end=f'{year:04}-{month:02}-{calendar.monthrange(year,month)[1]:02}',expected=months[ym],file_sha256=m['sha256'])
    write(out/'r_target.json',dict(target=target,release_sha256=lane.sha(out/'analysis_release_manifest.json')))
    result=dict(new_files=len(new),new_rows=sum(m['input_rows'] for m in new),new_errors=sum(m['error_rows'] for m in new),repeated_extra_occurrences=sum(m['duplicate_extra_occurrences'] for m in new),cumulative_files=len(index),cumulative_rows=sum(m['input_rows'] for m in index.values()),selected_files=len(active),selected_rows=manifest['active_rows'],added_selected_files=len(added),existing_sha_skips=len(skips),received_cells=sum(c['received'] for c in plan),processed_cells=sum(c['processed'] for c in plan),analysis_selected_cells=sum(c['analysis_selected'] for c in plan),not_received_cells=sum(not c['received'] for c in plan),plan_status_counts=dict(Counter(c['status'] for c in plan)),scope_count=len(cells),cell_conflicts=len(manifest['unresolved_cells']),parse_failures=len(failures),discovery_holds=len(issues),processing_seconds=time.perf_counter()-t,new_store_bytes=sum(Path(s).stat().st_size for s in stores),raw_bytes=sum(p.stat().st_size for p in raw.iterdir()),population_completeness='UNPROVEN',Seoul='PILOT_PARTIAL',Cheongju='PARTIAL_MATCH',production_API=0,START_END=0,authorization=0,Batch204=0,API_ledger_addition=0,downloads=0,guard_changes=0)
    write(out/'processing_result.json',result)
    return result

def worker(out):
    g=lane.resource.ReferenceGuard(ROOT);work=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY'])
    try:
        g.admit();settings=read(HERE/'settings.json');pins_check(settings,g)
        invocation=read(out/'invocation.json');cells=read(HERE/'frozen_cells.json')
        need(len(cells)==len({c['cell_id'] for c in cells})==settings['scope_count']==86,'FROZEN_SCOPE_COUNT')
        if invocation.get('cell'):
            cells=[c for c in cells if c['cell_id']==invocation['cell']]
            need(len(cells)==1,'TARGET_CELL_OUTSIDE_FROZEN_SCOPE')
            settings=dict(settings,targeted_full_stream_preflight=True)
        result=process(out,settings,invocation['parent'],cells,Path(invocation['downloads']),g,invocation['receipt_note'])
        pins_check(settings,g);write(work/'worker_resource_receipt.json',g.publication_gate());print(lane.dump(result),flush=True)
    except BaseException as e:
        write(work/'primary_exception.json',dict(type=type(e).__name__,reason=str(e),traceback=traceback.format_exc()))
        if not (work/'worker_resource_receipt.json').exists():write(work/'worker_resource_receipt.json',g.receipt())
        raise
    finally:g.reader.close()

def run_r(out,settings):
    if not read(out/'r_target.json')['target']:
        r=dict(status='NOT_RUN_NO_NEW_SELECTED_NONZERO_SCOPE')
        write(out/'r_connection_validation.json',r);return r
    tmp=out/'r_runtime_tmp';tmp.mkdir();env=dict(os.environ)
    for k in ('TMPDIR','TMP','TEMP','R_USER'):env[k]=str(tmp)
    env.update(R_LIBS_USER=settings['r_library'],R_LIBS=settings['r_library'],LC_ALL='English_United States.utf8',R_DEFAULT_PACKAGES='datasets,utils,grDevices,graphics,stats,methods')
    try:
        with (out/'r_stdout.log').open('x',encoding='utf-8') as so,(out/'r_stderr.log').open('x',encoding='utf-8') as se:
            p=subprocess.run([settings['rscript'],'--vanilla',str(HERE/'validate_r.R'),str(out)],cwd=str(ROOT),env=env,stdout=so,stderr=se,timeout=300)
        need(p.returncode==0,'R_EXIT_'+str(p.returncode))
        r=read(out/'r_connection_validation.json');need(r['status']=='PASS','R_NOT_PASS');return r
    except (OSError,ValueError,subprocess.TimeoutExpired) as e:
        r=dict(status='NOT_VERIFIED',reason=str(e),note='Processing/release retained; no existing files will be reprocessed. Inspect R logs; no build/check or automatic retry.')
        write(out/'r_unverified.json',r);return r

def run(downloads=None,note=None,cell=None):
    settings=read(HERE/'settings.json');pins_check(settings)
    lane.safe(HERE);runs=lane.safe(HERE/'runs');runs.mkdir(exist_ok=True)
    # A process-owned lock only; no removal of a stale lock from an interrupted run.
    lock=HERE/'receipt_running.lock';owned=False
    try:
        with lock.open('x',encoding='utf-8') as f:f.write(str(os.getpid()))
        owned=True;parent=resolve_state(settings,runs)
        source=lane.safe(Path(downloads or settings['downloads']));need(source.is_dir(),'DOWNLOAD_DIRECTORY_MISSING')
        out=runs/datetime.now(timezone.utc).strftime('receipt_%Y%m%dT%H%M%S_%fZ');out.mkdir()
        notes=read(Path(note)) if note else {'files':[]}
        need(isinstance(notes.get('files'),list),'RECEIPT_NOTE_SCHEMA')
        write(out/'invocation.json',dict(started_at=stamp(),parent=parent,downloads=str(source),receipt_note=notes,cell=cell,scope_sha256=lane.sha(HERE/'frozen_cells.json')))
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1');t=time.perf_counter()
        sup=lane.resource.supervise([sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'worker','--out',str(out)],str(ROOT),env,out/'supervised')
        need(sup['status']=='COMPLETE','RESOURCE_HOLD_OR_WORKER_FAILURE:'+str(out/'supervised'))
        r=run_r(out,settings);result=read(out/'processing_result.json')
        names=['invocation.json','analysis_release_manifest.json','national_cell_status.json','registry_index.json','processing_result.json','file_coverage_manifest.json','unresolved.json','r_target.json','discovery.json','cell_receipts.csv','candidate_exclusions_applied.json']
        if (out/'target_stream_validation.json').exists():names.append('target_stream_validation.json')
        names += ['r_connection_validation.json'] if (out/'r_connection_validation.json').exists() else ['r_unverified.json']
        write(out/'final_receipt.json',dict(status='COMPLETED_RECEIPT',completed_at=stamp(),parent_receipt_sha256=parent['receipt_sha256'],result=result,r_connection=r,supervisor=sup,elapsed_seconds=time.perf_counter()-t,artifacts=[dict(path=n,sha256=lane.sha(out/n)) for n in names]))
        print(lane.dump(dict(output=str(out),result=result,r_connection=r)),flush=True)
        return 0 if r['status']!='NOT_VERIFIED' and result['parse_failures']==0 and result['cell_conflicts']==0 and result['discovery_holds']==0 else 2
    finally:
        if owned:lock.unlink() # only this invocation's temporary lock, never source/data

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['run','worker']);ap.add_argument('--out',type=Path);ap.add_argument('--downloads');ap.add_argument('--receipt-note');ap.add_argument('--cell');a=ap.parse_args()
    if a.mode=='worker':worker(a.out)
    else:sys.exit(run(a.downloads,a.receipt_note,a.cell))
