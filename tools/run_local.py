"""Windows local install/example with unchanged KHMD worker guard. No network."""
import sys,os,json,time,subprocess,argparse
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));import khmd_reference_resource_monitor_v0_2 as resource
from verify_bundle import verify
def main():
 parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['verify','example','demo']);parser.add_argument('--bundle',type=Path,default=HERE.parent);parser.add_argument('--library',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--rscript',type=Path,required=True);a=parser.parse_args()
 root=a.bundle.resolve();out=a.output.resolve();lib=a.library.resolve();out.mkdir(parents=True,exist_ok=False);(out/'tmp').mkdir()
 # Run bounded verification before any workload. This guard is the same, unmodified module/contract.
 verify_guard=resource.ReferenceGuard(root,root/'tools/resource_contract.json',require_supervisor=False);verify_guard.admit()
 integrity=verify(root,verify_guard.checkpoint);(out/'integrity.json').write_text(json.dumps(integrity,indent=2));(out/'verifier_resource.json').write_text(json.dumps(verify_guard.publication_gate(),indent=2));verify_guard.reader.close()
 if a.mode=='verify':print(json.dumps(integrity));return 0
 if not lib.is_dir():raise RuntimeError('DEDICATED_LIBRARY_MISSING')
 # Existing dependencies must already be installed here; no user/project library fallback.
 gate=out/'admission.json';tmp=out/'tmp'
 env=dict(os.environ,R_LIBS=str(lib),R_LIBS_USER=str(lib),R_LIBS_SITE='',R_ENVIRON_USER=str(tmp/'absent.Renviron'),R_PROFILE_USER=str(tmp/'absent.Rprofile'),R_USER=str(tmp),TMP=str(tmp),TEMP=str(tmp),TMPDIR=str(tmp),R_GC_MEM_GROW='0',R_VSIZE='4M',LC_ALL='English_United States.utf8',KHMD_R_START_GATE=str(gate))
 cmd=[str(a.rscript),'--vanilla',str(root/'tools'/'quickstart.R')]
 cmd += [str(root),str(lib),str(out),'demo' if a.mode=='demo' else 'full']
 process=guard=job=None;error=None;start=time.monotonic()
 try:
  with (out/'stdout.log').open('x') as stdout,(out/'stderr.log').open('x') as stderr:
   process=subprocess.Popen(cmd,cwd=tmp,env=env,stdout=stdout,stderr=stderr)
   reader=resource.WindowsReader(process.pid);job=resource.WorkerJob(process);guard=resource.ReferenceGuard(root,root/'tools/resource_contract.json',reader=reader,require_supervisor=False);guard.admit();guard.reserve_output(128*1024**2)
   gate.write_text(json.dumps({'pid':process.pid,'creation':reader.creation_time_100ns}))
   with (out/'external_samples.jsonl').open('x') as samples:
    while process.poll() is None:
     samples.write(json.dumps(guard.checkpoint('R_'+a.mode))+'\n');samples.flush();time.sleep(resource.SAMPLE_SECONDS)
   guard.publication_gate()
   if process.returncode:raise RuntimeError('R_EXIT_'+str(process.returncode))
   if a.mode!='install':assert json.loads((out/'example_result.json').read_text())['status']=='PASS'
 except BaseException as e:error=str(e)
 finally:
  if process and process.poll() is None:process.terminate();process.wait(timeout=10)
  result={'status':'HOLD' if error else 'COMPLETE','mode':a.mode,'error':error,'returncode':process.returncode if process else None,'elapsed_seconds':time.monotonic()-start,'automatic_retry':False,'receipt':guard.receipt() if guard else None,'command':cmd,'cwd':str(tmp)}
  if guard:guard.reader.close()
  if job:job.close()
  (out/'supervisor.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));return 1 if error else 0
if __name__=='__main__':sys.exit(main())
