"""New projected-plane grid; deliberately separate from the frozen 5186 grid."""
import math
VERSION='KHMD_UTMK_1KM_V1'
def index(x,y):
    if not all(math.isfinite(v) for v in (x,y)):raise ValueError('NONFINITE_GRID_COORDINATE')
    # Exact floor on represented floats, including negative subnormals.
    def f(v):
        n,d=float(v).as_integer_ratio()
        return n//(d*1000)
    return f(x),f(y)
def identifier(x,y):
    i,j=index(x,y)
    return f'{VERSION}:{i}:{j}'
def point(geometry):
    # Same POINT_ON_SURFACE and strict-inside checks as the pinned old kernel.
    if geometry is None:raise ValueError('GEOMETRY_MISSING')
    if geometry.is_empty:raise ValueError('GEOMETRY_EMPTY')
    if geometry.geom_type not in ('Polygon','MultiPolygon'):raise ValueError('GEOMETRY_NONPOLYGON')
    polygons=[geometry] if geometry.geom_type=='Polygon' else geometry.geoms
    if not all(math.isfinite(v) for p in polygons for ring in (p.exterior,*p.interiors) for xy in ring.coords for v in xy):raise ValueError('GEOMETRY_NONFINITE')
    if not geometry.is_valid:raise ValueError('GEOMETRY_INVALID_RAW')
    if not math.isfinite(geometry.area) or geometry.area<=0:raise ValueError('GEOMETRY_AREA_INVALID')
    p=geometry.representative_point()
    if not geometry.contains(p):raise ValueError('POS_OUTSIDE')
    return p
