from django.db import models
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.fields import GeometryField
from c3nav.mapdata.models.geometry.base import GeometryMixin
from c3nav.mapdata.models.locations import SpecificLocation

SECTION_MODELS = []


class SectionGeometryMixin(GeometryMixin):
    section = models.ForeignKey('mapdata.Section', on_delete=models.CASCADE, verbose_name=_('section'))

    class Meta:
        abstract = True

    def get_geojson_properties(self) -> dict:
        result = super().get_geojson_properties()
        result['layer'] = getattr(self, 'level', 'base')
        if hasattr(self, 'get_color'):
            color = self.get_color()
            if color:
                result['color'] = color
        return result

    def _serialize(self, section=True, **kwargs):
        result = super()._serialize(**kwargs)
        if section:
            result['section'] = self.section.id
        return result


class Building(SectionGeometryMixin, models.Model):
    """
    The outline of a building on a specific level
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Building')
        verbose_name_plural = _('Buildings')
        default_related_name = 'buildings'


class Space(SpecificLocation, SectionGeometryMixin, models.Model):
    """
    An accessible space. Shouldn't overlap with spaces on same secion and level.
    """
    LEVELS = (
        ('normal', _('normal')),
        ('upper', _('upper')),
        ('lower', _('lower')),
    )
    CATEGORIES = (
        ('normal', _('normal')),
        ('stairs', _('stairs')),
        ('escalator', _('escalator')),
        ('elevator', _('elevator')),
    )
    geometry = GeometryField('polygon')
    level = models.CharField(verbose_name=_('level'), choices=LEVELS, default='normal', max_length=16)
    category = models.CharField(verbose_name=_('category'), choices=CATEGORIES, default='normal', max_length=16)
    outside = models.BooleanField(default=False, verbose_name=_('is outside of building'))

    class Meta:
        verbose_name = _('Space')
        verbose_name_plural = _('Spaces')
        default_related_name = 'spaces'

    def _serialize(self, space=True, **kwargs):
        result = super()._serialize(**kwargs)
        if space:
            result['category'] = self.category
            result['level'] = self.level
            result['public'] = self.public
        return result

    def get_color(self):
        color = super().get_color()
        if not color:
            color = {
                'stairs': '#dddddd',
                'escalator': '#bbbbbb',
                'elevator': '#00ffff',
            }.get(self.category)
        return color


class Door(SectionGeometryMixin, models.Model):
    """
    A connection between two spaces
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Door')
        verbose_name_plural = _('Doors')
        default_related_name = 'doors'
