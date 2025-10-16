from shapely.geometry import Polygon

from c3nav.mapdata.utils.geometry.inspect import assert_multipolygon


def get_nearest_point(polygon, point):
    """
    calculate the nearest point on of a polygon to another point that lies outside
    :param polygon: a Polygon or a MultiPolygon
    :param point: something that shapely understands as a point
    :return: a Point
    """
    polygons = assert_multipolygon(polygon)
    nearest_distance = float('inf')
    nearest_point = None
    for polygon in polygons:
        if point.within(Polygon(polygon.exterior.coords)):
            for interior in polygon.interiors:
                if point.within(Polygon(interior.coords)):
                    point_ = _nearest_point_ring(interior, point)
                    distance = point_.distance(point)
                    if distance and distance < nearest_distance:
                        nearest_distance = distance
                        nearest_point = point_
                    break  # in a valid polygon a point can not be within multiple interiors
            break  # in a valid multipolygon a point can not be within multiple polygons
        else:
            point_ = _nearest_point_ring(polygon.exterior, point)
            distance = point_.distance(point)
            if distance and distance < nearest_distance:
                nearest_distance = distance
                nearest_point = point_

    if nearest_point is None:
        raise ValueError('Point inside polygon.')
    return nearest_point


def _nearest_point_ring(ring, point):
    return ring.interpolate(ring.project(point))
