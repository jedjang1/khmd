import json,hashlib,csv
from pathlib import Path
from datetime import datetime,timezone
H=Path(__file__).resolve().parent; ROOT=H.parents[3]
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
def put(p,x):
 with p.open('x',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2)
m=json.loads((H/'panel/panel_release_manifest.json').read_text(encoding='utf-8'))
path=H/'panel/panel.sqlite';blocks=[]
with path.open('rb') as f:
 for chunk in iter(lambda:f.read(1048576),b''):blocks.append(hashlib.sha256(chunk).hexdigest())
m['database_integrity']=dict(algorithm='sha256',bytes=path.stat().st_size,chunk_bytes=1048576,chunk_sha256=blocks)
m['limited_mountain_review']=dict(path=str(H/'mountain/mountain_review.json'),sha256=sha(H/'mountain/mountain_review.json'),new_assignments=0)
m['created_utc']=datetime.now(timezone.utc).isoformat()
put(H/'panel/release_manifest.json',m)
original=H/'evidence/official_pnu_description.html'
assert original.is_file()
html=original.read_text(encoding='utf-8'); assert '1:일반, 2:산' in html
put(H/'evidence/evidence_inventory.json',dict(retrieved_utc=datetime.now(timezone.utc).isoformat(),official_document=dict(url='https://www.data.go.kr/data/15122764/fileData.do',title='경기도 광주시 도시계획정보 건축물주제도 설명',path=str(original),sha256=sha(original),section='상세 및 제공정보 / 설명',confirmed='19자리 지번코드의 법정코드10 + 필지구분1(1 일반/2 산) + 본번4 + 부번4',scope_limit='공식 지번코드 설명이며 실거래 CSV 미표시의 일반필지 의미를 입증하지 않음'),held_evidence=[dict(path=str(ROOT/x),sha256=sha(ROOT/x)) for x in ['metadata/khmd_landcd_pnu_document_trace_v0_1.json','metadata/khmd_land_pnu_official_evidence_v0_1.json','docs/source_docs/spatial_reference_readiness_v0_1/gis_column_dictionary_20260819.xlsx']],failed_official_url=dict(url='https://www.data.go.kr/data/15098809/openapi.do?recommendDataYn=Y',result='web fetch 404; not used'),automatic_digit_mapping=False,CSV_absence_means_general='UNCONFIRMED'))
print(json.dumps(dict(manifest=str(H/'panel/release_manifest.json'),sha256=sha(H/'panel/release_manifest.json')),ensure_ascii=False))
