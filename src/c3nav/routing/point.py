import numpy as np
from django.conf import settings
from django.utils.functional import cached_property

from c3nav.routing.connection import GraphConnection


class GraphPoint():
    def __init__(self, x, y, room=None, rooms=None):
        self.rooms = rooms if rooms is not None else [room]
        self.x = x
        self.y = y
        self.xy = np.array((x, y))

        self.connections = {}
        self.connections_in = {}

    def serialize(self):
        return (
            self.x,
            self.y,
        )

    @cached_property
    def ellipse_bbox(self):
        x = self.x * settings.RENDER_SCALE
        y = self.y * settings.RENDER_SCALE
        return ((x-5, y-5), (x+5, y+5))

    def connect_to(self, other_point):
        connection = GraphConnection(self, other_point)
        self.connections[other_point] = connection
        other_point.connections_in[self] = connection
