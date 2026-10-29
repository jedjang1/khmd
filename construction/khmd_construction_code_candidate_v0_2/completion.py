"""Normal geometry checkpoint closure used by the corrected real Busan producer."""
from binding import need,sha

def geometry_ready(spatial,candidates,config,policy,keys,occurrences,scope,g):
    from runtime import load,ANNUAL
    r=load('geometry_closure_base',ANNUAL/'csv_spatial_5179_busan_v0_2/run.py')
    c=r.db(spatial,True);k=r.db(candidates,True)
    try:
        need(c.execute('select count(*),sum(n) from results').fetchone()==(keys,occurrences),'GEOMETRY_CHECKPOINT_INCOMPLETE')
        expected=r.b.digest(dict(config=sha(config,g),policy=sha(policy,g)))
        need(c.execute('select binding from meta').fetchone()==(expected,),'GEOMETRY_CHECKPOINT_BINDING')
        need(k.execute('select count(*),sum(occurrences) from key_results').fetchone()==(keys,occurrences),'CANDIDATE_SCOPE')
        for aid,n in c.execute('select address_id,n from results'):
            need(k.execute('select occurrences from key_results where address_id=?',(aid,)).fetchone()==(n,),'GEOMETRY_KEY_WEIGHT')
    finally:c.close();k.close()
    return dict(status='BUSAN_GEOMETRY_CHECKPOINT_READY',scope=scope,address_keys=keys,input_occurrences=occurrences,
        spatial_sha256=sha(spatial,g),candidate_sha256=sha(candidates,g),config_sha256=sha(config,g),policy_sha256=sha(policy,g))
