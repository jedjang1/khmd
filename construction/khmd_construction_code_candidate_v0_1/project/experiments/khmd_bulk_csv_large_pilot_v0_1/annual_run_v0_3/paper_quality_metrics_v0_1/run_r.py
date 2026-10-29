"""Same external R guard/start-gate/WorkerJob pattern as khmd 0.0.3 monitor_r_query.py."""
import os as _khmd_path_env  # candidate-only path configuration
import sys,os,time,json,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'src/khmd_reference_resource_monitor_v0_2.py').exists())
sys.path.insert(0,str(ROOT/'src'))
import khmd_reference_resource_monitor_v0_2 as resource
out=Path(sys.argv[1]).resolve();out.mkdir();tmp=out/'tmp';tmp.mkdir()
lib=ROOT/'experiments/khmd_r_csv_release_v0_3/check_tools/user_run_20261028_080606_469/library'
env=dict(os.environ,R_LIBS=str(lib),R_LIBS_USER=str(lib),R_LIBS_SITE='',TMPDIR=str(tmp),TMP=str(tmp),TEMP=str(tmp),R_USER=str(tmp),LC_ALL='English_United States.utf8',KHMD_R_START_GATE=str(out/'admission.json'),R_GC_MEM_GROW='0',R_VSIZE='4M')
args=[str(out) if a=='{OUT}' else a for a in sys.argv[2:]]
start=time.monotonic();process=guard=job=None;error=None
try:
 with (out/'stdout.log').open('x') as stdout,(out/'stderr.log').open('x') as stderr:
  process=subprocess.Popen([_khmd_path_env.environ['KHMD_EXTERNAL_BB932EA6DE'],'--vanilla',*args],cwd=ROOT,env=env,stdout=stdout,stderr=stderr)
  reader=resource.WindowsReader(process.pid);job=resource.WorkerJob(process);guard=resource.ReferenceGuard(ROOT,reader=reader,require_supervisor=False);guard.admit();guard.reserve_output(30000000)
  (out/'admission.json').write_text(json.dumps(dict(pid=process.pid,creation=reader.creation_time_100ns)))
  with (out/'external_samples.jsonl').open('x') as f:
   while process.poll() is None:
    sample=guard.checkpoint('external_R_worker');f.write(json.dumps(sample)+'\n');f.flush();time.sleep(resource.SAMPLE_SECONDS)
  guard.publication_gate()
  if process.returncode:raise RuntimeError('R_EXIT_'+str(process.returncode))
except BaseException as e:error=str(e)
finally:
 if process and process.poll() is None:process.terminate();process.wait(timeout=10)
 result=dict(status='HOLD' if error else 'COMPLETE',error=error,returncode=process.returncode if process else None,elapsed_seconds=time.monotonic()-start,adapter='external R process; unchanged ReferenceGuard + WorkerJob + admission gate',automatic_retry=False,receipt=guard.receipt() if guard else None)
 if guard:guard.reader.close()
 if job:job.close()
 (out/'supervisor.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));sys.exit(1 if error else 0)
