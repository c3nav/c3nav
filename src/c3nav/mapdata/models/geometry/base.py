from collections import OrderedDict

from django.db import models
from django.utils.translation import ugettext_lazy as _
from shapely.geometry import Point, mapping

from c3nav.mapdata.models.base import SerializableMixin
from c3nav.mapdata.utils.json import format_geojson


class GeometryManager(models.Manager):
    def within(self, minx, miny, maxx, maxy):
        return self.get_queryset().filter(minx__lte=maxx, maxx__gte=minx, miny__lte=maxy, maxy__gte=miny)


class GeometryMixin(SerializableMixin):
    """
    A map feature with a geometry
    """
    geometry = None
    minx = models.DecimalField(_('min x coordinate'), max_digits=6, decimal_places=2, db_index=True)
    miny = models.DecimalField(_('min y coordinate'), max_digits=6, decimal_places=2, db_index=True)
    maxx = models.DecimalField(_('max x coordinate'), max_digits=6, decimal_places=2, db_index=True)
    maxy = models.DecimalField(_('max y coordinate'), max_digits=6, decimal_places=2, db_index=True)
    objects = GeometryManager()

    class Meta:
        abstract = True
        base_manager_name = 'objects'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.orig_geometry = None if 'geometry' in self.get_deferred_fields() else self.geometry

    def get_geojson_properties(self, *args, **kwargs) -> dict:
        result = OrderedDict((
            ('type', self.__class__.__name__.lower()),
            ('id', self.pk),
        ))
        if getattr(self, 'bounds', False):
            result['bounds'] = True
        return result

    def to_geojson(self, instance=None) -> dict:
        result = OrderedDict((
            ('type', 'Feature'),
            ('properties', self.get_geojson_properties(instance=instance)),
            ('geometry', format_geojson(mapping(self.geometry), round=False)),
        ))
        original_geometry = getattr(self, 'original_geometry', None)
        if original_geometry:
            result['original_geometry'] = format_geojson(mapping(original_geometry), round=False)
        return result

    @classmethod
    def serialize_type(cls, geomtype=True, **kwargs):
        result = super().serialize_type()
        if geomtype:
            result['geomtype'] = cls._meta.get_field('geometry').geomtype
        return result

    def serialize(self, geometry=True, **kwargs):
        result = super().serialize(geometry=geometry, **kwargs)
        if geometry:
            result.move_to_end('geometry')
        return result

    def _serialize(self, geometry=True, **kwargs):
        result = super()._serialize(**kwargs)
        if geometry:
            result['geometry'] = format_geojson(mapping(self.geometry), round=False)
        return result

    def get_shadow_geojson(self):
        pass

    def contains(self, x, y) -> bool:
        return self.geometry.contains(Point(x, y))

    def recalculate_bounds(self):
        self.minx, self.miny, self.maxx, self.maxy = self.geometry.bounds

    @property
    def geometry_changed(self):
        return self.orig_geometry is None or (self.geometry is not self.orig_geometry and
                                              not self.geometry.almost_equals(self.orig_geometry, 2))

    def get_changed_geometry(self):
        return self.geometry if self.orig_geometry is None else self.geometry.symmetric_difference(self.orig_geometry)

    def save(self, *args, **kwargs):
        self.recalculate_bounds()
        super().save(*args, **kwargs)
