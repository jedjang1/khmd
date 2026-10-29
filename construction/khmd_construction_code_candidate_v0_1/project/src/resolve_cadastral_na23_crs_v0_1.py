"""Exact CRS-definition comparison helpers; no legacy canary or API driver."""
import math,sys

def same_unit_factor(a,b):
    return math.isfinite(a) and math.isfinite(b) and math.isclose(a,b,rel_tol=8*sys.float_info.epsilon,abs_tol=0)

def definition_checks(source,target):
    sdatum=source.datum.to_json_dict();tdatum=target.datum.to_json_dict()
    sp={str(p.code):p for p in source.coordinate_operation.params};tp={str(p.code):p for p in target.coordinate_operation.params}
    checks=dict(projected=source.is_projected and target.is_projected,
        datum_authority=sdatum.get('id')==tdatum.get('id') and sdatum.get('id') is not None,
        semimajor=source.ellipsoid.semi_major_metre==target.ellipsoid.semi_major_metre,
        inverse_flattening=source.ellipsoid.inverse_flattening==target.ellipsoid.inverse_flattening,
        prime_meridian_value=source.prime_meridian.longitude==target.prime_meridian.longitude,
        prime_meridian_unit=same_unit_factor(source.prime_meridian.unit_conversion_factor,target.prime_meridian.unit_conversion_factor),
        operation_method=(source.coordinate_operation.method_auth_name,source.coordinate_operation.method_code)==(target.coordinate_operation.method_auth_name,target.coordinate_operation.method_code),
        parameter_code_set=set(sp)==set(tp),axis_dimension=len(source.axis_info)==len(target.axis_info)==2,
        axis_direction_set={a.direction for a in source.axis_info}=={a.direction for a in target.axis_info}=={'east','north'})
    parameters=[]
    for code in sorted(set(sp)|set(tp)):
        a=sp.get(code);b=tp.get(code)
        value_equal=a is not None and b is not None and a.value==b.value
        unit_equal=a is not None and b is not None and same_unit_factor(a.unit_conversion_factor,b.unit_conversion_factor)
        checks['parameter_'+code]=value_equal and unit_equal
        parameters.append(dict(EPSG_parameter_code=code,source_value=a.value if a else None,reference_value=b.value if b else None,
            source_unit_factor=a.unit_conversion_factor if a else None,reference_unit_factor=b.unit_conversion_factor if b else None,
            value_exact_equal=value_equal,unit_factor_within_representation_roundoff=unit_equal))
    for direction in ('east','north'):
        sa=next((a for a in source.axis_info if a.direction==direction),None);ta=next((a for a in target.axis_info if a.direction==direction),None)
        checks['axis_unit_'+direction]=sa is not None and ta is not None and same_unit_factor(sa.unit_conversion_factor,ta.unit_conversion_factor)
    return checks,parameters
