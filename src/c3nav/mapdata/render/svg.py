from django.core.cache import cache
from django.utils.functional import cached_property
from shapely import prepared
from shapely.geometry import box
from shapely.ops import unary_union

from c3nav.mapdata.cache import MapHistory
from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.render.base import get_level_render_data
from c3nav.mapdata.utils.svg import SVGImage


class SVGRenderer:
    def __init__(self, level, miny, minx, maxy, maxx, scale=1, access_permissions=None):
        self.level = level
        self.miny = miny
        self.minx = minx
        self.maxy = maxy
        self.maxx = maxx
        self.scale = scale
        self.access_permissions = access_permissions

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
        svg = SVGImage(bounds=((self.miny, self.minx), (self.maxy, self.maxx)), scale=self.scale, buffer=1)

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
                                 fill_color='#eeeeee', altitude=altitudearea.altitude)

                for color, areas in altitudearea.colors.items():
                    # only select ground colors if their access restriction is unlocked
                    areas = tuple(area for access_restriction, area in areas.items()
                                  if access_restriction in unlocked_access_restrictions)
                    if areas:
                        svg.add_geometry(bbox.intersection(unary_union(areas)), fill_color=color)

            # add walls, stroke_px makes sure that all walls are at least 1px thick on all zoom levels,
            if not add_walls.is_empty or not geoms.walls.is_empty:
                svg.add_geometry(bbox.intersection(geoms.walls.union(add_walls)),
                                 fill_color='#aaaaaa', stroke_px=0.5, stroke_color='#aaaaaa', elevation=default_height)

            if not geoms.doors.is_empty:
                svg.add_geometry(bbox.intersection(geoms.doors.difference(add_walls)),
                                 fill_color='#ffffff', stroke_px=0.5, stroke_color='#ffffff')

        return svg
