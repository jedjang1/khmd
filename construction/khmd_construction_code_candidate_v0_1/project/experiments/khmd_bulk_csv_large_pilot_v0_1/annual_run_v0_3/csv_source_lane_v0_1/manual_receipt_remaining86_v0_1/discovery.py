"""Read-only routing: registered bytes before annual-scope conflict decisions."""
import codecs,csv,hashlib,io,zipfile,xml.etree.ElementTree as ET

# Positive content signatures for unrelated tables, never filename exclusions.
OTHER_SCHEMAS=[
 ('SURVEY',{'통합 ID','데이터 ID','조사유형(조사구/신축아파트)'}),
 ('MODEL_RESULTS',{'horizon_month','std_error_cr1'}),('MODEL_RESULTS',{'horizon_month','coef_log1p_per_100k'}),
 ('MODEL_DIAGNOSTICS',{'model_group','missing_sale','duplicate_region_month'}),
 ('TAX_SCENARIO',{'homes','mean_extra_80_won','mean_extra_100_won'}),
 ('DEVELOPMENT_REGISTER',{'사업번호','세부절차코드','세부절차명'}),
 ('APARTMENT_MASTER',{'지역본부','단지코드','세대수','임대유형'}),
 ('ADMIN_CODE_TABLE',{'시도','중분류','시군구','소분류','읍면동'}),
 ('BIBLIOGRAPHY',{'Authors','Title','Year'}),
 ('MODEL_RESULTS',{'coef','p_value'}),('MODEL_RESULTS',{'estimate','standard_error'}),
 ('MODEL_RESULTS',{'model_group','outcome'}),('MODEL_RESULTS',{'formula','r2'}),
 ('MODEL_RESULTS',{'cluster','event','continuation_spec'}),
 ('MODEL_RESULTS',{'cluster','distance_bin','calibrated_gap_pct'}),
 ('MODEL_RESULTS',{'start_month','factor','mean_3_6_12m_holdout_rmse'}),
 ('MODEL_RESULTS',{'cluster','identification_status'}),('MODEL_RESULTS',{'cluster','window','calibrated_gap_pct'}),
 ('MODEL_RESULTS',{'cluster','pre_period','slope_log_per_month'}),('MODEL_RESULTS',{'rate_spec','mean_pre_holdout_rmse'}),
 ('MODEL_RESULTS',{'cluster','zone','raw_gap_pct'}),('MODEL_RESULTS',{'cluster','spearman_zone_order_effect'}),
 ('MODEL_RESULTS',{'start_year','cluster','inside_raw_gap_pct'}),('MODEL_RESULTS',{'cluster','term','estimate_log'}),
 ('SCENARIO',{'Year','Scenario','Debt'}),('DERIVED_PANEL',{'panel_id','date','sale_index'}),
 ('TAX_AGGREGATES',{'year','model_group','homes'}),('TAX_AGGREGATES',{'year','matched_homes'}),
 ('TAX_AGGREGATES',{'year','panel_id','homes'}),('TAX_AGGREGATES',{'year','price_decile','homes'}),
 ('TAX_AGGREGATES',{'year','observations','missing_legal_code'}),
 ('METADATA',{'file_name','data_content'}),('METADATA',{'field_name','data_type'}),
 ('METADATA',{'variable','definition'}),('METADATA',{'model_stage','variable_or_effect','status'}),
 ('METADATA',{'번호','이름','수록기간','자료출처'}),('STATISTICS',{'항목','단위'}),
 ('PRICE_INDEX',{'No','지역','규모'}),('POPULATION_TABLE',{'시점','총인구 (명)'}),
 ('SURVEY',{'ID_GAGU','SIDO_CD'}),('SURVEY',{'dong_cd','Y_SWB'}),('SURVEY',{'dong_cd','YYY'}),
 ('SURVEY',{'가구 ID','가구원 ID'}),('SURVEY',{'가구주연령대','가구원수','연령_SHAP'}),
 ('SURVEY',{'전망가구수','연령기여','규모기여'}),
 ('LEGAL_CODE_TABLE',{'법정동코드','법정동명','폐지여부'}),('LEGAL_CODE_TABLE',{'법정동코드','시도명','생성일자'}),
 ('ADMIN_CODE_TABLE',{'시도','시군구','행정동'}),('ADMIN_CODE_TABLE',{'시도','행정동','법정동'}),
 ('STATISTICS_CATALOG',{'통계명','통계표명','통계리스트 주소'}),
 ('GIS_DERIVATIVE',{'apt_id','crs_epsg','n_transactions'}),('GIS_DERIVATIVE',{'BJD_CD','RISK_EQ'}),
 ('DEVELOPMENT_REGISTER',{'조서관리코드','프로젝트코드'}),('DEVELOPMENT_REGISTER',{'정비 구역명','정비유형'}),
 ('DEVELOPMENT_REGISTER',{'사업번호','사업코드'}),('DEVELOPMENT_REGISTER',{'조감도 이미지 파일경로','사업주체'}),
 ('LOCAL_STATISTICS',{'행정동_코드','지출_총금액'}),('PERMIT_REGISTER',{'관리번호','인허가일자'}),
 ('WELFARE_STATISTICS',{'자격','연령구간','수급권자수'}),('VEHICLE_STATISTICS',{'연료','관용_승용'}),
 ('ROAD_REGISTER',{'보행자전용도로명','지정일자'}),('APARTMENT_MASTER',{'apt_cd','hshld_co'}),
 ('APARTMENT_MASTER',{'임대단지코드','총세대수'}),('WASTE_STATISTICS',{'examin_yr','조사년도'}),
 ('WASTE_STATISTICS',{'exhst_yy','exhst_qy'}),('GUARANTEE_RECORDS',{'보증완료월','대위변제여부'}),
 ('SUBSCRIPTION_TABLE',{'주택관리번호','공고번호','경쟁률'})]

def probe_unreadable(path):
    """Bounded evidence, tolerant of a cut last UTF-8 byte; never replacement decode."""
    with path.open('rb') as f:b=f.read(65536)
    encodings=['utf-16'] if b.startswith((b'\xff\xfe',b'\xfe\xff')) else ['utf-8-sig','cp949']
    decoded=[]
    for enc in encodings:
        try:t=codecs.getincrementaldecoder(enc)(errors='strict').decode(b,final=False)
        except UnicodeError:
            try:t=b.split(b'\n',1)[0].decode(enc,errors='strict')
            except UnicodeError:continue
        try:head=next(csv.reader(io.StringIO(t),strict=True))
        except (csv.Error,StopIteration):head=[]
        decoded.append((enc,t,head))
    evidence=dict(prefix_bytes=len(b),prefix_sha256=hashlib.sha256(b).hexdigest())
    # One observed non-CSV container: identify the price/income-ratio table by
    # bounded XML vocabulary, not the misleading .csv suffix or its filename.
    if b.startswith(b'PK\x03\x04') and path.stat().st_size<=1048576:
        try:
            with zipfile.ZipFile(path) as z:
                info=z.getinfo('xl/sharedStrings.xml')
                if info.file_size<=65536:
                    xml=z.read(info);texts={e.text for e in ET.fromstring(xml).iter() if e.tag.endswith('}t')}
                    if {'자료시점','항목','PIR','LIR'}<=texts and not {'실거래구분','계약년월','계약일'} & texts:
                        return dict(evidence,status='OUTSIDE_OTHER_CSV_SCHEMA',kind='NON_CSV_XLSX_PIR_LIR_TABLE',matched_fields=['자료시점','항목','PIR','LIR'],xml_sha256=hashlib.sha256(xml).hexdigest())
        except (zipfile.BadZipFile,KeyError,OSError,ET.ParseError,RuntimeError):pass
    # Real-estate signals win over any other schema match. Name is only a positive
    # suspicion when content cannot be established; never an exclusion criterion.
    for enc,t,head in decoded:
        cols=set(head)
        if '실거래구분' in t or ('계약일자' in t and '주소구분' in t) or {'계약년월','계약일'}<=cols or '실거래가 공개시스템' in t:
            return dict(evidence,status='REAL_ESTATE_HEADER_REVIEW_HOLD',encoding=enc,header=head)
    for enc,t,head in decoded:
        for kind,required in OTHER_SCHEMAS:
            if required<=set(x.strip() for x in head):
                return dict(evidence,status='OUTSIDE_OTHER_CSV_SCHEMA',kind=kind,encoding=enc,header=head,matched_fields=sorted(required))
    if '실거래' in path.name:
        return dict(evidence,status='REAL_ESTATE_HEADER_REVIEW_HOLD',reason='Candidate filename plus unreadable/unrecognized content; not selected')
    return dict(evidence,status='UNCLASSIFIED_HEADER_REVIEW_HOLD',header=decoded[0][2] if decoded else [],reason='No positive unrelated-schema evidence; retained for review')

def inspect_file(path,cells,registered,header_reader,classify,sha,guard):
    try:cond,cols=header_reader(path)
    except (ValueError,UnicodeError,csv.Error,OSError) as e:
        try:probe=probe_unreadable(path)
        except OSError as why:probe=dict(status='SOURCE_READ_REVIEW_HOLD',reason=str(why))
        return dict(probe,path=str(path),cell_ids=[],original_header_error=str(e))
    ids,status=classify(cond,cells)
    base=dict(path=str(path),cell_ids=ids,conditions=cond,columns=cols)
    if not ids:return dict(base,status='OUTSIDE_FROZEN_SCOPE')
    try:s=sha(path,guard)
    except OSError as e:return dict(base,status='SOURCE_READ_FAILED',reason=str(e))
    base['sha256']=s
    if s in registered:
        m=registered[s]
        if m['conditions']!=cond or m['columns']!=cols:
            return dict(base,status='REGISTERED_METADATA_CONFLICT_HOLD')
        return dict(base,status='REGISTERED_EXISTING_INPUT',registered_query=m['query'],scope_classification=status,
                    annual_cell_credit=False if status!='ELIGIBLE_FULL_YEAR' else True)
    return dict(base,status=status)
