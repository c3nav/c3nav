import numpy as np
from django.conf import settings
from django.utils.functional import cached_property


class GraphPoint():
    def __init__(self, x, y, room=None, rooms=None):
        self.rooms = rooms if rooms is not None else [room]
        self.x = x
        self.y = y
        self.xy = np.array((x, y))

        # self.level = room.level
        self.graph = self.rooms[0].graph

        self.connections = {}
        self.connections_in = {}

    @cached_property
    def ellipse_bbox(self):
        x = self.x * settings.RENDER_SCALE
        y = self.y * settings.RENDER_SCALE
        return ((x-5, y-5), (x+5, y+5))

    def connect_to(self, to_point):
        self.graph.add_connection(self, to_point)
