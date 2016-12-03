from math import atan2, degrees

import numpy as np
from matplotlib.path import Path


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


def polygon_to_mpl_path(polygon):
    """
    convert a shapely Polygon to a matplotlib Path
    :param polygon: shapely Polygon
    :return: matplotlib Path
    """
    vertices = []
    codes = []
    _mpl_add_linearring(polygon.exterior, vertices, codes)
    for interior in polygon.interiors:
        _mpl_add_linearring(interior, vertices, codes)
    return Path(np.array(vertices), codes=codes)


def _mpl_add_linearring(linearring, vertices, codes):
    coords = list(linearring.coords)
    vertices.extend(coords)
    vertices.append(coords[0])
    codes.append(Path.MOVETO)
    codes.extend([Path.LINETO] * len(coords))
