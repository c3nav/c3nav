from collections import OrderedDict
from django.db import models
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.models.geometry.base import GeometryFeature, GeometryFeatureBase

LEVEL_FEATURE_TYPES = OrderedDict()


class LevelFeatureBase(GeometryFeatureBase):
    def __new__(mcs, name, bases, attrs):
        cls = super().__new__(mcs, name, bases, attrs)
        if not cls._meta.abstract:
            LEVEL_FEATURE_TYPES[name.lower()] = cls
        return cls


class LevelFeature(GeometryFeature, metaclass=LevelFeatureBase):
    """
    a map feature that has a geometry and belongs to a level
    """
    level = models.ForeignKey('mapdata.Level', on_delete=models.CASCADE, verbose_name=_('level'))

    class Meta:
        abstract = True

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['level'] = self.level.id
        return result


class Building(LevelFeature):
    """
    The outline of a building on a specific level
    """
    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Building')
        verbose_name_plural = _('Buildings')
        default_related_name = 'buildings'


class Space(LevelFeature):
    """
    An accessible space. Shouldn't overlap.
    """
    geomtype = 'polygon'

    CATEGORIES = (
        ('', _('normal')),
        ('stairs', _('stairs')),
        ('escalator', _('escalator')),
        ('elevator', _('elevator')),
    )
    LAYERS = (
        ('', _('normal')),
        ('upper', _('upper')),
        ('lowerr', _('lower')),
    )

    public = models.BooleanField(verbose_name=_('public'))
    category = models.CharField(verbose_name=_('category'), choices=CATEGORIES, max_length=16)
    layer = models.CharField(verbose_name=_('layer'), choices=LAYERS, max_length=16)

    class Meta:
        verbose_name = _('Area')
        verbose_name_plural = _('Areas')
        default_related_name = 'areas'

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['category'] = self.category
        result['layer'] = self.layer
        result['public'] = self.public
        return result


class Door(LevelFeature):
    """
    A connection between two rooms
    """
    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Door')
        verbose_name_plural = _('Doors')
        default_related_name = 'doors'


class Hole(LevelFeature):
    """
    A hole in the ground of a room, e.g. for stairs.
    """
    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Hole')
        verbose_name_plural = _('Holes')
        default_related_name = 'holes'
