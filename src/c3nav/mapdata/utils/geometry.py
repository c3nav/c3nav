from shapely.geometry import LineString, Polygon


def clean_geometry(geometry):
    """
    if the given geometry is a Polygon and invalid, try to make it valid if it results in a Polygon (not MultiPolygon)
    """
    if geometry.is_valid:
        return geometry

    if isinstance(geometry, Polygon):
        p = Polygon(list(geometry.exterior.coords))
        for interior in geometry.interiors:
            p = p.difference(Polygon(list(interior.coords)))

        if isinstance(p, Polygon) and p.is_valid:
            return p

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
