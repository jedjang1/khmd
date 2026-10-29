"""Explicit file binding for the three construction handoffs; no success inheritance."""
import argparse, hashlib, json, os
from pathlib import Path

HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'khmd_construction_code_candidate_v0_1'
PROJECT=BASE/'project'
ANNUAL=PROJECT/'experiments/khmd_bulk_csv_large_pilot_v0_1/annual_run_v0_3'

def need(ok, why):
    if not ok: raise ValueError(why)

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, obj):
    with Path(path).open('x',encoding='utf-8') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2)

def sha(path,g=None):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
            if g:g.checkpoint('binding_bytes_hashed')
    return h.hexdigest()

def regular(path):
    p=Path(path).resolve(strict=True)
    need(p.is_file(),'INPUT_NOT_FILE:'+str(p))
    for part in [Path(path).absolute(),*Path(path).absolute().parents]:
        need(not(part.lstat().st_file_attributes & 1024) if os.name=='nt' else not part.is_symlink(), 'REPARSE_INPUT:'+str(part))
    return p

def bind(config, output, g=None):
    config=regular(config); c=read(config)
    need(c.get('schema')=='KHMD_CONSTRUCTION_INPUTS_V2','CONFIG_SCHEMA')
    need(c.get('scope') in ('SYNTHETIC','EXTERNAL'),'INPUT_SCOPE')
    need(c.get('stage') in ('busan_finish','guji_seed','guji_prepare'),'STAGE')
    need(c.get('inputs') and c.get('parameters') is not None,'CONFIG_INPUTS')
    rows=[]; roles=set()
    for x in c['inputs']:
        role=x.get('role'); need(role and role not in roles,'DUPLICATE_OR_MISSING_ROLE');roles.add(role)
        for k in ('schema','source','version','reference_time','acquisition_time_status'):
            need(x.get(k) not in (None,''),'REQUIRED_METADATA:'+role+':'+k)
        need(x.get('path'),'INPUT_PATH_MISSING:'+role)
        p=regular(config.parent/x['path']); digest=sha(p,g)
        need(not x.get('expected_sha256') or digest==x['expected_sha256'],'INPUT_SHA_MISMATCH:'+role)
        rows.append(dict(x,path=str(p),sha256=digest,
            hash_confirmation='EXPECTED_SHA_MATCH' if x.get('expected_sha256') else 'HASH_RECORDED_THIS_BINDING'))
    required={
        'busan_finish':{'spatial','candidates','candidate_input','candidate_manifest','candidate_publication','candidate_completion','geometry_completion','geometry_config','grid_policy','policy_completion','regression_completion','demand'},
        'guji_seed':{'baseline_manifest','demand','mapping','legal_codes','official_change'},
        'guji_prepare':{'seed_manifest','seed_database','seed_crosswalk','demand','mapping','members','parcel_index'},
    }[c['stage']]
    need(required<=roles,'MISSING_INPUT_ROLES:'+','.join(sorted(required-roles)))
    # Bind the actual referenced source closure, not old execution source pins.
    code=[]
    for x in read(HERE/'code_dependencies.json'):
        p=regular(HERE/x['path']); need(sha(p,g)==x['sha256'],'CANDIDATE_CODE_DRIFT:'+x['path'])
        code.append(dict(path=str(p),sha256=x['sha256']))
    result=dict(schema='KHMD_BOUND_STAGE_V2',scope=c['scope'],stage=c['stage'],
        status='INPUTS_BOUND_NOT_EXECUTED',configuration_path=str(config),configuration_sha256=sha(config,g),
        parameters=c['parameters'],inputs=rows,code=code)
    write(output,result);return result

def verify(path, stage, g=None):
    m=read(path);need(m.get('schema')=='KHMD_BOUND_STAGE_V2' and m.get('stage')==stage,'BOUND_STAGE')
    need(m.get('status')=='INPUTS_BOUND_NOT_EXECUTED','NOT_AN_EXECUTION_RECEIPT')
    need(sha(m['configuration_path'],g)==m['configuration_sha256'],'CONFIG_DRIFT')
    for x in m['inputs']+m['code']:
        need(sha(regular(x['path']),g)==x['sha256'],'BOUND_FILE_DRIFT:'+x['path'])
    return m,{x['role']:Path(x['path']) for x in m['inputs']}

def verify_stage(path, status, scope, g=None):
    m=read(path)
    need(m.get('schema')=='KHMD_CONSTRUCTION_STAGE_V2' and m.get('scope')==scope,'STAGE_SCOPE_SCHEMA')
    need(m.get('status')==status,'STAGE_NOT_COMPLETE:'+str(m.get('status')))
    need(sha(m['bound_manifest'],g)==m['bound_sha256'],'STAGE_PARENT_DRIFT')
    verify(m['bound_manifest'],m['stage'],g)
    need(sha(m['completion'],g)==m['completion_sha256'],'COMPLETION_DRIFT')
    completion=read(m['completion']);sup=completion['supervisor']
    need(sup['status']=='COMPLETE' and sup['returncode']==0 and not sup.get('hold_reason'),'SUPERVISOR_NOT_COMPLETE')
    need(completion['result']==m['result'],'STAGE_RESULT_DRIFT')
    for x in m['artifacts']:need(sha(x['path'],g)==x['sha256'],'STAGE_OUTPUT_DRIFT')
    return m

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();bind(a.config,a.output)
