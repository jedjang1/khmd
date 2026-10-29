"""Release-selected normalized rows -> regional demand counts, crash-safe chunks.

Source occurrences remain in their immutable original stores, referenced by file
SHA/ordinal ranges and rolling chunk digests. Counts preserve all multiplicity.
No raw CSV parsing, spatial assignment, network, or source writes.
"""
import argparse,csv,hashlib,json,os,sqlite3,sys,time,traceback
from collections import Counter,defaultdict,OrderedDict
from pathlib import Path
H=Path(__file__).resolve().parent;ROOT=H.parents[3]
sys.path.insert(0,str(H.parent/'csv_spatial_bridge_v0_1'));import bridge as b

def database(path,readonly=False):
    if readonly:
        b.lane.safe(path);c=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    else:c=sqlite3.connect(path)
    c.execute('PRAGMA cache_size=-2048');c.execute('PRAGMA mmap_size=0');c.execute('PRAGMA temp_store=FILE')
    if not readonly:c.execute('PRAGMA journal_mode=DELETE');c.execute('PRAGMA synchronous=FULL')
    return c

def schema(c,binding):
    c.executescript('''
    CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE files(sha TEXT PRIMARY KEY,province TEXT,family TEXT,query_json TEXT,store TEXT,metadata_sha TEXT,input_rows INTEGER,last_ordinal INTEGER NOT NULL DEFAULT0,processed INTEGER NOT NULL DEFAULT0,complete INTEGER NOT NULL DEFAULT0,store_identity TEXT);
    CREATE TABLE keys(id TEXT PRIMARY KEY,province TEXT,region_literal TEXT,lot TEXT,legal_codes TEXT,status TEXT,n INTEGER NOT NULL);
    CREATE INDEX keys_region ON keys(province);
    CREATE TABLE weights(file_sha TEXT,key_id TEXT,quarter TEXT,row_status TEXT,n INTEGER NOT NULL,PRIMARY KEY(file_sha,key_id,quarter,row_status)) WITHOUT ROWID;
    CREATE TABLE chunks(file_sha TEXT,first_ordinal INTEGER,last_ordinal INTEGER,n INTEGER,digest TEXT,PRIMARY KEY(file_sha,first_ordinal)) WITHOUT ROWID;
    '''.replace('DEFAULT0','DEFAULT 0'))
    c.execute('insert into meta values(?,?)',('binding',binding));c.commit()

def commit_chunk(c,sha,first,last,rows_digest,key_rows,weights,n,fail_before_commit=False):
    """All effects and checkpoint share one transaction; exception rolls back."""
    try:
        c.execute('BEGIN IMMEDIATE')
        c.executemany('insert into keys values(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET n=keys.n+excluded.n',key_rows)
        c.executemany('insert into weights values(?,?,?,?,?) ON CONFLICT(file_sha,key_id,quarter,row_status) DO UPDATE SET n=weights.n+excluded.n',weights)
        c.execute('insert into chunks values(?,?,?,?,?)',(sha,first,last,n,rows_digest))
        c.execute('update files set last_ordinal=?,processed=processed+? where sha=?',(last,n,sha))
        if fail_before_commit:raise RuntimeError('INJECTED_BEFORE_COMMIT')
        c.commit()
    except BaseException:c.rollback();raise

class Names:
    def __init__(self,cfg):
        self.names=defaultdict(set);leaf={};self.cache=OrderedDict()
        with (ROOT/cfg['legal_master']).open(encoding='utf-8-sig',newline='') as f:
            for r in csv.DictReader(f):
                if r['읍면동명']:
                    code=r['법정동코드'];self.names[' '.join(r[k] for k in ['시도명','시군구명','읍면동명','리명'] if r[k])].add(code)
                    leaf[code]=r['읍면동명']+(' '+r['리명'] if r['리명'] else '')
        with (ROOT/cfg['historical_names']).open(encoding='utf-8-sig',newline='') as f:
            for r in csv.DictReader(f):
                if r['case_id']=='CHEONGJU_20140701' and r['after_full_code'] in leaf and r['after_region_name'].endswith(' '+leaf[r['after_full_code']]):
                    self.names[r['after_region_name']].add(r['after_full_code'])
        self.lot=b.compile_pure(ROOT/cfg['literal_selector'],{'transaction_jibun'})['transaction_jibun']
        self.quarter=b.compile_pure(ROOT/cfg['quarter_source'],{'quarter_id','_integer'})['quarter_id']
    def key(self,province,region,lot):
        key=(province,region,lot)
        if key in self.cache:return self.cache[key]
        codes=sorted(self.names.get(region,()));lot_status,literal=self.lot(lot)
        status='EXACT_KEY_ELIGIBLE' if len(codes)==1 and literal is not None else ('AMBIGUOUS_LEGAL_NAME' if len(codes)>1 else 'UNRESOLVED_LEGAL_NAME' if not codes else lot_status)
        val=(b.digest(key),province,region,lot,b.dump(codes),status);self.cache[key]=val
        if len(self.cache)>4096:self.cache.popitem(last=False)
        return val

def pin(cfg,g):
    for x in cfg['bindings']:b.need(b.lane.sha(ROOT/x['path'],g)==x['sha256'],'INPUT_SHA_DRIFT:'+x['path'])

def process(cfg,work,g,pause_after=None):
    start=time.monotonic();pin(cfg,g);release=b.read(ROOT/cfg['release']);registry=b.read(ROOT/cfg['registry']);scope=cfg['regions']
    selected=sorted([x for x in release['active_files'] if x['query']['province'] in scope],key=lambda x:(x['query']['province']!='부산광역시',x['query']['province'],x['query']['family'],x['query']['date_from']))
    b.need(len(selected)==cfg['expected_files'],'SELECTED_SCOPE');binding=b.digest(cfg)
    dbpath=work/'demand.sqlite';exists=dbpath.exists();c=database(dbpath)
    if not exists:schema(c,binding)
    b.need(c.execute('select value from meta where key=?',('binding',)).fetchone()[0]==binding,'RESTART_BINDING_DRIFT')
    names=Names(cfg);chunks_this_attempt=0;new_rows=0
    try:
        for entry in selected:
            sha=entry['file_sha256'];reg=registry[sha];q=entry['query'];path=Path(entry['store']);stamp=b.dump(b.identity(path));state=c.execute('select last_ordinal,processed,complete,store_identity from files where sha=?',(sha,)).fetchone()
            if state:
                b.need(stamp==state[3],'RESTART_SOURCE_IDENTITY_CHANGED')
                if state[2]:continue
            src=database(path,True)
            try:
                meta,expected,good,errors=src.execute('select metadata,input_rows,good_rows,error_rows from files where sha=?',(sha,)).fetchone()
                b.need(hashlib.sha256(meta.encode()).hexdigest()==reg['metadata_sha256'],'NORMALIZED_METADATA_SHA')
                b.need((expected,good,errors)==(reg['input_rows'],reg['good_rows'],reg['error_rows']),'REGISTERED_COUNTS_DRIFT')
                cols=json.loads(meta)['columns'];lot_index=cols.index('번지')
                if not state:
                    c.execute('insert into files(sha,province,family,query_json,store,metadata_sha,input_rows,store_identity) values(?,?,?,?,?,?,?,?)',(sha,q['province'],q['family'],b.dump(q),str(path),reg['metadata_sha256'],expected,stamp));c.commit();last=0;processed=0
                else:last,processed=state[:2]
                while True:
                    sql="select ordinal,obs_id,json_extract(derived,'$.csv_region_literal'),json_extract(derived,'$.contract_month'),json_extract(raw_values,?),row_status from observations where file_sha=? and ordinal>? order by ordinal limit ?"
                    records=src.execute(sql,('$['+str(lot_index)+']',sha,last,cfg['chunk_rows'])).fetchall()
                    if not records:break
                    keys={};weights=Counter();hashrows=hashlib.sha256();first=last+1
                    for ordinal,oid,region,ym,lot,status in records:
                        b.need(ordinal==last+1,'ORDINAL_GAP_OR_DUPLICATE');last=ordinal
                        k=names.key(q['province'],region,lot)
                        try:quarter=names.quarter(ym[:4],ym[4:])
                        except (ValueError,TypeError):quarter='UNASSIGNABLE_PERIOD'
                        if k[0] not in keys:keys[k[0]]=[*k,0]
                        keys[k[0]][6]+=1;weights[(sha,k[0],quarter,status)]+=1
                        hashrows.update((b.dump([ordinal,oid,region,ym,lot,status,k[0]])+'\n').encode())
                    commit_chunk(c,sha,first,last,hashrows.hexdigest(),list(keys.values()),[(*k,n) for k,n in weights.items()],len(records))
                    processed+=len(records);new_rows+=len(records);chunks_this_attempt+=1
                    g.checkpoint('normalized_chunk_committed_'+sha[:8]+'_'+str(last))
                    if pause_after and chunks_this_attempt>=pause_after:
                        return dict(status='INTENTIONAL_PAUSE',new_rows=new_rows,chunks=chunks_this_attempt,elapsed_seconds=time.monotonic()-start)
                b.need(processed==expected,'NEW_DEMAND_CONSERVATION_VS_REGISTERED_METADATA')
                b.need(stamp==b.dump(b.identity(path)),'SOURCE_CHANGED_DURING_READ')
                c.execute('update files set complete=1 where sha=?',(sha,));c.commit()
                print(b.dump(dict(file_complete=sha,province=q['province'],family=q['family'],period=q['date_from'],rows=processed)),flush=True)
            finally:src.close()
        # These are new derived tables, not a repeated count of original stores.
        summary=[dict(province=p,source_files=n,input_occurrences=e,processed_occurrences=d,complete_files=f) for p,n,e,d,f in c.execute('select province,count(*),sum(input_rows),sum(processed),sum(complete) from files group by province')]
        key_counts={p:n for p,n in c.execute('select province,count(*) from keys group by province')}
        status_counts=[dict(province=p,key_status=s,distinct_keys=n,occurrences=w) for p,s,n,w in c.execute('select province,status,count(*),sum(n) from keys group by province,status')]
        expected=sum(registry[x['file_sha256']]['input_rows'] for x in selected)
        b.need(sum(x['processed_occurrences'] for x in summary)==sum(x['input_occurrences'] for x in summary)==expected,'TOTAL_NEW_DEMAND_CONSERVATION')
        b.need(c.execute('select sum(n) from weights').fetchone()[0]==expected,'WEIGHT_CONSERVATION')
        result=dict(status='DEMAND_COMPLETE',new_rows_this_attempt=new_rows,chunks_this_attempt=chunks_this_attempt,elapsed_seconds=time.monotonic()-start,expected_from_registered_metadata=expected,regions=summary,keys_by_region=key_counts,status_by_region=status_counts,occurrences_preserved=True,raw_CSV_parses=0,source_full_SQL_count=0,spatial_assignments=0,source_store_identity_basis='registered metadata SHA plus original size/mtime/file identity; no claim these substitute for full content SHA',historical_jurisdiction='UNVERIFIED',query_regions='ACQUISITION_QUERY_UNITS',reference_name_basis='exact current legal master or existing official Cheongju after-name bridge')
        pin(cfg,g);return result
    finally:c.close()

def worker(config,work,attempt,pause_after):
    g=b.lane.resource.ReferenceGuard(ROOT);wd=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY'])
    try:
        g.admit();g.reserve_output(2*1024**3);r=process(b.read(config),work,g,pause_after)
        b.write(wd/'worker_resource_receipt.json',g.publication_gate());b.write(attempt/'result.json',r)
    except BaseException as e:
        b.write(wd/'primary_exception.json',dict(type=type(e).__name__,error=str(e),traceback=traceback.format_exc()))
        if not (wd/'worker_resource_receipt.json').exists():b.write(wd/'worker_resource_receipt.json',g.receipt())
        raise
    finally:g.reader.close()

def run_unlocked(config,work,attempt,pause_after):
    b.need(not attempt.exists(),'ATTEMPT_NO_REPLACE');work.mkdir(parents=True,exist_ok=True);attempt.mkdir(parents=True)
    command=[sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'worker','--config',str(config),'--work',str(work),'--attempt',str(attempt)]
    if pause_after:command+=['--pause-after-chunks',str(pause_after)]
    sup=b.lane.resource.supervise(command,str(ROOT),dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),attempt/'supervised')
    b.need(sup['status']=='COMPLETE','SUPERVISED_HOLD:'+str(attempt))
    result=b.read(attempt/'result.json')
    b.write(attempt/'completion.json',dict(supervisor=sup,result=result,config_sha256=b.lane.sha(config),source_sha256=b.lane.sha(Path(__file__))))
    if result['status']=='DEMAND_COMPLETE':
        final=work/'final_manifest.json'
        if not final.exists():b.write(final,dict(status='DEMAND_COMPLETE_NOT_SPATIAL_RESULT',config_sha256=b.lane.sha(config),database='demand.sqlite',database_sha256=b.lane.sha(work/'demand.sqlite'),completion=str(attempt/'completion.json'),completion_sha256=b.lane.sha(attempt/'completion.json')))
    print(b.dump(dict(status=result['status'],new_rows=result.get('new_rows_this_attempt',result.get('new_rows')),elapsed=sup['elapsed_seconds'])),flush=True)

def run(config,work,attempt,pause_after):
    import msvcrt
    work.mkdir(parents=True,exist_ok=True)
    with (work/'coordinator.lock').open('a+b') as lock:
        if lock.tell()==0:lock.write(b'1');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise RuntimeError('CONCURRENT_COORDINATOR_REJECTED')
        try:
            if (work/'final_manifest.json').exists():
                final=b.read(work/'final_manifest.json')
                b.need(final['config_sha256']==b.lane.sha(config),'COMPLETED_CONFIG_DRIFT')
                b.need(final['database_sha256']==b.lane.sha(work/'demand.sqlite'),'COMPLETED_DATABASE_DRIFT')
                print('REUSED_COMPLETED_DEMAND_NO_SOURCE_REREAD');return
            run_unlocked(config,work,attempt,pause_after)
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['run','worker']);p.add_argument('--config',type=Path,required=True);p.add_argument('--work',type=Path,required=True);p.add_argument('--attempt',type=Path,required=True);p.add_argument('--pause-after-chunks',type=int);a=p.parse_args()
    (run if a.mode=='run' else worker)(a.config.resolve(),a.work.resolve(),a.attempt.resolve(),a.pause_after_chunks)
