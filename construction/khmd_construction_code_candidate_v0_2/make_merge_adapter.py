"""Extract only the existing aggregate consumer; parameterize input manifests."""
from binding import *
from assemble_overlay import function,save

if __name__=='__main__':
    old=(ANNUAL/'csv_spatial_national_5179_v0_1/pipeline.py').read_text(encoding='utf-8')
    body=function(old,'merge')
    body=body.replace('def merge(out,g):','def merge(out,g,manifests,scope,expected_input,expected_cells):')
    body=body.replace('    cfg=config(g);c=db(', '    allregions=checked_inputs(manifests,scope,g)\n    if scope==\'EXTERNAL\':need(len(allregions)==16 and expected_input==20916100 and expected_cells==480,\'NATIONAL_FROZEN_SCOPE\')\n    c=db(')
    first=body.index('    allregions=[]');last=body.index('    per_region_grid_groups=0',first)
    body=body[:first]+body[last:]
    body=body.replace('total==20916100','total==expected_input').replace("status='NATIONAL_SPATIAL_COMPLETE',regions=16,cells=480", "status=('NATIONAL_SPATIAL_COMPLETE' if scope=='EXTERNAL' else 'SYNTHETIC_MERGE_CONNECTION_COMPLETE'),scope=scope,regions=len(allregions),cells=expected_cells")
    header='''"""Manifest-directed consumer of the unchanged national merge SQL."""
import csv
from pathlib import Path
from binding import *
from runtime import load
p=load('merge_original',ANNUAL/'csv_spatial_national_5179_v0_1/pipeline.py')
b=p.b;db=p.db;table=p.table;grid=p.grid

def checked_inputs(manifests,scope,g):
    need(scope in ('SYNTHETIC','EXTERNAL'),'MERGE_SCOPE')
    regions=set();seen=set();rows=[]
    for region,path in manifests:
        path=Path(path).resolve();need(region not in regions and path not in seen,'DUPLICATE_REGION_OR_MANIFEST');regions.add(region);seen.add(path)
        m=read(path)
        if m.get('schema')=='KHMD_CONSTRUCTION_STAGE_V2':
            verify_stage(path,'BUSAN_5179_SPATIAL_COMPLETE',scope,g)
            need(region=='부산광역시','BUSAN_REGION')
        else:
            need(scope=='EXTERNAL' and m.get('status')=='REGION_COMPLETE','REGIONAL_STAGE_STATUS')
            p.verify_final(path,g)
        result=m['result'];need(result['assigned']+result['unassigned']==result['input_occurrences'],'REGIONAL_COUNT_CONSERVATION')
        exports=[Path(x['path']).resolve() for x in m['artifacts'] if Path(x['path']).name=='grid_quarter_counts.csv']
        need(len(exports)==1,'GRID_EXPORT_NOT_UNIQUE')
        rows.append((region,result,exports[0].parent,path))
    return rows

'''
    save('aggregate_consumer.py',header+body,old)
