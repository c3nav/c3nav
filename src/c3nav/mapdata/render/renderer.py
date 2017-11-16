from itertools import chain

from django.core.cache import cache
from django.utils.functional import cached_property
from shapely import prepared
from shapely.geometry import box

from c3nav.mapdata.cache import MapHistory
from c3nav.mapdata.models import Level, MapUpdate
from c3nav.mapdata.render.data import LevelRenderData, hybrid_union
from c3nav.mapdata.render.engines.base import FillAttribs, StrokeAttribs


class MapRenderer:
    def __init__(self, level, minx, miny, maxx, maxy, scale=1, access_permissions=None, full_levels=False):
        self.level = level.pk if isinstance(level, Level) else level
        self.minx = minx
        self.miny = miny
        self.maxx = maxx
        self.maxy = maxy
        self.scale = scale
        self.access_permissions = set(access_permissions) if access_permissions else set()
        self.full_levels = full_levels

        self.width = int(round((maxx - minx) * scale))
        self.height = int(round((maxy - miny) * scale))

    @cached_property
    def bbox(self):
        return box(self.minx-1, self.miny-1, self.maxx+1, self.maxy+1)

    @cached_property
    def level_render_data(self):
        return LevelRenderData.get(self.level)

    @cached_property
    def last_update(self):
        return MapHistory.open_level_cached(self.level, 'composite').last_update(self.minx, self.miny,
                                                                                 self.maxx, self.maxy)

    @cached_property
    def update_cache_key(self):
        return MapUpdate.build_cache_key(*self.last_update)

    @cached_property
    def affected_access_restrictions(self):
        cache_key = 'mapdata:affected-ars-%.2f-%.2f-%.2f-%.2f:%s' % (self.minx, self.miny, self.maxx, self.maxy,
                                                                     self.update_cache_key)
        result = cache.get(cache_key, None)
        if result is None:
            result = set(ar for ar, area in self.level_render_data.access_restriction_affected.items()
                         if area.intersects(self.bbox))
            cache.set(cache_key, result, 120)
        return result

    @cached_property
    def unlocked_access_restrictions(self):
        return self.affected_access_restrictions & self.access_permissions

    @cached_property
    def access_cache_key(self):
        return '_'.join(str(i) for i in sorted(self.unlocked_access_restrictions)) or '0'

    @cached_property
    def cache_key(self):
        return self.update_cache_key + ':' + self.access_cache_key

    def render(self, engine_cls, center=True):
        engine = engine_cls(self.width, self.height, self.minx, self.miny,
                            scale=self.scale, buffer=1, background='#DCDCDC', center=center)

        # add no access restriction to “unlocked“ access restrictions so lookup gets easier
        unlocked_access_restrictions = self.unlocked_access_restrictions | set([None])

        bbox = prepared.prep(self.bbox)

        if self.full_levels:
            levels = tuple(chain(*(
                tuple(sublevel for sublevel in LevelRenderData.get(level.pk).levels
                      if sublevel.pk == level.pk or sublevel.on_top_of_id == level.pk)
                for level in self.level_render_data.levels if level.on_top_of_id is None
            )))
        else:
            levels = self.level_render_data.levels

        min_altitude = min(chain(*(tuple(area.altitude for area in geoms.altitudeareas)
                                   for geoms in levels)))

        not_full_levels = not self.full_levels and engine.is_3d
        full_levels = self.full_levels and engine.is_3d
        for geoms in levels:
            if not bbox.intersects(geoms.affected_area):
                continue

            engine.add_group('level_%s' % geoms.short_label)

            # hide indoor and outdoor rooms if their access restriction was not unlocked
            add_walls = hybrid_union(tuple(area for access_restriction, area in geoms.restricted_spaces_indoors.items()
                                           if access_restriction not in unlocked_access_restrictions))
            crop_areas = hybrid_union(
                tuple(area for access_restriction, area in geoms.restricted_spaces_outdoors.items()
                      if access_restriction not in unlocked_access_restrictions)
            ).union(add_walls)

            if not_full_levels:
                engine.add_geometry(geoms.walls_base, fill=FillAttribs('#aaaaaa'), category='walls')
                engine.add_geometry(geoms.walls_bottom.fit(scale=geoms.min_altitude-min_altitude,
                                                           offset=min_altitude-int(0.7*1000)),
                                    fill=FillAttribs('#aaaaaa'), category='walls')
                for i, altitudearea in enumerate(geoms.altitudeareas):
                    scale = (altitudearea.altitude - min_altitude) / int(0.7 * 1000)
                    offset = (min_altitude - int(0.7*1000)) - (altitudearea.altitude - int(0.7*1000)) * scale
                    geometry = altitudearea.geometry.difference(crop_areas)
                    engine.add_geometry(geometry.fit(scale=scale, offset=offset).filter(top=False),
                                        fill=FillAttribs('#eeeeee'), category='ground', item=i)

            # render altitude areas in default ground color and add ground colors to each one afterwards
            # shadows are directly calculated and added by the engine
            for i, altitudearea in enumerate(geoms.altitudeareas):
                geometry = altitudearea.geometry.difference(crop_areas)
                if not_full_levels:
                    geometry = geometry.filter(bottom=False)
                engine.add_geometry(geometry, altitude=altitudearea.altitude, fill=FillAttribs('#eeeeee'),
                                    category='ground', item=i)

                i = 0
                for color, areas in altitudearea.colors.items():
                    # only select ground colors if their access restriction is unlocked
                    areas = tuple(area for access_restriction, area in areas.items()
                                  if access_restriction in unlocked_access_restrictions)
                    if areas:
                        i += 1
                        engine.add_geometry(hybrid_union(areas), fill=FillAttribs(color),
                                            category='groundcolor%s' % i, item=i)

                for height, obstacle in altitudearea.obstacles.items():
                    engine.add_geometry(obstacle, fill=FillAttribs('#cccccc'), category='obstacles')

            # add walls, stroke_px makes sure that all walls are at least 1px thick on all zoom levels,
            walls = None
            if not add_walls.is_empty or not geoms.walls.is_empty:
                walls = geoms.walls.union(add_walls)

            walls_extended = geoms.walls_extended and full_levels
            if walls is not None:
                engine.add_geometry(walls.filter(bottom=not not_full_levels,
                                                 top=not walls_extended),
                                    height=geoms.default_height, fill=FillAttribs('#aaaaaa'), category='walls')

            if walls_extended:
                engine.add_geometry(geoms.walls_extended, fill=FillAttribs('#aaaaaa'), category='walls')

            doors_extended = geoms.doors_extended and full_levels
            if not geoms.doors.is_empty:
                engine.add_geometry(geoms.doors.difference(add_walls).filter(top=not doors_extended),
                                    fill=FillAttribs('#ffffff'),
                                    stroke=StrokeAttribs('#ffffff', 0.05, min_px=0.2),
                                    category='doors')

            if doors_extended:
                engine.add_geometry(geoms.doors_extended, fill=FillAttribs('#aaaaaa'), category='doors')

            if walls is not None:
                engine.add_geometry(walls, stroke=StrokeAttribs('#666666', 0.05, min_px=0.2), category='walls')

        return engine
