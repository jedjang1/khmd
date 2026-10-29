"""One-time, no-replace extraction of only changed construction connections."""
import ast, difflib, json
from pathlib import Path
from binding import HERE, BASE, ANNUAL, write

def function(text,name):
    n=next(x for x in ast.parse(text).body if isinstance(x,ast.FunctionDef) and x.name==name)
    return '\n'.join(text.splitlines()[n.lineno-1:n.end_lineno])+'\n'

def save(name,text,source):
    dest=HERE/name
    with dest.open('x',encoding='utf-8') as f:f.write(text)
    with (HERE/'diffs'/ (name+'.diff')).open('x',encoding='utf-8') as f:
        f.writelines(difflib.unified_diff(source.splitlines(True),text.splitlines(True),fromfile='v0_1/'+name,tofile='v0_2/'+name))

def main():
    (HERE/'diffs').mkdir()
    old=(ANNUAL/'csv_spatial_5179_busan_v0_3/finish.py').read_text(encoding='utf-8')
    body=function(old,'process').replace('def process(out,work,g,pause):','def process(bound,out,work,g,pause=0):')
    replacements={
      "cfg=check(g);g.reserve_output(64*1024**2)":"cfg,inputs=check(bound,g);g.reserve_output(64*1024**2)",
      'test_results=tests(out)':"test_results=[] # prior regression tests are bound separately; not repeated here",
      "V/'busan_run/spatial.sqlite'":"inputs['spatial']",
      "P/'busan_candidates/candidates.sqlite'":"inputs['candidates']",
      "V/'config.json'":"inputs['geometry_config']",
      "V/'grid_policy.json'":"inputs['grid_policy']",
      '(5120,1327806)':"(cfg['address_keys'],cfg['input_occurrences'])",
      "'all_5120_geometry_checkpoint_bindings_verified'":"'all_bound_geometry_checkpoint_bindings_verified'",
      "H/'config.json'":'bound',
      "P/'national_demand/demand.sqlite'":"inputs['demand']",
      'len(files)==30':"len(files)==cfg['input_cells']",
      'sum(x[3] for x in files)==1327806':"sum(x[3] for x in files)==cfg['input_occurrences']",
      'total==1327806':"total==cfg['input_occurrences']",
      "fetchone()[0]==30":"fetchone()[0]==cfg['input_cells']",
      "input_cells=30":"input_cells=cfg['input_cells']",
      'geometry_recomputed_this_resume=0,old_HOLD_preserved=True':'geometry_recomputed_this_resume=0,normal_completion=True',
      "statuses['ASSIGNED']":"statuses.get('ASSIGNED',0)",
      "select sum(n) from counts where status='ASSIGNED'":"select coalesce(sum(n),0) from counts where status='ASSIGNED'",
    }
    for a,z in replacements.items():
        assert a in body,a;body=body.replace(a,z)
    header='''"""Normal Busan finalization; original finish.process validation and aggregation."""
import csv,json,sqlite3
from pathlib import Path
from binding import verify, read, sha, need, ANNUAL
from runtime import load
r=load('busan_base_run',ANNUAL/'csv_spatial_5179_busan_v0_2/run.py')
b=r.b;d=r.d

def check(bound,g):
    m,inputs=verify(bound,'busan_finish',g);cfg=m['parameters']
    for k in ('address_keys','input_cells','input_occurrences'):
        need(isinstance(cfg.get(k),int) and cfg[k]>0,'MISSING_SCOPE:'+k)
    if m['scope']=='EXTERNAL':
        need((cfg['address_keys'],cfg['input_cells'],cfg['input_occurrences'])==(5120,30,1327806),'BUSAN_FROZEN_SCOPE')
    cw=inputs['candidates'].parent
    for role,name in [('candidate_input','input_manifest.json'),('candidate_manifest','candidate_manifest.json'),('candidate_publication','publication_receipt.json')]:
        need(inputs[role]==cw/name,'CANDIDATE_LAYOUT:'+role)
    receipt=read(inputs['candidate_publication'])
    need(Path(receipt['supervised_completion']).resolve()==inputs['candidate_completion'],'CANDIDATE_COMPLETION_PATH')
    r.publication.check(cw) # unchanged candidate SHA/supervisor gate
    geometry=read(inputs['geometry_completion']); sup=geometry['supervisor']
    need(sup['status']=='COMPLETE' and sup['returncode']==0 and not sup.get('hold_reason'),'GEOMETRY_SUPERVISOR')
    result=geometry['result']
    need(result['status']=='BUSAN_GEOMETRY_CHECKPOINT_READY','GEOMETRY_STAGE_INCOMPLETE')
    need(result['spatial_sha256']==sha(inputs['spatial'],g),'GEOMETRY_SHA')
    need(result['config_sha256']==sha(inputs['geometry_config'],g) and result['policy_sha256']==sha(inputs['grid_policy'],g),'GEOMETRY_INPUT_BINDING')
    need(result['candidate_sha256']==sha(inputs['candidates'],g),'GEOMETRY_CANDIDATE_BINDING')
    need((result['address_keys'],result['input_occurrences'])==(cfg['address_keys'],cfg['input_occurrences']),'GEOMETRY_SCOPE')
    need(result.get('scope')==m['scope'],'GEOMETRY_SCOPE_KIND')
    policy=read(inputs['policy_completion']); regression=read(inputs['regression_completion'])
    for receipt in (policy,regression):
        need(receipt['supervisor']['status']=='COMPLETE' and receipt['supervisor']['returncode']==0,'PREREQUISITE_SUPERVISOR')
    need(policy['result']['status']=='POLICY_TESTS_PASS' and policy['policy_sha256']==sha(inputs['grid_policy'],g),'POLICY_TESTS_BINDING')
    need(regression['result']['status']=='RESTART_TESTS_PASS','RESTART_TESTS')
    return cfg,inputs

'''
    save('busan_finish.py',header+function(old,'table')+'\n'+function(old,'transaction')+'\n'+body,old)

    # Geometry writes committed results, validates unchanged source identities, and
    # ends normally BEFORE the historical failing ATTACH. No fake failure receipt.
    oldgeo=(ANNUAL/'csv_spatial_5179_busan_v0_2/run.py').read_text(encoding='utf-8')
    geo=oldgeo.replace("H=Path(__file__).resolve().parent;ROOT=H.parents[3];P=H.parent/'csv_regional_demand_v0_1'", "from binding import PROJECT, ANNUAL\nH=Path(os.environ['KHMD_BUSAN_STAGE']).resolve();ROOT=PROJECT;P=H.parent/'csv_regional_demand_v0_1'")
    geo=geo.replace('sys.path.insert(0,str(P));import demand as d',"sys.path.insert(0,str(ANNUAL/'csv_regional_demand_v0_1'));import demand as d")
    geo=geo.replace("sys.path.insert(0,str(H.parent/'csv_spatial_supply_v0_1'));import supply_v0_4 as s", "sys.path.insert(0,str(ANNUAL/'csv_spatial_supply_v0_1'));import supply_v0_4 as s\nsys.path.insert(0,str(ANNUAL/'csv_spatial_5179_busan_v0_2'))")
    start=geo.index('        # Use already-derived file/key/quarter weights')
    end=geo.index('    finally:source[2].close()',start)
    geo=geo[:start]+'''        b.need(all(b.identity(p)==v for p,v in source_ids.items()),'SOURCE_CHANGED')
        b.write(work/'source_CRS.json',source[4]);c.commit();c.close()
        from completion import geometry_ready
        return geometry_ready(work/'spatial.sqlite',P/'busan_candidates/candidates.sqlite',H/'config.json',H/'grid_policy.json',5120,1327806,'EXTERNAL',g)
'''+geo[end:]
    # close is idempotent. The existing supervisor writes a real completion receipt;
    # the final national-consumable manifest is produced by busan_finish only.
    save('busan_geometry.py',geo,oldgeo)

    oldseed=(ANNUAL/'csv_spatial_target_quality_v0_1/quality.py').read_text(encoding='utf-8')
    prefix=function(oldseed,'prepare').split('    # Existing candidates are retained')[0]
    prefix=prefix.replace('def prepare(out,g):','def seed(bound,out,work,g):')
    prefix=prefix.replace("cfg=p.config(g);p.verify_final(N/'national/final_manifest.json',g)", "cfg,inputs=seed_check(bound,g);H=work;N=inputs['mapping'].parent")
    prefix=prefix.replace("path=current_region(region,cfg);r=db(path,True)","path=inputs['region:'+region];r=db(path,True)")
    prefix=prefix.replace("p.V/'busan_run/spatial.sqlite'","inputs['busan_spatial']")
    prefix=prefix.replace('(47676,20916100)',"(cfg['baseline_keys'],cfg['baseline_occurrences'])")
    prefix=prefix.replace("p.P/'national_demand/demand.sqlite'","inputs['demand']").replace("N/'normalization.sqlite'","inputs['mapping']")
    prefix=prefix.replace("(H/'evidence/legal_code_table.txt')","inputs['legal_codes']").replace("(H/'evidence/change.hwpx.txt')","inputs['official_change']")
    prefix=prefix.replace("rows=mapping.execute('select id,province,n from mapping where reason=? order by n desc,id',(rule,)).fetchall();top=rows[:10]", "rows=mapping.execute('select id,province,n from mapping where reason=? order by n desc,id',(rule,)).fetchall();b.need(len(rows)>=30,'INSUFFICIENT_RULE_SAMPLE:'+rule);top=rows[:10]")
    prefix=prefix.replace("cfg,inputs=seed_check(bound,g);H=work;N=inputs['mapping'].parent", "cfg,inputs=seed_check(bound,g);H=work;N=inputs['mapping'].parent\n    need(not(work/'quality.sqlite').exists(),'SEED_INITIAL_OUTPUT_EXISTS_USE_NEW_WORK_OR_COMPLETED_MANIFEST')")
    prefix+='''    c.commit();c.close();demand.close();mapping.close()
    result=validate_seed(work/'quality.sqlite',cfg)
    g.checkpoint('official_crosswalk_and_selected_weights_seed_complete')
    return dict(status='GUJI_SEED_READY',**result)
'''
    oldnext=(ANNUAL/'csv_spatial_target_quality_v0_2/quality_v0_3.py').read_text(encoding='utf-8')
    prepare=function(oldnext,'prepare').replace('def prepare(out,g):','def prepare(bound,out,work,g):')
    prepare=prepare.replace("cfg=p.config(g);c=db(H/'quality.sqlite');demand=db(p.P/'national_demand/demand.sqlite',True);mapping=db(N/'normalization.sqlite',True)", "cfg,inputs=prepare_check(bound,work,g);H=work;c=db(work/'quality.sqlite');demand=db(inputs['demand'],True);mapping=db(inputs['mapping'],True)")
    prepare=prepare.replace("p.P/'busan_candidates/candidates.sqlite'","inputs['busan_candidates']")
    prepare=prepare.replace("b.read(BASE/'csv_spatial_supply_v0_1/supply_run_v0_4/regional_extraction.json')","b.read(inputs['busan_extraction'])")
    prepare=prepare.replace("O/'regions'/cfg['region_ids'][region]/'regional.sqlite'","inputs['base_region:'+region]")
    prepare=prepare.replace("ix=db(ROOT/cfg['index_path'],True);sets=member_sets(cfg)","ix=db(inputs['parcel_index'],True);sets=b.read(inputs['members'])['sets_by_id']")
    prepare=prepare.replace('guji_keys=9,guji_occurrences=8629',"guji_keys=9,guji_occurrences=cfg['guji_occurrences']")
    # Final validate uses the exact legacy prepare schema/selection contract.
    header='''"""Extracted real seed prefix and next prepare, with explicit immutable handoff."""
import csv,json,hashlib,sqlite3
from pathlib import Path
from collections import defaultdict
from binding import *
from runtime import load
from guji_contract import seed_check,prepare_check,validate_seed
p=load('national_base',ANNUAL/'csv_spatial_national_5179_v0_1/pipeline.py')
b=p.b;s=p.s;d=p.d;db=p.db

'''
    save('guji.py',header+prefix+'\n'+prepare,oldseed+'\n'+oldnext)

if __name__=='__main__':main()
