from django.db import models
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.fields import GeometryField
from c3nav.mapdata.models import Level
from c3nav.mapdata.models.access import AccessRestrictionMixin
from c3nav.mapdata.models.geometry.base import GeometryMixin
from c3nav.mapdata.models.locations import SpecificLocation


class LevelGeometryMixin(GeometryMixin):
    level = models.ForeignKey('mapdata.Level', on_delete=models.CASCADE, verbose_name=_('level'))

    class Meta:
        abstract = True

    def get_geojson_properties(self, *args, instance=None, **kwargs) -> dict:
        result = super().get_geojson_properties(*args, **kwargs)
        result['level'] = self.level_id
        if hasattr(self, 'get_color'):
            color = self.get_color(instance=instance)
            if color:
                result['color'] = color
        if hasattr(self, 'opacity'):
            result['opacity'] = self.opacity
        return result

    def _serialize(self, level=True, **kwargs):
        result = super()._serialize(**kwargs)
        if level:
            result['level'] = self.level_id
        return result


class Building(LevelGeometryMixin, models.Model):
    """
    The outline of a building on a specific level
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Building')
        verbose_name_plural = _('Buildings')
        default_related_name = 'buildings'


class Space(SpecificLocation, LevelGeometryMixin, models.Model):
    """
    An accessible space. Shouldn't overlap with spaces on the same level.
    """
    geometry = GeometryField('polygon')
    outside = models.BooleanField(default=False, verbose_name=_('only outside of building'))

    class Meta:
        verbose_name = _('Space')
        verbose_name_plural = _('Spaces')
        default_related_name = 'spaces'


class Door(AccessRestrictionMixin, LevelGeometryMixin, models.Model):
    """
    A connection between two spaces
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Door')
        verbose_name_plural = _('Doors')
        default_related_name = 'doors'


class AltitudeArea(LevelGeometryMixin, models.Model):
    """
    An altitude area
    """
    geometry = GeometryField('polygon')
    altitude = models.DecimalField(_('altitude'), null=False, max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = _('Altitude Area')
        verbose_name_plural = _('Altitude Areas')
        default_related_name = 'altitudeareas'
