from collections import OrderedDict

from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from shapely.geometry import CAP_STYLE, JOIN_STYLE, Point
from shapely.geometry.geo import mapping

from c3nav.mapdata.fields import GeometryField
from c3nav.mapdata.models import Elevator
from c3nav.mapdata.models.base import MapItem, MapItemMeta
from c3nav.mapdata.utils.json import format_geojson

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
    geometry = GeometryField()

    geomtype = None

    class Meta:
        abstract = True

    def get_geojson_properties(self):
        return OrderedDict((
            ('type', self.__class__.__name__.lower()),
            ('name', self.name),
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


class GeometryMapItemWithLevel(GeometryMapItem):
    """
    A map feature
    """
    level = models.ForeignKey('mapdata.Level', on_delete=models.CASCADE, verbose_name=_('level'))

    class Meta:
        abstract = True

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['level'] = self.level.name
        return result


class DirectedLineGeometryMapItemWithLevel(GeometryMapItemWithLevel):
    geomtype = 'polyline'

    class Meta:
        abstract = True

    def to_geojson(self):
        result = super().to_geojson()
        original_geometry = result['geometry']
        draw = self.geometry.buffer(0.05, join_style=JOIN_STYLE.mitre, cap_style=CAP_STYLE.flat)
        result['geometry'] = format_geojson(mapping(draw))
        result['original_geometry'] = original_geometry
        return result

    def to_shadow_geojson(self):
        shadow = self.geometry.parallel_offset(0.03, 'right', join_style=JOIN_STYLE.mitre)
        shadow = shadow.buffer(0.019, join_style=JOIN_STYLE.mitre, cap_style=CAP_STYLE.flat)
        return OrderedDict((
            ('type', 'Feature'),
            ('properties', OrderedDict((
                ('type', 'shadow'),
                ('original_type', self.__class__.__name__.lower()),
                ('original_name', self.name),
                ('level', self.level.name),
            ))),
            ('geometry', format_geojson(mapping(shadow), round=False)),
        ))


class Building(GeometryMapItemWithLevel):
    """
    The outline of a building on a specific level
    """
    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Building')
        verbose_name_plural = _('Buildings')
        default_related_name = 'buildings'


class Area(GeometryMapItemWithLevel):
    """
    An accessible area. Shouldn't overlap.
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
        result['public'] = self.public
        return result


class StuffedArea(GeometryMapItemWithLevel):
    """
    A slow area with many tables or similar. Avoid it from routing by slowing it a bit down
    """
    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Stuffed Area')
        verbose_name_plural = _('Stuffed Areas')
        default_related_name = 'stuffedareas'


class Escalator(GeometryMapItemWithLevel):
    """
    An escalator area
    """
    DIRECTIONS = (
        (True, _('up')),
        (False, _('down')),
    )
    direction = models.BooleanField(verbose_name=_('direction'), choices=DIRECTIONS)

    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Escalator')
        verbose_name_plural = _('Escalators')
        default_related_name = 'escalators'

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['direction'] = 'up' if self.direction else 'down'
        return result


class Stair(DirectedLineGeometryMapItemWithLevel):
    """
    A stair
    """
    class Meta:
        verbose_name = _('Stair')
        verbose_name_plural = _('Stairs')
        default_related_name = 'stairs'


class Obstacle(GeometryMapItemWithLevel):
    """
    An obstacle
    """
    crop_to_level = models.ForeignKey('mapdata.Level', on_delete=models.CASCADE, null=True, blank=True,
                                      verbose_name=_('crop to other level'), related_name='crops_obstacles')

    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Obstacle')
        verbose_name_plural = _('Obstacles')
        default_related_name = 'obstacles'

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        if self.crop_to_level is not None:
            result['crop_to_level'] = self.crop_to_level.name
        return result


class LineObstacle(GeometryMapItemWithLevel):
    """
    An obstacle that is a line with a specific width
    """
    width = models.DecimalField(_('obstacle width'), max_digits=4, decimal_places=2, default=0.15)

    geomtype = 'polyline'

    class Meta:
        verbose_name = _('Line Obstacle')
        verbose_name_plural = _('Line Obstacles')
        default_related_name = 'lineobstacles'

    def to_geojson(self):
        result = super().to_geojson()
        original_geometry = result['geometry']
        draw = self.geometry.buffer(self.width/2, join_style=JOIN_STYLE.mitre, cap_style=CAP_STYLE.flat)
        result['geometry'] = format_geojson(mapping(draw))
        result['original_geometry'] = original_geometry
        return result

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['width'] = float(self.width)
        return result


class LevelConnector(GeometryMapItem):
    """
    A connector connecting levels
    """
    geomtype = 'polygon'
    levels = models.ManyToManyField('mapdata.Level', verbose_name=_('levels'))

    class Meta:
        verbose_name = _('Level Connector')
        verbose_name_plural = _('Level Connectors')
        default_related_name = 'levelconnectors'

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['levels'] = tuple(self.levels.all().order_by('name').values_list('name', flat=True))
        return result


class Door(GeometryMapItemWithLevel):
    """
    A connection between two rooms
    """
    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Door')
        verbose_name_plural = _('Doors')
        default_related_name = 'doors'


class Hole(GeometryMapItemWithLevel):
    """
    A hole in the ground of a room, e.g. for stairs.
    """
    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Hole')
        verbose_name_plural = _('Holes')
        default_related_name = 'holes'


class ElevatorLevel(GeometryMapItemWithLevel):
    """
    An elevator Level
    """
    elevator = models.ForeignKey(Elevator, on_delete=models.PROTECT)
    button = models.SlugField(_('Button label'), max_length=10)
    override_altitude = models.DecimalField(_('override level altitude'),
                                            blank=True, null=True, max_digits=6, decimal_places=2)
    public = models.BooleanField(verbose_name=_('public'))

    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Elevator Level')
        verbose_name_plural = _('Elevator Levels')
        default_related_name = 'elevatorlevels'

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['public'] = self.public
        result['elevator'] = self.elevator.name
        result['button'] = self.button
        return result

    @cached_property
    def altitude(self):
        if self.override_altitude is not None:
            return self.override_altitude
        return self.level.altitude
