import json
from collections import namedtuple
from itertools import chain
from math import ceil, log10
from typing import Union, TYPE_CHECKING, Iterable, overload

from django.utils.functional import cached_property
from shapely import line_merge, prepared, simplify, normalize, set_precision, make_valid
from shapely.geometry import GeometryCollection, LinearRing, LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.geometry import mapping as shapely_mapping
from shapely.geometry import shape as shapely_shape
from shapely.geometry.base import BaseGeometry, JOIN_STYLE
from shapely.ops import polygonize, unary_union

if TYPE_CHECKING:
    pass


class WrappedGeometry:
    wrapped_geojson = None

    def __init__(self, geojson):
        self.wrapped_geojson = geojson

    @cached_property
    def wrapped_geom(self):
        if not self.wrapped_geojson or not self.wrapped_geojson.get('coordinates', ()):
            return GeometryCollection()
        return shapely_shape(self.wrapped_geojson)

    def __getattr__(self, name):
        return getattr(self.wrapped_geom, name)

    @property
    def __class__(self):
        return self.wrapped_geom.__class__

    def __reduce__(self):
        return WrappedGeometry, (self.wrapped_geojson, )


def unwrap_geom(geometry):
    return geometry.wrapped_geom if isinstance(geometry, WrappedGeometry) else geometry


def smart_mapping(geometry):
    if hasattr(geometry, 'wrapped_geojson'):
        return geometry.wrapped_geojson
    return shapely_mapping(geometry)


def assert_multipolygon(geometry: Union[Polygon, MultiPolygon, GeometryCollection, Iterable]) -> list[Polygon]:
    """
    given a Polygon or a MultiPolygon, return a list of Polygons
    :param geometry: a Polygon or a MultiPolygon
    :return: a list of Polygons
    """
    if not isinstance(geometry, BaseGeometry):
        geometry = GeometryCollection(tuple(geometry))
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if not hasattr(geometry, "geoms"):
        return []
    return [geom for geom in geometry.geoms if isinstance(geom, Polygon)]


def assert_multilinestring(geometry: Union[LineString, MultiLineString, GeometryCollection, Iterable]) -> list[LineString]:
    """
    given a LineString or MultiLineString, return a list of LineStrings
    :param geometry: a LineString or a MultiLineString
    :return: a list of LineStrings
    """
    if not isinstance(geometry, BaseGeometry):
        geometry = GeometryCollection(tuple(geometry))
    if geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry]
    if not hasattr(geometry, "geoms"):
        return []
    return [geom for geom in geometry.geoms if isinstance(geom, LineString)]


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


def get_rings(geometry):
    if isinstance(geometry, Polygon):
        return chain((geometry.exterior, ), geometry.interiors)
    try:
        geoms = geometry.geoms
    except AttributeError:
        pass
    else:
        return chain(*(get_rings(geom) for geom in geoms))

    if isinstance(geometry, LinearRing):
        return (geometry, )

    return ()


cutpoint = namedtuple('cutpoint', ('point', 'polygon', 'ring'))


def calculate_precision(geometry: BaseGeometry):
    if geometry.is_empty:
        return 10 ** -14
    return 10 ** (-14 + int(ceil(log10(max((abs(i) for i in geometry.bounds), default=1)))))


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


def _remove_redundant_points_coords_linearring(ring: LinearRing) -> list[tuple[float, ...]]:
    coords = tuple(ring.coords)
    if coords[0] == coords[-1]:
        coords = coords[:-1]
    if len(coords) < 3:
        return list(coords)
    new_coords = []
    for i in range(len(coords)):
        if not ((coords[i][0] == coords[i-1][0] and coords[i-1][0] == coords[i-2][0]) or
                (coords[i][1] == coords[i-1][1] and coords[i-1][1] == coords[i-2][1])):
            new_coords.append(coords[i-1])
    return new_coords


def _remove_redundant_points_coords_linestring(ring: LineString) -> list[tuple[float, ...]]:
    coords = tuple(ring.coords)
    if len(coords) < 3:
        return list(coords)
    new_coords = [coords[0]]
    for i in range(1, len(coords)-1):
        if not ((coords[i-1][0] == coords[i][0] and coords[i][0] == coords[i+1][0]) or
                (coords[i-1][1] == coords[i][1] and coords[i][1] == coords[i+1][1])):
            new_coords.append(coords[i])
    new_coords.append(coords[-1])
    return new_coords


def remove_redundant_points_polygon(polygon: Polygon) -> Polygon:
    polygon = simplify(polygon, tolerance=0)
    return Polygon(
        _remove_redundant_points_coords_linearring(polygon.exterior),
        [_remove_redundant_points_coords_linearring(interior) for interior in polygon.interiors],
    )


def remove_redundant_points_linearring(line: LinearRing) -> LinearRing:
    line = simplify(line, tolerance=0)
    return LinearRing(_remove_redundant_points_coords_linearring(line))


def remove_redundant_points_linestring(line: LineString) -> LineString:
    line = simplify(line, tolerance=0)
    return LineString(_remove_redundant_points_coords_linestring(line))


def remove_redundent_points[T: BaseGeometry](geometry: T) -> T:
    match geometry:
        case LineString():
            return remove_redundant_points_linestring(geometry)
        case MultiLineString():
            return MultiLineString(remove_redundant_points_linestring(geom) for geom in geometry.geoms)
        case Polygon():
            return remove_redundant_points_polygon(geometry)
        case MultiPolygon():
            return MultiPolygon(remove_redundant_points_polygon(geom) for geom in geometry.geoms)
        case GeometryCollection():
            return GeometryCollection(remove_redundent_points(geom) for geom in geometry.geoms)
        case _:
            raise ValueError(f"Unsupported geometry for remove_redundant_points: {geometry}")


@overload
def snap_to_grid_and_fully_normalized(geom: Union[Polygon, MultiPolygon]) -> Union[Polygon, MultiPolygon]:
    pass


@overload
def snap_to_grid_and_fully_normalized(geom: Union[LineString, MultiLineString]) -> Union[LineString, MultiLineString]:
    pass


@overload
def snap_to_grid_and_fully_normalized(geom: GeometryCollection) -> GeometryCollection:
    pass


def snap_to_grid_and_fully_normalized(geom: BaseGeometry) -> BaseGeometry:
    match geom:
        case MultiLineString() | LineString():
            for i in range(10):
                new_geom = normalize(unary_union(tuple(
                    remove_redundant_points_linestring(LineString(_snap_to_grid_coords(linestring.coords)))
                    for linestring in assert_multilinestring(set_precision(set_precision(geom, 0.01), 0))
                )))
                if new_geom == geom:  # todo: can we shorten this?
                    break
                geom = new_geom
            return geom
        case Polygon() | MultiPolygon():
            for i in range(10):
                new_geom = normalize(unary_union(tuple(
                    remove_redundant_points_polygon(_snap_to_grid_polygon(polygon))
                    for polygon in assert_multipolygon(set_precision(set_precision(geom, 0.01), 0))
                )))
                if new_geom == geom:
                    break
                geom = new_geom
            else:
                raise ValueError
            return geom
        case Point():
            return Point(round(geom.x, 2), round(geom.y, 2))
        case GeometryCollection():
            return GeometryCollection(tuple(snap_to_grid_and_fully_normalized(g) for g in geom.geoms))
        case _:
            raise ValueError(f"Unsupported geometry for snap_to_grid_and_fully_normalized: {geom}")


def _snap_to_grid_coords(coords: Iterable[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    return tuple((round(x, 2), round(y, 2)) for x, y in coords)


def _snap_to_grid_polygon(polygon: Polygon) -> Polygon:
    return make_valid(Polygon(  # noqa
        _snap_to_grid_coords(polygon.exterior.coords),
        tuple(_snap_to_grid_coords(interior.coords) for interior in polygon.interiors),
    ))


def _snap_to_grid_point(point: Point) -> Point:
    return Point(round(point.x, 2), round(point.y, 2))


def merge_bounds(*bounds: "BoundsByLevelSchema") -> "BoundsByLevelSchema":
    collected_bounds = {}
    for one_bounds in bounds:
        for level_id, level_bounds in one_bounds.items():
            collected_bounds.setdefault(level_id, []).append(chain(*level_bounds))
    zipped_bounds = {level_id: tuple(zip(*level_bounds)) for level_id, level_bounds in collected_bounds.items()}
    return {level_id: ((min(zipped[0]), min(zipped[1])), (max(zipped[2]), max(zipped[3])))
            for level_id, zipped in zipped_bounds.items()}


def comparable_mapping(geometry: BaseGeometry) -> dict:
    return json.loads(json.dumps(shapely_mapping(snap_to_grid_and_fully_normalized(geometry))))