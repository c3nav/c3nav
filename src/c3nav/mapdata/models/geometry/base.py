from collections import OrderedDict

from shapely.geometry import Point, mapping

from c3nav.mapdata.fields import GeometryField
from c3nav.mapdata.models.base import Feature, FeatureBase
from c3nav.mapdata.utils.json import format_geojson

GEOMETRY_FEATURE_TYPES = OrderedDict()


class GeometryFeatureBase(FeatureBase):
    def __new__(mcs, name, bases, attrs):
        cls = super().__new__(mcs, name, bases, attrs)
        if not cls._meta.abstract:
            GEOMETRY_FEATURE_TYPES[name.lower()] = cls
        return cls


class GeometryFeature(Feature, metaclass=GeometryFeatureBase):
    """
    A map feature with a geometry
    """
    geometry = GeometryField()

    geomtype = None

    class Meta:
        abstract = True

    def get_geojson_properties(self):
        return OrderedDict((
            ('type', self.__class__.__name__.lower()),
            ('id', self.id),
        ))

    def to_geojson(self):
        return OrderedDict((
            ('type', 'Feature'),
            ('properties', self.get_geojson_properties()),
            ('geometry', format_geojson(mapping(self.geometry), round=False)),
        ))

    def get_shadow_geojson(self):
        return None

    def contains(self, x, y):
        return self.geometry.contains(Point(x, y))
