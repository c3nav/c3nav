import os
import pickle
from collections import OrderedDict
from itertools import permutations

from django.conf import settings

from c3nav.mapdata.models import Level
from c3nav.routing.connection import GraphConnection
from c3nav.routing.level import GraphLevel
from c3nav.routing.point import GraphPoint
from c3nav.routing.room import GraphRoom
from c3nav.routing.router import Router


class Graph():
    default_filename = os.path.join(settings.DATA_DIR, 'graph.pickle')

    def __init__(self):
        self.levels = OrderedDict()
        for level in Level.objects.all():
            self.levels[level.name] = GraphLevel(self, level)

        self.points = []
        self.connections = []
        self.rooms = []
        self.levelconnector_points = {}

        self.transfer_points = []
        self.router = Router()

    def build(self):
        for level in self.levels.values():
            level.build()

        print('Total:')
        self.points = sum((level.points for level in self.levels.values()), [])
        print('%d points' % len(self.points))

        self.rooms = sum((level.rooms for level in self.levels.values()), [])
        print('%d rooms' % len(self.rooms))

        self.connect_levelconnectors()

        print('%d connections' % len(self.connections))
        print()

    def serialize(self):
        for i, room in enumerate(self.rooms):
            room.i = i

        for i, point in enumerate(self.points):
            point.i = i

        rooms = tuple((room.level.level.name, room.geometry, room.mpl_paths) for room in self.rooms)
        points = tuple((point.room.i, point.x, point.y) for point in self.points)
        connections = tuple((conn.from_point.i, conn.to_point.i, conn.distance) for conn in self.connections)

        return (rooms, points, connections)

    def save(self, filename=None):
        if filename is None:
            filename = self.default_filename
        with open(filename, 'wb') as f:
            pickle.dump(self.serialize(), f)

    @classmethod
    def unserialize(cls, data):
        graph = cls()
        rooms, points, connections = data

        graph.rooms = [GraphRoom(graph.levels[room[0]], room[1], room[2]) for room in rooms]
        graph.points = [GraphPoint(graph.rooms[point[0]], point[1], point[2]) for point in points]

        for point in graph.points:
            point.room.points.append(point)

        for room in graph.rooms:
            room.level.rooms.append(room)
            room.level.points.extend(room.points)

        for from_point, to_point, distance in connections:
            graph.add_connection(graph.points[from_point], graph.points[to_point], distance)

        return graph

    @classmethod
    def load(cls, filename=None):
        if filename is None:
            filename = cls.default_filename
        with open(filename, 'rb') as f:
            graph = cls.unserialize(pickle.load(f))
        return graph

    def build_router(self):
        for room in self.rooms:
            room.build_router()
            self.transfer_points.extend(room.router.transfer_points)

        self.router.build(self.transfer_points, global_routing=True)

    def draw_pngs(self, points=True, lines=True, transfer_points=False, transfer_lines=False):
        for level in self.levels.values():
            level.draw_png(points, lines, transfer_points, transfer_lines)

    def add_levelconnector_point(self, levelconnector, point):
        self.levelconnector_points.setdefault(levelconnector.name, []).append(point)

    def connect_levelconnectors(self):
        for levelconnector_name, points in self.levelconnector_points.items():
            for from_point, to_point in permutations(points, 2):
                self.add_connection(from_point, to_point)

    def add_connection(self, from_point, to_point, distance=None):
        self.connections.append(GraphConnection(self, from_point, to_point, distance))
