"""Record this overlay and references; no external data walk or hash."""
import csv,json,os
from pathlib import Path
from binding import *

def main():
    rows=[];pins=[]
    for x in csv.DictReader((BASE/'SOURCE_MAP.csv').open(encoding='utf-8-sig',newline='')):
        copy=BASE/x['copy'];relative=os.path.relpath(copy,HERE).replace('\\','/')
        rows.append(dict(original=x['original'],original_sha256=x['original_sha256'],copy=relative,copy_sha256=x['copy_sha256'],role=x['role'],modified='REFERENCED_UNCHANGED_BASE',dependency='v0_1/'+x['copy']))
        if copy.suffix=='.py' or copy.name=='khmd_nationwide_reference_resource_monitor_contract_v0_2.json':pins.append(dict(path=relative,sha256=x['copy_sha256']))
    origin={'busan_finish.py':'csv_spatial_5179_busan_v0_3/finish.py','busan_geometry.py':'csv_spatial_5179_busan_v0_2/run.py','guji.py':'csv_spatial_target_quality_v0_1/quality.py;csv_spatial_target_quality_v0_2/quality_v0_3.py','aggregate_consumer.py':'csv_spatial_national_5179_v0_1/pipeline.py'}
    for p in sorted(HERE.glob('*.py')):
        digest=sha(p)
        predecessors=[ANNUAL/x for x in origin.get(p.name,'').split(';') if x]
        rows.append(dict(original=';'.join(str(x.relative_to(BASE)) for x in predecessors) or 'NEW_CONNECTION_CODE',original_sha256=';'.join(sha(x) for x in predecessors),copy=p.name,copy_sha256=digest,role='changed handoff' if predecessors else 'binding/tooling',modified='NEW_OR_CONNECTION_ONLY',dependency='code_dependencies.json;base v0_1'))
        pins.append(dict(path=p.name,sha256=digest))
    # Development pin refresh is explicit; execution never changes pins.
    for name,obj in [('code_dependencies.json',pins)]:
        path=HERE/name
        if path.exists():path.rename(HERE/(name+'.prior_'+__import__('datetime').datetime.now().strftime('%H%M%S%f')))
        write(path,obj)
    dest=HERE/'SOURCE_MAP.csv'
    if dest.exists():dest.rename(HERE/('SOURCE_MAP.prior_'+__import__('datetime').datetime.now().strftime('%H%M%S%f')+'.csv'))
    with dest.open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

if __name__=='__main__':main()
