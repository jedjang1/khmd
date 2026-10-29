"""Pure S1 geometry kernel. No I/O, transforms, repairs, centroid or building data."""
import math
from parcel_representative_grid_contract_v0_1 import grid_id, grid_index, boundary_class

def compute(geometry, max_candidate_cells=100000):
    from shapely.geometry import box
    if geometry is None: raise ValueError('GEOMETRY_MISSING')
    if geometry.is_empty: raise ValueError('GEOMETRY_EMPTY')
    if geometry.geom_type not in ('Polygon','MultiPolygon'): raise ValueError('GEOMETRY_NONPOLYGON')
    polygons=[geometry] if geometry.geom_type=='Polygon' else geometry.geoms
    if not all(math.isfinite(v) for p in polygons for ring in (p.exterior,*p.interiors) for xy in ring.coords for v in xy):
        raise ValueError('GEOMETRY_NONFINITE')
    if not geometry.is_valid: raise ValueError('GEOMETRY_INVALID_RAW')
    if not all(math.isfinite(v) for v in geometry.bounds) or not math.isfinite(geometry.area) or geometry.area<=0:
        raise ValueError('GEOMETRY_AREA_OR_BOUNDS_INVALID')
    point=geometry.representative_point()
    if point.is_empty or not all(math.isfinite(v) for v in (point.x,point.y)):raise ValueError('POS_NONFINITE')
    if not geometry.covers(point) or not geometry.contains(point): raise ValueError('POS_OUTSIDE')
    i,j=grid_index(point.x,point.y);pos=grid_id(i,j)
    xmin,ymin,xmax,ymax=geometry.bounds;imin,jmin=grid_index(xmin,ymin);imax,jmax=grid_index(xmax,ymax)
    imin-=1;jmin-=1
    count=(imax-imin+1)*(jmax-jmin+1)
    if type(max_candidate_cells) is not int or not 1<=count<=max_candidate_cells:raise ValueError('CELL_BUDGET_EXCEEDED')
    positive=[];touches=0
    for ci in range(imin,imax+1):
        for cj in range(jmin,jmax+1):
            intersection=geometry.intersection(box(ci*1000,cj*1000,(ci+1)*1000,(cj+1)*1000))
            if intersection.is_empty:continue
            area=float(intersection.area)
            if not math.isfinite(area) or area<0:raise ValueError('INVALID_INTERSECTION_AREA')
            if area>0:positive.append((ci,cj,area))
            else:touches+=1
    if not positive:raise ValueError('NO_POSITIVE_CELL')
    maximum=max(a for _,_,a in positive);winners=[(ci,cj) for ci,cj,a in positive if a==maximum]
    tied=len(winners)>1;dominant=None if tied else grid_id(*winners[0])
    equal=None if tied else pos==dominant;cross=len(positive)>1
    category=boundary_class(cross,equal,tied)
    disclosure={'PARCEL_SINGLE_GRID':'NOT_BOUNDARY_SENSITIVE',
        'PARCEL_CROSS_GRID_POS_DOMINANT_AGREE':'BOUNDARY_CROSSING_POS_DOMINANT_AGREE',
        'PARCEL_CROSS_GRID_POS_DOMINANT_DIFFER':'BOUNDARY_CROSSING_POS_DOMINANT_DIFFER',
        'PARCEL_CROSS_GRID_DOMINANT_TIE':'BOUNDARY_CROSSING_DOMINANT_TIE'}[category]
    return dict(geometry_type=geometry.geom_type,geometry_area_m2=float(geometry.area),geometry_status='GEOMETRY_VALID',
        computation_status='OK',representative_method='POINT_ON_SURFACE',representative_x=point.x,representative_y=point.y,
        representative_crs='EPSG:5186',representative_point_inside=True,representative_point_strictly_inside=True,
        grid_crs='EPSG:5186',grid_i=i,grid_j=j,parcel_representative_grid_id=pos,
        parcel_grid_intersection_count=len(positive),parcel_touch_only_grid_count=touches,
        parcel_crosses_grid_boundary=cross,parcel_dominant_grid_id=dominant,
        parcel_dominant_grid_i=None if tied else winners[0][0],parcel_dominant_grid_j=None if tied else winners[0][1],
        parcel_dominant_candidate_grid_ids=sorted(grid_id(*pair) for pair in winners),
        parcel_dominant_area_share=maximum/geometry.area,parcel_dominant_tie=tied,
        parcel_area_sum_delta=math.fsum(a for _,_,a in positive)-geometry.area,
        parcel_pos_equals_dominant_grid=equal,parcel_boundary_class=category,boundary_uncertainty_status=disclosure)
