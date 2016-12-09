import os
import pickle
from collections import OrderedDict

from django.conf import settings

from c3nav.mapdata.models import Level
from c3nav.mapdata.models.geometry import LevelConnector
from c3nav.routing.connection import GraphConnection
from c3nav.routing.level import GraphLevel
from c3nav.routing.point import GraphPoint
from c3nav.routing.room import GraphRoom
from c3nav.routing.router import Router


class Graph:
    default_filename = os.path.join(settings.DATA_DIR, 'graph.pickle')

    def __init__(self):
        self.levels = OrderedDict()
        for level in Level.objects.all():
            self.levels[level.name] = GraphLevel(self, level)

        self.points = []
        self.connections = []
        self.rooms = []

        self.level_transfer_points = []
        self.levelconnector_points = {}

    def build(self):
        for level in self.levels.values():
            level.build()

        self.rooms = sum((level.rooms for level in self.levels.values()), [])
        self.points = sum((level.points for level in self.levels.values()), [])

        print()
        self.connect_levelconnectors()

        print()
        print('Total:')
        print('%d points' % len(self.points))
        print('%d rooms' % len(self.rooms))
        print('%d level transfer points' % len(self.level_transfer_points))
        print('%d connections' % len(self.connections))

        print()
        print('Points per room:')
        for name, level in self.levels.items():
            print(('Level %s:' % name), *(sorted((len(room.points) for room in level.rooms), reverse=True)))

    def serialize(self):
        for i, room in enumerate(self.rooms):
            room.i = i

        for i, point in enumerate(self.points):
            point.i = i

        rooms = tuple((room.level.level.name, room.mpl_clear) for room in self.rooms)
        points = tuple((point.x, point.y, tuple(room.i for room in point.rooms)) for point in self.points)
        connections = tuple((conn.from_point.i, conn.to_point.i, conn.distance) for conn in self.connections)

        return rooms, points, connections

    def save(self, filename=None):
        if filename is None:
            filename = self.default_filename
        with open(filename, 'wb') as f:
            pickle.dump(self.serialize(), f)

    @classmethod
    def unserialize(cls, data):
        graph = cls()
        rooms, points, connections = data

        graph.rooms = [GraphRoom(graph.levels[room[0]], mpl_clear=room[1]) for room in rooms]
        graph.points = [GraphPoint(point[0], point[1], rooms=tuple(graph.rooms[i] for i in point[2]))
                        for point in points]

        for point in graph.points:
            for room in point.rooms:
                room.points.append(point)

        for name, level in graph.levels.items():
            level.rooms = [room for room in graph.rooms if room.level == level]
            level.points = list(set(sum((room.points for room in level.rooms), [])))
            level.room_transfer_points = [point for point in level.points if len(point.rooms) > 1]

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

        self.router = Router()
        self.router.build(self.transfer_points, global_routing=True)

    def draw_pngs(self, points=True, lines=True):
        for level in self.levels.values():
            level.draw_png(points, lines)

    def add_levelconnector_point(self, levelconnector, point):
        self.levelconnector_points.setdefault(levelconnector.name, []).append(point)

    def connect_levelconnectors(self):
        for levelconnector in LevelConnector.objects.all():
            center = levelconnector.geometry.centroid
            points = self.levelconnector_points.get(levelconnector.name, [])
            rooms = tuple(set(sum((point.rooms for point in points), [])))

            if len(rooms) < 2:
                print('levelconnector %s on levels %s at (%.2f, %.2f) has <2 rooms (%d%s)!' %
                      (levelconnector.name, ', '.join(level.name for level in levelconnector.levels.all()),
                       center.x, center.y, len(rooms), (' on level '+rooms[0].level.level.name) if rooms else ''))
                continue

            center_point = GraphPoint(center.x, center.y, rooms=rooms)
            self.points.append(center_point)

            levels = tuple(set(room.level for room in rooms))
            for level in levels:
                level.room_transfer_points.append(center_point)
                level.points.append(center_point)

            for room in rooms:
                room.points.append(center_point)

            for point in points:
                center_point.connect_to(point)
                point.connect_to(center_point)

    def add_connection(self, from_point, to_point, distance=None):
        self.connections.append(GraphConnection(self, from_point, to_point, distance))
