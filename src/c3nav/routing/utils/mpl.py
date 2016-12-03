from matplotlib.path import Path

from c3nav.routing.utils.base import assert_multipolygon


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
