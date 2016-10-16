from collections import OrderedDict

from django.db import models
from django.utils.translation import ugettext_lazy as _
from shapely.geometry.geo import mapping, shape

from c3nav.mapdata.fields import GeometryField
from c3nav.mapdata.models.base import MapdataModel
from c3nav.mapdata.utils import format_geojson

FEATURE_TYPES = OrderedDict()


def register_featuretype(cls):
    FEATURE_TYPES[cls.__name__.lower()] = cls
    return cls


class Feature(MapdataModel):
    """
    A map feature
    """
    level = models.ForeignKey('mapdata.Level', on_delete=models.CASCADE, verbose_name=_('level'))
    geometry = GeometryField()

    EditorForm = None

    class Meta:
        abstract = True

    @property
    def title(self):
        return self.name

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        if 'geometry' not in data:
            raise ValueError('missing geometry.')
        try:
            kwargs['geometry'] = shape(data['geometry'])
        except:
            raise ValueError(_('Invalid GeoJSON.'))

        if 'level' not in data:
            raise ValueError('missing level.')
        kwargs['level'] = data['level']

        return kwargs

    def tofile(self):
        result = super().tofile()
        result['level'] = self.level.name
        result['geometry'] = format_geojson(mapping(self.geometry))
        return result


@register_featuretype
class Inside(Feature):
    """
    The outline of a building on a specific level
    """
    geomtype = 'polygon'
    color = '#333333'

    class Meta:
        verbose_name = _('Inside Area')
        verbose_name_plural = _('Inside Areas')
        default_related_name = 'insides'


@register_featuretype
class Room(Feature):
    """
    A room inside
    """
    geomtype = 'polygon'
    color = '#FFFFFF'

    class Meta:
        verbose_name = _('Room')
        verbose_name_plural = _('Rooms')
        default_related_name = 'rooms'


@register_featuretype
class Obstacle(Feature):
    """
    An obstacle
    """
    height = models.DecimalField(_('height of the obstacle'), null=True, max_digits=4, decimal_places=2)

    geomtype = 'polygon'
    color = '#999999'

    class Meta:
        verbose_name = _('Obstacle')
        verbose_name_plural = _('Obstacles')
        default_related_name = 'obstacles'

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        if 'height' in data:
            if not isinstance(data['height'], (int, float)):
                raise ValueError('altitude has to be int or float.')
            kwargs['height'] = data['height']

        return kwargs

    def tofile(self):
        result = super().tofile()
        if self.height is not None:
            result['height'] = float(self.level.name)
        return result


@register_featuretype
class Door(Feature):
    """
    A connection between two rooms
    """
    geomtype = 'polygon'
    color = '#FF00FF'

    class Meta:
        verbose_name = _('Door')
        verbose_name_plural = _('Doors')
        default_related_name = 'doors'
