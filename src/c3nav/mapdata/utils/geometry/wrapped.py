from functools import cached_property

from shapely import GeometryCollection
from shapely.geometry import shape as shapely_shape, mapping as shapely_mapping


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
