"""Targeted full stream verification before registration, unchanged parser values."""
import csv,re
from collections import Counter
from datetime import date
from pathlib import Path
def is_excluded(item,entries):
    return next((e for e in entries if item.get('sha256')==e['sha256'] and item.get('cell_ids')==[e['cell_id']]),None)
def validate(spec,lane,guard,func):
    p=Path(spec['path']);before=p.stat();lane.need(lane.sha(p,guard)==spec['sha256'],'CANDIDATE_SHA_DRIFT')
    counts=Counter();widths=Counter();months=Counter();regions=Counter();first_errors=[];n=good=0;syntax=None
    with p.open('rb') as f:
        lines=lane.Lines(f,spec['encoding'],guard);rr=csv.reader(lines,strict=True)
        pre=[]
        for values in rr:
            if values and values[0]=='NO':break
            pre.append(values[0])
        lane.need(values==spec['columns'],'PREFLIGHT_HEADER_DRIFT')
        cond={s.split(' : ',1)[0]:s.split(' : ',1)[1] for s in pre if ' : ' in s}
        lane.need(cond==spec['conditions'],'PREFLIGHT_CONDITIONS_DRIFT')
        while True:
            start=f.tell()
            try:values=next(rr)
            except StopIteration:break
            except (UnicodeError,csv.Error,ValueError) as e:
                syntax=dict(reason=str(e),byte_start=start);break
            n+=1;widths[len(values)]+=1
            try:
                lane.need(len(values)==len(spec['columns']),'ROW_WIDTH');r=dict(zip(spec['columns'],values))
                lane.need(r['NO']==str(n),'ROW_NUMBER_SEQUENCE')
                ym=r['계약년월'];lane.need(bool(re.fullmatch(r'\d{6}',ym)),'CONTRACT_MONTH')
                day=date(int(ym[:4]),int(ym[4:]),int(r['계약일'])).isoformat();q=spec['query']
                lane.need(q['date_from']<=day<=q['date_to'],'ROW_DATE_OUTSIDE_QUERY')
                lane.need(r['시군구'].startswith(q['province']+' '),'ROW_REGION_OUTSIDE_QUERY')
                for k in ['전용면적(㎡)','층','건축년도','거래금액(만원)','보증금(만원)','월세금(만원)','종전계약 보증금(만원)','종전계약 월세(만원)']:
                    if k in r:func['num'](r[k],k=='전용면적(㎡)')
                good+=1;months[ym]+=1;regions[r['시군구']]+=1
            except (ValueError,KeyError,TypeError) as e:
                counts[str(e)]+=1
                if len(first_errors)<3:first_errors.append(dict(ordinal=n,byte_start=start,reason=str(e)))
            if n%256==0:guard.checkpoint('preflight_records_'+str(n))
        eof=f.tell()
    after=p.stat();lane.need((before.st_size,before.st_mtime_ns,before.st_ino)==(after.st_size,after.st_mtime_ns,after.st_ino),'CANDIDATE_IDENTITY_DRIFT')
    lane.need(lane.sha(p,guard)==spec['sha256'],'CANDIDATE_BYTES_DRIFT')
    ok=syntax is None and n==good==spec['expected_rows'] and eof==before.st_size
    return dict(status='PASS' if ok else 'HOLD',path=str(p),sha256=spec['sha256'],bytes=before.st_size,conditions=spec['conditions'],header_columns=spec['columns'],encoding=spec['encoding'],records=n,valid_records=good,error_reasons=dict(counts),width_counts=dict(widths),syntax_error=syntax,first_errors=first_errors,month_counts=dict(months),region_counts=dict(regions),EOF_reached=eof==before.st_size,population_completeness='UNPROVEN')
