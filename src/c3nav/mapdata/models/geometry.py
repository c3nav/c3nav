from collections import OrderedDict

from django.db import models
from django.utils.translation import ugettext_lazy as _
from shapely.geometry.geo import mapping, shape

from c3nav.mapdata.fields import GeometryField
from c3nav.mapdata.models import Elevator
from c3nav.mapdata.models.base import MapItem, MapItemMeta
from c3nav.mapdata.utils import format_geojson

GEOMETRY_MAPITEM_TYPES = OrderedDict()


class GeometryMapItemMeta(MapItemMeta):
    def __new__(mcs, name, bases, attrs):
        cls = super().__new__(mcs, name, bases, attrs)
        if not cls._meta.abstract:
            GEOMETRY_MAPITEM_TYPES[name.lower()] = cls
        return cls


class GeometryMapItem(MapItem, metaclass=GeometryMapItemMeta):
    """
    A map feature
    """
    level = models.ForeignKey('mapdata.Level', on_delete=models.CASCADE, verbose_name=_('level'))
    geometry = GeometryField()

    geomtype = None

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

    @classmethod
    def get_styles(cls):
        return {
            cls.__name__.lower(): cls.color
        }

    def get_geojson_properties(self):
        return OrderedDict((
            ('type', self.__class__.__name__.lower()),
            ('name', self.name),
            ('package', self.package.name),
            ('level', self.level.name),
        ))

    def to_geojson(self):
        return [OrderedDict((
            ('type', 'Feature'),
            ('properties', self.get_geojson_properties()),
            ('geometry', format_geojson(mapping(self.geometry), round=False)),
        ))]

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

    class Meta:
        verbose_name = _('Building')
        verbose_name_plural = _('Buildings')
        default_related_name = 'buildings'


class Room(GeometryMapItem):
    """
    An accessible area like a room. Can overlap.
    """
    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Room')
        verbose_name_plural = _('Rooms')
        default_related_name = 'rooms'


class Outside(GeometryMapItem):
    """
    An accessible outdoor area like a court. Can overlap.
    """
    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Outside Area')
        verbose_name_plural = _('Outside Areas')
        default_related_name = 'outsides'


class Obstacle(GeometryMapItem):
    """
    An obstacle
    """
    height = models.DecimalField(_('height of the obstacle'), null=True, max_digits=4, decimal_places=2)

    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Obstacle')
        verbose_name_plural = _('Obstacles')
        default_related_name = 'obstacles'

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['height'] = float(self.height)
        return result

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
            result['height'] = float(self.height)
        return result


class Door(GeometryMapItem):
    """
    A connection between two rooms
    """
    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Door')
        verbose_name_plural = _('Doors')
        default_related_name = 'doors'


class Hole(GeometryMapItem):
    """
    A hole in the ground of a room, e.g. for stairs.
    """
    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Hole')
        verbose_name_plural = _('Holes')
        default_related_name = 'holes'


class ElevatorLevel(GeometryMapItem):
    """
    An elevator Level
    """
    elevator = models.ForeignKey(Elevator, on_delete=models.PROTECT, related_name='levels')
    button = models.SlugField(_('Button label'), max_length=10)

    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Elevator Level')
        verbose_name_plural = _('Elevator Levels')
        default_related_name = 'elevatorlevels'

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['elevator'] = self.elevator.name
        result['button'] = self.button
        return result

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        if 'elevator' not in data:
            raise ValueError('missing elevator.')
        kwargs['elevator'] = data['elevator']

        if 'button' not in data:
            raise ValueError('missing button.')
        kwargs['button'] = data['button']

        return kwargs

    def tofile(self):
        result = super().tofile()
        result['elevator'] = self.elevator.name
        result['button'] = self.button
        return result
