from itertools import chain
from math import ceil, log10
from typing import Union, Iterable

from shapely import Polygon, MultiPolygon, GeometryCollection, LineString, MultiLineString, LinearRing
from shapely.geometry.base import BaseGeometry


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


def calculate_precision(geometry: BaseGeometry):
    if geometry.is_empty:
        return 10 ** -14
    return 10 ** (-14 + int(ceil(log10(max((abs(i) for i in geometry.bounds), default=1)))))


def check_ring(coordinates):
    # check if this is a valid ring
    # that measn it has at least 3 points (or 4 if the first and last one are identical)
    return len(coordinates) >= (4 if coordinates[0] == coordinates[-1] else 3)
