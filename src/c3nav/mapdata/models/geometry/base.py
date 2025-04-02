from contextlib import contextmanager
from itertools import batched
from typing import TypeAlias, NamedTuple, Sequence, Iterator

from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django_pydantic_field import SchemaField
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, shape, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from c3nav.api.schema import GeometriesByLevelSchema, PolygonSchema, MultiPolygonSchema
from c3nav.mapdata.grid import grid
from c3nav.mapdata.permissions import MapPermissionTaggedItem, LazyMapPermissionFilteredTaggedValue
from c3nav.mapdata.schemas.model_base import LocationPoint, BoundsByLevelSchema
from c3nav.mapdata.utils.geometry import assert_multipolygon, good_representative_point, smart_mapping, unwrap_geom
from c3nav.mapdata.utils.json import format_geojson

geometry_affecting_fields = ('height', 'width', 'access_restriction')


class GeometryMixin(models.Model):
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
            self._orig_geometry = None if 'geometry' in self.get_deferred_fields() else self.geometry
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

    @property
    def can_access_geometry(self) -> bool:
        return True

    @property
    def all_geometry_changed(self):
        try:
            if self._orig_geometry is None:
                return True
        except AttributeError:
            return True
        return any(getattr(self, attname) != value for attname, value in self._orig.items())

    @property
    def geometry_changed(self):
        try:
            if self._orig_geometry is None:
                return True
        except AttributeError:
            return True
        if self.geometry is self._orig_geometry:
            return False
        if not self.geometry.equals_exact(unwrap_geom(self._orig_geometry), 0.05):
            return True
        field = self._meta.get_field('geometry')
        rounded = field.to_python(field.get_prep_value(self.geometry))
        if not rounded.equals_exact(unwrap_geom(self._orig_geometry), 0.005):
            return True
        return False

    def get_changed_geometry(self):
        field = self._meta.get_field('geometry')
        new_geometry = field.get_final_value(self.geometry)
        try:
            if self._orig_geometry is None:
                return new_geometry
        except AttributeError:
            return new_geometry
        difference = new_geometry.symmetric_difference(unwrap_geom(self._orig_geometry))
        if self._meta.get_field('geometry').geomtype in ('polygon', 'multipolygon'):
            difference = unary_union(assert_multipolygon(difference))
        return difference

    def pre_delete_changed_geometries(self):
        self.register_delete()

    def delete(self, *args, **kwargs):
        self.pre_delete_changed_geometries()
        super().delete(*args, **kwargs)


CachedEffectiveGeometries: TypeAlias = list[MapPermissionTaggedItem[PolygonSchema | MultiPolygonSchema]]
CachedPoints: TypeAlias = list[MapPermissionTaggedItem[tuple[float, float]]]
CachedBound: TypeAlias = list[MapPermissionTaggedItem[float]]


class CachedBounds(NamedTuple):
    minx: list[MapPermissionTaggedItem[float]]
    miny: list[MapPermissionTaggedItem[float]]
    maxx: list[MapPermissionTaggedItem[float]]
    maxy: list[MapPermissionTaggedItem[float]]


class LazyMapPermissionFilteredBounds(NamedTuple):
    minx: LazyMapPermissionFilteredTaggedValue[float, None]
    miny: LazyMapPermissionFilteredTaggedValue[float, None]
    maxx: LazyMapPermissionFilteredTaggedValue[float, None]
    maxy: LazyMapPermissionFilteredTaggedValue[float, None]


class CachedEffectiveGeometryMixin(models.Model):
    cached_effective_geometries: CachedEffectiveGeometries = SchemaField(schema=CachedEffectiveGeometries, default=list)
    cached_points: CachedPoints = SchemaField(schema=CachedPoints, default=list)
    cached_bounds: CachedBounds = SchemaField(schema=CachedBounds, null=True)

    class Meta:
        abstract = True

    @cached_property
    def _effective_geometries(self) -> LazyMapPermissionFilteredTaggedValue[Polygon | MultiPolygon, GeometryCollection]:
        return LazyMapPermissionFilteredTaggedValue(tuple(
            MapPermissionTaggedItem(
                value=shape(item.value.model_dump()),
                access_restrictions=item.access_restrictions
            )
            for item in self.cached_effective_geometries
        ), default=GeometryCollection())

    @property
    def effective_geometry(self) -> Polygon | MultiPolygon | GeometryCollection:
        return self._effective_geometries.get()

    @property
    def geometries_by_level(self) -> GeometriesByLevelSchema:
        if self.level_id is None:
            return {}
        return {
            self.level_id: [self.effective_geometry]  # todo: split into multiple polygons maybe?
        }

    @cached_property
    def _points(self) -> LazyMapPermissionFilteredTaggedValue[tuple[float, float], None]:
        return LazyMapPermissionFilteredTaggedValue(self.cached_points, default=None)

    @property
    def point(self) -> LocationPoint | None:
        if self.main_level_id is None:
            return None
        xy = self._points.get()
        if xy is None:
            return None
        return self.main_level_id, *xy

    @classmethod
    def recalculate_points(cls):
        for space in cls.objects.prefetch_related():
            results: list[MapPermissionTaggedItem[tuple[float, float]]] = []

            # we are caching resulting points to find duplicates
            point_results: dict[tuple[float, float], list[frozenset[int]]] = {}

            # go through all possible geometries, starting with the least restricted ones
            for geometry, access_restriction_ids in reversed(space.cached_effective_geometries):
                point = good_representative_point(shape(geometry)).coords[0]

                # seach whether we had this same points as a result before
                for previous_result in point_results.get(point, []):
                    if access_restriction_ids >= previous_result:
                        # if we already had this point with a subset of these access restrictions, skip
                        break

                # create and store item
                item = MapPermissionTaggedItem(value=point, access_restrictions=access_restriction_ids)
                point_results.setdefault(point, []).append(access_restriction_ids)
                results.append(item)

            # we need to reverse the list back to make the logic work
            space.cached_points = list(reversed(results))
            space.save()

    @cached_property
    def _bounds(self) -> LazyMapPermissionFilteredBounds:
        return LazyMapPermissionFilteredBounds(
            *(LazyMapPermissionFilteredTaggedValue(item, default=None) for item in self.cached_bounds)
        )

    @property
    def bounds(self) -> BoundsByLevelSchema:
        values = tuple(item.get() for item in self._bounds)
        if any((v is None) for v in values):
            return {}
        return {self.main_level_id: tuple(batched((round(i, 2) for i in values), 2))}

    @staticmethod
    def filter_bounds(bounds: Sequence[tuple[float, frozenset[int]]]) -> Iterator[MapPermissionTaggedItem[float]]:
        last_value = None
        done = []
        for value, restrictions in bounds:
            if value != last_value:
                done = []
                last_value = value
            if any((d <= restrictions) for d in done):
                # skip restriction supersets of other instances of the same value
                continue
            done.append(restrictions)
            yield MapPermissionTaggedItem(value=value, access_restrictions=restrictions)

    @classmethod
    def recalculate_bounds(cls):
        for obj in cls.objects.prefetch_related():
            if obj.cached_effective_geometries:
                geometries, access_restrictions = zip(*obj.cached_effective_geometries)
                obj.cached_bounds = CachedBounds(*(
                    list(cls.filter_bounds(sorted(zip(values, access_restrictions),
                                                  key=lambda v: (v[0]*(-1 if (i > 1) else 1), len(v[1])),
                                                  reverse=(i > 1))))
                    for i, values in enumerate(zip(*(shape(geometry).bounds for geometry in geometries)))
                ))
            else:
                obj.cached_bounds = CachedBounds([], [], [], [])
            obj.save()