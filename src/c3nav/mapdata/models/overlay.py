from typing import Optional

from django.db import models
from django.utils.translation import gettext_lazy as _
from django_pydantic_field import SchemaField

from c3nav.mapdata.fields import GeometryField
from c3nav.mapdata.models.access import AccessRestrictionMixin
from c3nav.mapdata.models.base import TitledMixin
from c3nav.mapdata.models.geometry.level import LevelGeometryMixin
from c3nav.mapdata.utils.geometry import smart_mapping
from c3nav.mapdata.utils.json import format_geojson


class DataOverlay(TitledMixin, AccessRestrictionMixin, models.Model):
    class GeometryType(models.TextChoices):
        POLYGON = "polygon", _("Polygon")
        LINESTRING = "linestring", _("Line string")
        MULTIPOINT = "multipoint", _("Multipoint")
        POINT = "point", _("Point")

    description = models.TextField(blank=True, verbose_name=_('Description'))
    stroke_color = models.CharField(max_length=255, blank=True, null=True, verbose_name=_('default stroke color'))
    stroke_width = models.FloatField(blank=True, null=True, verbose_name=_('default stroke width'))
    stroke_opacity = models.FloatField(blank=True, null=True, verbose_name=_('stroke opacity'))
    fill_color = models.CharField(max_length=255, blank=True, null=True, verbose_name=_('default fill color'))
    fill_opacity = models.FloatField(blank=True, null=True, verbose_name=_('fill opacity'))

    default_geomtype = models.CharField(max_length=255, blank=True, null=True, choices=GeometryType, verbose_name=_('default geometry type'))

    pull_url = models.URLField(blank=True, null=True, verbose_name=_('pull URL'))
    pull_headers: dict[str, str] = SchemaField(schema=dict[str, str], null=True,
                                               verbose_name=_('headers for pull http request (JSON object)'))
    pull_interval = models.DurationField(blank=True, null=True, verbose_name=_('pull interval'))

    class Meta:
        verbose_name = _('Data Overlay')
        verbose_name_plural = _('Data Overlays')
        default_related_name = 'dataoverlays'


class DataOverlayFeature(TitledMixin, LevelGeometryMixin, models.Model):
    overlay = models.ForeignKey('mapdata.DataOverlay', on_delete=models.CASCADE, verbose_name=_('Overlay'), related_name='features')
    geometry = GeometryField()
    # level = models.ForeignKey('mapdata.Level', on_delete=models.CASCADE, verbose_name=_('level'), related_name='data_overlay_features')
    external_url = models.URLField(blank=True, null=True, verbose_name=_('external URL'))
    stroke_color = models.CharField(max_length=255, blank=True, null=True, verbose_name=_('stroke color'))
    stroke_width = models.FloatField(blank=True, null=True, verbose_name=_('stroke width'))
    stroke_opacity = models.FloatField(blank=True, null=True, verbose_name=_('stroke opacity'))
    fill_color = models.CharField(max_length=255, blank=True, null=True, verbose_name=_('fill color'))
    fill_opacity = models.FloatField(blank=True, null=True, verbose_name=_('fill opacity'))
    show_label = models.BooleanField(default=False, verbose_name=_('show label'))
    show_geometry = models.BooleanField(default=True, verbose_name=_('show geometry'))
    interactive = models.BooleanField(default=True, verbose_name=_('interactive'),
                                      help_text=_('disable to make this feature click-through'))
    point_icon = models.CharField(max_length=255, blank=True, null=True, verbose_name=_('point icon'),
                                  help_text=_(
                                      'use this material icon to display points, instead of drawing a small circle (only makes sense if the geometry is a point)'))
    extra_data: Optional[dict[str, str|int|bool]] = SchemaField(schema=dict[str, str|int|bool], blank=True, null=True,
                                                                default=None,
                                                                verbose_name=_('extra data (JSON object)'))

    def to_geojson(self, instance=None) -> dict:
        result = {
            'type': 'Feature',
            'properties': {
                'type': 'dataoverlayfeature',
                'id': self.id,
                'level': self.level_id,
                'overlay': self.overlay_id,
            },
            'geometry': format_geojson(smart_mapping(self.geometry), rounded=False),
        }
        original_geometry = getattr(self, 'original_geometry', None)
        if original_geometry:
            result['original_geometry'] = format_geojson(smart_mapping(original_geometry), rounded=False)
        return result

    def get_geojson_key(self):
        return 'dataoverlayfeature', self.id

    class Meta:
        default_related_name = "dataoverlayfeatures"
