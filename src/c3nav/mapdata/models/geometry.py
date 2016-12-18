from collections import OrderedDict

from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from shapely.geometry import CAP_STYLE, JOIN_STYLE
from shapely.geometry.geo import mapping, shape

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

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        if 'geometry' not in data:
            raise ValueError('missing geometry.')
        try:
            kwargs['geometry'] = shape(data['geometry'])
        except:
            raise ValueError(_('Invalid GeoJSON.'))

        return kwargs

    def get_geojson_properties(self):
        return OrderedDict((
            ('type', self.__class__.__name__.lower()),
            ('name', self.name),
            ('package', self.package.name),
        ))

    def to_geojson(self):
        return OrderedDict((
            ('type', 'Feature'),
            ('properties', self.get_geojson_properties()),
            ('geometry', format_geojson(mapping(self.geometry), round=False)),
        ))

    def tofile(self):
        result = super().tofile()
        result['geometry'] = format_geojson(mapping(self.geometry))
        return result

    def get_shadow_geojson(self):
        return None


class GeometryMapItemWithLevel(GeometryMapItem):
    """
    A map feature
    """
    level = models.ForeignKey('mapdata.Level', on_delete=models.CASCADE, verbose_name=_('level'))

    class Meta:
        abstract = True

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        if 'level' not in data:
            raise ValueError('missing level.')
        kwargs['level'] = data['level']

        return kwargs

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['level'] = self.level.name
        return result

    def tofile(self):
        result = super().tofile()
        result['level'] = self.level.name
        result.move_to_end('geometry')
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


class Room(GeometryMapItemWithLevel):
    """
    An accessible area like a room. Can overlap.
    """
    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Room')
        verbose_name_plural = _('Rooms')
        default_related_name = 'rooms'


class Outside(GeometryMapItemWithLevel):
    """
    An accessible outdoor area like a court. Can overlap.
    """
    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Outside Area')
        verbose_name_plural = _('Outside Areas')
        default_related_name = 'outsides'


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

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        if 'direction' not in data:
            raise ValueError('missing direction.')
        kwargs['direction'] = data['direction']

        return kwargs

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['direction'] = 'up' if self.direction else 'down'
        return result

    def tofile(self):
        result = super().tofile()
        result['direction'] = self.direction
        return result


class EscalatorSlope(DirectedLineGeometryMapItemWithLevel):
    """
    An escalator slope, indicating which side of the escalator is up
    """
    class Meta:
        verbose_name = _('Escalator Slope')
        verbose_name_plural = _('Escalator Slopes')
        default_related_name = 'escalatorslopes'


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

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        if 'crop_to_level' in data:
            kwargs['crop_to_level'] = data['crop_to_level']

        return kwargs

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        if self.crop_to_level is not None:
            result['crop_to_level'] = self.crop_to_level.name
        return result

    def tofile(self):
        result = super().tofile()
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

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        if 'width' not in data:
            raise ValueError('missing width.')
        kwargs['width'] = data['width']

        return kwargs

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['width'] = float(self.width)
        return result

    def tofile(self):
        result = super().tofile()
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

    @classmethod
    def fromfile(cls, data, file_path):
        kwargs = super().fromfile(data, file_path)

        if 'levels' not in data:
            raise ValueError('missing levels.')
        levels = data.get('levels', None)
        if not isinstance(levels, list):
            raise TypeError('levels has to be a list')
        if len(levels) < 2:
            raise ValueError('a level connector needs at least two levels')
        kwargs['levels'] = levels

        return kwargs

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['levels'] = tuple(self.levels.all().order_by('name').values_list('name', flat=True))
        return result

    def tofile(self):
        result = super().tofile()
        result['levels'] = sorted(self.levels.all().order_by('name').values_list('name', flat=True))
        result.move_to_end('geometry')
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
    override_altitude = models.DecimalField(_('override level altitude'), null=True, max_digits=6, decimal_places=2)

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

        if 'override_altitude' in data:
            kwargs['override_altitude'] = data['override_altitude']

        return kwargs

    def tofile(self):
        result = super().tofile()
        result['elevator'] = self.elevator.name
        result['button'] = self.button
        if self.override_altitude is not None:
            result['override_altitude'] = float(self.override_altitude)
        return result

    @cached_property
    def altitude(self):
        if self.override_altitude is not None:
            return self.override_altitude
        return self.level.altitude
