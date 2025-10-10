import logging
import time
from collections import namedtuple, defaultdict
from decimal import Decimal
from itertools import chain, combinations
from operator import attrgetter, itemgetter
from typing import Sequence, TypeAlias, Union, NamedTuple

import numpy as np
from django.core.exceptions import ObjectDoesNotExist
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import CheckConstraint, Q
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django_pydantic_field import SchemaField
from scipy.interpolate._rbfinterp import RBFInterpolator
from shapely import prepared, set_precision
from shapely.geometry import JOIN_STYLE, LineString, MultiLineString, MultiPolygon, Polygon, shape, GeometryCollection
from shapely.ops import unary_union

from c3nav.api.schema import PolygonSchema, MultiPolygonSchema
from c3nav.mapdata.fields import GeometryField, I18nField
from c3nav.mapdata.models import Level
from c3nav.mapdata.models.access import AccessRestrictionMixin, AccessRestrictionLogicMixin
from c3nav.mapdata.models.geometry.base import GeometryMixin, CachedEffectiveGeometryMixin
from c3nav.mapdata.models.locations import LocationTagTargetMixin
from c3nav.mapdata.permissions import MapPermissionTaggedItem, MapPermissionGuardedTaggedValue
from c3nav.mapdata.utils.cache.changes import changed_geometries
from c3nav.mapdata.utils.geometry import (assert_multilinestring, assert_multipolygon, unwrap_geom,
                                          cut_polygons_with_lines, snap_to_grid_and_fully_normalized,
                                          calculate_precision)
from c3nav.mapdata.utils.index import Index


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


RampConnectedTo = namedtuple('RampConnectedTo', ('area', 'intersections'))
type AltitudeAreaLookup = dict[Union[float, frozenset[AltitudeAreaPoint]], dict[Union[Polygon, MultiPolygon], int]]


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
        # collect location areas
        all_areas: list[Union[Polygon, MultiPolygon]] = []
        area_connections: list[tuple[int, int]] = []
        area_altitudes: dict[int, float] = {}
        level_areas: dict[int, set[int]] = {}
        level_ramps: dict[int, Union[Polygon, MultiPolygon, GeometryCollection]] = {}
        level_obstacles_areas: dict[int, list[Union[Polygon, MultiPolygon]]] = {}
        from c3nav.mapdata.models import AltitudeMarker
        level_altitudemarkers: dict[int, list[AltitudeMarker]] = {}

        space_areas: dict[int, set[int]] = defaultdict(set)  # all non-ramp altitude areas present in the given space
        levels = Level.objects.prefetch_related('buildings', 'doors', 'spaces', 'spaces__columns',
                                                'spaces__obstacles', 'spaces__lineobstacles', 'spaces__holes',
                                                'spaces__stairs', 'spaces__ramps',
                                                'spaces__altitudemarkers__groundaltitude')
        logger = logging.getLogger('c3nav')

        starttime = time.time()
        logger.info('- Collecting levels...')

        space_index = None

        for level in levels:
            logger.info(f'  - Level {level.short_label}')

            areas_collect: list[Union[Polygon, MultiPolygon]] = []
            obstacles_collect: list[Union[Polygon, MultiPolygon]] = []
            ramps_collect: list[Union[Polygon, MultiPolygon]] = []
            stairs_collect: list[Union[LineString, MultiLineString]] = []

            spaces_geom: dict[int, Union[Polygon, MultiPolygon]] = {}  # spaces by space id
            spaces_geom_prep: dict[int, prepared.PreparedGeometry] = {}

            buildings_geom = unary_union(tuple(unwrap_geom(building.geometry) for building in level.buildings.all()))

            space_index = Index()

            # how precise can be depends on how big our accessible geom is
            precision = calculate_precision(
                GeometryCollection(tuple(unwrap_geom(space.geometry) for space in level.spaces.all()))
            )
            logger.info(f'    - Precision: {precision}')

            # collect all accessible areas on this level
            altitudemarkers = []
            for space in level.spaces.all():
                this_area = space.geometry
                if space.outside:
                    this_area = this_area.difference(buildings_geom)
                this_area = this_area.difference(unary_union(
                    tuple(unwrap_geom(c.geometry) for c in space.columns.all() if c.access_restriction_id is None) +
                    tuple(unwrap_geom(h.geometry) for h in space.holes.all())),
                )

                if not this_area.area:
                    continue
                space_clip = this_area.buffer(precision, join_style=JOIN_STYLE.round, quad_segs=2)
                spaces_geom[space.pk] = space_clip
                spaces_geom_prep[space.pk] = prepared.prep(space_clip)
                space_index.insert(space.pk, space_clip)
                areas_collect.append(this_area)

                obstacles_collect.extend(
                    space_clip.intersection(geom)
                    for geom in chain(
                        (o.buffered_geometry for o in space.lineobstacles.all() if o.altitude == 0),
                        (unwrap_geom(o.geometry) for o in space.obstacles.all() if o.altitude == 0),
                    )
                )
                ramps_collect.append(space_clip.intersection(
                    unary_union(tuple(unwrap_geom(r.geometry) for r in space.ramps.all()))
                ))
                stairs_collect.append(space_clip.intersection(
                    unary_union(tuple(unwrap_geom(stair.geometry) for stair in space.stairs.all()))
                ))

                for altitudemarker in space.altitudemarkers.all():
                    if not this_area.intersects(unwrap_geom(altitudemarker.geometry)):
                        logger.error(
                            _('AltitudeMarker #%(marker_id)d in Space #%(space_id)d on Level %(level_label)s '
                              'is not placed in the space') % {'marker_id': altitudemarker.pk,
                                                               'space_id': space.pk,
                                                               'level_label': level.short_label})
                        continue
                    altitudemarkers.append(altitudemarker)

            altitudemarkers.sort(key=attrgetter("altitude"), reverse=True)

            level_altitudemarkers[level.pk] = altitudemarkers

            areas_collect.extend(unwrap_geom(door.geometry) for door in level.doors.all())

            areas_geom: Union[Polygon, MultiPolygon] = unary_union(areas_collect)  # noqa
            obstacles_geom: Union[Polygon, MultiPolygon] = unary_union(obstacles_collect)  # noqa
            ramps_geom: Union[Polygon, MultiPolygon] = unary_union(ramps_collect)  # noqa

            obstacles_geom_prep = prepared.prep(obstacles_geom.buffer(precision,
                                                                      join_style=JOIN_STYLE.round, quad_segs=2))

            # collect cuts on this level
            stair_ramp_cuts = unary_union(tuple(chain(
                chain.from_iterable(
                    chain((polygon.exterior, ), polygon.interiors)
                    for polygon in chain.from_iterable(assert_multipolygon(ramp) for ramp in chain(ramps_collect))
                ),
                chain.from_iterable(assert_multilinestring(s) for s in stairs_collect),
            )))
            stair_ramp_cuts_prep = prepared.prep(stair_ramp_cuts)

            # noinspection PyTypeChecker
            cuts = list(chain(
                assert_multilinestring(stair_ramp_cuts),
                assert_multilinestring(unary_union(tuple(chain.from_iterable(
                    chain((polygon.exterior, ), polygon.interiors)
                    for polygon in chain.from_iterable(assert_multipolygon(obstacle) for obstacle in obstacles_collect
                                                       if stair_ramp_cuts_prep.intersects(obstacle))
                ))))
            ))

            logger.info(f'    - Performing cuts...')
            cut_result = cut_polygons_with_lines(areas_geom, cuts)

            # divide cut result into accessible ares and obstacle areas
            logger.info(f'    - Processing cut result...')
            accessible_areas = []
            obstacle_areas = []
            for section in assert_multipolygon(cut_result):
                (obstacle_areas if obstacles_geom_prep.covers(section) else accessible_areas).append(section)

            logger.info(f'    - {len(accessible_areas)} accessible areas, {len(obstacle_areas)} obstacle areas')

            # import matplotlib.pyplot as plt
            # ax = plt.axes([0.05, 0.05, 0.85, 0.85])  # [left, bottom, width, height]
            # from shapely.plotting import plot_polygon, plot_line
            # plot_polygon(areas_geom, ax, add_points=False, facecolor="#00000020", edgecolor="#00000000")
            # for cut in cuts:
            #     plot_line(cut, ax, add_points=False, color="#ff0000", linewidth=1)
            # for area in accessible_areas:
            #     plot_polygon(area, ax, add_points=False, facecolor="#0000ff50", edgecolor="#0000ff")
            # for area in obstacle_areas:
            #     plot_polygon(area, ax, add_points=False, facecolor="#009950", edgecolor="#009900")
            # plt.show()

            # prepare stuff for the next few steps
            accessible_areas_prep = [prepared.prep(area) for area in accessible_areas]  # pragma: nobranch
            from_i = len(all_areas)

            # join obstacle areas into accessible areas if they are only touching one
            logger.info(f'    - Joining trivial obstacle areas...')
            while True:
                index = Index()
                for i, area in enumerate(accessible_areas):
                    index.insert(i, area)

                old_obstacle_areas = obstacle_areas
                obstacle_areas = []
                add: dict[int, list[Polygon]] = defaultdict(list)
                for area in old_obstacle_areas:
                    matches = {i for i in index.intersection(area)  # pragma: nobranch
                               if (accessible_areas_prep[i].touches(area) and
                                   assert_multilinestring(accessible_areas[i].intersection(area)))}
                    if len(matches) == 1:
                        add[next(iter(matches))].append(area)
                    else:
                        obstacle_areas.append(area)

                if not add:
                    break
                for i, area_add in add.items():
                    accessible_areas[i] = unary_union((accessible_areas[i], *area_add))
                    accessible_areas_prep[i] = prepared.prep(accessible_areas[i])

            del old_obstacle_areas
            del add

            logger.info(f'    - Preparing interpolation graph...')

            # assign areas to spaces
            for area_i, area in enumerate(accessible_areas):
                i = 0
                for space_id in space_index.intersection(area):
                    if spaces_geom_prep[space_id].intersects(area):
                        space_areas[space_id].add(from_i+area_i)
                        i += 1
                if not i:  # pragma: nocover
                    raise ValueError(f'- Area {area_i} {area.representative_point} {area.area}m² has no space')

            # determine connections between areas
            for i, area in enumerate(accessible_areas):
                for j in (index.intersection(area) - {i}):
                    if not accessible_areas_prep[i].touches(accessible_areas[j]):
                        continue
                    if not assert_multilinestring(accessible_areas[i].intersection(accessible_areas[j])):
                        continue
                    area_connections.append((i+from_i, j+from_i))

            # assign altitude markers to altitude areas
            logger.info(f'    - Assigning altitude markers...')
            for altitudemarker in altitudemarkers:
                matches = {i for i in index.intersection(altitudemarker.geometry)  # pragma: nocover
                           if accessible_areas_prep[i].intersects(unwrap_geom(altitudemarker.geometry))}
                if len(matches) == 1:
                    this_i = next(iter(matches))+from_i
                    if this_i not in area_altitudes:
                        area_altitudes[this_i] = float(altitudemarker.groundaltitude.altitude)
                    else:
                        logger.warning(
                            _(f'AltitudeMarker {altitudemarker.pk} {unwrap_geom(altitudemarker.geometry)} '
                              f'in Space #{altitudemarker.space_id} on Level {level.short_label} '
                              f'is on the same area as a different altitude marker.')
                        )
                elif len(matches) > 1:
                    logger.warning(
                        _(f'AltitudeMarker {altitudemarker.pk} {unwrap_geom(altitudemarker.geometry)} '
                          f'in Space #{altitudemarker.space_id} on Level {level.short_label} '
                          f'is placed between accessible areas {matches} '
                          f'{tuple(accessible_areas[i].representative_point() for i in matches)}')
                    )
                else:
                    logger.warning(
                        _(f'AltitudeMarker {altitudemarker.pk} {unwrap_geom(altitudemarker.geometry)}'
                          f'in Space #{altitudemarker.space_id} on Level {level.short_label} '
                          f'is on an obstacle in between altitude areas')
                    )

            level_areas[level.pk] = set(range(len(all_areas), len(all_areas) + len(accessible_areas)))
            all_areas.extend(accessible_areas)
            level_ramps[level.pk] = ramps_geom
            level_obstacles_areas[level.pk] = obstacle_areas

            #import matplotlib.pyplot as plt
            #ax = plt.axes([0.05, 0.05, 0.85, 0.85])  # [left, bottom, width, height]
            #from shapely.plotting import plot_polygon, plot_line
            #plot_polygon(areas_geom, ax, add_points=False, facecolor="#00000020", edgecolor="#00000000")
            #for cut in cuts:
            #    plot_line(cut, ax, add_points=False, color="#ff0000", linewidth=1)
            #for area in enumerate(accessible_areas, ):
            #    plot_polygon(area, ax, add_points=False, facecolor="#0000ff50", edgecolor="#0000ff")
            # plt.show()

        del space_index

        # interpolate altitudes
        logger.info('- Interpolating altitudes...')

        areas_without_altitude = {i for i in range(len(all_areas)) if i not in area_altitudes}  # pragma: nocover
        csgraph = np.zeros((len(all_areas), len(all_areas)), dtype=bool)
        for i, j in area_connections:
            csgraph[i, j] = True
            csgraph[j, i] = True

        logger.info(f'  - {len(areas_without_altitude)} areas without altitude before')

        repeat = True
        from scipy.sparse.csgraph._shortest_path import dijkstra
        while repeat:
            repeat = False
            # noinspection PyTupleAssignmentBalance
            distances, predecessors = dijkstra(csgraph, directed=False, return_predecessors=True, unweighted=True)
            np_areas_with_altitude = np.array(tuple(area_altitudes), dtype=np.uint32)
            relevant_distances = distances[np_areas_with_altitude[:, None], np_areas_with_altitude]
            # noinspection PyTypeChecker
            for from_i, to_i in np.argwhere(np.logical_and(relevant_distances < np.inf, relevant_distances > 1)):
                from_area = int(np_areas_with_altitude[from_i])
                to_area = int(np_areas_with_altitude[to_i])
                if area_altitudes[from_area] == area_altitudes[to_area]:
                    continue

                path = [to_area]
                while path[-1] != from_area:
                    path.append(predecessors[from_area, path[-1]])

                from_altitude = area_altitudes[from_area]
                to_altitude = area_altitudes[to_area]
                delta_altitude = (to_altitude-from_altitude)/(len(path)-1)

                if set(path[1:-1]).difference(areas_without_altitude):
                    continue

                for i, area_id in enumerate(reversed(path[1:-1]), start=1):
                    area_altitudes[area_id] = round(from_altitude + (delta_altitude * i), 2)
                    areas_without_altitude.discard(area_id)

                for from_area, to_area in zip(path[:-1], path[1:]):
                    csgraph[from_area, to_area] = False
                    csgraph[to_area, from_area] = False

                repeat = True

        logger.info(f'  - now {len(areas_without_altitude)} areas without altitude')

        old_area_connections = area_connections
        area_connections: dict[int, set[int]] = defaultdict(set)
        for i, j in old_area_connections:
            area_connections[i].add(j)
            area_connections[j].add(i)

        logger.info(f'- Assigning non-interpolateable areas...')

        # remaining areas: copy altitude from connected areas if any
        done = False
        while not done:
            done = True
            for i in tuple(areas_without_altitude):
                connected_with_altitude = tuple(j for j in area_connections[i] if j in area_altitudes)
                if connected_with_altitude:
                    area_altitudes[i] = area_altitudes[next(iter(connected_with_altitude))]
                    areas_without_altitude.discard(i)
                    done = False

        # remaining areas which belong to a room that has an altitude somewhere
        for space_i, contained_areas in space_areas.items():
            contained_areas_with_altitude = contained_areas - areas_without_altitude
            contained_areas_without_altitude = contained_areas - contained_areas_with_altitude
            if contained_areas_with_altitude and contained_areas_without_altitude:
                logger.info(f"  - {len(contained_areas_without_altitude)} areas still to assign in Space #{space_i}")
                altitude_areas = {}
                for i in contained_areas_with_altitude:
                    altitude_areas.setdefault(area_altitudes[i], []).append(all_areas[i])

                for altitude in altitude_areas.keys():
                    altitude_areas[altitude] = unary_union(altitude_areas[altitude])

                for i in contained_areas_without_altitude:
                    area = all_areas[i]
                    centroid = area.centroid
                    area_altitudes[i] = min(
                        altitude_areas.items(),
                        key=lambda a: (a[1].distance(area), a[1].centroid.distance(centroid), a[0])
                    )[0]

                areas_without_altitude.difference_update(contained_areas_without_altitude)

        logger.info(f'- Finalizing level altitude areas...')

        num_modified = 0
        num_deleted = 0
        num_created = 0

        del areas_without_altitude
        del np_areas_with_altitude

        for level in levels:
            logger.info(f'  - Level {level.short_label}')

            level_areas_without_altitude = set(level_areas[level.pk]) - set(area_altitudes)
            if level_areas_without_altitude:
                level_areas_with_altitude = set(level_areas[level.pk]) & set(area_altitudes)
                if level_areas_with_altitude:
                    for area_i in level_areas_without_altitude:
                        match_i = min(level_areas_with_altitude, key=lambda i: all_areas[i].distance(all_areas[area_i]))
                        area_altitudes[area_i] = area_altitudes[match_i]
                        logger.warning(
                            f"    - Altitude area {set_precision(all_areas[area_i].representative_point(), 0.001)} "
                            f"({all_areas[area_i].area:.2f}m²) in Level {level.short_label}, isn't connected to "
                            f"interpolated areas. Using altitude {area_altitudes[area_i]:.2f}m from closest area "
                            f"({all_areas[match_i].distance(all_areas[area_i]):.2f}m away)"
                        )
                else:
                    logger.warning(f"    - No altitudes on Level {level.short_label}, "
                                   f"defaulting to base_altitude for all areas on this level.")
                    for area_i in level_areas_without_altitude:
                        area_altitudes[area_i] = float(level.base_altitude)

            ramps_geom_prep = prepared.prep(level_ramps[level.pk].buffer(1e-14,
                                                                         join_style=JOIN_STYLE.round, quad_segs=2))

            logger.info(f'    - Processing ramps...')

            # detect ramps and non-ramps
            areas_by_altitude: dict[float, list[Union[Polygon, MultiPolygon]]] = defaultdict(list)
            ramp_areas: list[Union[Polygon, MultiPolygon]] = []
            for i in level_areas.get(level.pk, ()):
                if ramps_geom_prep.covers(all_areas[i]):
                    ramp_areas.append(all_areas[i])
                else:
                    areas_by_altitude[area_altitudes[i]].append(all_areas[i])

            this_areas: list[list[Union[Polygon, MultiPolygon]]] = []
            this_area_altitudes: list[float | frozenset[AltitudeAreaPoint]] = []
            for altitude, a in areas_by_altitude.items():
                this_area_altitudes.append(altitude)
                this_areas.append(a)

            # noinspection PyTypeChecker
            this_areas: list[Union[Polygon, MultiPolygon]] = [  # pragma: nobranch
                unary_union(geoms) for geoms in this_areas
            ]  # noqa
            this_areas_prep: list[prepared.PreparedGeometry] = [  #pragma: nobranch
                prepared.prep(geom) for geom in this_areas
            ]
            index = Index()
            for i, area in enumerate(this_areas):
                index.insert(i, area)

            # finalize ramps
            add_non_ramps: dict[float, list[Union[Polygon, MultiPolygon]]] = defaultdict(list)
            for i, ramp in enumerate(assert_multipolygon(unary_union(ramp_areas))):  # noqa
                points: dict[tuple[float, float], AltitudeAreaPoint] = {}
                for area_i in index.intersection(ramp):
                    if not this_areas_prep[area_i].intersects(ramp):
                        continue
                    for linestring in assert_multilinestring(this_areas[area_i].intersection(ramp)):  # noqa
                        points.update({  # pragma: nobranch
                            coords: AltitudeAreaPoint(coordinates=coords, altitude=float(this_area_altitudes[area_i]))
                            for coords in linestring.coords
                        })
                ramp_prep = prepared.prep(ramp)
                points.update({  # pragma: nobranch
                    marker.geometry.coords: AltitudeAreaPoint(coordinates=marker.geometry.coords[0],
                                                              altitude=float(marker.altitude))
                    for marker in level_altitudemarkers[level.pk]
                    if ramp_prep.intersects(unwrap_geom(marker.geometry))
                })
                # todo: make sure the points are all inside the ramp / touching the ramp
                unique_altitudes = set(p.altitude for p in points.values())
                if len(unique_altitudes) >= 2:
                    this_area_altitudes.append(frozenset(points.values()))
                    this_areas.append(ramp)
                elif unique_altitudes:
                    logger.warning(f'      - Ramp in {ramp.representative_point()} has only altitude '
                                   f'{next(iter(unique_altitudes))}, thus not a ramp!')
                    add_non_ramps[next(iter(unique_altitudes))].append(ramp)
                else:
                    logger.warning(f'      - Ramp in {ramp.representative_point()} has no altitude, defaulting to '
                                   f'level\'s base altitude!')
                    add_non_ramps[float(level.base_altitude)].append(ramp)

            # add add_non_ramps ramps
            for i, (altitude, geom) in enumerate(zip(this_area_altitudes, this_areas)):
                add_ramps = add_non_ramps.pop(altitude, None)
                if add_ramps:
                    this_areas[i] = unary_union((geom, *add_ramps))  # noqa

            for altitude, geoms in add_non_ramps.items():
                this_area_altitudes.append(altitude)
                this_areas.append(unary_union(geoms))  # noqa

            logger.info(f'    - Processing obstacles...')

            # assign remaining obstacle areas
            remaining_obstacle_areas = level_obstacles_areas[level.pk]
            done = False
            while not done and remaining_obstacle_areas:
                done = True

                index = Index()
                for i, area in enumerate(this_areas):
                    index.insert(i, area)

                this_areas_prep: list[prepared.PreparedGeometry] = [  # pragma: nobranch
                    prepared.prep(geom) for geom in this_areas
                ]

                new_remaining_obstacle_areas: list[Union[Polygon, MultiPolygon]] = []
                add_to_area: dict[int, list[Union[Polygon, MultiPolygon]]] = defaultdict(list)
                for obstacle in remaining_obstacle_areas:
                    matched_area: int | None = max((
                        area_i for area_i in index.intersection(obstacle)
                        if (this_areas_prep[area_i].intersects(obstacle)
                            and assert_multilinestring(this_areas[area_i].intersection(obstacle))  # noqa
                            and isinstance(this_area_altitudes[area_i], float))
                    ), key=lambda a_i: this_area_altitudes[a_i], default=None)  # todo: interpolate here
                    if matched_area is not None:
                        add_to_area[matched_area].append(obstacle)
                        done = False
                    else:
                        new_remaining_obstacle_areas.append(obstacle)

                remaining_obstacle_areas = new_remaining_obstacle_areas
                if add_to_area:
                    done = False
                    for area_i, add_geoms in add_to_area.items():
                        this_areas[area_i] = unary_union((this_areas[area_i], *add_geoms))  # noqa

            add_to_area: dict[int, list[Union[Polygon, MultiPolygon]]] = defaultdict(list)
            for obstacle in remaining_obstacle_areas:
                add_to_area[min(enumerate(this_areas),
                                key=lambda aa: aa[1].distance(obstacle))[0]].append(obstacle)

            for area_i, add_geoms in add_to_area.items():
                this_areas[area_i] = unary_union((this_areas[area_i], *add_geoms))  # noqa

            logger.info(f'    - Matching and saving...')

            # normalize
            if this_areas:
                this_areas, this_area_altitudes = zip(*(
                    (area, altitude) for area, altitude in (
                        (snap_to_grid_and_fully_normalized(area), altitude)
                        for area, altitude in zip(this_areas, this_area_altitudes)
                    ) if not area.is_empty
                ))
            this_areas: list[Union[Polygon, MultiPolygon]]

            logger.info(f"    - {len(this_areas)} altitude areas on this level")

            # find matching areas
            old_areas_lookup: AltitudeAreaLookup = defaultdict(dict)

            for area in level.altitudeareas.all():
                old_areas_lookup[
                    float(area.altitude) if area.altitude is not None else frozenset(area.points)
                ][snap_to_grid_and_fully_normalized(unwrap_geom(area.geometry))] = area

            done_areas = set()

            # find exactly matching areas
            for i, (geom, altitude) in enumerate(zip(this_areas, this_area_altitudes)):
                old_area = old_areas_lookup.get(altitude, {}).pop(geom, None)
                if old_area is not None:
                    done_areas.add(i)

            # find overlapping areas with same altitude
            for i, (geom, altitude) in enumerate(zip(this_areas, this_area_altitudes)):
                if i in done_areas:
                    continue
                geom_prep = prepared.prep(geom)
                match_geom, match_area = max(
                    [(geom, i) for geom, i in old_areas_lookup.get(altitude, {}).items() if geom_prep.overlaps(geom)],
                    key=lambda other: other[0].intersection(geom).area,
                    default=(None, None)
                )
                if match_geom is not None:
                    num_modified += 1
                    old_areas_lookup.get(altitude, {}).pop(match_geom, None)
                    match_area.geometry = geom
                    match_area.save()
                    done_areas.add(i)

            for altitudearea in chain.from_iterable(items.values() for items in old_areas_lookup.values()):
                altitudearea.delete()
                num_deleted += 1

            for i, (geom, altitude) in enumerate(zip(this_areas, this_area_altitudes)):
                if i in done_areas:
                    continue
                obj = cls(
                    level_id=level.pk,
                    geometry=geom,
                    altitude=altitude if isinstance(altitude, float) else None,
                    points=list(altitude) if not isinstance(altitude, float) else None,
                )
                obj.save()
                num_created += 1

        logger = logging.getLogger('c3nav')
        logger.info(_('%d altitude areas built (took %.2f seconds).') % (num_created + num_modified,
                                                                         time.time() - starttime))
        logger.info(_('%(num_modified)d modified, %(num_deleted)d deleted, %(num_created)d created.') %
                    {'num_modified': num_modified, 'num_deleted': num_deleted, 'num_created': num_created})
