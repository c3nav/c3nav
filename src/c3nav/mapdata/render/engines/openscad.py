import math
from abc import ABC, abstractmethod
from collections import UserList
from operator import attrgetter

from shapely import prepared
from shapely.geometry import JOIN_STYLE, MultiPolygon
from shapely.ops import unary_union

from c3nav.mapdata.render.engines import register_engine
from c3nav.mapdata.render.engines.base3d import Base3DEngine
from c3nav.mapdata.render.utils import get_full_levels, get_main_levels
from c3nav.mapdata.utils.geometry.inspect import assert_multipolygon


class AbstractOpenScadElem(ABC):
    @abstractmethod
    def render(self) -> str:
        raise NotADirectoryError


class AbstractOpenScadBlock(AbstractOpenScadElem, UserList, ABC):
    def render_children(self):
        return '\n'.join(child.render() for child in self.data if child is not None)


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
class OpenSCADEngine(Base3DEngine):
    filetype = 'scad'

    def __init__(self, *args, center=True, **kwargs):
        super().__init__(*args, center=center, **kwargs)

        if center:
            self.root = OpenScadBlock('scale([%(scale)f, %(scale)f, %(scale)f]) translate([%(x)f, %(y)f, 0])' % {
                'scale': self.scale,
                'x': -(self.minx + self.maxx) / 2,
                'y': -(self.miny + self.maxy) / 2,
            })
        else:
            self.root = OpenScadBlock('scale([%(scale)f, %(scale)f, %(scale)f])' % {
                'scale': self.scale,
            })

    def custom_render(self, level_render_data, access_permissions, full_levels):
        if full_levels:
            levels = get_full_levels(level_render_data)
        else:
            levels = get_main_levels(level_render_data)

        buildings = None
        areas = None

        main_building_block = None
        main_building_block_diff = None

        current_upper_bound = None
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
                areas = MultiPolygon()
                current_upper_bound = geoms.upper_bound

                holes = geoms.holes.difference(restricted_spaces)
                buildings = buildings.difference(holes)
                areas = areas.union(holes.buffer(0).buffer(0.01, join_style=JOIN_STYLE.mitre))

                main_building_block = OpenScadBlock('union()', comment='Level %s' % geoms.short_label)
                self.root.append(main_building_block)
                main_building_block_diff = OpenScadBlock('difference()')
                main_building_block.append(main_building_block_diff)
                main_building_block_inner = OpenScadBlock('union()')
                main_building_block_diff.append(main_building_block_inner)
                main_building_block_inner.append(
                    self._add_polygon(None, buildings.intersection(self.bbox), geoms.lower_bound, geoms.upper_bound)
                )

            for altitudearea in sorted(geoms.altitudeareas, key=attrgetter('altitude')):
                if not altitudearea.geometry.intersects(self.bbox):
                    continue

                if altitudearea.altitude2 is not None:
                    name = 'Altitudearea %s-%s' % (altitudearea.altitude/1000, altitudearea.altitude2/1000)
                else:
                    name = 'Altitudearea %s' % (altitudearea.altitude / 1000)

                # why all this buffering?
                # buffer(0) ensures a valid geometry, this is sadly needed sometimes
                # the rest of the buffering is meant to make polygons overlap a little so no glitches appear
                # the intersections below will ensure that they they only overlap with each other and don't eat walls
                geometry = altitudearea.geometry.buffer(0)
                inside_geometry = geometry.intersection(buildings).buffer(0).buffer(0.01, join_style=JOIN_STYLE.mitre)
                outside_geometry = geometry.difference(buildings).buffer(0).buffer(0.01, join_style=JOIN_STYLE.mitre)
                geometry_buffered = geometry.buffer(0.01, join_style=JOIN_STYLE.mitre)
                if geoms.on_top_of_id is None:
                    areas = areas.union(geometry)
                    buildings = buildings.difference(geometry).buffer(0)
                    inside_geometry = inside_geometry.intersection(areas).buffer(0)
                    outside_geometry = outside_geometry.intersection(areas).buffer(0)
                    geometry_buffered = geometry_buffered.intersection(areas).buffer(0)
                outside_geometry = outside_geometry.intersection(self.bbox)

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
                        main_building_block_diff.append(
                            OpenScadBlock('difference()', children=[polygon, slope], comment=name+' inside cut')
                        )

                        # actual thingy
                        if max_slope_altitude > current_upper_bound and inside_geometry.intersects(self.bbox):
                            polygon = self._add_polygon(None, inside_geometry.intersection(self.bbox),
                                                        current_upper_bound-10, max_slope_altitude+10)
                            slope = self._add_slope(bounds, altitudearea.altitude, altitudearea.altitude2,
                                                    altitudearea.point1, altitudearea.point2, bottom=False)
                            main_building_block.append(
                                OpenScadBlock('difference()',
                                              children=[polygon, slope], comment=name + 'outside')
                            )
                    else:
                        if altitudearea.altitude < current_upper_bound:
                            main_building_block_diff.append(
                                self._add_polygon(name+' inside cut', inside_geometry,
                                                  altitudearea.altitude, current_upper_bound+1000)
                            )
                        else:
                            main_building_block.append(
                                self._add_polygon(name+' inside', inside_geometry.intersection(self.bbox),
                                                  min(altitudearea.altitude-700, current_upper_bound-10),
                                                  altitudearea.altitude)
                            )

                if not outside_geometry.is_empty:
                    if altitudearea.altitude2 is not None:
                        min_slope_altitude = min(altitudearea.altitude, altitudearea.altitude2)
                        max_slope_altitude = max(altitudearea.altitude, altitudearea.altitude2)
                        bounds = outside_geometry.bounds

                        polygon = self._add_polygon(None, outside_geometry,
                                                    min_slope_altitude-710, max_slope_altitude+10)
                        slope1 = self._add_slope(bounds, altitudearea.altitude, altitudearea.altitude2,
                                                 altitudearea.point1, altitudearea.point2, bottom=False)
                        slope2 = self._add_slope(bounds, altitudearea.altitude-700, altitudearea.altitude2-700,
                                                 altitudearea.point1, altitudearea.point2, bottom=True)
                        union = OpenScadBlock('union()', children=[slope1, slope2], comment=name+'outside')
                        main_building_block.append(
                            OpenScadBlock('difference()',
                                          children=[polygon, union], comment=name+'outside')
                        )
                    else:
                        if geoms.on_top_of_id is None:
                            lower = geoms.lower_bound
                        else:
                            lower = altitudearea.altitude-700
                            if lower == current_upper_bound:
                                lower -= 10
                        main_building_block.append(
                            self._add_polygon(name+' outside', outside_geometry, lower, altitudearea.altitude)
                        )

                # obstacles
                if altitudearea.altitude2 is not None:
                    obstacles_diff_block = OpenScadBlock('difference()', comment=name + ' obstacles')
                    had_obstacles = False

                    obstacles_block = OpenScadBlock('union()')
                    obstacles_diff_block.append(obstacles_block)

                    min_slope_altitude = min(altitudearea.altitude, altitudearea.altitude2)
                    max_slope_altitude = max(altitudearea.altitude, altitudearea.altitude2)
                    bounds = geometry.bounds

                    for height, obstacles in altitudearea.obstacles.items():
                        height_diff = OpenScadBlock('difference()')
                        had_height_obstacles = None

                        height_union = OpenScadBlock('union()')
                        height_diff.append(height_union)

                        for obstacle in obstacles:
                            if not obstacle.geom.intersects(self.bbox):
                                continue
                            obstacle = obstacle.geom.buffer(0).buffer(0.01, join_style=JOIN_STYLE.mitre)
                            if self.min_width:
                                obstacle = obstacle.union(self._satisfy_min_width(obstacle)).buffer(0)
                            obstacle = obstacle.intersection(geometry_buffered)
                            if not obstacle.is_empty:
                                had_height_obstacles = True
                                had_obstacles = True
                            height_union.append(
                                self._add_polygon(None, obstacle.intersection(self.bbox),
                                                  min_slope_altitude-20, max_slope_altitude+height+10)
                            )

                        if had_height_obstacles:
                            obstacles_block.append(height_diff)
                            height_diff.append(
                                self._add_slope(bounds, altitudearea.altitude+height, altitudearea.altitude2+height,
                                                altitudearea.point1, altitudearea.point2, bottom=False)
                            )

                    if had_obstacles:
                        main_building_block.append(obstacles_diff_block)
                        obstacles_diff_block.append(
                            self._add_slope(bounds, altitudearea.altitude-10, altitudearea.altitude2-10,
                                            altitudearea.point1, altitudearea.point2, bottom=True)
                        )
                else:
                    obstacles_block = OpenScadBlock('union()', comment=name + ' obstacles')
                    had_obstacles = False
                    for height, obstacles in altitudearea.obstacles.items():
                        for obstacle in obstacles:
                            if not obstacle.geom.intersects(self.bbox):
                                continue
                            obstacle = obstacle.geom.buffer(0).buffer(0.01, join_style=JOIN_STYLE.mitre)
                            if self.min_width:
                                obstacle = obstacle.union(self._satisfy_min_width(obstacle)).buffer(0)
                            obstacle = obstacle.intersection(geometry_buffered).intersection(self.bbox)
                            if not obstacle.is_empty:
                                had_obstacles = True
                            obstacles_block.append(
                                self._add_polygon(None, obstacle,
                                                  altitudearea.altitude-10, altitudearea.altitude+height)
                            )

                    if had_obstacles:
                        main_building_block.append(obstacles_block)

            if self.min_width and geoms.on_top_of_id is None:
                # noinspection PyUnboundLocalVariable
                main_building_block_inner.append(
                    self._add_polygon('min width',
                                      self._satisfy_min_width(buildings).intersection(self.bbox).buffer(0),
                                      geoms.lower_bound, geoms.upper_bound)
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
                if output_ring[0] == output_ring[-1]:
                    output_ring = output_ring[:-1]
                output_rings.append(output_ring)
            polygons.append(OpenScadCommand('polygon(%(points)r, %(rings)r, 10);' % {
                'points': points,
                'rings': output_rings,
            }))

        if not polygons:
            return None

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
        cmd = OpenScadBlock('linear_extrude(height=16, convexity=10)', children=[cmd])
        cmd = OpenScadBlock('rotate([0, %f, %f])' % (rotate_y, rotate_z), children=[cmd])
        cmd = OpenScadBlock('translate([%f, %f, %f])' % (point1.x, point1.y, altitude1/1000), children=[cmd])
        return cmd

    def _satisfy_min_width(self, geometry):
        return geometry.buffer(self.min_width/2, join_style=JOIN_STYLE.mitre)

    def render(self, filename=None):
        return self.root.render().encode()
