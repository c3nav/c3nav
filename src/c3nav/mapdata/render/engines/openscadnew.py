import math
from abc import ABC, abstractmethod
from collections import UserList
from operator import attrgetter

from shapely import prepared
from shapely.geometry import JOIN_STYLE
from shapely.ops import unary_union

from c3nav.mapdata.render.engines import register_engine
from c3nav.mapdata.render.engines.base3d import Base3DEngine
from c3nav.mapdata.render.utils import get_full_levels
from c3nav.mapdata.utils.geometry import assert_multipolygon


class AbstractOpenScadElem(ABC):
    @abstractmethod
    def render(self) -> str:
        raise NotADirectoryError


class AbstractOpenScadBlock(AbstractOpenScadElem, UserList):
    def render_children(self):
        return '\n'.join(child.render() for child in self.data)


class OpenScadRoot(AbstractOpenScadBlock):
    def render(self):
        return self.render_children()


class OpenScadBlock(AbstractOpenScadBlock):
    def __init__(self, command, comment=None, children=None):
        super().__init__(children if children else [])
        self.command = command
        self.comment = comment

    def render(self):
        if self.comment or len(self.data) != 1:
            return '%s {%s\n    %s\n}' % (
                self.command,
                '' if self.comment is None else (' // '+self.comment),
                self.render_children().replace('\n', '\n    ')
            )
        return '%s %s' % (self.command, self.render_children())


class OpenScadCommand(AbstractOpenScadElem):
    def __init__(self, command):
        super().__init__()
        self.command = command

    def render(self):
        return self.command


@register_engine
class OpenSCADNewEngine(Base3DEngine):
    filetype = 'new.scad'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.root = OpenScadRoot()

    def custom_render(self, level_render_data, access_permissions):
        levels = get_full_levels(level_render_data)

        buildings = None

        main_building_block = None
        main_building_block_diff = None

        last_lower_bound = None
        for geoms in reversed(levels):
            if geoms.on_top_of_id is not None:
                continue

            altitudes = [geoms.base_altitude]
            for altitudearea in geoms.altitudeareas:
                altitudes.append(altitudearea.altitude)
                if altitudearea.altitude2 is not None:
                    altitudes.append(altitudearea.altitude2)

            if last_lower_bound is None:
                altitude = max(altitudes)
                height = max((height for (geometry, height) in geoms.heightareas), default=geoms.default_height)
                last_lower_bound = altitude+height

            geoms.upper_bound = last_lower_bound
            geoms.lower_bound = min(altitudes)-700
            last_lower_bound = geoms.lower_bound

        current_upper_bound = last_lower_bound
        for geoms in levels:
            # hide indoor and outdoor rooms if their access restriction was not unlocked
            restricted_spaces_indoors = unary_union(
                tuple(area.geom for access_restriction, area in geoms.restricted_spaces_indoors.items()
                      if access_restriction not in access_permissions)
            )
            restricted_spaces_outdoors = unary_union(
                tuple(area.geom for access_restriction, area in geoms.restricted_spaces_outdoors.items()
                      if access_restriction not in access_permissions)
            )
            restricted_spaces = unary_union((restricted_spaces_indoors, restricted_spaces_outdoors))  # noqa

            # crop altitudeareas
            for altitudearea in geoms.altitudeareas:
                altitudearea.geometry = altitudearea.geometry.geom.difference(restricted_spaces)
                altitudearea.geometry_prep = prepared.prep(altitudearea.geometry)

            # crop heightareas
            new_heightareas = []
            for geometry, height in geoms.heightareas:
                geometry = geometry.geom.difference(restricted_spaces)
                geometry_prep = prepared.prep(geometry)
                new_heightareas.append((geometry, geometry_prep, height))
            geoms.heightareas = new_heightareas

            if geoms.on_top_of_id is None:
                buildings = geoms.buildings
                current_upper_bound = geoms.upper_bound

                holes = geoms.holes.difference(restricted_spaces)
                buildings = buildings.difference(holes)

                main_building_block = OpenScadBlock('union()', comment='Level %s' % geoms.short_label)
                self.root.append(main_building_block)
                main_building_block_diff = OpenScadBlock('difference()')
                main_building_block.append(main_building_block_diff)
                main_building_block_diff.append(
                    self._add_polygon(None, buildings, geoms.lower_bound, geoms.upper_bound)
                )

            for altitudearea in sorted(geoms.altitudeareas, key=attrgetter('altitude')):
                name = 'Level %s Altitudearea %s' % (geoms.short_label, altitudearea.altitude)
                geometry = altitudearea.geometry.buffer(0)
                inside_geometry = geometry.intersection(buildings).buffer(0).buffer(0.004, join_style=JOIN_STYLE.mitre)
                outside_geometry = geometry.difference(buildings).buffer(0).buffer(0.004, join_style=JOIN_STYLE.mitre)

                slopes = True

                if not inside_geometry.is_empty:
                    if altitudearea.altitude2 is not None:
                        min_slope_altitude = min(altitudearea.altitude, altitudearea.altitude2)
                        max_slope_altitude = max(altitudearea.altitude, altitudearea.altitude2)
                        bounds = inside_geometry.bounds

                        # cut in
                        polygon = self._add_polygon(None, inside_geometry,
                                                    min_slope_altitude-10, current_upper_bound+1000)

                        slope = self._add_slope(bounds, altitudearea.altitude, altitudearea.altitude2,
                                                altitudearea.point1, altitudearea.point2, bottom=True)
                        if slopes:
                            main_building_block_diff.append(
                                OpenScadBlock('difference()', children=[polygon, slope], comment='slope')
                            )

                        # actual thingy
                        polygon = self._add_polygon(None, inside_geometry,
                                                    current_upper_bound - 1, max_slope_altitude+10)
                        slope = self._add_slope(bounds, altitudearea.altitude, altitudearea.altitude2,
                                                altitudearea.point1, altitudearea.point2)
                        if slopes:
                            main_building_block.append(
                                OpenScadBlock('difference()', children=[polygon, slope], comment='slope')
                            )
                    else:
                        if altitudearea.altitude < current_upper_bound:
                            main_building_block_diff.append(
                                self._add_polygon(name, inside_geometry,
                                                  altitudearea.altitude, current_upper_bound+1000)
                            )
                        else:
                            main_building_block.append(
                                self._add_polygon(name, inside_geometry, current_upper_bound-1, altitudearea.altitude)
                            )

                if not outside_geometry.is_empty:
                    if altitudearea.altitude2 is not None:
                        min_slope_altitude = min(altitudearea.altitude, altitudearea.altitude2)
                        max_slope_altitude = max(altitudearea.altitude, altitudearea.altitude2)
                        bounds = outside_geometry.bounds

                        # cut in
                        polygon = self._add_polygon(None, outside_geometry,
                                                    min_slope_altitude-710, max_slope_altitude+10)
                        slope1 = self._add_slope(bounds, altitudearea.altitude, altitudearea.altitude2,
                                                 altitudearea.point1, altitudearea.point2, bottom=False)
                        slope2 = self._add_slope(bounds, altitudearea.altitude-700, altitudearea.altitude2-700,
                                                 altitudearea.point1, altitudearea.point2, bottom=True)
                        if slopes:
                            main_building_block.append(
                                OpenScadBlock('difference()', children=[polygon, slope1, slope2], comment='slope')
                            )
                    else:
                        lower = altitudearea.altitude-700
                        if lower == current_upper_bound:
                            lower -= 10
                        main_building_block.append(
                            self._add_polygon(name, outside_geometry, lower, altitudearea.altitude)
                        )

    def _add_polygon(self, name, geometry, minz, maxz):
        geometry = geometry.buffer(0)
        polygons = []
        for polygon in assert_multipolygon(geometry):
            points = []
            points_lookup = {}
            output_rings = []
            for ring in [polygon.exterior]+list(polygon.interiors):
                output_ring = []
                for coords in ring.coords:
                    try:
                        i = points_lookup[coords]
                    except KeyError:
                        points_lookup[coords] = len(points)
                        i = len(points)
                        points.append(list(coords))
                    output_ring.append(i)
                output_rings.append(output_ring)
            polygons.append(OpenScadCommand('polygon(%(points)r, %(rings)r, 10);' % {
                'points': points,
                'rings': output_rings,
            }))

        extrude_cmd = 'linear_extrude(height=%f, convexity=10)' % (abs(maxz-minz)/1000)
        translate_cmd = 'translate([0, 0, %f])' % (min(maxz, minz)/1000)
        return OpenScadBlock(translate_cmd, children=[OpenScadBlock(extrude_cmd, comment=name, children=polygons)])

    def _add_slope(self, bounds, altitude1, altitude2, point1, point2, bottom=False):
        distance = point1.distance(point2)
        altitude_diff = (altitude2-altitude1)/1000

        rotate_y = -math.degrees(math.atan2(altitude_diff, distance))
        rotate_z = math.degrees(math.atan2(point2.y-point1.y, point2.x-point1.x))

        if bottom:
            rotate_y += 180

        minx, miny, maxx, maxy = bounds
        size = ((maxx-minx)+(maxy-miny))*2

        cmd = OpenScadCommand('square([%f, %f], center=true);' % (size, size))
        cmd = OpenScadBlock('linear_extrude(height=100, convexity=10)', children=[cmd])
        cmd = OpenScadBlock('rotate([0, %f, %f])' % (rotate_y, rotate_z), children=[cmd])
        cmd = OpenScadBlock('translate([%f, %f, %f])' % (point1.x, point1.y, altitude1/1000), children=[cmd])
        return cmd

    def render(self, filename=None):
        return self.root.render().encode()
