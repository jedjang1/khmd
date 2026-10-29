"""Validate official seed inputs and hand off a COPY to the real candidate prepare."""
import sqlite3
from pathlib import Path
from binding import *

def ro(path):
    c=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    c.execute('pragma cache_size=-2048');return c

def seed_check(bound,g):
    m,inputs=verify(bound,'guji_seed',g);cfg=m['parameters']
    for k in ('baseline_keys','baseline_occurrences','guji_occurrences','regions'):
        need(k in cfg,'GUJI_PARAMETER:'+k)
    if m['scope']=='EXTERNAL':
        need((cfg['baseline_keys'],cfg['baseline_occurrences'],cfg['guji_occurrences'])==(47676,20916100,8629),'GUJI_FROZEN_SCOPE')
    baseline=read(inputs['baseline_manifest'])
    need(baseline.get('scope', 'EXTERNAL')==m['scope'],'BASELINE_SCOPE_KIND')
    # Original final manifest artifact hashes are evidence, never rewritten.
    need(baseline.get('result',{}).get('status') in ('NATIONAL_SPATIAL_COMPLETE','NATIONAL_5179_COMPLETE','SYNTHETIC_BASELINE_READY'),'BASELINE_STATUS')
    artifacts={str(Path(x['path']).resolve()):x['sha256'] for x in baseline['artifacts']}
    source_manifests={}
    if m['scope']=='EXTERNAL':
        need('baseline_database' in inputs,'BASELINE_DATABASE_REQUIRED')
        need(artifacts.get(str(inputs['baseline_database']))==sha(inputs['baseline_database'],g),'BASELINE_DATABASE_BINDING')
        national=ro(inputs['baseline_database'])
        try:source_manifests=dict(national.execute('select region,manifest_sha from sources'))
        finally:national.close()
    required=['busan_spatial',*('region:'+r for r in cfg['regions'])]
    for role in required:
        need(role in inputs,'REGIONAL_INPUT_MISSING:'+role)
        if m['scope']=='EXTERNAL':
            region='부산광역시' if role=='busan_spatial' else role.split(':',1)[1]
            mr='region_manifest:'+region;need(mr in inputs,'REGIONAL_MANIFEST_REQUIRED:'+region)
            need(source_manifests.get(region)==sha(inputs[mr],g),'NATIONAL_REGIONAL_CHAIN:'+region)
            regional=read(inputs[mr]);ra={str(Path(x['path']).resolve()):x['sha256'] for x in regional['artifacts']}
            need(ra.get(str(inputs[role]))==sha(inputs[role],g),'REGIONAL_DATABASE_BINDING:'+region)
        else:
            need(artifacts.get(str(inputs[role]))==sha(inputs[role],g),'BASELINE_REGIONAL_BINDING:'+role)
    manifest_roles={x['role']:x for x in m['inputs']}
    for role in ('legal_codes','official_change'):
        need(manifest_roles[role]['reference_time']=='2026-09-30','OFFICIAL_EFFECTIVE_DATE')
    need(cfg.get('reference_date')=='2026-09-08','REFERENCE_DATE')
    return cfg,inputs

SCHEMA={
 'results':['id','region','status','n','payload','source_db'],
 'selected':['id','category','selection'],
 'weights':['file_sha','key_id','quarter','row_status','n'],
 'candidates':['id','set_id','pnu','ordinal','sha','code','lot','eligibility'],
 'guji':['id','source','lot','old_code','new_code','old_name','new_name','n','effective_date'],
}

def validate_seed(path,cfg):
    c=ro(path)
    try:
        for table,cols in SCHEMA.items():
            need([x[1] for x in c.execute('pragma table_info('+table+')')]==cols,'SEED_SCHEMA:'+table)
        need(c.execute('select count(*),sum(n) from results').fetchone()==(cfg['baseline_keys'],cfg['baseline_occurrences']),'SEED_BASELINE_SCOPE')
        need(c.execute('select count(*) from selected').fetchone()[0]==109,'SEED_SELECTION_109')
        need(c.execute('select count(*),sum(n) from guji').fetchone()==(9,cfg['guji_occurrences']),'SEED_GUJI_SCOPE')
        for aid,n in c.execute('select s.id,r.n from selected s join results r using(id)'):
            need(c.execute('select sum(n) from weights where key_id=?',(aid,)).fetchone()[0]==n,'SEED_WEIGHT_CONSERVATION:'+aid)
        for aid,source,lot,old,new,on,nn,n,date in c.execute('select * from guji'):
            need(old!=new and date=='2026-09-30' and source==nn and source.endswith(on.split()[-1]),'GUJI_CODE_TRANSITION')
            need(c.execute('select category from selected where id=?',(aid,)).fetchone()==('GUJI',),'GUJI_SELECTION')
            need(c.execute('select status,n from results where id=?',(aid,)).fetchone()==('UNLINKED_NAME_OR_JIBUN',n),'GUJI_PRIOR_STATE')
        need(c.execute('select count(*) from weights where n<=0').fetchone()[0]==0,'NONPOSITIVE_WEIGHT')
        return dict(selected_keys=109,guji_keys=9,guji_occurrences=cfg['guji_occurrences'],seed_schema='LEGACY_QUALITY_SQLITE_V1')
    finally:c.close()

def prepare_check(bound,work,g):
    m,inputs=verify(bound,'guji_prepare',g);cfg=m['parameters']
    seed=verify_stage(inputs['seed_manifest'],'GUJI_SEED_READY',m['scope'],g)
    artifacts={str(Path(x['path']).resolve()):x['sha256'] for x in seed['artifacts']}
    for role in ('seed_database','seed_crosswalk'):
        need(artifacts.get(str(inputs[role]))==sha(inputs[role],g),'SEED_ARTIFACT_BINDING:'+role)
    parent=read(seed['bound_manifest']); parentroles={x['role']:x for x in parent['inputs']}
    for role in ('demand','mapping'):
        need(sha(inputs[role],g)==parentroles[role]['sha256'],'SEED_INPUT_CHANGED:'+role)
    need(cfg==parent['parameters'],'SEED_PARAMETERS_CHANGED')
    validate_seed(inputs['seed_database'],cfg)
    members=read(inputs['members'])['sets_by_id']
    bound_paths={str(Path(x['path']).resolve()):x['sha256'] for x in m['inputs']}
    for sid,rec in members.items():
        for ext,member in rec['members'].items():
            path=str(Path(member['path']).resolve())
            need(bound_paths.get(path)==member['sha256'],'UNBOUND_MEMBER:'+sid+':'+ext)
    # Fallback candidate sources and their records must be bound before prepare.
    src=ro(inputs['seed_database'])
    try:
        for path, in src.execute('select distinct source_db from results where id in(select id from selected)'):
            need(str(Path(path).resolve()) in bound_paths,'UNBOUND_CANDIDATE_SOURCE:'+path)
    finally:src.close()
    token=work/'seed_handoff.json';dbpath=work/'quality.sqlite'
    fingerprint=dict(bound_sha256=sha(bound,g),seed_sha256=sha(inputs['seed_database'],g))
    if token.exists():
        need(read(token)==fingerprint,'SEED_RESUME_BINDING')
        need(dbpath.is_file(),'SEED_RESUME_DATABASE_MISSING')
        validate_seed(dbpath,cfg)
        original=ro(inputs['seed_database']); current=ro(dbpath)
        try:
            for table in ('results','selected','weights','guji'):
                order=','.join(SCHEMA[table])
                a=original.execute('select * from '+table+' order by '+order)
                z=current.execute('select * from '+table+' order by '+order)
                import itertools
                for left,right in itertools.zip_longest(a,z):
                    need(left==right,'SEED_IMMUTABLE_STATE_DRIFT:'+table)
        finally:original.close();current.close()
    else:
        need(not dbpath.exists(),'UNOWNED_QUALITY_DATABASE')
        tmp=work/'quality.partial.sqlite';need(not tmp.exists(),'INTERRUPTED_SEED_COPY_REQUIRES_REVIEW')
        source=ro(inputs['seed_database']);dest=sqlite3.connect(tmp)
        try:source.backup(dest,pages=128,progress=lambda *_:g.checkpoint('seed_copy_pages'))
        finally:source.close();dest.close()
        validate_seed(tmp,cfg);tmp.rename(dbpath);write(token,fingerprint)
    return cfg,inputs
