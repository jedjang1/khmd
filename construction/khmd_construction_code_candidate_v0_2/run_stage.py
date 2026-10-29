"""Single guarded invocation; no retry loop and no national orchestration."""
import argparse,os,sys,time,traceback
from pathlib import Path
from binding import *
import runtime
sys.path.insert(0,str(PROJECT/'src'))
import khmd_reference_resource_monitor_v0_2 as monitor

def worker(bound,work,out,pause):
    g=monitor.ReferenceGuard(PROJECT);wd=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY'])
    try:
        g.admit();m,inputs=verify(bound,read(bound)['stage'],g)
        if m['stage']=='busan_finish':
            import busan_finish; result=busan_finish.process(bound,out,work,g,pause)
        else:
            import guji
            result=(guji.seed if m['stage']=='guji_seed' else guji.prepare)(bound,out,work,g)
        runtime.audit_loaded_modules(out)
        write(out/'result.json',result);write(wd/'worker_resource_receipt.json',g.publication_gate())
    except BaseException as e:
        write(wd/'primary_exception.json',dict(error=str(e),traceback=traceback.format_exc()))
        if not(wd/'worker_resource_receipt.json').exists():write(wd/'worker_resource_receipt.json',g.receipt())
        raise
    finally:g.reader.close()

def run(bound,work,out,python,pause=0):
    # Fast code/config preflight without bypassing the worker's guarded recheck.
    m=read(bound);need(m['stage'] in ('busan_finish','guji_seed','guji_prepare'),'STAGE')
    work.mkdir(parents=True,exist_ok=True)
    import msvcrt
    with (work/'coordinator.lock').open('a+b') as lock:
        if not lock.tell():lock.write(b'1');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        try:
            final=work/'final_manifest.json'
            if final.exists():
                old=read(final);need(old['bound_sha256']==sha(bound),'COMPLETED_BOUND_CHANGED')
                verify_stage(final,old['status'],m['scope']);return dict(status='REUSED_COMPLETE_NO_REPROCESSING',manifest=str(final))
            need(not out.exists(),'ATTEMPT_NO_REPLACE');out.mkdir(parents=True)
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PROJ_NETWORK='OFF')
            if Path(python).parent.name=='Python312':
                rr=Path(python).parents[2];env.update(PROJ_DATA=str(rr/'share/proj'),GDAL_DATA=str(rr/'apps/gdal/share'))
            sup=monitor.supervise([str(python),'-B','-X','utf8',__file__,'worker','--bound',str(bound),'--work',str(work),'--out',str(out),'--pause',str(pause)],str(PROJECT),env,out/'supervisor')
            write(out/'supervisor.json',sup)
            need(sup['status']=='COMPLETE' and sup['returncode']==0,'STAGE_HOLD:'+str(out))
            result=read(out/'result.json');completion=out/'completion.json'
            write(completion,dict(supervisor=sup,result=result))
            if result['status']=='AGGREGATION_INTENTIONAL_PAUSE':return result
            if m['stage']=='busan_finish':
                paths=[work/'aggregate.sqlite',out/'grid_quarter_counts.csv',out/'quarter_status_counts.csv',out/'address_results.csv']
            elif m['stage']=='guji_seed':paths=[work/'quality.sqlite',out/'guji_ri_crosswalk.csv']
            else:paths=[work/'quality.sqlite',work/'seed_handoff.json',work/'sets.json',out/'selected_keys.csv',out/'selection.json']
            manifest=dict(schema='KHMD_CONSTRUCTION_STAGE_V2',scope=m['scope'],stage=m['stage'],status=result['status'],
                out=str(out),
                bound_manifest=str(bound),bound_sha256=sha(bound),config_sha256=sha(bound),completion=str(completion),completion_sha256=sha(completion),
                artifacts=[dict(path=str(p),sha256=sha(p)) for p in paths],result=result)
            write(final,manifest);return manifest
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['run','worker']);p.add_argument('--bound',type=Path,required=True);p.add_argument('--work',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--python',type=Path,default=Path(sys.executable));p.add_argument('--pause',type=int,default=0)
    a=p.parse_args();args=(a.bound.resolve(),a.work.resolve(),a.out.resolve())
    if a.mode=='worker':worker(*args,a.pause)
    else:print(__import__('json').dumps(run(*args,a.python,a.pause),ensure_ascii=False))
