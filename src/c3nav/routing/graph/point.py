from django.conf import settings
from django.utils.functional import cached_property


class GraphPoint():
    def __init__(self, room, x, y):
        self.room = room
        self.x = x
        self.y = y
        self.xy = (x, y)
        self.connections = {}
        self.connections_in = {}
        self.in_room_transfer_distances = None

    @cached_property
    def ellipse_bbox(self):
        x = self.x * settings.RENDER_SCALE
        y = self.y * settings.RENDER_SCALE
        return ((x-5, y-5), (x+5, y+5))

    def connect_to(self, to_point):
        self.room.level.graph.add_connection(self, to_point)
