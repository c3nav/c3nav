import logging
from decimal import Decimal
from itertools import combinations
from typing import Sequence, TypeAlias, NamedTuple

import numpy as np
from django.core.exceptions import ObjectDoesNotExist
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import CheckConstraint, Q
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django_pydantic_field import SchemaField
from scipy.interpolate._rbfinterp import RBFInterpolator
from shapely.geometry import MultiPolygon, Polygon, shape, GeometryCollection
from shapely.ops import unary_union

from c3nav.api.schema import PolygonSchema, MultiPolygonSchema
from c3nav.mapdata.fields import GeometryField, I18nField
from c3nav.mapdata.models import Level
from c3nav.mapdata.models.access import AccessRestrictionMixin, AccessRestrictionLogicMixin
from c3nav.mapdata.models.geometry.base import GeometryMixin, CachedEffectiveGeometryMixin
from c3nav.mapdata.models.locations import LocationTagTargetMixin
from c3nav.mapdata.permissions import MapPermissionTaggedItem, MapPermissionGuardedTaggedValue
from c3nav.mapdata.utils.cache.changes import changed_geometries
from c3nav.mapdata.utils.geometry import (unwrap_geom)


class LevelGeometryMixin(AccessRestrictionLogicMixin, GeometryMixin, models.Model):
    level = models.ForeignKey('mapdata.Level', on_delete=models.CASCADE, verbose_name=_('level'))

    class Meta:
        abstract = True

    def get_geojson_properties(self, *args, **kwargs) -> dict:
        result = super().get_geojson_properties(*args, **kwargs)
        result['level'] = self.level_id
        if hasattr(self, 'get_color'):
            from c3nav.mapdata.render.theme import ColorManager
            color = self.get_color(ColorManager.for_theme(None))
            if color:
                result['color'] = color
        if hasattr(self, 'opacity'):
            result['opacity'] = self.opacity
        return result

    @property
    def can_access_geometry(self) -> bool:
        from c3nav.mapdata.permissions import active_map_permissions
        return active_map_permissions.all_base_mapdata

    @property
    def subtitle(self):
        if "level" in self._state.fields_cache:
            return self.level.title
        return None

    def register_change(self, force=False):
        if force or self._state.adding or self.geometry_changed or self.all_geometry_changed:
            changed_geometries.register(
                self.level_id, self.geometry if force or self._state.adding else self.get_changed_geometry()
            )

    def register_delete(self):
        changed_geometries.register(self.level_id, self.geometry)

    @classmethod
    def q_for_permissions(cls, permissions: "MapPermissions", prefix=''):
        return (
            super().q_for_permissions(permissions, prefix=prefix) &
            Level.q_for_permissions(permissions, prefix=prefix+'level__')
        )

    @cached_property
    def effective_access_restrictions(self) -> frozenset[int]:
        return (
            super().effective_access_restrictions |
            self.level.effective_access_restrictions
        )

    def pre_save_changed_geometries(self):
        self.register_change()

    @cached_property
    def primary_level_id(self):
        try:
            return self.level.on_top_of_id or self.level_id
        except ObjectDoesNotExist:
            return None

    def save(self, *args, **kwargs):
        self.pre_save_changed_geometries()
        super().save(*args, **kwargs)


class Building(LevelGeometryMixin, models.Model):
    """
    The outline of a building on a specific level
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Building')
        verbose_name_plural = _('Buildings')
        default_related_name = 'buildings'


CachedSimplifiedGeometries: TypeAlias = list[MapPermissionTaggedItem[PolygonSchema]]


class Space(CachedEffectiveGeometryMixin, LevelGeometryMixin, LocationTagTargetMixin,
            AccessRestrictionMixin, models.Model):
    """
    An accessible space. Shouldn't overlap with spaces on the same level.
    """
    geometry = GeometryField('polygon')
    height = models.DecimalField(_('height'), max_digits=6, decimal_places=2, null=True, blank=True,
                                 validators=[MinValueValidator(Decimal('0'))])
    outside = models.BooleanField(default=False, verbose_name=_('only outside of building'))
    enter_description = I18nField(_('Enter description'), blank=True, fallback_language=None)
    base_mapdata_accessible = models.BooleanField(default=False,
                                                  verbose_name=_('always accessible (overwrites base mapdata setting)'))

    identifyable = models.BooleanField(null=True, default=None,
                                       verbose_name=_('easily identifyable/findable'),
                                       help_text=_('if unknown, this will be a quest. if yes, quests for enter, '
                                                   'leave or cross descriptions to this room will be generated.'))
    media_panel_done = models.BooleanField(default=False, verbose_name=_("All media panels mapped"))

    cached_simplified_geometries: CachedSimplifiedGeometries = SchemaField(schema=CachedSimplifiedGeometries,
                                                                           default=list)

    class Meta:
        verbose_name = _('Space')
        verbose_name_plural = _('Spaces')
        default_related_name = 'spaces'

    def for_details_display(self):
        location = self.get_location()
        if location:
            return {
                'id': location.pk,
                'slug': location.effective_slug,
                'title': location.title,
                'can_search': location.can_search,
            }
        return _('Unnamed space')

    @property
    def can_access_geometry(self) -> bool:
        from c3nav.mapdata.permissions import active_map_permissions
        return (self.base_mapdata_accessible
                or active_map_permissions.all_base_mapdata
                or self.id in active_map_permissions.spaces)

    @classmethod
    def recalculate_effective_geometries(cls):
        logger = logging.getLogger('c3nav')

        # collect all buildings, by level and merge polygons
        buildings_by_level = {}
        for building in buildings_by_level:
            buildings_by_level.setdefault(building.level_id, []).append(building.geometry)
        buildings_by_level = {level_id: unary_union(geoms) for level_id, geoms in buildings_by_level.items()}

        for space in cls.objects.prefetch_related("columns").select_related("level"):
            # collect all columns by restrictions and merge polygons
            columns_by_restrictions = {}
            for column in space.columns.all():
                access_restriction_id = column.access_restriction_id
                if access_restriction_id in space.effective_access_restrictions:
                    # remove access restrictions of the space to avoid unnecessary duplicates
                    access_restriction_id = None
                columns_by_restrictions.setdefault(access_restriction_id, []).append(unwrap_geom(column.geometry))
            columns_by_restrictions = {access_restriction_id: unary_union(geoms)
                                       for access_restriction_id, geoms in columns_by_restrictions.items()}

            # collect all restrictions we know for columns
            column_restrictions: frozenset[int] = frozenset(columns_by_restrictions.keys()) - {None}  # noqa

            # create starting geometry with building cropped off (if outside) and always-visible colums removed
            starting_geometry = unwrap_geom(space.geometry)
            if space.outside and space.level_id in buildings_by_level:
                starting_geometry = starting_geometry.difference(buildings_by_level[space.level_id])
            if None in columns_by_restrictions:
                starting_geometry = starting_geometry.difference(columns_by_restrictions[None])

            # start building the results
            from c3nav.mapdata.permissions import MapPermissionTaggedItem
            result: list[MapPermissionTaggedItem[PolygonSchema | MultiPolygonSchema]] = []

            # get all combinations of restrictions, any number of them, from n tuples down to single tuples to none#
            # yes this HAS TO get down to none, don't optimize, Area.recalculate_effecive_geometries depends on it
            for num_selected_restrictions in reversed(range(0, len(column_restrictions)+1)):
                for selected_restrictions in combinations(column_restrictions, num_selected_restrictions):
                    # now add (=subtract) all columns that have an access restriction that the user CAN'T see
                    # columns have inverted access restriction logic, hiding areas unless you have the permission
                    geometry = starting_geometry.difference(unary_union(tuple(
                        geom for access_restriction_id, geom in columns_by_restrictions.items()
                        if access_restriction_id not in selected_restrictions
                    )))
                    if geometry.is_empty:
                        # no geometry is the default
                        continue

                    result.append(MapPermissionTaggedItem(
                        value=geometry,
                        # here we add the access restrictions of the space back in
                        access_restrictions=frozenset(selected_restrictions) | space.effective_access_restrictions,
                    ))

            if not result:
                logger.warning(f"Space with no effective geometry at all: {space}")
                pass # todo: some nice warning here wrould be nice… in other places too

            space.cached_effective_geometries = result
            space.save()

    @classmethod
    def recalculate_simplified_geometries(cls):
        for space in cls.objects.all():
            results: list[MapPermissionTaggedItem[Polygon]] = []
            # we are caching resulting polygons by their area to find duplicates
            results_by_area: dict[float, list[MapPermissionTaggedItem[Polygon]]] = {}

            # go through all possible space geometries, starting with the least restricted ones
            for space_geometry, access_restriction_ids in reversed(space.cached_effective_geometries):
                # get the minimum rotated rectangle
                simplified_geometry = shape(space_geometry).minimum_rotated_rectangle

                # seach whether we had this same polygon as a result before
                for previous_result in results_by_area.get(simplified_geometry.area, []):
                    if (access_restriction_ids >= results_by_area
                            and previous_result.value.equals_exact(simplified_geometry, 1e-3)):
                        # if the found polygon matches and has a subset of restrictions, no need to store this one
                        break

                # create and store item
                item = MapPermissionTaggedItem(
                    value=simplified_geometry,
                    access_restrictions=access_restriction_ids
                )
                results_by_area.setdefault(simplified_geometry.area, []).append(item)
                results.append(item)

            # we need to reverse the list back to make the logic work
            space.cached_simplified_geometries = list(reversed(results))
            space.save()

    @cached_property
    def _simplified_geometries(self) -> MapPermissionGuardedTaggedValue[Polygon, GeometryCollection]:
        return MapPermissionGuardedTaggedValue(tuple(
            MapPermissionTaggedItem(
                value=shape(item.value.model_dump()),
                access_restrictions=item.access_restrictions
            )
            for item in self.cached_effective_geometries
        ), default=GeometryCollection())

    @property
    def effective_geometry(self) -> Polygon | MultiPolygon | GeometryCollection:
        if not self.can_access_geometry:
            return self._simplified_geometries.get()
        return super().effective_geometry


class Door(LevelGeometryMixin, AccessRestrictionMixin, models.Model):
    """
    A connection between two spaces
    """
    geometry = GeometryField('polygon')
    name = models.CharField(_('Name'), unique=True, max_length=50, blank=True, null=True)
    todo = models.BooleanField(default=False, verbose_name=_('todo'))

    class Meta:
        verbose_name = _('Door')
        verbose_name_plural = _('Doors')
        default_related_name = 'doors'

    def get_geojson_properties(self, *args, **kwargs) -> dict:
        result = super().get_geojson_properties(*args, **kwargs)
        if self.todo:
            result['color'] = "#FFFF00"
        return result

    @property
    def title(self):
        return ('*TODO* ' if self.todo else '') + (self.name or super().title)


class ItemWithValue:
    def __init__(self, obj, func):
        self.obj = obj
        self._func = func

    @cached_property
    def value(self):
        return self._func()


class AltitudeAreaPoint(NamedTuple):
    coordinates: tuple[float, float]
    altitude: float


class AltitudeArea(LevelGeometryMixin, models.Model):
    """
    An altitude area
    """
    geometry: MultiPolygon = GeometryField('multipolygon')
    altitude = models.DecimalField(_('altitude'), null=True, max_digits=6, decimal_places=2)
    points: Sequence[AltitudeAreaPoint] = SchemaField(schema=list[AltitudeAreaPoint], null=True)

    constraints = (
        CheckConstraint(check=(Q(points__isnull=True, altitude__isnull=False) |
                               Q(points__isnull=False, altitude__isnull=True)),
                        name="altitudearea_needs_precisely_one_of_altitude_or_points"),
    )

    class Meta:
        verbose_name = _('Altitude Area')
        verbose_name_plural = _('Altitude Areas')
        default_related_name = 'altitudeareas'
        ordering = ('altitude', )

    def __str__(self):
        return f'<Altitudearea #{self.pk} // Level #{self.level_id}, Bounds: {self.geometry.bounds}>'

    def get_altitudes(self, points):
        points = np.asanyarray(points).reshape((-1, 2))
        if self.altitude is not None:
            return np.full((points.shape[0],), fill_value=float(self.altitude))

        if len(self.points) == 1:
            raise ValueError

        max_altitude = max(p.altitude for p in self.points)
        min_altitude = min(p.altitude for p in self.points)

        if len(self.points) == 2:
            slope = np.array(self.points[1].coordinates) - np.array(self.points[0].coordinates)
            distances = (
                (np.sum(((points - np.array(self.points[0].coordinates)) * slope), axis=1)  # noqa
                / (slope ** 2).sum()).clip(0, 1)
            )
            altitudes = self.points[0].altitude + distances*(self.points[1].altitude-self.points[0].altitude)
        else:
            altitudes = RBFInterpolator(
                np.array([p.coordinates for p in self.points]),
                np.array([p.altitude for p in self.points])
            )(points)

        return np.clip(altitudes, a_min=min_altitude, a_max=max_altitude)

    @classmethod
    def recalculate(cls):
        from c3nav.mapdata.utils.altitudes import AltitudeAreaBuilder
        AltitudeAreaBuilder.build()