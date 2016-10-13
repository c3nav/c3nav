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

    class Meta:
        abstract = True

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
