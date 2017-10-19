from itertools import chain

import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.path import Path
from shapely import speedups
from shapely.geometry import LineString, Polygon


if speedups.available:
    speedups.enable()


def clean_geometry(geometry):
    """
    if the given geometry is a Polygon and invalid, try to make it valid if it results in a Polygon (not MultiPolygon)
    """
    if geometry.is_valid:
        return geometry

    if isinstance(geometry, Polygon):
        return geometry.buffer(0)

    return geometry


def assert_multipolygon(geometry):
    """
    given a Polygon or a MultiPolygon, return a list of Polygons
    :param geometry: a Polygon or a MultiPolygon
    :return: a list of Polygons
    """
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    return [geom for geom in geometry.geoms if isinstance(geom, Polygon)]


def assert_multilinestring(geometry):
    """
    given a Geometry or GeometryCollection, return a list of Geometries
    :param geometry: a Geometry or a GeometryCollection
    :return: a list of Geometries
    """
    if geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry]
    return geometry.geoms


def plot_geometry(geom, title=None, bounds=None):
    fig = plt.figure()
    axes = fig.add_subplot(111)
    if bounds is None:
        bounds = geom.bounds
    axes.set_xlim(bounds[0], bounds[2])
    axes.set_ylim(bounds[1], bounds[3])
    verts = []
    codes = []
    if not isinstance(geom, (tuple, list)):
        geom = assert_multipolygon(geom)
    else:
        geom = tuple(chain(*(assert_multipolygon(g) for g in geom)))
    for polygon in geom:
        for ring in chain([polygon.exterior], polygon.interiors):
            verts.extend(ring.coords)
            codes.append(Path.MOVETO)
            codes.extend((Path.LINETO,) * len(ring.coords))
            verts.append(verts[-1])

    if title is not None:
        plt.title(title)

    path = Path(verts, codes)
    patch = PathPatch(path)
    axes.add_patch(patch)
    plt.show()
