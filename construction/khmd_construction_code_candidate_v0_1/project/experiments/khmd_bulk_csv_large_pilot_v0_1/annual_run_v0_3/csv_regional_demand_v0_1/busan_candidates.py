"""One Busan DBF pass for the complete frozen regional demand, no geometry."""
import argparse,csv,hashlib,json,os,sqlite3,sys,time,traceback
from collections import defaultdict,Counter
from pathlib import Path
H=Path(__file__).resolve().parent;ROOT=H.parents[3]
sys.path.insert(0,str(H));import demand as d
b=d.b
sys.path.insert(0,str(H.parent/'csv_spatial_supply_v0_1'));import supply_v0_4 as supply

def snapshot(work):
    """Read one consistent completed-region view even while other regions grow."""
    b.need(not work.exists(),'CANDIDATE_WORK_NO_REPLACE');work.mkdir(parents=True)
    src=sqlite3.connect((H/'national_demand/demand.sqlite').resolve().as_uri()+'?mode=ro',uri=True,timeout=30)
    src.execute('PRAGMA cache_size=-2048');src.execute('BEGIN')
    files=src.execute('select sha,family,query_json,input_rows,processed,complete from files where province=? order by sha',('부산광역시',)).fetchall()
    b.need(len(files)==30 and all(x[5]==1 and x[3]==x[4] for x in files),'BUSAN_NOT_COMPLETE')
    path=work/'demand_snapshot.sqlite';dst=d.database(path)
    dst.execute('create table addresses(id TEXT PRIMARY KEY,province TEXT,region_literal TEXT,lot TEXT,legal_codes TEXT,status TEXT,n INTEGER)')
    for x in src.execute('select * from keys where province=? order by id',('부산광역시',)):dst.execute('insert into addresses values(?,?,?,?,?,?,?)',x)
    dst.commit();rows=dst.execute('select count(*),sum(n) from addresses').fetchone();dst.close();src.commit();src.close()
    b.need(rows[1]==sum(x[3] for x in files)==1327806,'BUSAN_SLICE_CONSERVATION')
    origin=H.parent/'csv_spatial_supply_v0_1/supply_run_v0_4'
    extraction=b.read(origin/'regional_extraction.json');prior=b.read(origin/'completion.json')
    for x in prior['artifacts']:
        if x['path'] in ('regional_extraction.json','generated_points.sqlite'):
            b.need(b.lane.sha(origin/x['path'])==x['sha256'],'PRIOR_SUPPLY_DRIFT')
    dbf=extraction['members']['.dbf'];crs=b.read(H/'crs_review.json')
    c=b.read(H/'demand_config.json')
    b.write(work/'input_manifest.json',dict(files=files,query_region='부산광역시',families=['SALE','RENT'],years=[2011,2025],source_occurrences=rows[1],distinct_keys=rows[0],snapshot_sha256=b.lane.sha(path),dbf=dbf,raw_source=extraction['source'],prior_point_db=str(origin/'generated_points.sqlite'),prior_point_db_sha256=b.lane.sha(origin/'generated_points.sqlite'),release=c['release'],release_sha256=b.lane.sha(ROOT/c['release']),candidate_source_sha256=b.lane.sha(Path(__file__)),CRS_review_sha256=b.lane.sha(H/'crs_review.json'),CRS_gate=crs['status'],national_geometry=0))

def geometry_gate(review):
    b.need(review['status']=='ACCEPTED_BY_EXPLICIT_EXISTING_POLICY' and review.get('numeric_acceptance_binding') and review.get('out_of_area_acceptance_record'),'CRS_ACCEPTANCE_NOT_ESTABLISHED')

def worker(work,attempt):
    t=time.monotonic();g=b.lane.resource.ReferenceGuard(ROOT);wd=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY']);c=None
    try:
        g.admit();g.reserve_output(64*1024**2);m=b.read(work/'input_manifest.json')
        b.need(b.lane.sha(Path(__file__))==m['candidate_source_sha256'],'CODE_SHA')
        b.need(b.lane.sha(work/'demand_snapshot.sqlite')==m['snapshot_sha256'],'DEMAND_SNAPSHOT_SHA')
        b.need(b.lane.sha(ROOT/m['release'])==m['release_sha256'],'RELEASE_SHA')
        b.need(b.lane.sha(H/'crs_review.json')==m['CRS_review_sha256'],'CRS_REVIEW_SHA')
        src=d.database(work/'demand_snapshot.sqlite',True);wanted=defaultdict(list);allkeys={}
        for row in src.execute('select * from addresses'):
            aid,province,region,lot,codes,status,n=row;allkeys[aid]=row
            if status=='EXACT_KEY_ELIGIBLE':
                code=json.loads(codes);b.need(len(code)==1,'NONUNIQUE_LEGAL_KEY');wanted[(code[0],lot)].append(aid)
        src.close();p=Path(m['dbf']['path']);identity=b.identity(p)
        c=d.database(work/'candidates.partial.sqlite')
        c.executescript('create table candidates(address_id TEXT,pnu TEXT,ordinal INTEGER,dbf_sha TEXT,raw_A2 TEXT,raw_A4 TEXT,eligibility TEXT,PRIMARY KEY(address_id,pnu,ordinal));create table key_results(address_id TEXT PRIMARY KEY,candidate_count INTEGER,match_status TEXT,occurrences INTEGER,cached_POS_available INTEGER);')
        exceptions={x['PNU']:x for x in csv.DictReader((ROOT/'metadata/khmd_nationwide_reference_row_exception_registry_v0_1.csv').open(encoding='utf-8-sig'))}
        counter=Counter();hsh=hashlib.sha256()
        with p.open('rb') as f:
            h=supply.inputs._dbf_header(f);b.need(h['record_count']==705940,'DBF_ROWS');f.seek(0);hsh.update(f.read(h['header_length']));fields={x['name']:x for x in h['fields']}
            for ordinal in range(1,h['record_count']+1):
                raw=f.read(h['record_length']);b.need(len(raw)==h['record_length'] and raw[:1]==b' ','DELETED_OR_SHORT_ROW');hsh.update(raw)
                code=raw[fields['A2']['offset']:fields['A2']['offset']+10].decode('ascii');lot=raw[fields['A4']['offset']:fields['A4']['offset']+10].decode('euc_kr').rstrip(' ')
                ids=wanted.get((code,lot))
                if ids:
                    vals=supply.rawfields(raw,h);pnu=vals['A1'];b.need(pnu[:10]==code and len(pnu)==19 and pnu.isascii() and pnu.isdigit(),'PNU_IDENTITY')
                    eligibility='EXACT_REFERENCE_CANDIDATE';ex=exceptions.get(pnu)
                    if ex:eligibility=ex['derived_row_status'] if ex['quarantine_flag']=='False' else 'QUARANTINED_REFERENCE_ROW'
                    for aid in ids:
                        c.execute('insert into candidates values(?,?,?,?,?,?,?)',(aid,pnu,ordinal,hashlib.sha256(raw).hexdigest(),code,lot,eligibility));counter[aid]+=1
                if ordinal%2048==0:g.checkpoint('Busan_DBF_rows_completed_'+str(ordinal))
            trailer=f.read();b.need(trailer in (b'',b'\x1a'),'DBF_TRAILER');hsh.update(trailer)
        b.need(hsh.hexdigest()==m['dbf']['sha256'],'SOURCE_DBF_SHA');b.need(b.identity(p)==identity,'SOURCE_CHANGED')
        cache=d.database(m['prior_point_db'],True);b.need(b.lane.sha(Path(m['prior_point_db']))==m['prior_point_db_sha256'],'SAVED_POS_SHA')
        state=Counter();keycounts=Counter();cached=0;unique_pnus=set()
        for aid,row in allkeys.items():
            n=counter[aid];w=row[6]
            status=('UNLINKED_NAME_OR_JIBUN' if row[5]!='EXACT_KEY_ELIGIBLE' else 'UNLINKED_PARCEL' if n==0 else 'AMBIGUOUS_PARCEL' if n>1 else 'UNIQUE_PARCEL_CRS_PENDING')
            hit=0
            if n==1:
                pnu,eligibility=c.execute('select pnu,eligibility from candidates where address_id=?',(aid,)).fetchone()
                if eligibility=='QUARANTINED_REFERENCE_ROW':status='QUARANTINED_REFERENCE'
                unique_pnus.add(pnu);hit=int(cache.execute('select 1 from points where pnu=?',(pnu,)).fetchone() is not None)
            cached+=hit;c.execute('insert into key_results values(?,?,?,?,?)',(aid,n,status,w,hit));state[status]+=w;keycounts[status]+=1
        cache.close();c.commit();c.close();c=None
        b.need(sum(state.values())==m['source_occurrences'],'CANDIDATE_OCCURRENCE_CONSERVATION')
        result=dict(status='PARCEL_CANDIDATES_COMPLETE_SPATIAL_CRS_HOLD',source_cells=30,source_occurrences=m['source_occurrences'],distinct_address_keys=len(allkeys),unique_lookup_keys=len(wanted),status_occurrences=dict(state),status_keys=dict(keycounts),unique_PNUs=len(unique_pnus),keys_with_existing_verified_POS=cached,new_POS_generated=0,new_grid_assignments=0,source_DBF_rows_scanned=705940,regional_passes=1,elapsed_seconds=time.monotonic()-t,CRS_gate=m['CRS_gate'],reference_snapshot='2026-09-08',historical_location_verified=False)
        # Publish only after resource/peak gate. A failed partial file remains.
        receipt=g.publication_gate();final=work/'candidates.sqlite';b.need(not final.exists(),'FINAL_NO_REPLACE');os.rename(work/'candidates.partial.sqlite',final)
        b.write(work/'candidate_manifest.json',dict(status=result['status'],input_manifest_sha256=b.lane.sha(work/'input_manifest.json'),database_sha256=b.lane.sha(final),result=result))
        b.write(attempt/'result.json',result);b.write(wd/'worker_resource_receipt.json',receipt)
    except BaseException as e:
        if c:c.close()
        b.write(wd/'primary_exception.json',dict(error=str(e),traceback=traceback.format_exc()))
        if not (wd/'worker_resource_receipt.json').exists():b.write(wd/'worker_resource_receipt.json',g.receipt())
        raise
    finally:g.reader.close()

def run(work,attempt):
    b.need(not attempt.exists(),'ATTEMPT_NO_REPLACE');attempt.mkdir(parents=True)
    if (work/'candidate_manifest.json').exists():
        m=b.read(work/'candidate_manifest.json');b.need(b.lane.sha(work/'candidates.sqlite')==m['database_sha256'],'COMPLETED_CANDIDATES_DRIFT');print('REUSE_COMPLETED_CANDIDATES');return
    b.need(not (work/'candidates.partial.sqlite').exists(),'PARTIAL_CANDIDATE_REVIEW_REQUIRED')
    sup=b.lane.resource.supervise([sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'worker','--work',str(work),'--attempt',str(attempt)],str(ROOT),dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),attempt/'supervised')
    b.need(sup['status']=='COMPLETE','SUPERVISOR_HOLD');b.write(attempt/'completion.json',dict(supervisor=sup,result=b.read(attempt/'result.json')));print(b.dump(b.read(attempt/'result.json')))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run','worker','spatial-gate']);p.add_argument('--work',type=Path,required=True);p.add_argument('--attempt',type=Path);a=p.parse_args()
    if a.mode=='prepare':snapshot(a.work.resolve())
    elif a.mode=='spatial-gate':geometry_gate(b.read(H/'crs_review.json'))
    else:(run if a.mode=='run' else worker)(a.work.resolve(),a.attempt.resolve())
