from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.text import format_lazy
from django.utils.translation import ugettext_lazy as _
from shapely.geometry import CAP_STYLE, JOIN_STYLE, mapping

from c3nav.mapdata.fields import GeometryField, I18nField, JSONField
from c3nav.mapdata.models.geometry.base import GeometryMixin
from c3nav.mapdata.models.locations import SpecificLocation
from c3nav.mapdata.utils.cache.changes import changed_geometries
from c3nav.mapdata.utils.json import format_geojson


class SpaceGeometryMixin(GeometryMixin):
    space = models.ForeignKey('mapdata.Space', on_delete=models.CASCADE, verbose_name=_('space'))

    class Meta:
        abstract = True

    @cached_property
    def level_id(self):
        return self.space.level_id

    def get_geojson_properties(self, *args, instance=None, **kwargs) -> dict:
        result = super().get_geojson_properties(*args, **kwargs)
        if hasattr(self, 'get_color'):
            color = self.get_color(instance=instance)
            if color:
                result['color'] = color
        if hasattr(self, 'opacity'):
            result['opacity'] = self.opacity
        return result

    @property
    def subtitle(self):
        base_subtitle = super().subtitle
        space = getattr(self, '_space_cache', None)
        if space is not None:
            level = getattr(space, '_level_cache', None)
            if level is not None:
                return format_lazy(_('{category}, {space}, {level}'),
                                   category=base_subtitle,
                                   space=space.title,
                                   level=level.title)
            return format_lazy(_('{category}, {space}'),
                               category=base_subtitle,
                               level=space.title)
        return base_subtitle

    def register_change(self, force=True):
        space = self.space
        force = force or self.all_geometry_changed
        if force or self.geometry_changed:
            changed_geometries.register(space.level_id, space.geometry.intersection(
                self.geometry if force else self.get_changed_geometry()
            ))

    def details_display(self):
        result = super().details_display()
        result['display'].insert(3, (
            _('Space'),
            {
                'id': self.space_id,
                'slug': self.space.get_slug(),
                'title': self.space.title,
                'can_search': self.space.can_search,
            },
        ))
        return result

    def register_delete(self):
        space = self.space
        changed_geometries.register(space.level_id, space.geometry.intersection(self.geometry))

    def save(self, *args, **kwargs):
        self.register_change()
        super().save(*args, **kwargs)


class Column(SpaceGeometryMixin, models.Model):
    """
    An column in a space, also used to be able to create rooms within rooms.
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Column')
        verbose_name_plural = _('Columns')
        default_related_name = 'columns'


class Area(SpaceGeometryMixin, SpecificLocation, models.Model):
    """
    An area in a space.
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Area')
        verbose_name_plural = _('Areas')
        default_related_name = 'areas'

    def _serialize(self, **kwargs):
        result = super()._serialize(**kwargs)
        return result

    def details_display(self):
        result = super().details_display()
        result['editor_url'] = reverse('editor.areas.edit', kwargs={'space': self.space_id, 'pk': self.pk})
        return result


class Stair(SpaceGeometryMixin, models.Model):
    """
    A stair
    """
    geometry = GeometryField('linestring')

    class Meta:
        verbose_name = _('Stair')
        verbose_name_plural = _('Stairs')
        default_related_name = 'stairs'


class Ramp(SpaceGeometryMixin, models.Model):
    """
    A ramp
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Ramp')
        verbose_name_plural = _('Ramps')
        default_related_name = 'ramps'


class Obstacle(SpaceGeometryMixin, models.Model):
    """
    An obstacle
    """
    geometry = GeometryField('polygon')
    height = models.DecimalField(_('height'), max_digits=6, decimal_places=2, default=0.8,
                                 validators=[MinValueValidator(Decimal('0'))])

    class Meta:
        verbose_name = _('Obstacle')
        verbose_name_plural = _('Obstacles')
        default_related_name = 'obstacles'

    def _serialize(self, geometry=True, **kwargs):
        result = super()._serialize(geometry=geometry, **kwargs)
        result['height'] = float(str(self.height))
        return result


class LineObstacle(SpaceGeometryMixin, models.Model):
    """
    An obstacle that is a line with a specific width
    """
    geometry = GeometryField('linestring')
    width = models.DecimalField(_('width'), max_digits=4, decimal_places=2, default=0.15)
    height = models.DecimalField(_('height'), max_digits=6, decimal_places=2, default=0.8,
                                 validators=[MinValueValidator(Decimal('0'))])

    class Meta:
        verbose_name = _('Line Obstacle')
        verbose_name_plural = _('Line Obstacles')
        default_related_name = 'lineobstacles'

    def serialize(self, geometry=True, **kwargs):
        result = super().serialize(geometry=geometry, **kwargs)
        if geometry:
            result.move_to_end('buffered_geometry')
        return result

    def _serialize(self, geometry=True, **kwargs):
        result = super()._serialize(geometry=geometry, **kwargs)
        result['width'] = float(str(self.width))
        result['height'] = float(str(self.height))
        if geometry:
            result['buffered_geometry'] = format_geojson(mapping(self.buffered_geometry))
        return result

    @property
    def buffered_geometry(self):
        return self.geometry.buffer(self.width / 2, join_style=JOIN_STYLE.mitre, cap_style=CAP_STYLE.flat)

    def to_geojson(self, *args, **kwargs):
        result = super().to_geojson(*args, **kwargs)
        result['original_geometry'] = result['geometry']
        result['geometry'] = format_geojson(mapping(self.buffered_geometry))
        return result


class POI(SpaceGeometryMixin, SpecificLocation, models.Model):
    """
    An point of interest
    """
    geometry = GeometryField('point')

    class Meta:
        verbose_name = _('Point of Interest')
        verbose_name_plural = _('Points of Interest')
        default_related_name = 'pois'

    def details_display(self):
        result = super().details_display()
        result['editor_url'] = reverse('editor.pois.edit', kwargs={'space': self.space_id, 'pk': self.pk})
        return result


class Hole(SpaceGeometryMixin, models.Model):
    """
    A hole in the ground of a space, e.g. for stairs.
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Hole')
        verbose_name_plural = _('Holes')
        default_related_name = 'holes'


class AltitudeMarker(SpaceGeometryMixin, models.Model):
    """
    An altitude marker
    """
    geometry = GeometryField('point')
    altitude = models.DecimalField(_('altitude'), null=False, max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = _('Altitude Marker')
        verbose_name_plural = _('Altitude Markers')
        default_related_name = 'altitudemarkers'

    @property
    def title(self):
        return '%s (%sm)' % (super().title, self.altitude)


class LeaveDescription(models.Model):
    """
    A description for leaving a space to another space
    """
    space = models.ForeignKey('mapdata.Space', on_delete=models.CASCADE, verbose_name=_('space'))
    target_space = models.ForeignKey('mapdata.Space', on_delete=models.CASCADE, verbose_name=_('target space'),
                                     related_name='enter_descriptions')
    description = I18nField(_('description'))

    class Meta:
        verbose_name = _('Leave description')
        verbose_name_plural = _('Leave descriptions')
        default_related_name = 'leave_descriptions'
        unique_together = (
            ('space', 'target_space')
        )

    @cached_property
    def title(self):
        return self.target_space.title


class CrossDescription(models.Model):
    """
    A description for crossing a space from one space to another space
    """
    space = models.ForeignKey('mapdata.Space', on_delete=models.CASCADE, verbose_name=_('space'))
    origin_space = models.ForeignKey('mapdata.Space', on_delete=models.CASCADE, verbose_name=_('origin space'),
                                     related_name='leave_cross_descriptions')
    target_space = models.ForeignKey('mapdata.Space', on_delete=models.CASCADE, verbose_name=_('target space'),
                                     related_name='cross_enter_descriptions')
    description = I18nField(_('description'))

    class Meta:
        verbose_name = _('Cross description')
        verbose_name_plural = _('Cross descriptions')
        default_related_name = 'cross_descriptions'
        unique_together = (
            ('space', 'origin_space', 'target_space')
        )

    @cached_property
    def title(self):
        return '%s → %s' % (self.origin_space.title, self.target_space.title)


class WifiMeasurement(SpaceGeometryMixin, models.Model):
    """
    A Wi-Fi measurement
    """
    geometry = GeometryField('point')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name=_('author'))
    comment = models.TextField(null=True, blank=True, verbose_name=_('comment'))
    data = JSONField(_('Measurement list'))

    class Meta:
        verbose_name = _('Wi-Fi Measurement')
        verbose_name_plural = _('Wi-Fi Measurements')
        default_related_name = 'wifi_measurements'
