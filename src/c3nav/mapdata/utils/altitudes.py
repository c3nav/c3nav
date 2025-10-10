from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from itertools import chain
from operator import attrgetter
from typing import Union

import numpy as np
from django.utils.translation import gettext_lazy as _
from shapely import prepared, set_precision
from shapely.geometry import JOIN_STYLE, LineString, MultiLineString, MultiPolygon, Polygon, GeometryCollection
from shapely.ops import unary_union

from c3nav.mapdata.models import Level, AltitudeMarker
from c3nav.mapdata.models.geometry.level import AltitudeAreaPoint, AltitudeArea
from c3nav.mapdata.utils.geometry import (assert_multilinestring, assert_multipolygon, unwrap_geom,
                                          cut_polygons_with_lines, snap_to_grid_and_fully_normalized,
                                          calculate_precision)
from c3nav.mapdata.utils.index import Index

logger = logging.getLogger('c3nav')


type AltitudeAreaLookup = dict[Union[float, frozenset[AltitudeAreaPoint]], dict[Union[Polygon, MultiPolygon], int]]


@dataclass
class CreationResult:
    modified: int = 0
    created: int = 0
    deleted: int = 0

    def __add__(self, other: CreationResult):
        return CreationResult(
            modified=self.modified + other.modified,
            created=self.created + other.created,
            deleted=self.deleted + other.deleted,
        )


@dataclass
class AltitudeAreaBuilderLevel:
    areas: set[int]
    ramps: Union[Polygon, MultiPolygon, GeometryCollection]
    obstacles_areas: list[Union[Polygon, MultiPolygon]]
    altitudemarkers: list[AltitudeMarker]


class AltitudeAreaBuilder:
    def __init__(self):
        self.all_areas: list[Union[Polygon, MultiPolygon]] = []
        self.area_connections: list[tuple[int, int]] = []
        self.area_altitudes: dict[int, float] = {}
        self.levels: dict[int, AltitudeAreaBuilderLevel] = {}

        self.space_areas: dict[int, set[int]] = defaultdict(set)  # all non-ramp altitude areas present in the given space

    @classmethod
    def build(cls):
        cls()._build()

    def _collect_level(self, level: Level):
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
        from_i = len(self.all_areas)

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
                    self.space_areas[space_id].add(from_i+area_i)
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
                self.area_connections.append((i+from_i, j+from_i))

        # assign altitude markers to altitude areas
        logger.info(f'    - Assigning altitude markers...')
        for altitudemarker in altitudemarkers:
            matches = {i for i in index.intersection(altitudemarker.geometry)  # pragma: nocover
                       if accessible_areas_prep[i].intersects(unwrap_geom(altitudemarker.geometry))}
            if len(matches) == 1:
                this_i = next(iter(matches))+from_i
                if this_i not in self.area_altitudes:
                    self.area_altitudes[this_i] = float(altitudemarker.groundaltitude.altitude)
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

        self.levels[level.pk] = AltitudeAreaBuilderLevel(
            areas=set(range(len(self.all_areas), len(self.all_areas) + len(accessible_areas))),
            ramps=ramps_geom,
            obstacles_areas=obstacle_areas,
            altitudemarkers=altitudemarkers,
        )
        self.all_areas.extend(accessible_areas)

        #import matplotlib.pyplot as plt
        #ax = plt.axes([0.05, 0.05, 0.85, 0.85])  # [left, bottom, width, height]
        #from shapely.plotting import plot_polygon, plot_line
        #plot_polygon(areas_geom, ax, add_points=False, facecolor="#00000020", edgecolor="#00000000")
        #for cut in cuts:
        #    plot_line(cut, ax, add_points=False, color="#ff0000", linewidth=1)
        #for area in enumerate(accessible_areas, ):
        #    plot_polygon(area, ax, add_points=False, facecolor="#0000ff50", edgecolor="#0000ff")
        # plt.show()

    def _interpolate_areas(self):
        # interpolate altitudes
        logger.info('- Interpolating altitudes...')

        areas_without_altitude = {i for i in range(len(self.all_areas)) if i not in self.area_altitudes}  # pragma: nocover
        csgraph = np.zeros((len(self.all_areas), len(self.all_areas)), dtype=bool)
        for i, j in self.area_connections:
            csgraph[i, j] = True
            csgraph[j, i] = True

        logger.info(f'  - {len(areas_without_altitude)} areas without altitude before')

        repeat = True
        from scipy.sparse.csgraph._shortest_path import dijkstra
        while repeat:
            repeat = False
            # noinspection PyTupleAssignmentBalance
            distances, predecessors = dijkstra(csgraph, directed=False, return_predecessors=True, unweighted=True)
            np_areas_with_altitude = np.array(tuple(self.area_altitudes), dtype=np.uint32)
            relevant_distances = distances[np_areas_with_altitude[:, None], np_areas_with_altitude]
            # noinspection PyTypeChecker
            for from_i, to_i in np.argwhere(np.logical_and(relevant_distances < np.inf, relevant_distances > 1)):
                from_area = int(np_areas_with_altitude[from_i])
                to_area = int(np_areas_with_altitude[to_i])
                if self.area_altitudes[from_area] == self.area_altitudes[to_area]:
                    continue

                path = [to_area]
                while path[-1] != from_area:
                    path.append(predecessors[from_area, path[-1]])

                from_altitude = self.area_altitudes[from_area]
                to_altitude = self.area_altitudes[to_area]
                delta_altitude = (to_altitude-from_altitude)/(len(path)-1)

                if set(path[1:-1]).difference(areas_without_altitude):
                    continue

                for i, area_id in enumerate(reversed(path[1:-1]), start=1):
                    self.area_altitudes[area_id] = round(from_altitude + (delta_altitude * i), 2)
                    areas_without_altitude.discard(area_id)

                for from_area, to_area in zip(path[:-1], path[1:]):
                    csgraph[from_area, to_area] = False
                    csgraph[to_area, from_area] = False

                repeat = True

        logger.info(f'  - now {len(areas_without_altitude)} areas without altitude')

        old_area_connections = self.area_connections
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
                connected_with_altitude = tuple(j for j in area_connections[i] if j in self.area_altitudes)
                if connected_with_altitude:
                    self.area_altitudes[i] = self.area_altitudes[next(iter(connected_with_altitude))]
                    areas_without_altitude.discard(i)
                    done = False

        # remaining areas which belong to a room that has an altitude somewhere
        for space_i, contained_areas in self.space_areas.items():
            contained_areas_with_altitude = contained_areas - areas_without_altitude
            contained_areas_without_altitude = contained_areas - contained_areas_with_altitude
            if contained_areas_with_altitude and contained_areas_without_altitude:
                logger.info(f"  - {len(contained_areas_without_altitude)} areas still to assign in Space #{space_i}")
                altitude_areas = {}
                for i in contained_areas_with_altitude:
                    altitude_areas.setdefault(self.area_altitudes[i], []).append(self.all_areas[i])

                for altitude in altitude_areas.keys():
                    altitude_areas[altitude] = unary_union(altitude_areas[altitude])

                for i in contained_areas_without_altitude:
                    area = self.all_areas[i]
                    centroid = area.centroid
                    self.area_altitudes[i] = min(
                        altitude_areas.items(),
                        key=lambda a: (a[1].distance(area), a[1].centroid.distance(centroid), a[0])
                    )[0]

                areas_without_altitude.difference_update(contained_areas_without_altitude)

    def _finalize_level(self, level: Level) -> CreationResult:
        logger.info(f'  - Level {level.short_label}')

        builder_level = self.levels[level.pk]

        level_areas_without_altitude = set(builder_level.areas) - set(self.area_altitudes)
        if level_areas_without_altitude:
            level_areas_with_altitude = set(builder_level.areas) & set(self.area_altitudes)
            if level_areas_with_altitude:
                for area_i in level_areas_without_altitude:
                    match_i = min(level_areas_with_altitude, key=lambda i: self.all_areas[i].distance(self.all_areas[area_i]))
                    self.area_altitudes[area_i] = self.area_altitudes[match_i]
                    logger.warning(
                        f"    - Altitude area {set_precision(self.all_areas[area_i].representative_point(), 0.001)} "
                        f"({self.all_areas[area_i].area:.2f}m²) in Level {level.short_label}, isn't connected to "
                        f"interpolated areas. Using altitude {self.area_altitudes[area_i]:.2f}m from closest area "
                        f"({self.all_areas[match_i].distance(self.all_areas[area_i]):.2f}m away)"
                    )
            else:
                logger.warning(f"    - No altitudes on Level {level.short_label}, "
                               f"defaulting to base_altitude for all areas on this level.")
                for area_i in level_areas_without_altitude:
                    self.area_altitudes[area_i] = float(level.base_altitude)

        ramps_geom_prep = prepared.prep(builder_level.ramps.buffer(1e-14, join_style=JOIN_STYLE.round, quad_segs=2))

        logger.info(f'    - Processing ramps...')

        # detect ramps and non-ramps
        areas_by_altitude: dict[float, list[Union[Polygon, MultiPolygon]]] = defaultdict(list)
        ramp_areas: list[Union[Polygon, MultiPolygon]] = []
        for i in builder_level.areas:
            if ramps_geom_prep.covers(self.all_areas[i]):
                ramp_areas.append(self.all_areas[i])
            else:
                areas_by_altitude[self.area_altitudes[i]].append(self.all_areas[i])

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
                for marker in builder_level.altitudemarkers
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
        remaining_obstacle_areas = builder_level.obstacles_areas
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

        result = CreationResult()

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
                result.modified += 1
                old_areas_lookup.get(altitude, {}).pop(match_geom, None)
                match_area.geometry = geom
                match_area.save()
                done_areas.add(i)

        for altitudearea in chain.from_iterable(items.values() for items in old_areas_lookup.values()):
            altitudearea.delete()
            result.deleted += 1

        for i, (geom, altitude) in enumerate(zip(this_areas, this_area_altitudes)):
            if i in done_areas:
                continue
            obj = AltitudeArea(
                level_id=level.pk,
                geometry=geom,
                altitude=altitude if isinstance(altitude, float) else None,
                points=list(altitude) if not isinstance(altitude, float) else None,
            )
            obj.save()
            result.created += 1

        return result

    def _build(self):
        # collect location areas
        """all_areas: list[Union[Polygon, MultiPolygon]] = []
        area_connections: list[tuple[int, int]] = []
        area_altitudes: dict[int, float] = {}
        level_areas: dict[int, set[int]] = {}
        level_ramps: dict[int, Union[Polygon, MultiPolygon, GeometryCollection]] = {}
        level_obstacles_areas: dict[int, list[Union[Polygon, MultiPolygon]]] = {}
        from c3nav.mapdata.models import AltitudeMarker
        level_altitudemarkers: dict[int, list[AltitudeMarker]] = {}

        space_areas: dict[int, set[int]] = defaultdict(set)  # all non-ramp altitude areas present in the given space
        """
        levels = Level.objects.prefetch_related('buildings', 'doors', 'spaces', 'spaces__columns',
                                                'spaces__obstacles', 'spaces__lineobstacles', 'spaces__holes',
                                                'spaces__stairs', 'spaces__ramps',
                                                'spaces__altitudemarkers__groundaltitude')

        starttime = time.time()
        logger.info('- Collecting levels...')

        for level in levels:
            self._collect_level(level)

        self._interpolate_areas()

        logger.info(f'- Finalizing level altitude areas...')

        result = CreationResult()

        for level in levels:
            result += self._finalize_level(level)

        logger.info(_('%d altitude areas built (took %.2f seconds).') % (result.created + result.modified,
                                                                         time.time() - starttime))
        logger.info(_('%(num_modified)d modified, %(num_deleted)d deleted, %(num_created)d created.') %
                    {'num_modified': result.modified, 'num_deleted': result.deleted, 'num_created': result.created})
