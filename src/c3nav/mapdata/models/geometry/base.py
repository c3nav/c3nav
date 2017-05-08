from collections import OrderedDict

from shapely.geometry import Point, mapping

from c3nav.mapdata.models.base import EditorFormMixin
from c3nav.mapdata.utils.json import format_geojson

GEOMETRY_FEATURE_TYPES = OrderedDict()


class GeometryMixin(EditorFormMixin):
    """
    A map feature with a geometry
    """
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
