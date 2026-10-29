import os,sys,json,csv,hashlib,time
from pathlib import Path
from datetime import datetime,timezone
import importlib.util
spec=importlib.util.spec_from_file_location('target_quality',Path(__file__).parent/'quality_v0_3.py');q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
H=q.H;p=q.p;b=q.b;db=q.db
def main(out,g):
    cfg=p.config(g);r=b.read(H/'publish_v0_3/result.json');audit=b.read(H/'audit/result.json');selection=b.read(H/'prepare/selection.json')
    b.need(r['input']==20916100 and r['assigned']+r['unassigned']==r['input'],'FINAL_CONSERVATION')
    c=db(H/'quality.sqlite',True);d=db(p.P/'national_demand/demand.sqlite',True)
    table=[];supply=[];sample=[]
    for text, in c.execute('select payload from audit_keys order by id'):
        x=json.loads(text);ev=[json.loads(z[0]) for z in c.execute('select payload from record_evidence where id=?',(x['id'],))]
        item=[x['id'],x['category'],x['selection'],x['source_address'],x['lot'],x['occurrences'],x['prior_status'],x['classification'],x['candidate_rows'],x['distinct_PNUs'],'|'.join(z['pnu'] for z in ev),'|'.join(z.get('grid_id','') for z in ev)]
        table.append(item)
        if x['category']=='UNLINKED_PARCEL':
            oid=x['reference_object'];code=x['master_code'];hits=0;paths=[]
            for base in [q.N,q.O]:
                path=base/'objects'/oid/'candidates.sqlite'
                if path.exists():
                    cc=db(path,True);hits+=cc.execute('select count(*) from candidates where code=?',(code,)).fetchone()[0];cc.close();paths.append(str(path))
            supply.append([x['id'],x['source_address'],x['lot'],x['occurrences'],code,oid,hits,'EXACT_PAIR_ABSENT_IN_COMPLETED_SCAN','PARCEL_CHANGE_OR_TIME_OR_TRUE_ABSENCE_UNCONFIRMED','|'.join(paths)])
        elif x['category'] in ['CITY_DISTRICT_FIELD_SPACING','SEJONG_UNIQUE_PARENT_OMITTED_IN_SOURCE']:
            sample.append([x['id'],x['category'],x['selection'],x['occurrences'],x['prior_status'],'RAW_PNU_GEOMETRY_POINT_GRID_VERIFIED' if x['prior_status']=='ASSIGNED' else 'MASTER_VERIFIED_NO_PARCEL_GRID_UNAVAILABLE'])
    p.table(out/'quality_table.csv',['id','category','selection','source_address','lot','occurrences','prior_status','finding','candidate_records','distinct_PNUs','PNUs','verified_grid_IDs'],table,g)
    p.table(out/'no_candidate_supply_audit.csv',['id','address','lot','occurrences','code','object','same_code_records_full_and_delta_indices','confirmed','unconfirmed','evidence_indices'],supply,g)
    p.table(out/'normalization_sample_findings.csv',['id','rule','selection','occurrences','prior_status','verified_scope'],sample,g)
    # Acquisition evidence is read from stored metadata, never filename time.
    acquisitions=[]
    for sha, in c.execute('select distinct file_sha from weights where key_id in (select id from guji)'):
        store,query=d.execute('select store,query_json from files where sha=?',(sha,)).fetchone();cc=db(store,True);meta=json.loads(cc.execute('select metadata from files where sha=?',(sha,)).fetchone()[0]);cc.close()
        acquisitions.append(dict(file_sha256=sha,query=json.loads(query),acquisition_time_status=meta['acquisition_time_status'],download_started_at=meta['download_started_at'],download_completed_at=meta['download_completed_at'],reference_snapshot='2026-09-08',change_effective='2026-09-30',contract_date_filter_applied=False))
    b.write(out/'guji_source_time_separation.json',acquisitions)
    # Original fixed source data and previous results remain SHA-bound.
    p.verify_final(q.N/'national/final_manifest.json',g)
    current=db(H/'publish_v0_3/national.sqlite',True);b.need(current.execute('select sum(n) from grid').fetchone()[0]==r['assigned'],'GRID_FINAL_SUM');current.close()
    supers=[b.read(H/st/'supervisor.json') for st in ['prepare','audit','publish','publish_v0_3']]
    initial=b.read(q.BASE/'csv_spatial_target_quality_v0_1/prepare/supervisor.json')
    result=dict(**r,target_quality=audit,selection=selection,successful_supervised_seconds=sum(x['elapsed_seconds'] for x in supers),initial_preserved_non_success_seconds=initial['elapsed_seconds'],max_current=max(x['observed_max_enforcement_metric'] for x in supers+[initial]),max_lifetime_peak=max(x['diagnostic_peak_value'] for x in supers+[initial]),successful_max_lifetime_peak=max(x['diagnostic_peak_value'] for x in supers),cap=119537664,initial_non_resource_hold='BUSAN_CANDIDATE_SCHEMA_REQUIRES_EXPLICIT_ADAPTER; fixed explicit schema adapter; failed source/evidence retained',publication_report_correction='Initial publish/result.json input field shadowed by per-weight n=8; SQL conservation remained20916100. quality_v0_3 and publish_v0_3 fix reporting value; previous output preserved, not authoritative.',resource_threshold_hold=0,source_sha=b.lane.sha(H/'quality_v0_3.py'),Seoul='PILOT_PARTIAL',Cheongju='PARTIAL_MATCH',population_completeness='UNPROVEN',forbidden_actions={'other_downloads':0,'external_API':0,'raw_reparse':0,'demand_regeneration':0,'full_spatial_rerun':0,'Production':0,'guard_changes':0,'original_or_past_results_modified':0,'geometry_repair':0,'prices_R_changes_deployment':0})
    b.write(out/'qualification.json',result);c.close();d.close();return result
if __name__=='__main__':
    if len(sys.argv)>1:
        out=H/'final';g=b.lane.resource.ReferenceGuard(q.ROOT);wd=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY'])
        try:g.admit();main(out,g);b.write(wd/'worker_resource_receipt.json',g.publication_gate())
        except BaseException as e:
            import traceback
            b.write(wd/'primary_exception.json',dict(error=str(e),traceback=traceback.format_exc()));b.write(wd/'worker_resource_receipt.json',g.receipt());raise
        finally:g.reader.close()
    else:
        out=H/'final';out.mkdir();sup=b.lane.resource.supervise([sys.executable,'-B','-X','utf8',__file__,'worker'],str(q.ROOT),dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),out/'supervised');b.write(out/'supervisor.json',sup);print(b.dump(sup));b.need(sup['status']=='COMPLETE','FINAL_HOLD')
