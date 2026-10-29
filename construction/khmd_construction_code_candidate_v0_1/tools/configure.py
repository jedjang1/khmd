"""Resolve path templates only; never change a SHA pin or run a stage.

Outputs remain NOT_EXECUTION_READY until external artifacts and historical
continuation contracts have been independently bound. No auto-discovery.
"""
import argparse,json,re
from pathlib import Path
C=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--settings',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 settings=json.loads(a.settings.read_text(encoding='utf-8-sig'))
 values={k:(v.get('value') if isinstance(v,dict) else v) for k,v in settings.items()}
 values['PROJECT_ROOT']=str((C/'project').resolve())
 if values.get('KHMD_PROJECT_ROOT') not in (None,'./project',str(C/'project')):raise ValueError('PROJECT_ROOT_MUST_BE_CANDIDATE_MIRROR')
 values['KHMD_PROJECT_ROOT']=values['PROJECT_ROOT']
 out=a.output.resolve()
 if C not in out.parents or out==C/'project' or C/'project' in out.parents:raise ValueError('OUTPUT_MUST_BE_NEW_CANDIDATE_CONFIG_DIRECTORY')
 out.mkdir(parents=True,exist_ok=False);unresolved=[];resolved=[]
 def convert(x,location):
  if isinstance(x,dict):return {k:convert(v,location+'/'+k) for k,v in x.items()}
  if isinstance(x,list):return [convert(v,location+'/'+str(i)) for i,v in enumerate(x)]
  if isinstance(x,str):
   def sub(m):
    val=values.get(m[1])
    if not val:unresolved.append({'location':location,'setting':m[1]});return m[0]
    return str(val)
   return re.sub(r'\$\{([^}]+)\}',sub,x)
  return x
 for src in (C/'config_templates').rglob('*.json'):
  rel=src.relative_to(C/'config_templates');target=out/rel;target.parent.mkdir(parents=True,exist_ok=True)
  doc=convert(json.loads(src.read_text(encoding='utf-8')),str(rel))
  with target.open('x',encoding='utf-8') as f:json.dump(doc,f,ensure_ascii=False,indent=2)
  resolved.append(str(rel))
 result={'status':'NOT_EXECUTION_READY','templates':resolved,'unresolved':unresolved,
   'pins_changed':0,'stages_run':0,'reason':'Historical source pins, fixed counts, continuation inputs and external artifact identities still require binding. Path substitution is not a verification PASS.'}
 with (out/'CONFIGURATION_STATUS.json').open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
 print(json.dumps({'status':result['status'],'unresolved':len(unresolved),'output':str(out)}))
if __name__=='__main__':main()
