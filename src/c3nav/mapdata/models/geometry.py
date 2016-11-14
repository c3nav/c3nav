from django.db import models
from django.utils.translation import ugettext_lazy as _
from shapely.geometry.geo import mapping, shape

from c3nav.mapdata.fields import GeometryField
from c3nav.mapdata.models.base import MapItem
from c3nav.mapdata.utils import format_geojson


class GeometryMapItem(MapItem):
    """
    A map feature
    """
    level = models.ForeignKey('mapdata.Level', on_delete=models.CASCADE, verbose_name=_('level'))
    geometry = GeometryField()

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


class Building(GeometryMapItem):
    """
    The outline of a building on a specific level
    """
    geomtype = 'polygon'
    color = '#333333'

    class Meta:
        verbose_name = _('Building')
        verbose_name_plural = _('Buildings')
        default_related_name = 'buildings'


class Area(GeometryMapItem):
    """
    An accessible area like a room. Can also be outside. Can overlap.
    """
    geomtype = 'polygon'
    color = '#FFFFFF'

    class Meta:
        verbose_name = _('Area')
        verbose_name_plural = _('Areas')
        default_related_name = 'areas'


class Obstacle(GeometryMapItem):
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


class Door(GeometryMapItem):
    """
    A connection between two rooms
    """
    geomtype = 'polygon'
    color = '#FF00FF'

    class Meta:
        verbose_name = _('Door')
        verbose_name_plural = _('Doors')
        default_related_name = 'doors'
