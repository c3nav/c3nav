from itertools import chain
from typing import Union

from shapely import Point, Polygon, MultiPolygon, LineString, GeometryCollection, prepared, line_merge
from shapely.geometry import JOIN_STYLE
from shapely.ops import polygonize, unary_union

from c3nav.mapdata.utils.geometry.inspect import assert_multipolygon, assert_multilinestring, calculate_precision
from c3nav.mapdata.utils.geometry.modify import remove_redundant_points_polygon
from c3nav.mapdata.utils.geometry.wrapped import unwrap_geom


def good_representative_point(geometry) -> Point:
    if isinstance(geometry, Point):
        return geometry
    c = geometry.centroid
    if not isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry.representative_point()
    for polygon in assert_multipolygon(geometry):
        if Polygon(polygon.exterior.coords).contains(c):
            return c
    x1, y1, x2, y2 = geometry.bounds
    lines = (tuple(assert_multilinestring(LineString(((x1, c.y), (x2, c.y))).intersection(unwrap_geom(geometry)))) +
             tuple(assert_multilinestring(LineString(((c.x, y1), (c.x, y2))).intersection(unwrap_geom(geometry)))))
    return min(lines, key=lambda line: (line.distance(c), line.length),
               default=geometry.representative_point()).centroid


def cut_polygons_with_lines(polygon: Union[Polygon, MultiPolygon, GeometryCollection],
                            lines: list[LineString]) -> tuple[Union[Polygon, MultiPolygon], ...]:
    precision = calculate_precision(polygon)
    polygon_prep = prepared.prep(polygon.buffer(precision, join_style=JOIN_STYLE.round, quad_segs=2))
    polygons = []
    holes = []
    for item in polygonize([
        line for line in assert_multilinestring(unary_union(line_merge((  # noqa
            *chain.from_iterable((p.exterior, *p.interiors) for p in assert_multipolygon(polygon)),
            *lines,
        ))))
        if polygon_prep.covers(line)
    ]):
        if polygon_prep.covers(item):
            polygons.append(item)
        else:
            holes.append(item)

    polygons_prep = [prepared.prep(polygon.buffer(precision*2, join_style=JOIN_STYLE.round, quad_segs=2))
                     for polygon in polygons]
    return tuple(
        remove_redundant_points_polygon(
            polygon.difference(unary_union([hole for hole in holes if polygons_prep[i].covers(hole)])),
        ) for i, polygon in enumerate(polygons)
    )
