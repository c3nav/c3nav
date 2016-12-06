import numpy as np
from django.conf import settings
from django.utils.functional import cached_property


class GraphPoint():
    def __init__(self, x, y, room=None, level=None, graph=None):
        self.room = room
        self.level = room.level if level is None and room is not None else level
        self.graph = self.level.graph if graph is None and self.level is not None else graph
        self.x = x
        self.y = y
        self.xy = np.array((x, y))
        self.connections = {}
        self.connections_in = {}
        self.in_room_transfer_distances = None

        if self.room is not None:
            self.room.points.append(self)
        elif self.level is not None:
            self.level.no_room_points.append(self)

        if self.level is not None:
            self.level.points.append(self)
        else:
            self.graph.no_level_points.append(self)

        self.graph.points.append(self)

    @cached_property
    def ellipse_bbox(self):
        x = self.x * settings.RENDER_SCALE
        y = self.y * settings.RENDER_SCALE
        return ((x-5, y-5), (x+5, y+5))

    def connect_to(self, to_point):
        self.graph.add_connection(self, to_point)
