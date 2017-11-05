from django.core.cache import cache
from django.utils.functional import cached_property
from shapely import prepared
from shapely.geometry import box
from shapely.ops import unary_union

from c3nav.mapdata.cache import MapHistory
from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.render.data import get_level_render_data
from c3nav.mapdata.render.engines.base import FillAttribs, StrokeAttribs
from c3nav.mapdata.render.engines.svg import SVGEngine


class ImageRenderer:
    def __init__(self, level, minx, miny, maxx, maxy, scale=1, access_permissions=None):
        self.level = level
        self.minx = minx
        self.miny = miny
        self.maxx = maxx
        self.maxy = maxy
        self.scale = scale
        self.access_permissions = access_permissions

        self.width = int(round((maxx - minx) * scale))
        self.height = int(round((maxy - miny) * scale))

    @cached_property
    def bbox(self):
        return box(self.minx-1, self.miny-1, self.maxx+1, self.maxy+1)

    @cached_property
    def level_render_data(self):
        return get_level_render_data(self.level)

    @cached_property
    def last_update(self):
        return MapHistory.open_level_cached(self.level, 'render').last_update(self.minx, self.miny,
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

    def render(self):
        svg = SVGEngine(self.width, self.height, self.minx, self.miny,
                        scale=self.scale, buffer=1, background='#DCDCDC')

        # add no access restriction to “unlocked“ access restrictions so lookup gets easier
        unlocked_access_restrictions = self.unlocked_access_restrictions | set([None])

        bbox = self.bbox
        bbox_prep = prepared.prep(bbox)

        for geoms, default_height in self.level_render_data.levels:
            if not bbox_prep.intersects(geoms.affected_area):
                continue

            # hide indoor and outdoor rooms if their access restriction was not unlocked
            add_walls = unary_union(tuple(area for access_restriction, area in geoms.restricted_spaces_indoors.items()
                                          if access_restriction not in unlocked_access_restrictions))
            crop_areas = unary_union(
                tuple(area for access_restriction, area in geoms.restricted_spaces_outdoors.items()
                      if access_restriction not in unlocked_access_restrictions)
            ).union(add_walls)

            # render altitude areas in default ground color and add ground colors to each one afterwards
            # shadows are directly calculated and added by the SVGImage class
            for altitudearea in geoms.altitudeareas:
                svg.add_geometry(bbox.intersection(altitudearea.geometry.difference(crop_areas)),
                                 altitude=altitudearea.altitude, fill=FillAttribs('#eeeeee'),
                                 stroke=StrokeAttribs('rgba(0, 0, 0, 0.15)', 0.05, min_px=0.2))

                for color, areas in altitudearea.colors.items():
                    # only select ground colors if their access restriction is unlocked
                    areas = tuple(area for access_restriction, area in areas.items()
                                  if access_restriction in unlocked_access_restrictions)
                    if areas:
                        svg.add_geometry(bbox.intersection(unary_union(areas)), fill=FillAttribs(color))

            # add walls, stroke_px makes sure that all walls are at least 1px thick on all zoom levels,
            walls = None
            if not add_walls.is_empty or not geoms.walls.is_empty:
                walls = bbox.intersection(geoms.walls.union(add_walls))

            if walls is not None:
                svg.add_geometry(walls, height=default_height, fill=FillAttribs('#aaaaaa'))

            if not geoms.doors.is_empty:
                svg.add_geometry(bbox.intersection(geoms.doors.difference(add_walls)), fill=FillAttribs('#ffffff'),
                                 stroke=StrokeAttribs('#ffffff', 0.05, min_px=0.2))

            if walls is not None:
                svg.add_geometry(walls, stroke=StrokeAttribs('#666666', 0.05, min_px=0.2))

        return svg
