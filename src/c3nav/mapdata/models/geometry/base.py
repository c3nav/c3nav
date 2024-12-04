import math
from contextlib import contextmanager

from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from c3nav.mapdata.models.base import SerializableMixin
from c3nav.mapdata.utils.geometry import assert_multipolygon, good_representative_point, smart_mapping, unwrap_geom
from c3nav.mapdata.utils.json import format_geojson

geometry_affecting_fields = ('height', 'width', 'access_restriction')


class GeometryMixin(SerializableMixin):
    no_orig = False

    """
    A map feature with a geometry
    """
    geometry: BaseGeometry
    level_id: int
    subtitle: str
    import_tag = models.CharField(_('import tag'), null=True, blank=True, max_length=64)

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.no_orig:
            self.orig_geometry = None if 'geometry' in self.get_deferred_fields() else self.geometry
            self._orig = {field.attname: (None if field.attname in self.get_deferred_fields()
                                          else getattr(self, field.attname))
                          for field in self._meta.get_fields()
                          if field.name in geometry_affecting_fields}

    @classmethod
    @contextmanager
    def dont_keep_originals(cls):
        # todo: invert this and to no_orig being True by default
        cls.no_orig = True
        yield
        cls.no_orig = False

    def get_geojson_properties(self, *args, **kwargs) -> dict:
        result = {
            'type': self.__class__.__name__.lower(),
            'id': self.id
        }
        if getattr(self, 'bounds', False):
            result['bounds'] = True
        return result

    def get_geojson_key(self):
        return (self.__class__.__name__.lower(), self.id)

    def to_geojson(self) -> dict:
        result = {
            'type': 'Feature',
            'properties': self.get_geojson_properties(),
            'geometry': format_geojson(smart_mapping(self.geometry), rounded=False),
        }
        original_geometry = getattr(self, 'original_geometry', None)
        if original_geometry:
            result['original_geometry'] = format_geojson(smart_mapping(original_geometry), rounded=False)
        return result

    @classmethod
    def serialize_type(cls, geomtype=True, **kwargs):
        result = super().serialize_type()
        if geomtype:
            result['geomtype'] = cls._meta.get_field('geometry').geomtype
        return result

    @cached_property
    def point(self):
        if "geometry" in self.get_deferred_fields():
            raise ValueError
        return good_representative_point(self.geometry)

    def details_display(self, detailed_geometry=True, **kwargs):
        result = super().details_display(**kwargs)
        result['geometry'] = self.get_geometry(detailed_geometry=detailed_geometry)
        return result

    def get_geometry(self, detailed_geometry=True):
        if "geometry" in self.get_deferred_fields():
            return None
        if detailed_geometry:
            return format_geojson(smart_mapping(self.geometry), rounded=False)
        return format_geojson(smart_mapping(self.geometry.minimum_rotated_rectangle), rounded=False)

    def get_shadow_geojson(self):
        pass

    def contains(self, x, y) -> bool:
        return self.geometry.contains(Point(x, y))

    @property
    def all_geometry_changed(self):
        return any(getattr(self, attname) != value for attname, value in self._orig.items())

    @property
    def geometry_changed(self):
        if self.orig_geometry is None:
            return True
        if self.geometry is self.orig_geometry:
            return False
        if not self.geometry.equals_exact(unwrap_geom(self.orig_geometry), 0.05):
            return True
        field = self._meta.get_field('geometry')
        rounded = field.to_python(field.get_prep_value(self.geometry))
        if not rounded.equals_exact(unwrap_geom(self.orig_geometry), 0.005):
            return True
        return False

    def get_changed_geometry(self):
        field = self._meta.get_field('geometry')
        new_geometry = field.get_final_value(self.geometry)
        if self.orig_geometry is None:
            return new_geometry
        difference = new_geometry.symmetric_difference(unwrap_geom(self.orig_geometry))
        if self._meta.get_field('geometry').geomtype in ('polygon', 'multipolygon'):
            difference = unary_union(assert_multipolygon(difference))
        return difference
