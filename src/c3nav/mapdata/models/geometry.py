from collections import OrderedDict
from django.db import models
from django.utils.translation import ugettext_lazy as _
from shapely.geometry import CAP_STYLE, JOIN_STYLE
from shapely.geometry.geo import mapping

from c3nav.mapdata.models.base import GeometryFeature
from c3nav.mapdata.utils.json import format_geojson


class LevelFeature(GeometryFeature):
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


class AreaFeature(GeometryFeature):
    """
    a map feature that has a geometry and belongs to an area
    """
    area = models.ForeignKey('mapdata.Area', on_delete=models.CASCADE, verbose_name=_('area'))

    class Meta:
        abstract = True

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['area'] = self.area.id
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


class Area(LevelFeature):
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
        result['category'] = self.category
        result['layer'] = self.layer
        result['public'] = self.public
        return result


class StuffedArea(AreaFeature):
    """
    A slow area with many tables or similar. Avoid it from routing by slowing it a bit down
    """
    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Stuffed Area')
        verbose_name_plural = _('Stuffed Areas')
        default_related_name = 'stuffedareas'


class Stair(AreaFeature):
    """
    A stair
    """
    geomtype = 'polyline'

    class Meta:
        verbose_name = _('Stair')
        verbose_name_plural = _('Stairs')
        default_related_name = 'stairs'

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
                ('original_id', self.id),
                ('area', self.area.id),
            ))),
            ('geometry', format_geojson(mapping(shadow), round=False)),
        ))


class Obstacle(AreaFeature):
    """
    An obstacle
    """
    geomtype = 'polygon'

    class Meta:
        verbose_name = _('Obstacle')
        verbose_name_plural = _('Obstacles')
        default_related_name = 'obstacles'


class LineObstacle(AreaFeature):
    """
    An obstacle that is a line with a specific width
    """
    width = models.DecimalField(_('obstacle width'), max_digits=4, decimal_places=2, default=0.15)

    geomtype = 'polyline'

    class Meta:
        verbose_name = _('Line Obstacle')
        verbose_name_plural = _('Line Obstacles')
        default_related_name = 'lineobstacles'

    @property
    def buffered_geometry(self):
        return self.geometry.buffer(self.width / 2, join_style=JOIN_STYLE.mitre, cap_style=CAP_STYLE.flat)

    def to_geojson(self):
        result = super().to_geojson()
        original_geometry = result['geometry']
        result['geometry'] = format_geojson(mapping(self.buffered_geometry))
        result['original_geometry'] = original_geometry
        return result

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
        result['width'] = float(self.width)
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
