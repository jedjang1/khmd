"""Bind only explicitly listed inputs under the unchanged resource supervisor."""
import argparse,os,sys,traceback
from pathlib import Path
from binding import *
import runtime
import khmd_reference_resource_monitor_v0_2 as monitor

def worker(config,out):
    g=monitor.ReferenceGuard(PROJECT);wd=Path(os.environ['KHMD_RESOURCE_WORK_DIRECTORY'])
    try:
        g.admit();bind(config,out/'bound.json',g)
        write(wd/'worker_resource_receipt.json',g.publication_gate())
    except BaseException as e:
        write(wd/'primary_exception.json',dict(error=str(e),traceback=traceback.format_exc()))
        if not(wd/'worker_resource_receipt.json').exists():write(wd/'worker_resource_receipt.json',g.receipt())
        raise
    finally:g.reader.close()

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('mode',choices=['run','worker']);a.add_argument('--config',type=Path,required=True);a.add_argument('--out',type=Path,required=True);a.add_argument('--python',type=Path,default=Path(sys.executable));v=a.parse_args()
    config=v.config.resolve();out=v.out.resolve()
    if v.mode=='worker':worker(config,out)
    else:
        need(not out.exists(),'BIND_ATTEMPT_NO_REPLACE');out.mkdir(parents=True)
        sup=monitor.supervise([str(v.python),'-B','-X','utf8',__file__,'worker','--config',str(config),'--out',str(out)],str(PROJECT),dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),out/'supervisor')
        write(out/'supervisor.json',sup)
        need(sup['status']=='COMPLETE' and sup['returncode']==0,'BINDING_HOLD:'+str(out))
        print(str(out/'bound.json'))
