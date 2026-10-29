"""Manifest-directed consumer of the unchanged national merge SQL."""
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

def merge(out,g,manifests,scope,expected_input,expected_cells):
    allregions=checked_inputs(manifests,scope,g)
    if scope=='EXTERNAL':need(len(allregions)==16 and expected_input==20916100 and expected_cells==480,'NATIONAL_FROZEN_SCOPE')
    c=db(out/'national.sqlite');c.executescript('create table grid(grid_id,quarter,family,n,primary key(grid_id,quarter,family));create table sources(region primary key,input,assigned,unassigned,manifest_sha);create table statuses(region,status,n,primary key(region,status));')
    per_region_grid_groups=0
    for region,result,folder,manifest in allregions:
        with c:
            total=0
            with (folder/'grid_quarter_counts.csv').open(encoding='utf-8-sig',newline='') as f:
                for row in csv.DictReader(f):
                    gid=row['grid_id'];b.need(gid.startswith(grid.VERSION+':'),'MIXED_GRID_VERSION');n=int(row['observation_occurrences']);total+=n;per_region_grid_groups+=1
                    c.execute('insert into grid values(?,?,?,?) on conflict(grid_id,quarter,family) do update set n=n+excluded.n',(gid,row['quarter'],row['family'],n))
            b.need(total==result['assigned'],'REGION_EXPORTED_GRID_SUM');c.execute('insert into sources values(?,?,?,?,?)',(region,result.get('input_occurrences'),total,result['unassigned'],b.lane.sha(manifest)))
            for status,n in result['status_occurrences'].items():c.execute('insert into statuses values(?,?,?)',(region,status,n))
        g.checkpoint('national_region_merge_committed_'+region)
    total,assigned,unassigned=c.execute('select sum(input),sum(assigned),sum(unassigned) from sources').fetchone();b.need(total==expected_input and assigned+unassigned==total,'NATIONAL_CONSERVATION');b.need(c.execute('select sum(n) from grid').fetchone()[0]==assigned,'NATIONAL_GRID_SUM')
    table(out/'national_grid_quarter_counts.csv',['grid_id','quarter','transaction_family','observation_occurrences'],c.execute('select * from grid order by 1,2,3'),g)
    table(out/'query_region_status_counts.csv',['query_region','status','observation_occurrences'],c.execute('select * from statuses order by 1,2'),g)
    table(out/'query_region_totals.csv',['query_region','input_occurrences','assigned','unassigned','manifest_sha256'],c.execute('select * from sources order by 1'),g)
    result=dict(status=('NATIONAL_SPATIAL_COMPLETE' if scope=='EXTERNAL' else 'SYNTHETIC_MERGE_CONNECTION_COMPLETE'),scope=scope,regions=len(allregions),cells=expected_cells,input_occurrences=total,assigned=assigned,unassigned=unassigned,status_occurrences=dict(c.execute('select status,sum(n) from statuses group by status')),grid_groups=c.execute('select count(*) from grid').fetchone()[0],regional_grid_groups=per_region_grid_groups,merged_cross_region_groups=per_region_grid_groups-c.execute('select count(*) from grid').fetchone()[0],same_value_occurrences_not_deduplicated=True,grid_version=grid.VERSION)
    c.close();return result
