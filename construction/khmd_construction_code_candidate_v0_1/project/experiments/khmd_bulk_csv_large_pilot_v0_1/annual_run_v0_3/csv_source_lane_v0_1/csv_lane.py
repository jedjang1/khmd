"""CSV source observations, not transaction IDs, API authority, or a fused population.

Only configured pilot inputs are allowed. SQLite is bounded and disk backed.
Original CP949 bytes live in immutable content-addressed snapshots. Read-only
comparison/spatial evidence is referenced, never rerun or promoted.
"""
import argparse, ast, csv, hashlib, json, os, re, socket, sqlite3, sys, time, unicodedata
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[3]
sys.path.insert(0,str(ROOT/'src'))
import khmd_reference_resource_monitor_v0_2 as resource
CHUNK=1024*1024
def dump(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def readj(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def need(x,c):
    if not x: raise ValueError(c)
def writej(p,x):
    with Path(p).open('x',encoding='utf-8') as f: json.dump(x,f,ensure_ascii=False,indent=2)
def netblock(*a,**k): raise RuntimeError('NETWORK_FORBIDDEN')
socket.create_connection=socket.socket.connect=socket.socket.connect_ex=netblock
def safe(p):
    p=Path(p).absolute()
    for q in [p,*p.parents]:
        if q.exists(): need(not q.is_symlink() and not (q.stat().st_file_attributes & 0x400),'REPARSE_FORBIDDEN')
    return p
def sha(p,guard=None):
    h=hashlib.sha256()
    with safe(p).open('rb') as f:
        while True:
            if guard: guard.checkpoint('hash_before')
            b=f.read(CHUNK)
            if not b: break
            h.update(b)
            if guard: guard.checkpoint('hash_after')
    return h.hexdigest()
def reused_functions(config):
    """Compile unchanged pure parsing primitives; importing original driver not needed."""
    p=ROOT/'experiments/khmd_bulk_csv_large_pilot_v0_1/validate_large_csv_v0_3.py'
    b=next(x for x in config['bindings'] if x['path']==str(p.relative_to(ROOT)))
    need(sha(p)==b['sha256'],'PARSER_SOURCE_DRIFT')
    names={'need','text','state','optional','num'}
    tree=ast.parse(p.read_text(encoding='utf-8-sig'))
    nodes=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name in names]
    need(len(nodes)==len(names),'PARSER_PRIMITIVES')
    env={'re':re,'unicodedata':unicodedata,'Decimal':Decimal}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(p)+':unchanged_pure_functions','exec'),env)
    return env
def overlap(a,b):
    return (a['family']==b['family'] and a['province']==b['province'] and
        (a['district']=='전체' or b['district']=='전체' or a['district']==b['district']) and
        max(a['date_from'],b['date_from'])<=min(a['date_to'],b['date_to']))
def check_selection(inputs):
    need(len({x['id'] for x in inputs})==len(inputs),'DUPLICATE_CONFIG_ID')
    selected=[x for x in inputs if x['selected']]
    need(len({x['sha256'] for x in selected})==len(selected),'DUPLICATE_SNAPSHOT_SELECTED')
    pairs=[]
    for i,a in enumerate(inputs):
        for b in inputs[i+1:]:
            if overlap(a['query'],b['query']):
                pairs.append({'a':a['id'],'b':b['id'],'both_selected':a['selected'] and b['selected'],
                              'meaning':'Query scope overlap; not proof of identical transactions'})
                need(not (a['selected'] and b['selected']),'ANALYSIS_QUERY_OVERLAP')
    return pairs
def db_open(p):
    c=sqlite3.connect(safe(p))
    c.execute('PRAGMA cache_size=-4096');c.execute('PRAGMA temp_store=FILE');c.execute('PRAGMA mmap_size=0')
    c.execute('PRAGMA journal_mode=DELETE');c.execute('PRAGMA synchronous=FULL')
    c.execute('PRAGMA max_page_count=524288')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS files(sha TEXT PRIMARY KEY, metadata TEXT NOT NULL, input_rows INT, good_rows INT, error_rows INT);
    CREATE TABLE IF NOT EXISTS observations(obs_id TEXT PRIMARY KEY,file_sha TEXT NOT NULL,ordinal INT NOT NULL,
      physical_line_start INT,physical_line_end INT,byte_start INT,byte_end INT,raw_values TEXT NOT NULL,
      states TEXT NOT NULL,derived TEXT,raw_content_digest TEXT,row_status TEXT,error TEXT,
      UNIQUE(file_sha,ordinal));
    CREATE TABLE IF NOT EXISTS raw_multiplicity(file_sha TEXT,content_digest TEXT,n INT NOT NULL,PRIMARY KEY(file_sha,content_digest)) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS selections(selection_sha TEXT,file_sha TEXT,config_id TEXT,selected INT,reason TEXT,PRIMARY KEY(selection_sha,config_id));
    CREATE VIEW IF NOT EXISTS source_observations AS SELECT o.*,json_extract(f.metadata,'$.columns') AS columns,
      json_extract(f.metadata,'$.source_url') AS source_url,'CSV' AS source_kind,
      'NOT_RUN' AS spatial_status,NULL AS PNU,NULL AS grid_id,NULL AS historical_jurisdiction,
      NULL AS API_query_code FROM observations o JOIN files f ON o.file_sha=f.sha;
    CREATE VIEW IF NOT EXISTS analysis_observations AS SELECT s.selection_sha,s.config_id,o.* FROM selections s
      JOIN source_observations o ON s.file_sha=o.file_sha WHERE s.selected=1 AND o.row_status='PARSED';
    ''')
    c.commit();return c
class Lines:
    def __init__(self,f,encoding,guard): self.f=f;self.encoding=encoding;self.guard=guard;self.n=0;self.size=0
    def __iter__(self): return self
    def __next__(self):
        b=self.f.readline(CHUNK+1)
        if not b: raise StopIteration
        need(len(b)<=CHUNK,'PHYSICAL_LINE_TOO_LARGE')
        self.n+=1;self.size+=len(b)
        if self.size>=65536: self.guard.checkpoint('csv_bytes_completed');self.size=0
        return b.decode(self.encoding,errors='strict')
def snapshot(spec,rawdir,guard):
    p=Path(spec['path'])
    if not p.exists(): return None,'FILE_ABSENT'
    p=safe(p); before=p.stat(); h=sha(p,guard)
    need(h==spec['sha256'],'SOURCE_SHA_MISMATCH:'+spec['id'])
    target=safe(rawdir/(h+'.csv'))
    if target.exists(): need(sha(target,guard)==h,'PRESERVED_SNAPSHOT_DRIFT')
    else:
        guard.reserve_output(before.st_size)
        acc=hashlib.sha256()
        with p.open('rb') as src,target.open('xb') as dest:
            while True:
                guard.checkpoint('copy_before'); b=src.read(CHUNK)
                if not b: break
                dest.write(b); acc.update(b);guard.checkpoint('copy_completed')
            dest.flush();os.fsync(dest.fileno())
        need(acc.hexdigest()==h,'COPY_SOURCE_CHANGED')
    after=p.stat()
    need((before.st_size,before.st_mtime_ns,before.st_ino)==(after.st_size,after.st_mtime_ns,after.st_ino),'SOURCE_IDENTITY_CHANGED')
    return target,'SNAPSHOT_VERIFIED'
def coverage_state(rows,errors):
    if errors: return 'PARSED_WITH_ERROR_ROWS_NOT_ANALYSIS_READY'
    if rows==0: return 'QUERY_SCOPE_ZERO_OBSERVED_UNVERIFIED_COMPLETENESS'
    return 'PARSED_NONZERO_COMPLETENESS_UNPROVEN'
def ingest(spec,c,rawdir,guard,func):
    snap,status=snapshot(spec,rawdir,guard)
    if snap is None: return dict(id=spec['id'],status=status,input_rows=None,good_rows=None,error_rows=None)
    old=c.execute('SELECT metadata,input_rows,good_rows,error_rows FROM files WHERE sha=?',(spec['sha256'],)).fetchone()
    if old:
        meta=json.loads(old[0]);need(meta['conditions']==spec['conditions'] and meta['columns']==spec['columns'],'SAME_SNAPSHOT_METADATA_CONFLICT')
        return dict(id=spec['id'],sha256=spec['sha256'],status='ALREADY_REGISTERED_NO_NEW_ROWS',input_rows=old[1],good_rows=old[2],error_rows=old[3])
    months=Counter();regions=Counter();obs=Counter();rows=good=errors=0; dates=[]
    minimum=maximum=None; pre=[]
    try:
        c.execute('BEGIN')
        with snap.open('rb') as f:
            lines=Lines(f,spec['encoding'],guard); rr=csv.reader(lines,strict=True)
            for values in rr:
                if values and values[0]=='NO': break
                need(len(pre)<100 and len(values)==1,'PREAMBLE_SCHEMA');pre.append(values[0])
            else: raise ValueError('HEADER_MISSING')
            columns=values
            need(columns==spec['columns'] and len(columns)==len(set(columns)),'HEADER_DRIFT')
            cond={x.split(' : ',1)[0]:x.split(' : ',1)[1] for x in pre if ' : ' in x}
            need(cond==spec['conditions'],'QUERY_CONDITIONS_DRIFT')
            while True:
                start=f.tell();firstline=lines.n+1
                try: values=next(rr)
                except StopIteration: break
                rows+=1; error=None; derived=None
                states=[func['state'](v) for v in values]
                for k,v in zip(columns,states): obs[(k,v)]+=1
                try:
                    need(len(values)==len(columns),'ROW_WIDTH');r=dict(zip(columns,values))
                    need(r['NO']==str(rows),'ROW_NUMBER_SEQUENCE')
                    ym=r['계약년월'];need(bool(re.fullmatch(r'\d{6}',ym)),'CONTRACT_MONTH')
                    day=date(int(ym[:4]),int(ym[4:]),int(r['계약일'])).isoformat()
                    q=spec['query'];need(q['date_from']<=day<=q['date_to'],'ROW_DATE_OUTSIDE_QUERY')
                    prefix=q['province']+' '+(q['district']+' ' if q['district']!='전체' else '')
                    need(r['시군구'].startswith(prefix),'ROW_REGION_OUTSIDE_QUERY')
                    numeric={k:func['num'](r[k],k=='전용면적(㎡)') for k in
                        ['전용면적(㎡)','층','건축년도','거래금액(만원)','보증금(만원)','월세금(만원)','종전계약 보증금(만원)','종전계약 월세(만원)'] if k in r}
                    derived=dict(contract_date=day,contract_month=ym,csv_region_literal=r['시군구'],numeric=numeric,
                                 derivation='Existing num() only; raw/states remain independent; no cross-source imputation')
                    months[ym]+=1;regions[r['시군구']]+=1
                    minimum=day if minimum is None else min(day,minimum);maximum=day if maximum is None else max(day,maximum)
                    good+=1
                except (ValueError,KeyError,TypeError) as e: error=str(e);errors+=1
                # Digest excludes NO only for describing within-file repetition, never deletion.
                content=hashlib.sha256(dump([[k,v] for k,v in zip(columns,values) if k!='NO']).encode()).hexdigest()
                identity=hashlib.sha256(f'CSV_OBSERVATION_V1|{spec["sha256"]}|{rows}|{start}|{f.tell()}'.encode()).hexdigest()
                c.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (identity,spec['sha256'],rows,firstline,lines.n,start,f.tell(),dump(values),dump(states),dump(derived),content,'ERROR' if error else 'PARSED',error))
                c.execute('INSERT INTO raw_multiplicity VALUES(?,?,1) ON CONFLICT(file_sha,content_digest) DO UPDATE SET n=n+1',(spec['sha256'],content))
                if rows%256==0: guard.checkpoint('rows_completed_'+str(rows))
        need(rows==spec['expected_rows'],'FILE_ROW_COUNT_DRIFT')
        need(rows==good+errors,'ROW_CONSERVATION')
        meta=dict(spec,preamble=pre,snapshot_path=str(snap),input_rows=rows,good_rows=good,error_rows=errors,
            observed_date_min=minimum,observed_date_max=maximum,observed_month_counts=dict(months),observed_region_counts=dict(regions),
            coverage_status=coverage_state(rows,errors),observability=[{'field':k,'state':s,'n':n} for (k,s),n in sorted(obs.items())],
            original_source_identity={'size':Path(spec['path']).stat().st_size,'mtime_ns_diagnostic_only':Path(spec['path']).stat().st_mtime_ns},
            observation_id_semantics='FILE_SHA + record ordinal + byte interval; NOT transaction ID',
            historical_jurisdiction='NOT_INFERRED_FROM_CSV_LABEL_OR_API_QUERY_CODE')
        c.execute('INSERT INTO files VALUES(?,?,?,?,?)',(spec['sha256'],dump(meta),rows,good,errors));c.commit()
    except Exception:
        c.rollback();raise
    guard.checkpoint('file_committed_'+spec['id'])
    return dict(id=spec['id'],sha256=spec['sha256'],status=meta['coverage_status'],input_rows=rows,good_rows=good,error_rows=errors)
def small_tests(config,func,guard,work):
    tests=[]
    def test(name,f): f();tests.append(name)
    def check_states():
        cases=[('',True,'EMPTY'),(' ',True,'WHITESPACE'),('-',True,'DISPLAY_DASH'),('0',True,'EXPLICIT_ZERO'),('NULL',True,'NULL_LITERAL'),('',False,'ABSENT')]
        for v,p,s in cases: need(func['state'](v,p)==s,'OBSERVABILITY_STATE')
    test('raw_observability_states_distinct',check_states)
    def reject_overlap():
        inputs=json.loads(dump(config['inputs']))
        for x in inputs: x['selected']=True
        try: check_selection(inputs)
        except ValueError as e: need(str(e)=='ANALYSIS_QUERY_OVERLAP','WRONG_REJECTION');return
        raise AssertionError('OVERLAP_ACCEPTED')
    test('annual_monthly_double_selection_rejected',reject_overlap)
    need(coverage_state(0,0)=='QUERY_SCOPE_ZERO_OBSERVED_UNVERIFIED_COMPLETENESS','ZERO_PROMOTED');tests.append('empty_is_not_verified_zero')
    t=work/'small_tests';t.mkdir();(t/'raw').mkdir();db=db_open(t/'test.sqlite')
    base=config['inputs'][0];cols=base['columns'];sample=[]
    original=Path(base['path'])
    with original.open(encoding='cp949',newline='') as f:
        rr=csv.reader(f)
        for row in rr:
            if row and row[0]=='NO':break
        sample=next(rr)
    def make(name,rows):
        p=t/name
        with p.open('x',encoding='cp949',newline='') as f:
            w=csv.writer(f)
            for k,v in base['conditions'].items():w.writerow([k+' : '+v])
            w.writerow(cols);w.writerows(rows)
        return dict(base,id=name,path=str(p),sha256=sha(p),expected_rows=len(rows),selected=False)
    second=list(sample);second[0]='2';bad=list(sample);bad[0]='3';bad[cols.index('계약일')]='99'
    spec=make('synthetic.csv',[sample,second,bad]);res=ingest(spec,db,t/'raw',guard,func)
    need((res['input_rows'],res['good_rows'],res['error_rows'])==(3,2,1),'ERROR_CONSERVATION');tests.append('error_row_preserved_with_raw_identity')
    need(db.execute('SELECT MAX(n) FROM raw_multiplicity').fetchone()[0]==2,'DUPLICATE_LOST');tests.append('repeated_content_preserved')
    ingest(spec,db,t/'raw',guard,func);need(db.execute('SELECT count(*) FROM observations').fetchone()[0]==3,'IDEMPOTENCE');tests.append('same_file_idempotent')
    modified=list(sample);modified[cols.index('건축년도')]='1901'
    newer=make('synthetic_changed.csv',[modified]);ingest(newer,db,t/'raw',guard,func)
    need(db.execute('SELECT count(*) FROM files').fetchone()[0]==2,'SNAPSHOT_COLLAPSED');tests.append('changed_content_separate_snapshot')
    missing=dict(base,path=str(t/'missing.csv'));need(ingest(missing,db,t/'raw',guard,func)['status']=='FILE_ABSENT','MISSING_AS_ZERO');tests.append('absent_file_not_zero')
    wrong=dict(newer,sha256='0'*64)
    try: ingest(wrong,db,t/'raw',guard,func)
    except ValueError as e: need(str(e).startswith('SOURCE_SHA_MISMATCH'),'WRONG_SHA_ERROR');tests.append('SHA_drift_rejected')
    else: raise AssertionError('SHA_DRIFT_ACCEPTED')
    db.close();return dict(PASS=len(tests),FAIL=0,tests=tests,synthetic=True,real_data_credit=0)
def worker(config,work,do_tests):
    guard=resource.ReferenceGuard(ROOT);guard.admit();started=time.perf_counter()
    guard.reserve_output(2147483648)
    try:
        temp=BASE/'tmp';temp.mkdir(exist_ok=True)
        for name in ('SQLITE_TMPDIR','TMP','TEMP'):os.environ[name]=str(temp)
        for x in config['bindings']: need(sha(ROOT/x['path'],guard)==x['sha256'],'INPUT_BINDING_DRIFT:'+x['path'])
        pairs=check_selection(config['inputs']);func=reused_functions(config)
        if do_tests: writej(work/'tests.json',small_tests(config,func,guard,work))
        rawdir=BASE/'raw_snapshots';rawdir.mkdir(exist_ok=True)
        c=db_open(BASE/'observations.sqlite');results=[]
        for s in config['inputs']:
            results.append(ingest(s,c,rawdir,guard,func));print(s['id'],results[-1]['status'],flush=True)
        need(all(r['input_rows'] is not None and r['error_rows']==0 for r in results),'FILES_NOT_ANALYSIS_READY')
        # Same real file entered again: no second occurrence registration.
        before=c.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
        repeat=ingest(config['inputs'][0],c,rawdir,guard,func)
        after=c.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
        need(before==after and repeat['status']=='ALREADY_REGISTERED_NO_NEW_ROWS','REAL_IDEMPOTENCE')
        selection_sha=hashlib.sha256(dump([{k:s[k] for k in ['id','sha256','selected','selection_reason']} for s in config['inputs']]).encode()).hexdigest()
        for s in config['inputs']:
            c.execute('INSERT OR IGNORE INTO selections VALUES(?,?,?,?,?)',(selection_sha,s['sha256'],s['id'],s['selected'],s['selection_reason']))
        c.commit();manifest=[];obsrows=[];universe=set(k for s in config['inputs'] for k in s['columns'])
        for s in config['inputs']:
            meta=json.loads(c.execute('SELECT metadata FROM files WHERE sha=?',(s['sha256'],)).fetchone()[0])
            d=c.execute('SELECT COUNT(*),COALESCE(SUM(n-1),0) FROM raw_multiplicity WHERE file_sha=? AND n>1',(s['sha256'],)).fetchone()
            meta['duplicate_content_groups_without_NO']=d[0];meta['extra_repeated_occurrences_without_NO']=d[1]
            for field in universe-set(meta['columns']):meta['observability'].append(dict(field=field,state='ABSENT',n=meta['input_rows']))
            manifest.append(meta)
            obsrows += [dict(id=s['id'],**x) for x in meta['observability']]
        selected=c.execute('SELECT COUNT(*) FROM analysis_observations WHERE selection_sha=?',(selection_sha,)).fetchone()[0]
        need(selected==sum(r['good_rows'] for r,s in zip(results,config['inputs']) if s['selected']),'SELECTION_COUNT')
        c.close();guard.checkpoint('database_closed')
        writej(work/'file_coverage_manifest.json',manifest)
        writej(work/'selection_manifest.json',dict(selection_sha=selection_sha,query_overlaps=pairs,files=[{k:s[k] for k in ['id','sha256','selected','selection_reason','query']} for s in config['inputs']],analysis_rows=selected,complete_transaction_population=False))
        with (work/'field_observability.csv').open('x',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,['id','field','state','n']);w.writeheader();w.writerows(obsrows)
        writej(work/'spatial_coverage.json',dict(reference_only=config['spatial_reference'],analysis_denominator=selected,spatially_processed=0,assigned=0,
            unassigned=selected,unassigned_reason='NOT_RUN; distinct from attempted-but-unmatched',grid_aggregate_eligible_denominator=0,grid_counts=None))
        result=dict(status='CSV_SOURCE_LANE_PROCESSED_NOT_PRODUCTION',files=len(results),registered_observations=after,selected_files=sum(s['selected'] for s in config['inputs']),analysis_rows=selected,
            input_rows=sum(r['input_rows'] for r in results),good_rows=sum(r['good_rows'] for r in results),error_rows=sum(r['error_rows'] for r in results),
            real_same_file_reentry=dict(before=before,after=after,new_rows=after-before,status=repeat['status']),
            duplicate_extra_occurrences=sum(x['extra_repeated_occurrences_without_NO'] for x in manifest),
            elapsed_seconds=time.perf_counter()-started,files_result=results,API_calls=0,API_completion_credit=0,prior_comparisons_rerun=0,
            database_bytes=(BASE/'observations.sqlite').stat().st_size,raw_snapshot_bytes=sum(p.stat().st_size for p in rawdir.iterdir()))
        receipt=guard.publication_gate();writej(work/'result_candidate.json',result)
        writej(work/'worker_resource_receipt.json',receipt)
    except BaseException as e:
        import traceback
        writej(work/'primary_exception.json',dict(type=type(e).__name__,reason=str(e),traceback=traceback.format_exc()))
        if not (work/'worker_resource_receipt.json').exists():writej(work/'worker_resource_receipt.json',guard.receipt())
        raise
    finally: guard.reader.close()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--worker',action='store_true');ap.add_argument('--config',default=str(BASE/'config.json'));ap.add_argument('--tests',action='store_true');args=ap.parse_args()
    config=readj(args.config);need(Path(config['output']).resolve()==BASE and Path(config['root']).resolve()==ROOT,'CONFIG_ROOT')
    safe(BASE)
    if args.worker: worker(config,Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY']),args.tests);return
    # Exclusive fresh supervision evidence on each explicit invocation; the raw store is idempotent.
    runs=BASE/'runs';runs.mkdir(exist_ok=True)
    work=runs/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    env=dict(os.environ);env['PYTHONDONTWRITEBYTECODE']='1'
    cmd=[sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'--worker','--config',str(Path(args.config).resolve())]
    if args.tests:cmd+=['--tests']
    receipt=resource.supervise(cmd,str(ROOT),env,work)
    if receipt['status']=='COMPLETE':
        writej(work/'qualification.json',dict(status='EXPERIMENTAL_CSV_INGESTION_PASS_NOT_NATIONAL_ADOPTION',supervisor=receipt,result=readj(work/'result_candidate.json'),config_sha=sha(Path(args.config)),source_sha=sha(Path(__file__))))
    print(dump({'work':str(work),'supervisor':receipt}),flush=True)
    raise SystemExit(0 if receipt['status']=='COMPLETE' else 1)
if __name__=='__main__': main()
