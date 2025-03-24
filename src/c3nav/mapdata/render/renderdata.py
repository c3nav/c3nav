import operator
import pickle
from collections import deque
from dataclasses import dataclass, field
from itertools import chain
from typing import Optional

import numpy as np
from django.conf import settings
from shapely import Geometry, MultiPolygon, prepared
from shapely.geometry import GeometryCollection
from shapely.ops import unary_union
from shapely.prepared import PreparedGeometry

from c3nav.mapdata.models import Level, MapUpdate, Source
from c3nav.mapdata.models.theme import Theme
from c3nav.mapdata.models.update import MapUpdateJob
from c3nav.mapdata.permissions import ManualMapPermissions, active_map_permissions
from c3nav.mapdata.render.geometry import AltitudeAreaGeometries, SingleLevelGeometries, CompositeLevelGeometries
from c3nav.mapdata.utils.cache import AccessRestrictionAffected, MapHistory
from c3nav.mapdata.utils.cache.package import CachePackage
from c3nav.mapdata.utils.geometry import get_rings, unwrap_geom

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext

empty_geometry_collection = GeometryCollection()


@dataclass
class Cropper:
    geometry: Optional[Geometry]
    geometry_prep: Optional[PreparedGeometry] = field(init=False, repr=False)

    def __post_init__(self):
        self.geometry_prep = None if self.geometry is None else prepared.prep(unwrap_geom(self.geometry))

    def intersection(self, other):
        if self.geometry is None:
            return other
        if self.geometry_prep.intersects(other):
            return self.geometry.intersection(other)
        return empty_geometry_collection


@dataclass
class LevelRenderData:
    """
    Renderdata for a level to display.
    This contains multiple LevelGeometries instances because you might to look through holes onto lower levels.
    """
    base_altitude: float
    lowest_important_level: int
    levels: list[CompositeLevelGeometries] = field(default_factory=list)
    darken_area: MultiPolygon | None = None
    darken_much: bool = False

    @staticmethod
    def rebuild(update_cache_key):
        with active_map_permissions.disable_access_checks():
            return LevelRenderData._rebuild(update_cache_key)

    @staticmethod
    def _rebuild(update_cache_key):
        # Levels are automatically sorted by base_altitude, ascending
        levels = tuple(Level.objects.prefetch_related('altitudeareas', 'buildings', 'doors', 'spaces',
                                                      'spaces__holes', 'spaces__areas', 'spaces__columns',
                                                      'spaces__obstacles', 'spaces__lineobstacles',
                                                      'spaces__locations__groups', 'spaces__ramps'))

        package = CachePackage(bounds=tuple(chain(*Source.max_bounds())))

        # todo: we should check that levels on top come before their levels as they should

        themes = [None, *Theme.objects.values_list('pk', flat=True)]
        from scipy.interpolate import NearestNDInterpolator  # moved in here to save memory

        from c3nav.mapdata.render.theme import ColorManager

        for theme in themes:
            color_manager = ColorManager.for_theme(theme)
            """
            first pass in reverse to collect some data that we need later
            """
            # level geometry for every single level
            single_level_geoms: dict[int, SingleLevelGeometries] = {}
            # interpolator are used to create the 3d mesh
            interpolators = {}
            last_interpolator: NearestNDInterpolator | None = None
            # altitudeareas of levels on top are collected on the way down to supply to the levelgeometries builder
            altitudeareas_above = []  # todo: typing
            for render_level in reversed(levels):
                # build level geometry for every single level
                single_level_geoms[render_level.pk] = SingleLevelGeometries.build_for_level(
                    render_level, color_manager, altitudeareas_above
                )

                # ignore intermediate levels in this pass
                if render_level.on_top_of_id is not None:
                    # todo: shouldn't this be cleared or something?
                    altitudeareas_above.extend(single_level_geoms[render_level.pk].altitudeareas)
                    altitudeareas_above.sort(key=operator.attrgetter('max_altitude'))
                    continue

                # create interpolator to create the pieces that fit multiple 3d layers together
                if last_interpolator is not None:
                    interpolators[render_level.pk] = last_interpolator

                coords = deque()
                values = deque()
                for area in single_level_geoms[render_level.pk].altitudeareas:
                    new_coords = np.vstack(tuple(np.array(ring.coords) for ring in get_rings(area.geometry)))
                    coords.append(new_coords)
                    values.append(np.full((new_coords.shape[0], 1), fill_value=area.altitude))

                if coords:
                    last_interpolator = NearestNDInterpolator(np.vstack(coords), np.vstack(values))
                else:
                    last_interpolator = NearestNDInterpolator(np.array([[0, 0]]),
                                                              np.array([float(render_level.base_altitude)]))

            """
            second pass, forward to create the LevelRenderData for each level
            """
            upper_bounds: dict[int, int] = {}
            for render_level in levels:
                # we don't create render data for on_top_of levels
                if render_level.on_top_of_id is not None:
                    continue

                map_history = MapHistory.open_level(render_level.pk, 'base')

                # collect potentially relevant levels for rendering this level
                # these are all levels that are on_top_of this level or below this level (inless intermediate)
                relevant_levels = tuple(
                    sublevel for sublevel in levels
                    if (sublevel.pk == render_level.pk or sublevel.on_top_of_id == render_level.pk or
                        (sublevel.base_altitude <= render_level.base_altitude and not sublevel.intermediate))
                )

                """
                choose a crop area for each level. non-intermediate levels (not on_top_of) below the one that we are
                currently rendering will be cropped to only render content that is visible through holes indoors in the
                levels above them.
                """
                # area to crop each level to, by id
                level_crop_to: dict[int, Cropper] = {}
                # current remaining area that we're cropping to – None means no cropping
                crop_to = None
                primary_level_count = 0
                main_level_passed = 0
                lowest_important_level = None
                last_lower_bound = None
                for level in reversed(relevant_levels):  # reversed means we are going down
                    geoms = single_level_geoms[level.pk]

                    if geoms.holes is not None:
                        primary_level_count += 1

                    # get lowest intermediate level directly below main level
                    if not main_level_passed:
                        if geoms.pk == render_level.pk:
                            main_level_passed = 1
                    else:
                        if not level.on_top_of_id:
                            main_level_passed += 1
                    if main_level_passed < 2:
                        lowest_important_level = level

                    # make upper bounds
                    if geoms.on_top_of_id is None:
                        if last_lower_bound is None:
                            upper_bounds[geoms.pk] = geoms.max_altitude+geoms.max_height
                        else:
                            upper_bounds[geoms.pk] = last_lower_bound
                        last_lower_bound = geoms.lower_bound

                    # set crop area if we are on the second primary layer from top or below
                    level_crop_to[level.pk] = Cropper(crop_to if primary_level_count > 1 else None)

                    if geoms.holes is not None:  # there area holes on this area
                        if crop_to is None:
                            crop_to = geoms.holes
                        else:
                            crop_to = crop_to.intersection(geoms.holes)

                        if crop_to.is_empty:
                            break

                if render_level.intermediate:
                    # todo: would be nice to still have the staircases leading to this level i guess?
                    lowest_important_level = render_level

                render_data = LevelRenderData(
                    base_altitude=render_level.base_altitude,
                    lowest_important_level=lowest_important_level.pk,
                )
                access_restriction_affected = {}

                # go through sublevels, get their level geometries and crop them
                lowest_important_level_passed = False
                for level in relevant_levels:
                    try:
                        crop_to = level_crop_to[level.pk]
                    except KeyError:
                        continue

                    single_geoms = single_level_geoms[level.pk]

                    if render_data.lowest_important_level == level.pk:
                        lowest_important_level_passed = True

                    if single_geoms.holes and render_data.darken_area is None and lowest_important_level_passed:
                        render_data.darken_area = single_geoms.holes
                        if render_level.intermediate:
                            render_data.darken_much = True

                    if crop_to.geometry is not None:
                        map_history.composite(MapHistory.open_level(level.pk, 'base'), crop_to.geometry)
                    elif render_level.pk != level.pk:
                        map_history.composite(MapHistory.open_level(level.pk, 'base'), None)

                    new_buildings_geoms = crop_to.intersection(single_geoms.buildings)
                    if single_geoms.on_top_of_id is None:
                        new_holes_geoms = crop_to.intersection(single_geoms.holes)
                    else:
                        new_holes_geoms = None
                    new_doors_geoms = crop_to.intersection(single_geoms.doors)
                    new_walls_geoms = crop_to.intersection(single_geoms.walls)
                    new_all_walls_geoms = crop_to.intersection(single_geoms.all_walls)
                    new_short_walls_geoms = tuple((altitude, geom) for altitude, geom in tuple(
                        (altitude, crop_to.intersection(geom))
                        for altitude, geom in single_geoms.short_walls
                    ) if not geom.is_empty)

                    new_altitudeareas = []
                    for altitudearea in single_geoms.altitudeareas:
                        new_geometry = crop_to.intersection(unwrap_geom(altitudearea.geometry))
                        if new_geometry.is_empty:
                            continue
                        new_geometry_prep = prepared.prep(new_geometry)

                        new_altitudearea = AltitudeAreaGeometries()
                        new_altitudearea.geometry = new_geometry
                        new_altitudearea.altitude = altitudearea.altitude
                        new_altitudearea.points = altitudearea.points

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

                        new_altitudearea_obstacles = {}
                        for height, height_obstacles in altitudearea.obstacles.items():
                            new_height_obstacles = {}
                            for color, color_obstacles in height_obstacles.items():
                                new_color_obstacles = []
                                for obstacle in color_obstacles:
                                    obstacle = obstacle.buffer(0)
                                    if new_geometry_prep.intersects(obstacle):
                                        new_color_obstacles.append(
                                            obstacle.intersection(unwrap_geom(altitudearea.geometry))
                                        )
                                if new_color_obstacles:
                                    new_height_obstacles[color] = new_color_obstacles
                            if new_height_obstacles:
                                new_altitudearea_obstacles[height] = new_height_obstacles
                        new_altitudearea.obstacles = new_altitudearea_obstacles

                        new_altitudeareas.append(new_altitudearea)

                    if new_walls_geoms.is_empty and not new_altitudeareas:
                        continue

                    new_heightareas = tuple(
                        (area, height) for area, height in ((crop_to.intersection(unwrap_geom(area)), height)
                                                            for area, height in single_geoms.heightareas)
                        if not area.is_empty
                    )

                    for access_restriction, area in single_geoms.access_restriction_affected.items():
                        new_area = crop_to.intersection(area)
                        if not new_area.is_empty:
                            access_restriction_affected.setdefault(access_restriction, []).append(new_area)

                    new_restricted_spaces_indoors = {}
                    for access_restriction, area in single_geoms.restricted_spaces_indoors.items():
                        new_area = crop_to.intersection(area)
                        if not new_area.is_empty:
                            new_restricted_spaces_indoors[access_restriction] = new_area

                    new_restricted_spaces_outdoors = {}
                    for access_restriction, area in single_geoms.restricted_spaces_outdoors.items():
                        new_area = crop_to.intersection(area)
                        if not new_area.is_empty:
                            new_restricted_spaces_outdoors[access_restriction] = new_area

                    composite_geoms = CompositeLevelGeometries(
                        pk=single_geoms.pk,
                        on_top_of_id=single_geoms.on_top_of_id,
                        short_label=single_geoms.short_label,
                        level_index=single_geoms.level_index,
                        base_altitude=single_geoms.base_altitude,
                        default_height=single_geoms.default_height,
                        door_height=single_geoms.door_height,
                        min_altitude=(min(area.min_altitude for area in new_altitudeareas)
                                                  if new_altitudeareas else single_geoms.base_altitude),
                        max_altitude=(max(area.max_altitude for area in new_altitudeareas)
                                                  if new_altitudeareas else single_geoms.base_altitude),
                        max_height=(min(height for area, height in new_heightareas)
                                                if new_heightareas else single_geoms.default_height),
                        lower_bound=single_geoms.lower_bound,
                        upper_bound=upper_bounds.get(single_geoms.pk, 0),  # might be wrong but only needed for 3d
                        heightareas=new_heightareas,
                        altitudeareas=new_altitudeareas,

                        buildings=new_buildings_geoms,
                        holes=new_holes_geoms,
                        doors=new_doors_geoms,
                        walls=new_walls_geoms,
                        all_walls=new_all_walls_geoms,
                        short_walls=new_short_walls_geoms,

                        restricted_spaces_indoors=new_restricted_spaces_indoors,
                        restricted_spaces_outdoors=new_restricted_spaces_outdoors,

                        ramps=tuple(
                            ramp for ramp in (crop_to.intersection(unwrap_geom(ramp)) for ramp in single_geoms.ramps)
                            if not ramp.is_empty
                        ),

                        affected_area=unary_union((
                            *(altitudearea.geometry for altitudearea in new_altitudeareas),
                            crop_to.intersection(new_walls_geoms.buffer(1)),
                            *((new_holes_geoms.buffer(1),) if new_holes_geoms else ()),
                        )),

                        doors_extended=None,
                        faces=None,
                        vertices=None,
                        walls_base=None,
                        walls_bottom=None,
                        walls_extended=None,
                    )

                    composite_geoms.build_mesh(interpolators.get(render_level.pk) if level.pk == render_level.pk else None)

                    render_data.levels.append(composite_geoms)

                access_restriction_affected = {
                    access_restriction: unary_union(areas)
                    for access_restriction, areas in access_restriction_affected.items()
                }

                access_restriction_affected = AccessRestrictionAffected.build(access_restriction_affected)
                access_restriction_affected.save_level(render_level.pk, 'composite')

                map_history.save_level(render_level.pk, 'composite')

                package.add_level(level_id=render_level.pk, theme_id=theme, history=map_history,
                                  restrictions=access_restriction_affected,
                                  level_restriction=render_level.access_restriction_id)

                render_data.save(update_cache_key, render_level.pk, theme)

        package.save_all(update_cache_key)

    cached = LocalContext()

    @staticmethod
    def _level_filename(update_cache_key, level_pk, theme_pk):
        if theme_pk is None:
            name = 'render_data_level_%d.pickle' % level_pk
        else:
            name = 'render_data_level_%d_theme_%d.pickle' % (level_pk, theme_pk)
        return settings.CACHE_ROOT / update_cache_key / name

    @classmethod
    def get(cls, level, theme):
        # get the current render data from local variable if no new processed mapupdate exists.
        # this is much faster than any other possible cache
        map_update = MapUpdateJob.last_successful_update("mapdata.recalculate_geometries")
        level_pk = level.pk if isinstance(level, Level) else level
        theme_pk = theme.pk if isinstance(theme, Theme) else theme
        key = f'{level_pk}_{theme_pk}'
        if getattr(cls.cached, 'key', None) != map_update:
            cls.cached.key = map_update
            cls.cached.data = {}
        else:
            result = cls.cached.data.get(key, None)
            if result is not None:
                return result

        result = pickle.load(open(cls._level_filename(map_update.cache_key, level_pk, theme_pk), 'rb'))

        cls.cached.data[key] = result
        return result

    def save(self, update_cache_key, level_pk, theme_pk):
        return pickle.dump(self, open(self._level_filename(update_cache_key, level_pk, theme_pk), 'wb'))
