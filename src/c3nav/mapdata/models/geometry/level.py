import logging
from collections import deque, namedtuple
from decimal import Decimal
from itertools import chain, combinations
from operator import attrgetter, itemgetter
from typing import Sequence, TYPE_CHECKING, TypeAlias

import numpy as np
from django.core.exceptions import ObjectDoesNotExist
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import CheckConstraint, Q
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django_pydantic_field import SchemaField
from pydantic import Field as APIField
from scipy.interpolate._rbfinterp import RBFInterpolator
from shapely import prepared
from shapely.affinity import scale
from shapely.geometry import JOIN_STYLE, LineString, MultiPolygon, Polygon, shape, GeometryCollection
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from c3nav.api.schema import BaseSchema, PolygonSchema, MultiPolygonSchema
from c3nav.mapdata.fields import GeometryField, I18nField
from c3nav.mapdata.models import Level
from c3nav.mapdata.models.access import AccessRestrictionMixin, AccessRestrictionLogicMixin
from c3nav.mapdata.models.geometry.base import GeometryMixin, CachedEffectiveGeometryMixin
from c3nav.mapdata.models.locations import LoadGroup, SpecificLocationGeometryTargetMixin
from c3nav.mapdata.utils.cache.changes import changed_geometries
from c3nav.mapdata.utils.geometry import (assert_multilinestring, assert_multipolygon, clean_cut_polygon,
                                          cut_polygon_with_line, unwrap_geom)

from c3nav.mapdata.permissions import MapPermissions, MapPermissionTaggedItem, MapPermissionGuardedTaggedValue


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


class Space(CachedEffectiveGeometryMixin, LevelGeometryMixin, SpecificLocationGeometryTargetMixin,
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
                print("Space with no effective geometry at all:", space)
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


class AltitudeAreaPoint(BaseSchema):
    coordinates: tuple[float, float] = APIField(
        example=[1, 2.5]
    )
    altitude: float


RampConnectedTo = namedtuple('RampConnectedTo', ('area', 'intersections'))


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
                (np.sum(((points - np.array(self.points[0].coordinates)) * slope), axis=1)
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
        # collect location areas
        all_areas: list[AltitudeArea] = []  # all non-ramp altitude areas of the entire map
        all_ramps: list[AltitudeArea] = []  # all ramp altitude areas of the entire map
        space_areas: dict[int, list[AltitudeArea]] = {}  # all non-ramp altitude areas present in the given space
        space_ramps: dict[int, list[AltitudeArea]] = {}  # all ramp altitude areas present in the given space
        spaces: dict[int, list[Space]] = {}  # all spaces by space id
        levels = Level.objects.prefetch_related('buildings', 'doors', 'spaces', 'spaces__columns',
                                                'spaces__obstacles', 'spaces__lineobstacles', 'spaces__holes',
                                                'spaces__stairs', 'spaces__ramps',
                                                'spaces__altitudemarkers__groundaltitude')
        logger = logging.getLogger('c3nav')

        for level in levels:
            areas = []  # all altitude areas on this level that aren't ramps
            ramps = []  # all altitude areas on this level that are ramps
            stairs = []  # all stairs on this level

            # collect all accessible areas on this level
            buildings_geom = unary_union(tuple(unwrap_geom(building.geometry) for building in level.buildings.all()))
            for space in level.spaces.all():
                spaces[space.pk] = space
                space.orig_geometry = space.geometry
                if space.outside:
                    space.geometry = space.geometry.difference(buildings_geom)
                space_accessible = space.geometry.difference(
                    unary_union(
                        tuple(unwrap_geom(c.geometry) for c in space.columns.all() if c.access_restriction_id is None) +
                        tuple(unwrap_geom(o.geometry) for o in space.obstacles.all() if o.altitude == 0) +
                        tuple(o.buffered_geometry for o in space.lineobstacles.all() if o.altitude == 0) +
                        tuple(unwrap_geom(h.geometry) for h in space.holes.all()))
                )

                space_ramps_geom = unary_union(tuple(unwrap_geom(r.geometry) for r in space.ramps.all()))
                areas.append(space_accessible.difference(space_ramps_geom))
                for geometry in assert_multipolygon(space_accessible.intersection(space_ramps_geom)):
                    ramp = AltitudeArea(geometry=geometry, level=level)
                    ramp.geometry_prep = prepared.prep(geometry)
                    ramp.space = space.pk
                    ramp.markers = []
                    ramps.append(ramp)
                    space_ramps.setdefault(space.pk, []).append(ramp)

            areas = tuple(orient(polygon) for polygon in assert_multipolygon(
                unary_union(areas+list(unwrap_geom(door.geometry) for door in level.doors.all()))
            ))

            # collect all stairs on this level
            for space in level.spaces.all():
                space_buffer = space.geometry.buffer(0.001, join_style=JOIN_STYLE.mitre)
                for stair in space.stairs.all():
                    stairs.extend(assert_multilinestring(
                        stair.geometry.intersection(space_buffer)
                    ))

            # divide areas using stairs
            for stair in stairs:
                areas = cut_polygon_with_line(areas, stair)

            # create altitudearea objects
            areas = [AltitudeArea(geometry=clean_cut_polygon(area), level=level)
                     for area in areas]

            # prepare area geometries
            for area in areas:
                area.geometry_prep = prepared.prep(area.geometry)

            # assign spaces to areas
            space_areas.update({space.pk: [] for space in level.spaces.all()})
            for area in areas:
                area.spaces = set()
                area.geometry_prep = prepared.prep(unwrap_geom(area.geometry))
                for space in level.spaces.all():
                    if area.geometry_prep.intersects(unwrap_geom(space.geometry)):
                        area.spaces.add(space.pk)
                        space_areas[space.pk].append(area)

            # give altitudes to areas
            for space in level.spaces.all():
                for altitudemarker in space.altitudemarkers.select_related('groundaltitude').all():
                    for area in space_areas[space.pk]:
                        if area.geometry_prep.contains(unwrap_geom(altitudemarker.geometry)):
                            area.altitude = altitudemarker.altitude
                            break
                    else:
                        for ramp in space_ramps[space.pk]:
                            if ramp.geometry_prep.contains(unwrap_geom(altitudemarker.geometry)):
                                ramp.markers.append(altitudemarker)
                                break
                        else:
                            logger.error(
                                _('AltitudeMarker #%(marker_id)d in Space #%(space_id)d on Level %(level_label)s '
                                  'is not placed in an accessible area') % {'marker_id': altitudemarker.pk,
                                                                            'space_id': space.pk,
                                                                            'level_label': level.short_label})

            # determine altitude area connections
            for area in areas:
                area.connected_to = []
            for area, other_area in combinations(areas, 2):
                if area.geometry_prep.intersects(other_area.geometry):
                    area.connected_to.append(other_area)
                    other_area.connected_to.append(area)

            # determine ramp connections
            for ramp in ramps:
                ramp.connected_to = []
                buffered = ramp.geometry.buffer(0.001)
                for area in areas:
                    if area.geometry_prep.intersects(buffered):
                        intersections = []
                        for area_polygon in assert_multipolygon(area.geometry):
                            for ring in chain([area_polygon.exterior], area_polygon.interiors):
                                if ring.intersects(buffered):
                                    intersections.append(ring.intersection(buffered))
                        ramp.connected_to.append(RampConnectedTo(area, intersections))
                num_altitudes = len(ramp.connected_to) + len(ramp.markers)
                if num_altitudes != 2:
                    if num_altitudes == 0:
                        logger.warning('A ramp in space #%d has no altitudes!' % ramp.space)
                    elif num_altitudes == 1:
                        logger.warning('A ramp in space #%d has only one altitude!' % ramp.space)

            # add areas to global areas
            all_areas.extend(areas)
            all_ramps.extend(ramps)

        # give temporary ids to all areas
        areas = all_areas
        ramps = all_ramps
        for i, area in enumerate(areas):
            area.tmpid = i
        for area in areas:
            area.connected_to = set(area.tmpid for area in area.connected_to)
        for space in space_areas.keys():
            space_areas[space] = set(area.tmpid for area in space_areas[space])
        areas_without_altitude = set(area.tmpid for area in areas if area.altitude is None)

        # interpolate altitudes
        logger.info('Interpolating altitudes...')

        areas_with_altitude = [i for i in range(len(areas)) if i not in areas_without_altitude]
        for i, tmpid in enumerate(areas_with_altitude):
            areas[tmpid].i = i

        csgraph = np.zeros((len(areas), len(areas)), dtype=bool)
        for area in areas:
            for connected_tmpid in area.connected_to:
                csgraph[area.tmpid, connected_tmpid] = True

        repeat = True

        from scipy.sparse.csgraph._shortest_path import dijkstra
        while repeat:
            repeat = False
            # noinspection PyTupleAssignmentBalance
            distances, predecessors = dijkstra(csgraph, directed=False, return_predecessors=True, unweighted=True)
            np_areas_with_altitude = np.array(areas_with_altitude, dtype=np.uint32)
            relevant_distances = distances[np_areas_with_altitude[:, None], np_areas_with_altitude]
            # noinspection PyTypeChecker
            for from_i, to_i in np.argwhere(np.logical_and(relevant_distances < np.inf, relevant_distances > 1)):
                from_area = areas[areas_with_altitude[from_i]]
                to_area = areas[areas_with_altitude[to_i]]
                if from_area.altitude == to_area.altitude:
                    continue

                path = [to_area.tmpid]
                while path[-1] != from_area.tmpid:
                    path.append(predecessors[from_area.tmpid, path[-1]])

                from_altitude = from_area.altitude
                delta_altitude = (to_area.altitude-from_altitude)/(len(path)-1)

                if set(path[1:-1]).difference(areas_without_altitude):
                    continue

                for i, tmpid in enumerate(reversed(path[1:-1]), start=1):
                    area = areas[tmpid]
                    area.altitude = Decimal(from_altitude+delta_altitude*i).quantize(Decimal('1.00'))
                    areas_without_altitude.discard(tmpid)
                    area.i = len(areas_with_altitude)
                    areas_with_altitude.append(tmpid)

                for from_tmpid, to_tmpid in zip(path[:-1], path[1:]):
                    csgraph[from_tmpid, to_tmpid] = False
                    csgraph[to_tmpid, from_tmpid] = False

                repeat = True

        # remaining areas: copy altitude from connected areas if any
        repeat = True
        while repeat:
            repeat = False
            for tmpid in tuple(areas_without_altitude):
                area = areas[tmpid]
                connected_with_altitude = area.connected_to-areas_without_altitude
                if connected_with_altitude:
                    area.altitude = areas[next(iter(connected_with_altitude))].altitude
                    areas_without_altitude.discard(tmpid)
                    repeat = True

        # remaining areas which belong to a room that has an altitude somewhere
        for contained_areas in space_areas.values():
            contained_areas_with_altitude = contained_areas - areas_without_altitude
            contained_areas_without_altitude = contained_areas - contained_areas_with_altitude
            if contained_areas_with_altitude and contained_areas_without_altitude:
                altitude_areas = {}
                for tmpid in contained_areas_with_altitude:
                    area = areas[tmpid]
                    altitude_areas.setdefault(area.altitude, []).append(area.geometry)

                for altitude in altitude_areas.keys():
                    altitude_areas[altitude] = unary_union(altitude_areas[altitude])
                for tmpid in contained_areas_without_altitude:
                    area = areas[tmpid]
                    area.altitude = min(altitude_areas.items(), key=lambda aa: aa[1].distance(area.geometry))[0]
                areas_without_altitude.difference_update(contained_areas_without_altitude)

        # last fallback: level base_altitude
        for tmpid in areas_without_altitude:
            area = areas[tmpid]
            area.altitude = area.level.base_altitude

        # prepare per-level operations
        level_areas = {}
        for area in areas:
            level_areas.setdefault(area.level, set()).add(area.tmpid)

        # make sure there is only one altitude area per altitude per level
        for level in levels:
            areas_by_altitude = {}
            for tmpid in level_areas.get(level, []):
                area = areas[tmpid]
                areas_by_altitude.setdefault(area.altitude, []).append(area.geometry)

            level_areas[level] = [AltitudeArea(level=level, geometry=unary_union(geometries), altitude=altitude)
                                  for altitude, geometries in areas_by_altitude.items()]

        # renumber joined areas
        areas = list(chain(*(a for a in level_areas.values())))
        for i, area in enumerate(areas):
            area.tmpid = i

        # finalize ramps
        for ramp in ramps:
            if not ramp.connected_to:
                for area in space_areas[ramp.space]:
                    ramp.altitude = areas[area].altitude
                    break
                else:
                    ramp.altitude = ramp.level.base_altitude
                continue

            if len(ramp.connected_to) == 1:
                ramp.altitude = ramp.connected_to[0].area.altitude
                continue

            # collecting this as a dict to ensure that there are no duplicate coordinates
            points = {}
            for connected_to in ramp.connected_to:
                for intersection in connected_to.intersections:
                    for linestring in assert_multilinestring(intersection):
                        points.update({
                            coords: AltitudeAreaPoint(coordinates=coords,
                                                      altitude=float(connected_to.area.altitude))
                            for coords in linestring.coords
                        })
            points.update({
                marker.geometry.coords: AltitudeAreaPoint(coordinates=marker.geometry.coords,
                                                          altitude=float(marker.altitude))
                for marker in ramp.markers
            })
            ramp.points = list(points.values())

            ramp.tmpid = len(areas)
            areas.append(ramp)
            level_areas[ramp.level].append(ramp)

        #
        # we have altitude areas, but they only cover accessible space for now
        # however, we need obstacles to be part of altitude areas too.
        # this is where we do that.
        #
        for level in levels:
            logger.info('Assign remaining space (%s)...' % level.title)
            for space in level.spaces.all():
                space.geometry = space.orig_geometry

            buildings_geom = unary_union(tuple(unwrap_geom(b.geometry) for b in level.buildings.all()))
            doors_geom = unary_union(tuple(unwrap_geom(d.geometry) for d in level.doors.all()))
            space_geom = unary_union(tuple((unwrap_geom(s.geometry)
                                            if not s.outside
                                            else s.geometry.difference(buildings_geom))
                                           for s in level.spaces.all()))

            # accessible area on this level is doors + spaces - holes
            accessible_area = unary_union((doors_geom, space_geom))
            for space in level.spaces.all():
                accessible_area = accessible_area.difference(space.geometry.intersection(
                    unary_union(tuple(unwrap_geom(h.geometry) for h in space.holes.all()))
                ))

            # areas mean altitude areas (including ramps) here
            our_areas = level_areas.get(level, [])
            for area in our_areas:
                area.orig_geometry = area.geometry
                area.orig_geometry_prep = prepared.prep(area.geometry)
                area.polygons_to_add = deque()

            stairs = []
            for space in level.spaces.all():
                space_geom = space.geometry
                if space.outside:
                    space_geom = space_geom.difference(buildings_geom)
                space_geom_prep = prepared.prep(unwrap_geom(space_geom))
                holes_geom = unary_union(tuple(unwrap_geom(h.geometry) for h in space.holes.all()))

                # remaining_space means remaining space (=obstacles) that still needs to be added to altitude areas
                remaining_space = (
                    tuple(unwrap_geom(o.geometry) for o in space.obstacles.all()) +
                    tuple(o.buffered_geometry for o in space.lineobstacles.all())
                )
                # make sure to remove everything outside the space the obstacles are in as well as holes
                remaining_space = tuple(g.intersection(unwrap_geom(space_geom)).difference(holes_geom)
                                        for g in remaining_space
                                        if space_geom_prep.intersects(unwrap_geom(g)))
                # we need this to be a list of simple normal polygons
                remaining_space = tuple(chain(*(
                    assert_multipolygon(g) for g in remaining_space if not g.is_empty
                )))
                if not remaining_space:
                    # if there are no remaining spaces? great, we're done here.
                    continue

                cuts = []
                for cut in chain(*(assert_multilinestring(stair.geometry) for stair in space.stairs.all()),
                                 (ramp.geometry.exterior for ramp in space.ramps.all())):
                    for coord1, coord2 in zip(tuple(cut.coords)[:-1], tuple(cut.coords)[1:]):
                        line = space_geom.intersection(LineString([coord1, coord2]))
                        if line.is_empty:
                            continue
                        factor = (line.length + 2) / line.length
                        line = scale(line, xfact=factor, yfact=factor)
                        centroid = line.centroid
                        line = min(assert_multilinestring(space_geom.intersection(line)),
                                   key=lambda line_: line_.centroid.distance(centroid), default=None)
                        cuts.append(scale(line, xfact=1.01, yfact=1.01))

                remaining_space = tuple(
                    orient(polygon) for polygon in remaining_space
                )

                for cut in cuts:
                    remaining_space = tuple(chain(*(cut_polygon_with_line(geom, cut)
                                                    for geom in remaining_space)))
                remaining_space = MultiPolygon(remaining_space)

                for polygon in assert_multipolygon(remaining_space):
                    polygon = clean_cut_polygon(polygon).buffer(0)
                    buffered = polygon.buffer(0.001)

                    center = polygon.centroid
                    touches = tuple(ItemWithValue(area, lambda: buffered.intersection(area.orig_geometry).area)
                                    for area in our_areas
                                    if area.orig_geometry_prep.intersects(buffered))
                    if len(touches) == 1:
                        area = touches[0].obj
                    elif touches:
                        min_touches = sum((t.value for t in touches), 0)/4
                        area = max(touches, key=lambda item: (
                            item.value > min_touches,
                            item.obj.points is not None,
                            (max(p.altitude for p in item.obj.points)
                             if item.obj.altitude is None else item.obj.altitude),
                            item.value
                        )).obj
                    else:
                        area = min(our_areas,
                                   key=lambda a: a.orig_geometry.distance(center)-(0 if a.points is None else 0.6))
                    area.polygons_to_add.append(polygon)

            for i_area, area in enumerate(our_areas):
                if area.polygons_to_add:
                    area.geometry = unary_union((area.geometry.buffer(0), *area.polygons_to_add))
                del area.polygons_to_add

        for level in levels:
            level_areas[level] = set(area.tmpid for area in level_areas.get(level, []))

        # save to database
        areas_to_save = set(range(len(areas)))

        all_candidates = AltitudeArea.objects.select_related('level')
        for candidate in all_candidates:
            candidate.area = candidate.geometry.area
            candidate.geometry_prep = prepared.prep(unwrap_geom(candidate.geometry))
        all_candidates = sorted(all_candidates, key=attrgetter('area'), reverse=True)

        num_modified = 0
        num_deleted = 0
        num_created = 0

        field = AltitudeArea._meta.get_field('geometry')

        for candidate in all_candidates:
            new_area = None

            if candidate.points is None:
                for tmpid in level_areas.get(candidate.level, set()):
                    area = areas[tmpid]
                    if area.points is None and area.altitude == candidate.altitude:
                        new_area = area
                        break
            else:
                potential_areas = [areas[tmpid] for tmpid in level_areas.get(candidate.level, set())]
                potential_areas = [area for area in potential_areas
                                   if ((candidate.altitude, set(p.altitude for p in (candidate.points or ()))) ==
                                       (area.altitude, set(p.altitude for p in (area.points or ()))))]
                potential_areas = [(area, area.geometry.intersection(unwrap_geom(candidate.geometry)).area)
                                   for area in potential_areas
                                   if candidate.geometry_prep.intersects(unwrap_geom(area.geometry))]
                if potential_areas:
                    new_area = max(potential_areas, key=itemgetter(1))[0]

            if new_area is None:
                candidate.delete()
                num_deleted += 1
                continue

            if not field.get_final_value(new_area.geometry).equals_exact(unwrap_geom(candidate.geometry), 0.00001):
                num_modified += 1

            candidate.geometry = new_area.geometry
            candidate.altitude = new_area.altitude
            candidate.points = new_area.points
            candidate.save()
            areas_to_save.discard(new_area.tmpid)
            level_areas[new_area.level].discard(new_area.tmpid)

        for tmpid in areas_to_save:
            num_created += 1
            areas[tmpid].save()

        logger = logging.getLogger('c3nav')
        logger.info(_('%d altitude areas built.') % len(areas))
        logger.info(_('%(num_modified)d modified, %(num_deleted)d deleted, %(num_created)d created.') %
                    {'num_modified': num_modified, 'num_deleted': num_deleted, 'num_created': num_created})
