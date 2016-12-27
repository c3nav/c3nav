from abc import ABC, abstractmethod

from matplotlib.path import Path
from shapely.geometry import MultiPolygon, Polygon

from c3nav.mapdata.utils.geometry import assert_multipolygon


class MplPathProxy(ABC):
    @abstractmethod
    def intersects_path(self, path):
        pass

    @abstractmethod
    def contains_point(self, point):
        pass


class MplMultipolygonPath(MplPathProxy):
    def __init__(self, polygon):
        self.polygons = [MplPolygonPath(polygon) for polygon in assert_multipolygon(polygon)]

    @property
    def exteriors(self):
        return tuple(polygon.exterior for polygon in self.polygons)

    def intersects_path(self, path, filled=False):
        for polygon in self.polygons:
            if polygon.intersects_path(path, filled=filled):
                return True
        return False

    def contains_point(self, point):
        for polygon in self.polygons:
            if polygon.contains_point(point):
                return True
        return False


class MplPolygonPath(MplPathProxy):
    def __init__(self, polygon):
        self.exterior = linearring_to_mpl_path(polygon.exterior)
        self.interiors = [linearring_to_mpl_path(interior) for interior in polygon.interiors]

    @property
    def exteriors(self):
        return (self.exterior, )

    def intersects_path(self, path, filled=False):
        if filled:
            if not self.exterior.intersects_path(path, filled=True):
                return False

            for interior in self.interiors:
                if interior.contains_path(path):
                    return False
            return True
        else:
            if self.exterior.intersects_path(path, filled=False):
                return True

            for interior in self.interiors:
                if interior.intersects_path(path, filled=False):
                    return True
            return False

    def contains_point(self, point):
        if not self.exterior.contains_point(point):
            return False

        for interior in self.interiors:
            if interior.contains_point(point):
                return False
        return True


def shapely_to_mpl(geometry):
    """
    convert a shapely Polygon or Multipolygon to a matplotlib Path
    :param polygon: shapely Polygon or Multipolygon
    :return: MplPathProxy
    """
    if isinstance(geometry, Polygon):
        return MplPolygonPath(geometry)
    elif isinstance(geometry, MultiPolygon) or geometry.is_empty:
        return MplMultipolygonPath(geometry)
    raise TypeError


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
