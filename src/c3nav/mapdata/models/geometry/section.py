from collections import OrderedDict

from django.db import models
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.fields import GeometryField
from c3nav.mapdata.models.geometry.base import GeometryMixin

SECTION_MODELS = OrderedDict()


class SectionGeometryMixin(GeometryMixin):
    section = models.ForeignKey('mapdata.Section', on_delete=models.CASCADE, verbose_name=_('section'))

    class Meta:
        abstract = True

    def get_geojson_properties(self):
        result = super().get_geojson_properties()
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


class Space(SectionGeometryMixin, models.Model):
    """
    An accessible space. Shouldn't overlap.
    """

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
    geometry = GeometryField('polygon')
    public = models.BooleanField(verbose_name=_('public'), default=True)
    category = models.CharField(verbose_name=_('category'), choices=CATEGORIES, default='', max_length=16)
    layer = models.CharField(verbose_name=_('layer'), choices=LAYERS, default='', max_length=16)

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


class Door(SectionGeometryMixin, models.Model):
    """
    A connection between two rooms
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Door')
        verbose_name_plural = _('Doors')
        default_related_name = 'doors'


class Hole(SectionGeometryMixin, models.Model):
    """
    A hole in the ground of a section (all spaces with layer "normal" and buildings), e.g. for stairs.
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Hole')
        verbose_name_plural = _('Holes')
        default_related_name = 'holes'
