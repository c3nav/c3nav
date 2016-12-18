import os
from collections import namedtuple

import numpy as np
from django.conf import settings
from matplotlib.path import Path
from PIL import Image, ImageDraw
from scipy.sparse.csgraph._shortest_path import shortest_path
from scipy.sparse.csgraph._tools import csgraph_from_dense
from shapely.geometry import JOIN_STYLE

from c3nav.mapdata.utils.geometry import assert_multilinestring, assert_multipolygon
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
        self.create_levelconnectors()
        self.create_elevatorlevels()

        self._built_points = sum((room._built_points for room in self.rooms), [])
        self._built_points.extend(self._built_room_transfer_points)

        for room in self.rooms:
            room.build_connections()

        self.collect_arealocations()

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

    def collect_rooms(self):
        accessibles = self.level.geometries.accessible
        accessibles = assert_multipolygon(accessibles)
        for geometry in accessibles:
            room = GraphRoom(self)
            if room.prepare_build(geometry):
                self.rooms.append(room)

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
                    room._built_points.append(point)
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

    def collect_arealocations(self):
        self._built_arealocations = {}
        for arealocation in self.level.arealocations.all():
            self._built_arealocations[arealocation.name] = shapely_to_mpl(arealocation.geometry)

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
        for name, mpl_arealocation in self._built_arealocations.items():
            rooms = [room for room in self.rooms
                     if room.mpl_clear.intersects_path(mpl_arealocation.exterior, filled=True)]
            possible_points = tuple(point for point in sum((room._built_points for room in rooms), []) if point.room)
            self.arealocation_points[name] = tuple(point.i for point in possible_points
                                                   if mpl_arealocation.contains_point(point.xy))

    # Drawing
    ctype_colors = {
        '': (50, 200, 0),
        'steps_up': (255, 50, 50),
        'steps_down': (255, 50, 50),
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
    def build_routers(self, allowed_ctypes):
        routers = {}

        empty_distances = np.empty(shape=(len(self.room_transfer_points),) * 2, dtype=np.float16)
        empty_distances[:] = np.inf

        sparse_distances = empty_distances.copy()

        room_transfers = np.zeros(shape=(len(self.room_transfer_points),) * 2, dtype=np.int16)
        room_transfers[:] = -1

        for i, room in enumerate(self.rooms):
            router = room.build_router(allowed_ctypes)
            routers[room] = router

            room_distances = empty_distances.copy()
            in_room_i = np.array(tuple(room.points.index(point) for point in room.room_transfer_points))
            in_level_i = np.array(tuple(self.room_transfer_points.index(point)
                                        for point in room.room_transfer_points))

            room_distances[in_level_i[:, None], in_level_i] = router.shortest_paths[in_room_i[:, None], in_room_i]
            better = room_distances < sparse_distances
            sparse_distances[better] = room_distances[better]
            room_transfers[better] = i

        g_sparse = csgraph_from_dense(sparse_distances, null_value=np.inf)
        shortest_paths, predecessors = shortest_path(g_sparse, return_predecessors=True)

        routers[self] = LevelRouter(shortest_paths, predecessors, room_transfers)
        return routers


LevelRouter = namedtuple('LevelRouter', ('shortest_paths', 'predecessors', 'room_transfers', ))
EscalatorData = namedtuple('EscalatorData', ('mpl_geom', 'direction_up', 'slope', 'angle'))
