from django.utils.functional import cached_property
from shapely.geometry import box
from shapely.ops import unary_union

from c3nav.mapdata.render.base import get_level_render_data
from c3nav.mapdata.utils.svg import SVGImage


class SVGRenderer:
    def __init__(self, level, miny, minx, maxy, maxx, scale=1, user=None):
        self.level = level
        self.miny = miny
        self.minx = minx
        self.maxy = maxy
        self.maxx = maxx
        self.scale = scale
        self.user = user

    @cached_property
    def bbox(self):
        return box(self.minx-1, self.miny-1, self.maxx+1, self.maxy+1)

    @cached_property
    def level_render_data(self):
        return get_level_render_data(self.level)

    def check_level(self):
        return self.level_render_data

    @cached_property
    def affected_access_restrictions(self):
        access_restrictions = set()
        for geoms, default_height in self.level_render_data:
            for access_restriction, area in geoms.access_restriction_affected.items():
                if access_restriction not in access_restrictions and area.intersects(self.bbox):
                    access_restrictions.add(access_restriction)
        return access_restrictions

    @cached_property
    def unlocked_access_restrictions(self):
        # todo access_restriction
        return set(access_restriction for access_restriction in self.affected_access_restrictions
                   if self.user is not None and self.user.is_superuser)

    @cached_property
    def access_cache_key(self):
        return '_'.join(str(i) for i in sorted(self.unlocked_access_restrictions)) or '0'

    def render(self):
        svg = SVGImage(bounds=((self.miny, self.minx), (self.maxy, self.maxx)), scale=self.scale, buffer=1)

        # add no access restriction to “unlocked“ access restrictions so lookup gets easier
        unlocked_access_restrictions = self.unlocked_access_restrictions | set([None])

        # choose a crop area for each level. non-intermediate levels (not on_top_of) below the one that we are
        # currently rendering will be cropped to only render content that is visible through holes indoors in the
        # levels above them.
        crop_to = None
        primary_level_count = 0
        for geoms, default_height in reversed(self.level_render_data):
            if geoms.holes is not None:
                primary_level_count += 1

            # set crop area if we area on the second primary layer from top or below
            geoms.crop_to = crop_to if primary_level_count > 1 else None

            if geoms.holes is not None:
                if crop_to is None:
                    crop_to = geoms.holes
                else:
                    crop_to = crop_to.intersection(geoms.holes)

        for geoms, default_height in self.level_render_data:
            crop_to = self.bbox
            if geoms.crop_to is not None:
                crop_to = crop_to.intersection(geoms.crop_to)

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
                svg.add_geometry(crop_to.intersection(altitudearea.geometry.difference(crop_areas)),
                                 fill_color='#eeeeee', altitude=altitudearea.altitude)

                for color, areas in altitudearea.colors.items():
                    # only select ground colors if their access restriction is unlocked
                    areas = tuple(area for access_restriction, area in areas.items()
                                  if access_restriction in unlocked_access_restrictions)
                    if areas:
                        svg.add_geometry(crop_to.intersection(unary_union(areas)), fill_color=color)

            # add walls, stroke_px makes sure that all walls are at least 1px thick on all zoom levels,
            svg.add_geometry(crop_to.intersection(geoms.walls.union(add_walls)),
                             fill_color='#aaaaaa', stroke_px=0.5, stroke_color='#aaaaaa', elevation=default_height)

            svg.add_geometry(crop_to.intersection(geoms.doors.difference(add_walls)),
                             fill_color='#ffffff', stroke_px=0.5, stroke_color='#ffffff')

        return svg
