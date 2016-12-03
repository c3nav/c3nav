from c3nav.mapdata.models import Level
from c3nav.routing.graph.connection import GraphConnection
from c3nav.routing.graph.level import GraphLevel


class Graph():
    def __init__(self):
        self.levels = {}
        self.connections = []

    def build(self):
        for level in Level.objects.all():
            self.levels[level.name] = GraphLevel(self, level)

        for level in self.levels.values():
            level.build()
            level.draw_png()

    def add_connection(self, from_point, to_point):
        self.connections.append(GraphConnection(self, from_point, to_point))
