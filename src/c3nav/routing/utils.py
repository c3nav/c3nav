from math import atan2, degrees

from matplotlib.path import Path
from shapely.geometry import Polygon


def cleanup_coords(coords):
    """
    remove coordinates that are closer than 0.01 (1cm)
    :param coords: list of (x, y) coordinates
    :return: list of (x, y) coordinates
    """
    result = []
    last_coord = coords[-1]
    for coord in coords:
        if ((coord[0] - last_coord[0]) ** 2 + (coord[1] - last_coord[1]) ** 2) ** 0.5 >= 0.01:
            result.append(coord)
        last_coord = coord
    return result


def coord_angle(coord1, coord2):
    """
    calculate angle in degrees from coord1 to coord2
    :param coord1: (x, y) coordinate
    :param coord2: (x, y) coordinate
    :return: angle in degrees
    """
    return degrees(atan2(-(coord2[1] - coord1[1]), coord2[0] - coord1[0])) % 360


def get_coords_angles(geom):
    """
    inspects all coordinates of a LinearRing counterclockwise and checks if they are a left or a right turn.
    :param geom: LinearRing
    :rtype: a list of ((x, y), is_left) tuples
    """
    coords = list(cleanup_coords(geom.coords))
    last_coords = coords[-2:]
    last_angle = coord_angle(last_coords[-2], last_coords[-1])
    result = []

    invert = not geom.is_ccw

    for coord in coords:
        angle = coord_angle(last_coords[-1], coord)
        angle_diff = (last_angle-angle) % 360
        result.append((last_coords[-1], (angle_diff < 180) ^ invert))
        last_coords.append(coord)
        last_angle = angle

    return result


def polygon_to_mpl_paths(polygon):
    """
    convert a shapely Polygon or Multipolygon to a matplotlib Path
    :param polygon: shapely Polygon or Multipolygon
    :return: matplotlib Path
    """
    paths = []
    for polygon in assert_multipolygon(polygon):
        paths.append(linearring_to_mpl_path(polygon.exterior))
        for interior in polygon.interiors:
            paths.append(linearring_to_mpl_path(interior))
    return paths


def linearring_to_mpl_path(linearring):
    vertices = []
    codes = []
    coords = list(linearring.coords)
    vertices.extend(coords)
    vertices.append(coords[0])
    codes.append(Path.MOVETO)
    codes.extend([Path.LINETO] * (len(coords)-1))
    codes.append(Path.CLOSEPOLY)
    return Path(vertices, codes, readonly=True)


def assert_multipolygon(geometry):
    """
    given a Polygon or a MultiPolygon, return a list of Polygons
    :param geometry: a Polygon or a MultiPolygon
    :return: a list of Polygons
    """
    if isinstance(geometry, Polygon):
        polygons = [geometry]
    else:
        polygons = geometry.geoms
    return polygons


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
