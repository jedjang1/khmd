"""Only supervised successful candidate results are reusable; partial != final."""
import argparse
from pathlib import Path
import demand as d
b=d.b;H=Path(__file__).resolve().parent
def verify(work,attempt):
    completion=b.read(attempt/'completion.json');sup=completion['supervisor']
    b.need(sup['status']=='COMPLETE' and sup['returncode']==0 and not sup['hold_triggered'],'CANDIDATE_SUPERVISOR_NOT_COMPLETE')
    m=b.read(work/'candidate_manifest.json')
    b.need(m['result']==completion['result'],'CANDIDATE_RESULT_BINDING')
    b.need(b.lane.sha(work/'input_manifest.json')==m['input_manifest_sha256'],'CANDIDATE_INPUT_BINDING')
    b.need(b.lane.sha(work/'candidates.sqlite')==m['database_sha256'],'CANDIDATE_DATABASE_SHA')
    return dict(status='SUPERVISED_CANDIDATE_REUSABLE_NOT_SPATIAL_PASS',candidate_manifest_sha256=b.lane.sha(work/'candidate_manifest.json'),supervised_completion=str(attempt/'completion.json'),supervised_completion_sha256=b.lane.sha(attempt/'completion.json'),database_sha256=m['database_sha256'])
def check(work):
    receipt=b.read(work/'publication_receipt.json');p=Path(receipt['supervised_completion'])
    b.need(b.lane.sha(p)==receipt['supervised_completion_sha256'],'SUPERVISION_DRIFT')
    b.need(verify(work,p.parent)==receipt,'PUBLICATION_RECEIPT_DRIFT');return receipt
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('mode',choices=['publish','check']);a.add_argument('--work',type=Path,required=True);a.add_argument('--attempt',type=Path);v=a.parse_args()
    if v.mode=='publish':b.write(v.work.resolve()/'publication_receipt.json',verify(v.work.resolve(),v.attempt.resolve()))
    else:print(b.dump(check(v.work.resolve())))
