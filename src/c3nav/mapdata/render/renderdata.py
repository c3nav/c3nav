import operator
import os
import pickle
import threading
from collections import deque
from itertools import chain

import numpy as np
from django.conf import settings
from scipy.interpolate import NearestNDInterpolator
from shapely import prepared
from shapely.geometry import GeometryCollection
from shapely.ops import unary_union

from c3nav.mapdata.models import Level, MapUpdate, Source
from c3nav.mapdata.render.geometry import AltitudeAreaGeometries, LevelGeometries
from c3nav.mapdata.utils.cache import AccessRestrictionAffected, MapHistory
from c3nav.mapdata.utils.cache.package import CachePackage
from c3nav.mapdata.utils.geometry import get_rings

empty_geometry_collection = GeometryCollection()


class Cropper:
    def __init__(self, geometry=None):
        self.geometry = geometry
        self.geometry_prep = None if geometry is None else prepared.prep(geometry)

    def intersection(self, other):
        if self.geometry is None:
            return other
        if self.geometry_prep.intersects(other):
            return self.geometry.intersection(other)
        return empty_geometry_collection


class LevelRenderData:
    """
    Renderdata for a level to display.
    This contains multiple LevelGeometries instances because you might to look through holes onto lower levels.
    """
    def __init__(self):
        self.levels = []
        self.base_altitude = None
        self.lowest_important_level = None
        self.darken_area = None

    @staticmethod
    def rebuild():
        levels = tuple(Level.objects.prefetch_related('altitudeareas', 'buildings', 'doors', 'spaces',
                                                      'spaces__holes', 'spaces__areas', 'spaces__columns',
                                                      'spaces__obstacles', 'spaces__lineobstacles',
                                                      'spaces__groups', 'spaces__ramps'))

        package = CachePackage(bounds=tuple(chain(*Source.max_bounds())))

        # first pass in reverse to collect some data that we need later
        single_level_geoms = {}
        interpolators = {}
        last_interpolator = None
        altitudeareas_above = []
        for level in reversed(levels):
            single_level_geoms[level.pk] = LevelGeometries.build_for_level(level, altitudeareas_above)

            # ignore intermediate levels in this pass
            if level.on_top_of_id is not None:
                altitudeareas_above.extend(single_level_geoms[level.pk].altitudeareas)
                altitudeareas_above.sort(key=operator.attrgetter('altitude'))
                continue

            # create interpolator to create the pieces that fit multiple layers together
            if last_interpolator is not None:
                interpolators[level.pk] = last_interpolator

            coords = deque()
            values = deque()
            for area in single_level_geoms[level.pk].altitudeareas:
                new_coords = np.vstack(tuple(np.array(ring.coords) for ring in get_rings(area.geometry)))
                coords.append(new_coords)
                values.append(np.full((new_coords.shape[0], 1), fill_value=area.altitude))

            if coords:
                last_interpolator = NearestNDInterpolator(np.vstack(coords), np.vstack(values))
            else:
                last_interpolator = NearestNDInterpolator(np.array([[0, 0]]), np.array([float(level.base_altitude)]))

        for i, level in enumerate(levels):
            if level.on_top_of_id is not None:
                continue

            map_history = MapHistory.open_level(level.pk, 'base')

            sublevels = tuple(sublevel for sublevel in levels
                              if sublevel.on_top_of_id == level.pk or sublevel.base_altitude <= level.base_altitude)

            level_crop_to = {}

            # choose a crop area for each level. non-intermediate levels (not on_top_of) below the one that we are
            # currently rendering will be cropped to only render content that is visible through holes indoors in the
            # levels above them.
            crop_to = None
            primary_level_count = 0
            main_level_passed = 0
            lowest_important_level = None
            for sublevel in reversed(sublevels):
                geoms = single_level_geoms[sublevel.pk]

                if geoms.holes is not None:
                    primary_level_count += 1

                # get lowest intermediate level directly below main level

                if not main_level_passed:
                    if geoms.pk == level.pk:
                        main_level_passed = 1
                else:
                    if not sublevel.on_top_of_id:
                        main_level_passed += 1
                if main_level_passed < 2:
                    lowest_important_level = sublevel

                # set crop area if we area on the second primary layer from top or below
                level_crop_to[sublevel.pk] = Cropper(crop_to if primary_level_count > 1 else None)

                if geoms.holes is not None:
                    if crop_to is None:
                        crop_to = geoms.holes
                    else:
                        crop_to = crop_to.intersection(geoms.holes)

                    if crop_to.is_empty:
                        break

            render_data = LevelRenderData()
            render_data.base_altitude = level.base_altitude
            render_data.lowest_important_level = lowest_important_level.pk
            access_restriction_affected = {}

            # go through sublevels, get their level geometries and crop them
            lowest_important_level_passed = False
            for sublevel in sublevels:
                try:
                    crop_to = level_crop_to[sublevel.pk]
                except KeyError:
                    break

                old_geoms = single_level_geoms[sublevel.pk]

                if render_data.lowest_important_level == sublevel.pk:
                    lowest_important_level_passed = True

                if old_geoms.holes and render_data.darken_area is None and lowest_important_level_passed:
                    render_data.darken_area = old_geoms.holes

                if crop_to.geometry is not None:
                    map_history.composite(MapHistory.open_level(sublevel.pk, 'base'), crop_to.geometry)
                elif level.pk != sublevel.pk:
                    map_history.composite(MapHistory.open_level(sublevel.pk, 'base'), None)

                new_geoms = LevelGeometries()
                new_geoms.buildings = crop_to.intersection(old_geoms.buildings)
                new_geoms.doors = crop_to.intersection(old_geoms.doors)
                new_geoms.walls = crop_to.intersection(old_geoms.walls)
                new_geoms.all_walls = crop_to.intersection(old_geoms.all_walls)
                new_geoms.short_walls = tuple((altitude, geom) for altitude, geom in tuple(
                    (altitude, crop_to.intersection(geom))
                    for altitude, geom in old_geoms.short_walls
                ) if not geom.is_empty)

                for altitudearea in old_geoms.altitudeareas:
                    new_geometry = crop_to.intersection(altitudearea.geometry)
                    if new_geometry.is_empty:
                        continue
                    new_geometry_prep = prepared.prep(new_geometry)

                    new_altitudearea = AltitudeAreaGeometries()
                    new_altitudearea.geometry = new_geometry
                    new_altitudearea.altitude = altitudearea.altitude
                    new_altitudearea.altitude2 = altitudearea.altitude2
                    new_altitudearea.point1 = altitudearea.point1
                    new_altitudearea.point2 = altitudearea.point2

                    new_colors = {}
                    for color, areas in altitudearea.colors.items():
                        new_areas = {}
                        for access_restriction, area in areas.items():
                            if not new_geometry_prep.intersects(area):
                                continue
                            new_area = new_geometry.intersection(area)
                            if not new_area.is_empty:
                                new_areas[access_restriction] = new_area
                        if new_areas:
                            new_colors[color] = new_areas
                    new_altitudearea.colors = new_colors

                    new_altitudearea.obstacles = {key: tuple(new_geometry.intersection(obstacle)
                                                             for obstacle in height_obstacles
                                                             if new_geometry_prep.intersects(obstacle))
                                                  for key, height_obstacles in altitudearea.obstacles.items()}
                    new_altitudearea.obstacles = {height: height_obstacles
                                                  for height, height_obstacles in new_altitudearea.obstacles.items()
                                                  if height_obstacles}

                    new_geoms.altitudeareas.append(new_altitudearea)

                if new_geoms.walls.is_empty and not new_geoms.altitudeareas:
                    continue

                new_geoms.ramps = tuple(
                    ramp for ramp in (crop_to.intersection(ramp) for ramp in old_geoms.ramps)
                    if not ramp.is_empty
                )

                new_geoms.heightareas = tuple(
                    (area, height) for area, height in ((crop_to.intersection(area), height)
                                                        for area, height in old_geoms.heightareas)
                    if not area.is_empty
                )

                new_geoms.affected_area = unary_union((
                    *(altitudearea.geometry for altitudearea in new_geoms.altitudeareas),
                    crop_to.intersection(new_geoms.walls.buffer(1))
                ))

                for access_restriction, area in old_geoms.access_restriction_affected.items():
                    new_area = crop_to.intersection(area)
                    if not new_area.is_empty:
                        access_restriction_affected.setdefault(access_restriction, []).append(new_area)

                new_geoms.restricted_spaces_indoors = {}
                for access_restriction, area in old_geoms.restricted_spaces_indoors.items():
                    new_area = crop_to.intersection(area)
                    if not new_area.is_empty:
                        new_geoms.restricted_spaces_indoors[access_restriction] = new_area

                new_geoms.restricted_spaces_outdoors = {}
                for access_restriction, area in old_geoms.restricted_spaces_outdoors.items():
                    new_area = crop_to.intersection(area)
                    if not new_area.is_empty:
                        new_geoms.restricted_spaces_outdoors[access_restriction] = new_area

                new_geoms.pk = old_geoms.pk
                new_geoms.on_top_of_id = old_geoms.on_top_of_id
                new_geoms.short_label = old_geoms.short_label
                new_geoms.base_altitude = old_geoms.base_altitude
                new_geoms.default_height = old_geoms.default_height
                new_geoms.door_height = old_geoms.door_height
                new_geoms.min_altitude = (min(area.altitude for area in new_geoms.altitudeareas)
                                          if new_geoms.altitudeareas else new_geoms.base_altitude)

                new_geoms.build_mesh(interpolators.get(level.pk) if sublevel.pk == level.pk else None)

                render_data.levels.append(new_geoms)

            access_restriction_affected = {
                access_restriction: unary_union(areas)
                for access_restriction, areas in access_restriction_affected.items()
            }

            access_restriction_affected = AccessRestrictionAffected.build(access_restriction_affected)
            access_restriction_affected.save_level(level.pk, 'composite')

            map_history.save_level(level.pk, 'composite')

            package.add_level(level.pk, map_history, access_restriction_affected)

            render_data.save(level.pk)

        package.save_all()

    cached = {}
    cache_key = None
    cache_lock = threading.Lock()

    @staticmethod
    def _level_filename(pk):
        return os.path.join(settings.CACHE_ROOT, 'render_data_level_%d.pickle' % pk)

    @classmethod
    def get(cls, level):
        # get the current render data from local variable if no new processed mapupdate exists.
        # this is much faster than any other possible cache
        with cls.cache_lock:
            cache_key = MapUpdate.current_processed_cache_key()
            level_pk = str(level.pk if isinstance(level, Level) else level)
            if cls.cache_key != cache_key:
                cls.cache_key = cache_key
                cls.cached = {}
            else:
                result = cls.cached.get(level_pk, None)
                if result is not None:
                    return result

            pk = level.pk if isinstance(level, Level) else level
            result = pickle.load(open(cls._level_filename(pk), 'rb'))

            cls.cached[level_pk] = result
            return result

    def save(self, pk):
        return pickle.dump(self, open(self._level_filename(pk), 'wb'))
