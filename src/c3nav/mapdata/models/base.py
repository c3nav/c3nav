from collections import OrderedDict

from django.db import models
from django.db.models.base import ModelBase
from django.utils.translation import get_language
from shapely.geometry import Point, mapping

from c3nav.mapdata.fields import GeometryField
from c3nav.mapdata.lastupdate import set_last_mapdata_update
from c3nav.mapdata.utils.json import format_geojson

FEATURE_TYPES = OrderedDict()
GEOMETRY_FEATURE_TYPES = OrderedDict()
LEVEL_FEATURE_TYPES = OrderedDict()
AREA_FEATURE_TYPES = OrderedDict()


class FeatureBase(ModelBase):
    def __new__(mcs, name, bases, attrs):
        cls = super().__new__(mcs, name, bases, attrs)
        if not cls._meta.abstract and name != 'Source':
            FEATURE_TYPES[name.lower()] = cls
            if hasattr(cls, 'geometry'):
                GEOMETRY_FEATURE_TYPES[name.lower()] = cls
            if hasattr(cls, 'level'):
                LEVEL_FEATURE_TYPES[name.lower()] = cls
            if hasattr(cls, 'area'):
                AREA_FEATURE_TYPES[name.lower()] = cls

        return cls


class Feature(models.Model, metaclass=FeatureBase):
    EditorForm = None

    @property
    def title(self):
        if not hasattr(self, 'titles'):
            return self.name
        lang = get_language()
        if lang in self.titles:
            return self.titles[lang]
        return next(iter(self.titles.values())) if self.titles else self.name

    def save(self, *args, **kwargs):
        with set_last_mapdata_update():
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with set_last_mapdata_update():
            super().delete(*args, **kwargs)

    class Meta:
        abstract = True


class GeometryFeature(Feature):
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
