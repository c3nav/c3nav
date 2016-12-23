import os
from collections import namedtuple

import numpy as np
from django.conf import settings
from django.core.cache import cache
from matplotlib.path import Path
from PIL import Image, ImageDraw
from scipy.sparse.csgraph._shortest_path import shortest_path
from scipy.sparse.csgraph._tools import csgraph_from_dense
from shapely.geometry import CAP_STYLE, JOIN_STYLE, LineString

from c3nav.access.apply import get_public_packages
from c3nav.mapdata.utils.geometry import assert_multilinestring, assert_multipolygon
from c3nav.mapdata.utils.misc import get_public_private_area
from c3nav.routing.point import GraphPoint
from c3nav.routing.room import GraphRoom
from c3nav.routing.utils.base import get_nearest_point
from c3nav.routing.utils.coords import coord_angle
from c3nav.routing.utils.draw import _ellipse_bbox, _line_coords
from c3nav.routing.utils.mpl import shapely_to_mpl


class GraphLevel():
    def __init__(self, graph, level):
        self.graph = graph
        self.level = level
        self.rooms = []

        self.points = []
        self.room_transfer_points = None
        self.level_transfer_points = None
        self.arealocation_points = None

    def serialize(self):
        return (
            [room.serialize() for room in self.rooms],
            self.points,
            self.room_transfer_points,
            self.level_transfer_points,
            self.arealocation_points,
        )

    def unserialize(self, data):
        rooms, self.points, self.room_transfer_points, self.level_transfer_points, self.arealocation_points = data
        self.rooms = tuple(GraphRoom.unserialize(self, room) for room in rooms)

    # Building the Graph
    def build(self):
        print()
        print('Level %s:' % self.level.name)

        self._built_points = []
        self._built_room_transfer_points = []

        self.collect_stairs()
        self.collect_escalators()

        self.collect_rooms()
        print('%d rooms' % len(self.rooms))

        for room in self.rooms:
            room.build_areas()
            room.build_points()

        self.create_doors()
        self.create_oneways()
        self.create_levelconnectors()
        self.create_elevatorlevels()

        self.collect_arealocations()

        self._built_points = sum((room._built_points for room in self.rooms), [])
        self._built_points.extend(self._built_room_transfer_points)

        for room in self.rooms:
            room.build_connections()

        print('%d excludables' % len(self._built_excludables))
        print('%d points' % len(self._built_points))
        print('%d room transfer points' % len(self._built_room_transfer_points))
        print('%d area locations' % len(self._built_arealocations))

    def connection_count(self):
        return sum(room.connection_count() for room in self.rooms)

    def collect_stairs(self):
        self.mpl_stairs = ()
        for stair_line in assert_multilinestring(self.level.geometries.stairs):
            coords = tuple(stair_line.coords)
            self.mpl_stairs += tuple((Path(part), coord_angle(*part)) for part in zip(coords[:-1], coords[1:]))

    def collect_escalators(self):
        self.mpl_escalatorslopes = ()
        for escalatorslope_line in assert_multilinestring(self.level.geometries.escalatorslopes):
            coords = tuple(escalatorslope_line.coords)
            self.mpl_escalatorslopes += tuple((Path(part), coord_angle(*part))
                                              for part in zip(coords[:-1], coords[1:]))

        self._built_escalators = []
        for escalator in self.level.escalators.all():
            mpl_escalator = shapely_to_mpl(escalator.geometry)
            for slope_line, angle in self.mpl_escalatorslopes:
                if mpl_escalator.intersects_path(slope_line, filled=True):
                    self._built_escalators.append(EscalatorData(mpl_escalator, escalator.direction, slope_line, angle))
                    break
            else:
                print('Escalator %s has no slope line!' % escalator.name)
                continue

    def collect_oneways(self):
        self._built_oneways = ()
        for oneway_line in assert_multilinestring(self.level.geometries.oneways):
            coords = tuple(oneway_line.coords)
            self._built_oneways += tuple((Path(part), coord_angle(*part))
                                         for part in zip(coords[:-1], coords[1:]))

    def collect_rooms(self):
        accessibles = self.level.geometries.accessible_without_oneways
        accessibles = assert_multipolygon(accessibles)
        for geometry in accessibles:
            room = GraphRoom(self)
            if room.prepare_build(geometry):
                self.rooms.append(room)

    def collect_arealocations(self):
        public_packages = get_public_packages()

        self._built_arealocations = {}
        self._built_excludables = {}
        for excludable in self.level.arealocations.all():
            self._built_arealocations[excludable.name] = excludable.geometry
            if excludable.routing_inclusion != 'default' or excludable.package not in public_packages:
                self._built_excludables[excludable.name] = excludable.geometry

        public_area, private_area = get_public_private_area(self.level)

        self._built_arealocations[':public'] = public_area
        self._built_excludables[':public'] = public_area

        self._built_arealocations[':nonpublic'] = private_area
        self._built_excludables[':nonpublic'] = private_area

        # add points inside arealocations to be able to route to its borders
        for excludable in self._built_arealocations.values():
            smaller = excludable.buffer(-0.05, join_style=JOIN_STYLE.mitre)
            for room in self.rooms:
                room.add_points_on_rings(assert_multipolygon(smaller))

        # add points outside excludables so if excluded you can walk around them
        for excludable in self._built_excludables.values():
            for polygon in assert_multipolygon(excludable.buffer(0.28, join_style=JOIN_STYLE.mitre)):
                for room in self.rooms:
                    room._add_ring(polygon.exterior, want_left=True)

                    for interior in polygon.interiors:
                        room._add_ring(interior, want_left=False)

    def create_doors(self):
        doors = self.level.geometries.doors
        doors = assert_multipolygon(doors)
        for door in doors:
            polygon = door.buffer(0.01, join_style=JOIN_STYLE.mitre)
            center = door.centroid

            num_points = 0
            connected_rooms = set()
            points = []
            for room in self.rooms:
                if not polygon.intersects(room._built_geometry):
                    continue

                for subpolygon in assert_multipolygon(polygon.intersection(room._built_geometry)):
                    connected_rooms.add(room)
                    nearest_point = get_nearest_point(room.clear_geometry, subpolygon.centroid)
                    point, = room.add_point(nearest_point.coords[0])
                    points.append(point)

            if len(points) < 2:
                print('door with <2 points (%d) detected at (%.2f, %.2f)' % (num_points, center.x, center.y))
                continue

            center_point = GraphPoint(center.x, center.y, None)
            self._built_room_transfer_points.append(center_point)
            for room in connected_rooms:
                room._built_points.append(center_point)

            for point in points:
                center_point.connect_to(point)
                point.connect_to(center_point)

    def create_oneways(self):
        oneways = self.level.geometries.oneways
        oneways = assert_multilinestring(oneways)

        segments = ()
        for oneway in oneways:
            coords = tuple(oneway.coords)
            segments += tuple((Path(part), coord_angle(*part))
                              for part in zip(coords[:-1], coords[1:]))

        for oneway, oneway_angle in segments:
            line_string = LineString(tuple(oneway.vertices))
            polygon = line_string.buffer(0.10, join_style=JOIN_STYLE.mitre, cap_style=CAP_STYLE.flat)
            center = polygon.centroid

            num_points = 0
            connected_rooms = set()
            points = []
            for room in self.rooms:
                if not polygon.intersects(room._built_geometry):
                    continue

                for subpolygon in assert_multipolygon(polygon.intersection(room._built_geometry)):
                    connected_rooms.add(room)
                    nearest_point = get_nearest_point(room.clear_geometry, subpolygon.centroid)
                    point, = room.add_point(nearest_point.coords[0])
                    points.append(point)

            if len(points) < 2:
                print('oneway with <2 points (%d) detected at (%.2f, %.2f)' % (num_points, center.x, center.y))
                continue

            center_point = GraphPoint(center.x, center.y, None)
            self._built_room_transfer_points.append(center_point)
            for room in connected_rooms:
                room._built_points.append(center_point)

            for point in points:
                angle = coord_angle(point.xy, center_point.xy)
                angle_diff = ((oneway_angle - angle + 180) % 360) - 180
                direction_up = (angle_diff > 0)
                if direction_up:
                    point.connect_to(center_point)
                else:
                    center_point.connect_to(point)

    def create_levelconnectors(self):
        for levelconnector in self.level.levelconnectors.all():
            polygon = levelconnector.geometry

            for room in self.rooms:
                if not polygon.intersects(room._built_geometry):
                    continue

                for subpolygon in assert_multipolygon(polygon.intersection(room._built_geometry)):
                    point = subpolygon.centroid
                    if not point.within(room.clear_geometry):
                        point = get_nearest_point(room.clear_geometry, point)
                    point, = room.add_point(point.coords[0])
                    self.graph.add_levelconnector_point(levelconnector, point)

    def create_elevatorlevels(self):
        for elevatorlevel in self.level.elevatorlevels.all():
            center = elevatorlevel.geometry.centroid
            mpl_elevatorlevel = shapely_to_mpl(elevatorlevel.geometry)
            for room in self.rooms:
                if not room.mpl_clear.contains_point(center.coords[0]):
                    continue

                room._built_is_elevatorlevel = True

                points = [point for point in room._built_points if mpl_elevatorlevel.contains_point(point.xy)]
                if not points:
                    print('elevatorlevel %s has 0 points!' % (elevatorlevel.name))
                    break
                elif len(points) > 1:
                    print('elevatorlevel %s has > 2 points!' % (elevatorlevel.name))
                    break

                point = points[0]
                self.graph.add_elevatorlevel_point(elevatorlevel, point)
                break

    def finish_build(self):
        self.rooms = tuple(self.rooms)
        self.points = tuple(point.i for point in self._built_points)
        self.room_transfer_points = tuple(point.i for point in self._built_room_transfer_points)
        self.level_transfer_points = tuple(i for i in self.points if i in self.graph.level_transfer_points)

        self.collect_arealocation_points()

        for room in self.rooms:
            room.finish_build()

    def collect_arealocation_points(self):
        self.arealocation_points = {}

        for room in self.rooms:
            room.excludables = []

        for name, arealocation in self._built_arealocations.items():
            mpl_area = shapely_to_mpl(arealocation)

            rooms = [room for room in self.rooms
                     if any(room.mpl_clear.intersects_path(exterior, filled=True) for exterior in mpl_area.exteriors)]
            possible_points = tuple(point for point in sum((room._built_points for room in rooms), []) if point.room)
            points = tuple(point for point in possible_points if mpl_area.contains_point(point.xy))
            self.arealocation_points[name] = tuple(point.i for point in points)

            if name in self._built_excludables:
                for room in set(point.room for point in points):
                    room.excludables.append(name)

    # Drawing
    ctype_colors = {
        '': (50, 200, 0),
        'stairs_up': (255, 50, 50),
        'stairs_down': (255, 50, 50),
        'escalator_up': (255, 150, 0),
        'escalator_down': (200, 100, 0),
        'elevator_up': (200, 0, 200),
        'elevator_down': (200, 0, 200),
    }

    def draw_png(self, points=True, lines=True):
        filename = os.path.join(settings.RENDER_ROOT, 'base-level-%s.png' % self.level.name)
        graph_filename = os.path.join(settings.RENDER_ROOT, 'graph-level-%s.png' % self.level.name)

        im = Image.open(filename)
        height = im.size[1]
        draw = ImageDraw.Draw(im)

        if lines:
            for room in self.rooms:
                # noinspection PyTypeChecker
                for ctype, from_i, to_i in np.argwhere(room.distances != np.inf):
                    draw.line(_line_coords(self.graph.points[room.points[from_i]],
                                           self.graph.points[room.points[to_i]], height),
                              fill=self.ctype_colors[room.ctypes[ctype]])

        if points:
            for point_i in self.points:
                point = self.graph.points[point_i]
                draw.ellipse(_ellipse_bbox(point.x, point.y, height), (200, 0, 0))

            for point_i in self.room_transfer_points:
                point = self.graph.points[point_i]
                draw.ellipse(_ellipse_bbox(point.x, point.y, height), (0, 0, 255))

            for point_i in self.level_transfer_points:
                point = self.graph.points[point_i]
                draw.ellipse(_ellipse_bbox(point.x, point.y, height), (0, 180, 0))

        if lines:
            for room in self.rooms:
                # noinspection PyTypeChecker
                for ctype, from_i, to_i in np.argwhere(room.distances != np.inf):
                    if room.points[from_i] in room.room_transfer_points:
                        draw.line(_line_coords(self.graph.points[room.points[from_i]],
                                               self.graph.points[room.points[to_i]], height), fill=(0, 255, 255))

        im.save(graph_filename)

    # Routing
    def build_routers(self, allowed_ctypes, allow_nonpublic, avoid, include):
        routers = {}

        empty_distances = np.empty(shape=(len(self.room_transfer_points),) * 2, dtype=np.float16)
        empty_distances[:] = np.inf

        sparse_distances = empty_distances.copy()

        room_transfers = np.zeros(shape=(len(self.room_transfer_points),) * 2, dtype=np.int16)
        room_transfers[:] = -1

        for i, room in enumerate(self.rooms):
            router = room.build_router(allowed_ctypes, allow_nonpublic, avoid, include)
            routers[room] = router

            room_distances = empty_distances.copy()
            in_room_i = np.array(tuple(room.points.index(point) for point in room.room_transfer_points), dtype=int)
            in_level_i = np.array(tuple(self.room_transfer_points.index(point)
                                        for point in room.room_transfer_points), dtype=int)

            room_distances[in_level_i[:, None], in_level_i] = router.shortest_paths[in_room_i[:, None], in_room_i]
            better = room_distances < sparse_distances
            sparse_distances[better] = room_distances[better]
            room_transfers[better] = i

        g_sparse = csgraph_from_dense(sparse_distances, null_value=np.inf)
        shortest_paths, predecessors = shortest_path(g_sparse, return_predecessors=True)

        routers[self] = LevelRouter(shortest_paths, predecessors, room_transfers)
        return routers

    def nearest_point(self, point, mode):
        cache_key = ('c3nav__routing__nearest_point__%s__%s__%.2f_%.2f__%s' %
                     (self.graph.mtime, self.level.name, point[0], point[1], mode))
        nearest_point = cache.get(cache_key, None)
        if nearest_point is None:
            nearest_point = self._nearest_point(point, mode)
            cache.set(cache_key, nearest_point, 60)
        if nearest_point is None:
            return None
        return self.graph.points[nearest_point]

    def _nearest_point(self, point, mode):
        points = self.connected_points(point, mode)
        if not points:
            return None

        nearest_point = min(points.items(), key=lambda x: x[1][0])
        return nearest_point[0]

    def connected_points(self, point, mode):
        cache_key = ('c3nav__routing__connected_points__%s__%s__%.2f_%.2f__%s' %
                     (self.graph.mtime, self.level.name, point[0], point[1], mode))
        points = cache.get(cache_key, None)
        if points is None or True:
            points = self._connected_points(point, mode)
            cache.set(cache_key, points, 60)
        return points

    def _connected_points(self, point, mode):
        for room in self.rooms:
            if room.contains_point(point):
                return room.connected_points(point, mode)
        return {}


LevelRouter = namedtuple('LevelRouter', ('shortest_paths', 'predecessors', 'room_transfers', ))
EscalatorData = namedtuple('EscalatorData', ('mpl_geom', 'direction_up', 'slope', 'angle'))
