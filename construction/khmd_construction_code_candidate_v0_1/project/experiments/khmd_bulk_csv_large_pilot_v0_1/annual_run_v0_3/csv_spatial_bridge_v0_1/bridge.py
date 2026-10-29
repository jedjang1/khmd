"""Bounded CSV release -> exact reference parcel -> saved POS -> sample counts.
No CSV/XML parsing, API, geometry computation, imputation or national execution.
"""
import argparse,ast,csv,hashlib,json,os,re,socket,sqlite3,sys,time,traceback
from collections import Counter,defaultdict,OrderedDict
from datetime import datetime,timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
LANE=HERE.parent/'csv_source_lane_v0_1'
sys.path.insert(0,str(LANE));sys.path.insert(0,str(ROOT/'src'))
import csv_lane as lane
from parcel_representative_grid_contract_v0_1 import grid_index,grid_id
read=lane.readj;write=lane.writej;need=lane.need
STATUSES=('UNIQUE_REFERENCE_ASSIGNED','AMBIGUOUS_REFERENCE','UNLINKED','NOT_AGGREGATABLE')
def dump(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(x):return hashlib.sha256(dump(x).encode()).hexdigest()
def db(path,guard):
    c=sqlite3.connect(lane.safe(path).as_uri()+'?mode=ro&immutable=1',uri=True)
    c.execute('PRAGMA cache_size=-1024');c.execute('PRAGMA mmap_size=0');c.execute('PRAGMA temp_store=FILE')
    def progress():guard.checkpoint('sqlite_vm_units_completed');return 0
    c.set_progress_handler(progress,100000);return c
def table(path,rows,fields=None):
    rows=list(rows)
    with path.open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields or list(rows[0]) if rows else fields or ['empty']);w.writeheader()
        for r in rows:w.writerow({k:dump(v) if isinstance(v,(list,dict)) else v for k,v in r.items()})
def compile_pure(path,names):
    tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    need(len(nodes)==len(names),'PURE_FUNCTION_MISSING')
    env={'re':re,'require':need}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path)+':unchanged_pure_functions','exec'),env)
    return env
def identity(p):
    s=Path(p).stat();return dict(size=s.st_size,mtime_ns=s.st_mtime_ns,ino=s.st_ino)
def bindings(config,g):
    for b in config['bindings']:need(lane.sha(ROOT/b['path'],g)==b['sha256'],'INPUT_BINDING_DRIFT:'+b['path'])

class Linker:
    def __init__(self,config,g):
        self.g=g;self.config=config;self.cache=OrderedDict();self.hits=0;self.lookups=0
        self.byname=defaultdict(set);self.leaf={};self.bridges=defaultdict(list)
        with (ROOT/config['legal_master']).open(encoding='utf-8-sig',newline='') as f:
            for row in csv.DictReader(f):
                if not row['읍면동명']:continue
                code=row['법정동코드'];need(bool(re.fullmatch('[0-9]{10}',code)),'LEGAL_CODE_FORMAT')
                name=' '.join(row[k] for k in ['시도명','시군구명','읍면동명','리명'] if row[k])
                self.byname[name].add(code);self.leaf[code]=row['읍면동명']+(' '+row['리명'] if row['리명'] else '')
        with (ROOT/config['historical_names']).open(encoding='utf-8-sig',newline='') as f:
            for h in csv.DictReader(f):
                if h['case_id']!='CHEONGJU_20140701':continue
                code=h['after_full_code'];name=h['after_region_name']
                if code in self.leaf and name.endswith(' '+self.leaf[code]):self.bridges[name].append((code,h['evidence_row_id']))
        mat=read(ROOT/config['parcel_materialization']);self.sets={x['set_id']:x for x in mat['physical_sets']}
        self.covered={x['region'] for x in self.sets.values()}
        self.index_path=ROOT/mat['index_path'];self.pos_path=ROOT/config['saved_pos_index']
        self.ix=db(self.index_path,g);self.sp=db(self.pos_path,g)
        self.input_identities={str(p):identity(p) for p in [self.index_path,self.pos_path]}
        self.partition_bindings={x['path']:x['sha256'] for x in read(ROOT/config['pos_manifest'])['partitions']}
        self.partition_rows={};self.verified_partitions={}
        self.jibun=compile_pure(ROOT/config['literal_selector'],{'transaction_jibun'})['transaction_jibun']
        self.prior={}
        for r in read(ROOT/config['prior_results']):
            if r['side']=='CSV':self.prior[(r['CSV_region_label'],r['literal_jibun'])]=r
        self.address_records=[]
    def close(self):self.ix.close();self.sp.close()
    def saved(self,payload):
        part=payload['_partition'];h=payload['_sha256'];need(self.partition_bindings.get(part)==h,'SAVED_PARTITION_AUTHORITY')
        if part not in self.partition_rows:
            path=ROOT/part;need(lane.sha(path,self.g)==h,'SAVED_POS_PARTITION_DRIFT')
            hashes={}
            with path.open(encoding='utf-8-sig',newline='') as f:
                for n,row in enumerate(csv.DictReader(f),1):
                    hashes[row['parcel_reference_pnu']]=digest(row)
                    if n%128==0:self.g.checkpoint('saved_POS_rows_authenticated_'+str(n))
            self.partition_rows[part]=hashes;self.verified_partitions[part]=h
        clean={k:v for k,v in payload.items() if k not in ('_partition','_sha256')}
        need(self.partition_rows[part].get(payload['parcel_reference_pnu'])==digest(clean),'SAVED_POS_INDEX_PAYLOAD_DRIFT')
        need(payload['grid_spec_sha256']==self.config['grid_sha256'],'GRID_BINDING_DRIFT')
        need(payload['reference_snapshot_date']=='2026-09-08' and payload['representative_crs']=='EPSG:5186','REFERENCE_CRS_DATE')
        if payload['spatial_assignment_status']!='SPATIAL_ASSIGNED_PARCEL_POS':return None
        need(payload['representative_method']=='POINT_ON_SURFACE','REPRESENTATIVE_METHOD')
        xy=[float(payload['representative_x']),float(payload['representative_y'])]
        gid=grid_id(*grid_index(*xy));need(gid==payload['parcel_representative_grid_id'],'SAVED_GRID_MISMATCH')
        return dict(pnu=payload['parcel_reference_pnu'],x=xy[0],y=xy[1],grid_id=gid,
            CRS='EPSG:5186',grid_version=payload['grid_version'],boundary_class=payload['parcel_boundary_class'],
            geometry_derivation=payload.get('geometry_derivation'),geometry_wkb_sha256=payload['geometry_wkb_sha256'],
            partition=part,partition_sha256=payload['_sha256'],representative_method='REUSED_VERIFIED_POINT_ON_SURFACE')
    def link(self,region,lot,query_province):
        key=(region,lot,query_province)
        if key in self.cache:
            self.hits+=1;self.cache.move_to_end(key);return self.cache[key]
        self.lookups+=1;codes=sorted(self.byname.get(region,()))
        basis='EXACT_CURRENT_MASTER_FULL_HIERARCHY';bridges=[]
        if not codes and region in self.bridges:
            codes=sorted({x[0] for x in self.bridges[region]});bridges=[x[1] for x in self.bridges[region]]
            basis='EXACT_EXISTING_OFFICIAL_CHEONGJU_AFTER_NAME_BRIDGE_CURRENT_MASTER_CONFIRMED'
        lot_status,literal=self.jibun(lot)
        result=dict(address_id=digest(key),csv_region_literal=region,jibun_literal=lot,legal_codes=codes,
            name_basis=basis,name_bridge_evidence=bridges,jibun_status=lot_status,parcel_candidates=[],spatial_candidates=[],
            reference_snapshot='2026-09-08',legal_master_snapshot='2026-06-30',historical_location='UNVERIFIED',actual_building_identity='NOT_ASSERTED')
        prior=self.prior.get((region,lot))
        if prior and prior['candidate_count']==0:
            result.update(status='UNLINKED',reason='REUSED_PRIOR_REFERENCE_SNAPSHOT_NO_PARCEL',prior_evidence='spatial_target_v0_1/bound_address_results.json',legal_codes=prior['legal_codes'])
        elif len(codes)>1:result.update(status='AMBIGUOUS_REFERENCE',reason='MULTIPLE_LEGAL_CODES')
        elif not codes:result.update(status='UNLINKED',reason='EXACT_NAME_NOT_IN_CURRENT_MASTER_OR_APPROVED_BRIDGE')
        elif literal is None:result.update(status='UNLINKED',reason=lot_status)
        elif query_province not in self.covered:result.update(status='NOT_AGGREGATABLE',reason='PARCEL_REFERENCE_REGION_NOT_MATERIALIZED')
        else:
            cursor=self.ix.execute('select set_id,row_ordinal,pnu,a2,a4_raw,jibun from parcels indexed by parcels_K2V2 where a2 COLLATE BINARY=? and jibun COLLATE BINARY=? order by pnu',(codes[0],literal))
            try:
                for sid,ordinal,pnu,a2,a4,ref_lot in cursor:
                    self.g.checkpoint('indexed_parcel_candidate_found');s=self.sets[sid];schema=json.loads(s['schema_json']);path=ROOT/s['dbf_path']
                    self.input_identities.setdefault(str(path),identity(path))
                    with path.open('rb') as f:
                        f.seek(schema['header_length']+(ordinal-1)*schema['record_length']);slot=f.read(schema['record_length'])
                    fields={x['name']:slot[x['offset']:x['offset']+x['width']].decode('cp949').rstrip(' ') for x in schema['fields']}
                    need(slot[:1]!=b'*' and len(slot)==schema['record_length'],'DBF_RECORD_INVALID')
                    need((fields['A1'],fields['A2'],fields['A4'])==(pnu,codes[0],literal),'PARCEL_INDEX_DBF_MISMATCH')
                    result['parcel_candidates'].append(dict(pnu=pnu,set_id=sid,row_ordinal=ordinal,dbf_record_sha256=hashlib.sha256(slot).hexdigest(),dbf_path=s['dbf_path'],raw_archive_sha256_recorded=s['raw_archive_sha']))
            finally:cursor.close()
            n=len(result['parcel_candidates'])
            if not n:result.update(status='UNLINKED',reason='NO_EXACT_REFERENCE_PARCEL')
            elif n>1:result.update(status='AMBIGUOUS_REFERENCE',reason='MULTIPLE_PARCEL_CANDIDATES_NO_AUTOMATIC_CHOICE')
            else:
                cand=result['parcel_candidates'][0];found=self.sp.execute('select payload from crosswalk where pnu=?',(cand['pnu'],)).fetchone()
                if not found:result.update(status='NOT_AGGREGATABLE',reason='UNIQUE_PARCEL_WITHOUT_VERIFIED_SAVED_POS')
                else:
                    payload=json.loads(found[0]);need(payload['matched_physical_set_id']==cand['set_id'] and int(payload['matched_source_row_ordinal'])==cand['row_ordinal'],'POS_PARCEL_LINEAGE')
                    pos=self.saved(payload)
                    if pos:result['spatial_candidates']=[pos];result.update(status='UNIQUE_REFERENCE_ASSIGNED',reason='EXACT_REFERENCE_MATCH_WITH_BOUND_VERIFIED_POS')
                    else:result.update(status='NOT_AGGREGATABLE',reason='SAVED_GEOMETRY_NOT_USABLE')
        need(result['status'] in STATUSES,'INVALID_STATUS')
        result['candidate_count']=len(result['parcel_candidates']) if 'REUSED_PRIOR' not in result.get('reason','') else 0
        self.cache[key]=result
        if len(self.cache)>512:self.cache.popitem(last=False)
        self.address_records.append(result);return result

def worker(config_path,out):
    g=lane.resource.ReferenceGuard(ROOT);work=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY']);linker=None;t=time.monotonic()
    try:
        g.admit();g.reserve_output(32*1024*1024);cfg=read(config_path);bindings(cfg,g)
        need(cfg['mode']=='BOUNDED_SAMPLE' and sum(x['limit'] for x in cfg['samples'])<=1024,'NATIONAL_EXECUTION_NOT_ENABLED')
        release=read(ROOT/cfg['release']);index=read(ROOT/cfg['registry']);active={x['file_sha256']:x for x in release['active_files']}
        need(len(active)==480 and release['active_rows']==20916100,'RELEASE_BASELINE')
        quarter=compile_pure(ROOT/cfg['quarter_source'],{'_integer','quarter_id'})['quarter_id']
        linker=Linker(cfg,g);g.checkpoint('spatial_initialization_complete');init=time.monotonic()-t
        rows=[];strata=[];counts=Counter();grid_counts=Counter();quarters=Counter();content=Counter();seen=set();source_bindings=[]
        with (out/'observations.jsonl').open('x',encoding='utf-8') as dest:
            for sample in cfg['samples']:
                st=time.monotonic();s=sample['file_sha256'];need(s in active,'UNSELECTED_SOURCE');entry=active[s];q=entry['query']
                need(q==sample['query'],'SAMPLE_QUERY_BINDING');path=Path(entry['store']);before=identity(path);c=db(path,g)
                try:
                    meta,n,good,errors=c.execute('select metadata,input_rows,good_rows,error_rows from files where sha=?',(s,)).fetchone()
                    need(hashlib.sha256(meta.encode()).hexdigest()==index[s]['metadata_sha256'],'STORE_METADATA_DRIFT')
                    need((n,good,errors)==(index[s]['input_rows'],index[s]['good_rows'],index[s]['error_rows']),'STORE_COUNTS_DRIFT')
                    m=json.loads(meta);columns=m['columns']
                    sql="select obs_id,ordinal,physical_line_start,physical_line_end,byte_start,byte_end,raw_values,states,derived,raw_content_digest,row_status from observations where file_sha=? and json_extract(derived,'$.contract_month')=?"
                    params=[s,sample['month']]
                    if sample.get('region_prefix'):
                        sql+=" and substr(json_extract(derived,'$.csv_region_literal'),1,?)=?";params.extend([len(sample['region_prefix']),sample['region_prefix']])
                    if sample.get('region_exact'):
                        sql+=" and json_extract(derived,'$.csv_region_literal')=?";params.append(sample['region_exact'])
                    if sample.get('lot_exact'):
                        sql+=" and json_extract(raw_values,?)=?";params.extend(['$['+str(columns.index('번지'))+']',sample['lot_exact']])
                    sql+=' order by ordinal limit ?';params.append(sample['limit'])
                    cursor=c.execute(sql,params);local=Counter();local_n=0
                    for record in cursor:
                        oid,ordinal,l0,l1,b0,b1,raw,states,derived,raw_digest,row_status=record
                        need(oid not in seen,'SAMPLE_OVERLAP_OBSERVATION_ID');seen.add(oid)
                        vals=dict(zip(columns,json.loads(raw)));obs_states=dict(zip(columns,json.loads(states)));d=json.loads(derived)
                        need(row_status=='PARSED' and d['csv_region_literal']==vals['시군구'],'DERIVED_ADDRESS_LINEAGE')
                        ym=d['contract_month'];period=quarter(ym[:4],ym[4:]);need(ym==sample['month'],'SAMPLE_MONTH')
                        result=linker.link(d['csv_region_literal'],vals.get('번지'),q['province']);status=result['status']
                        pos=result['spatial_candidates'][0] if status=='UNIQUE_REFERENCE_ASSIGNED' else None
                        record_out=dict(observation_id=oid,observation_id_semantics='SOURCE_ROW_NOT_TRANSACTION_ID',sample_id=sample['id'],file_sha256=s,store=str(path),ordinal=ordinal,
                            physical_line_start=l0,physical_line_end=l1,byte_start=b0,byte_end=b1,stored_row_sha256=digest(record),raw_content_digest=raw_digest,
                            query_province=q['province'],query_region_role='ACQUISITION_QUERY_UNIT_NOT_EVENT_TIME_BOUNDARY',API_query_code=None,
                            csv_region_literal=d['csv_region_literal'],transaction_time_jurisdiction=None,transaction_time_jurisdiction_status='NOT_ESTABLISHED',
                            jibun_literal=vals.get('번지'),complex_literal=vals.get('단지명'),build_year_literal=vals.get('건축년도'),
                            source_observability={k:obs_states.get(k,'FIELD_ABSENT') for k in ['시군구','번지','건축년도','단지명','해제사유발생일','종전계약 월세(만원)']},
                            contract_date=d['contract_date'],quarter=period,family=q['family'],address_id=result['address_id'],status=status,reason=result['reason'],
                            reference_legal_codes=result['legal_codes'],reference_snapshot='2026-09-08',CRS='EPSG:5186',grid_version=cfg['grid_version'],
                            pnu=pos['pnu'] if pos else None,grid_id=pos['grid_id'] if pos else None,x=pos['x'] if pos else None,y=pos['y'] if pos else None,
                            cancelled_or_revised_filter='NOT_APPLIED_OCCURRENCE_COUNT_ONLY',historical_location_verified=False)
                        dest.write(dump(record_out)+'\n');rows.append(record_out);local[status]+=1;local_n+=1;counts[status]+=1
                        quarters[(sample['id'],q['family'],period,status)]+=1;content[(s,raw_digest)]+=1
                        if pos:grid_counts[(q['family'],period,pos['grid_id'])]+=1
                        g.checkpoint('observation_link_and_count_completed_'+str(len(rows)))
                    cursor.close()
                    source_bindings.append(dict(file_sha256=s,store=str(path),metadata_sha256=index[s]['metadata_sha256'],stored_file_rows=n,identity_before=before,identity_after=identity(path),fresh_whole_store_SHA='NOT_RUN',provenance='Inherited registered raw SHA; selected metadata and consumed stored row digests checked'))
                    need(before==identity(path),'STORE_CHANGED_DURING_READ')
                    strata.append(dict(sample_id=sample['id'],family=q['family'],query_province=q['province'],month=sample['month'],selection=sample,observed_rows=local_n,status_counts=dict(local),elapsed_seconds=time.monotonic()-st,
                        sample_strategy='First bounded stored ordinals matching explicit month/region; purposive, not population representative',full_month_count_tested=False))
                finally:c.close()
        need(len(rows)==sum(counts.values())==sum(quarters.values()),'OBSERVATION_CONSERVATION')
        need(sum(grid_counts.values())==counts['UNIQUE_REFERENCE_ASSIGNED'],'GRID_COUNT_CONSERVATION')
        for p,before in linker.input_identities.items():need(identity(p)==before,'SPATIAL_INPUT_CHANGED')
        table(out/'grid_quarter_counts.csv',[dict(family=f,quarter=q,grid_id=gid,n_assigned_observation_occurrences=n,coverage='BOUNDED_SAMPLE_ONLY_NOT_FULL_QUARTER') for (f,q,gid),n in sorted(grid_counts.items())])
        table(out/'quarter_status_counts.csv',[dict(sample_id=s,family=f,quarter=q,status=k,occurrences=n) for (s,f,q,k),n in sorted(quarters.items())])
        table(out/'sample_summary.csv',strata)
        with (out/'address_results.jsonl').open('x',encoding='utf-8') as f:
            for a in linker.address_records:f.write(dump(a)+'\n')
        write(out/'input_observation_bindings.json',source_bindings)
        write(out/'spatial_reference_bindings.json',dict(verified_saved_POS_partitions=linker.verified_partitions,recorded_reference_index_sha256=read(ROOT/cfg['parcel_materialization'])['index_sha256'],fresh_whole_spatial_index_SHA='NOT_RUN',positive_parcels='Fixed-offset original DBF rows verified; saved POS partition and row payload verified',negative_results='Current preserved index snapshot only',index_regions=sorted(linker.covered)))
        result=dict(status='BOUNDED_CSV_SPATIAL_BRIDGE_COMPLETE_WITH_UNRESOLVED_PRESERVED',sample_occurrences=len(rows),distinct_address_keys=len(linker.address_records),
            mutually_exclusive_status_counts={s:counts[s] for s in STATUSES},assigned_occurrence_rate=counts['UNIQUE_REFERENCE_ASSIGNED']/len(rows) if rows else None,
            grid_quarter_rows=len(grid_counts),grid_quarter_occurrences=sum(grid_counts.values()),unassigned_occurrences=len(rows)-sum(grid_counts.values()),
            conservation=True,repeated_content_extra_occurrences_preserved=sum(n-1 for n in content.values() if n>1),
            address_cache_hits=linker.hits,address_lookup_work_units=linker.lookups,initialization_seconds=init,elapsed_seconds=time.monotonic()-t,
            metadata_release_files=480,metadata_release_rows=20916100,national_execution='NOT_RUN_NOT_READY',historical_location_verified=False,
            resource_scope='Existing114MiB reference guard and supervisor, unchanged',raw_reparsing=0,API_comparison=0,geometry_computation=0,coordinate_transform=0,
            source_occurrence_deduplication=0,price_metrics=0,production_API=0,START_END=0,authorization=0,Batch204=0,API_ledger_addition=0,guard_changes=0,downloads=0,
            prior_11_group_test_rerun=False,Seoul='PILOT_PARTIAL',Cheongju='PARTIAL_MATCH',population_completeness='UNPROVEN')
        bindings(cfg,g);write(out/'result.json',result)
        write(work/'worker_resource_receipt.json',g.publication_gate())
    except BaseException as e:
        write(work/'primary_exception.json',dict(type=type(e).__name__,reason=str(e),traceback=traceback.format_exc()))
        if not (work/'worker_resource_receipt.json').exists():write(work/'worker_resource_receipt.json',g.receipt())
        raise
    finally:
        if linker:linker.close()
        g.reader.close()

def run(config_path,out):
    need(not out.exists(),'OUTPUT_EXISTS_NO_REPLACE');out.mkdir(parents=True)
    cfg=read(config_path);need(cfg['mode']=='BOUNDED_SAMPLE','NATIONAL_EXECUTION_NOT_READY')
    write(out/'invocation.json',dict(config=str(config_path),config_sha256=lane.sha(config_path),code_sha256=lane.sha(Path(__file__)),started_utc=datetime.now(timezone.utc).isoformat()))
    sup=lane.resource.supervise([sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'worker','--config',str(config_path),'--out',str(out)],str(ROOT),dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),out/'supervised')
    need(sup['status']=='COMPLETE','RESOURCE_OR_WORKER_HOLD:'+str(out/'supervised'))
    write(out/'completion.json',dict(status='SUPERVISED_SAMPLE_PASS_WITH_LIMITATIONS',result=read(out/'result.json'),supervisor=sup,
        artifacts=[dict(path=p.name,sha256=lane.sha(p)) for p in out.iterdir() if p.is_file()]))
    print(dump(read(out/'completion.json')))

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('mode',choices=['run','worker']);a.add_argument('--config',type=Path,required=True);a.add_argument('--out',type=Path,required=True);args=a.parse_args()
    if args.mode=='worker':worker(args.config.resolve(),args.out.resolve())
    else:run(args.config.resolve(),args.out.resolve())
