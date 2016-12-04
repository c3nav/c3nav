from itertools import permutations

from c3nav.mapdata.models import Level
from c3nav.routing.graph.connection import GraphConnection
from c3nav.routing.graph.level import GraphLevel


class Graph():
    def __init__(self):
        self.levels = {}
        for level in Level.objects.all():
            self.levels[level.name] = GraphLevel(self, level)

        self.connections = []
        self.levelconnector_points = {}

    def build(self):
        for level in self.levels.values():
            level.build()

        self.connect_levelconnectors()

    def draw_pngs(self, points=True, lines=True):
        for level in self.levels.values():
            level.draw_png(points=points, lines=lines)

    def add_levelconnector_point(self, levelconnector, point):
        self.levelconnector_points.setdefault(levelconnector.name, []).append(point)

    def connect_levelconnectors(self):
        for levelconnector_name, points in self.levelconnector_points.items():
            for from_point, to_point in permutations(points, 2):
                self.add_connection(from_point, to_point)

    def add_connection(self, from_point, to_point):
        self.connections.append(GraphConnection(self, from_point, to_point))
