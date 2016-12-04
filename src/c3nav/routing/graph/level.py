import os
from itertools import permutations

from django.conf import settings
from PIL import Image, ImageDraw
from shapely.geometry import JOIN_STYLE

from c3nav.mapdata.utils import assert_multipolygon
from c3nav.routing.graph.point import GraphPoint
from c3nav.routing.graph.room import GraphRoom
from c3nav.routing.utils.base import get_nearest_point
from c3nav.routing.utils.draw import _ellipse_bbox, _line_coords


class GraphLevel():
    def __init__(self, graph, level):
        self.graph = graph
        self.level = level
        self.rooms = []

    def build(self):
        self.collect_rooms()
        self.create_points()

    def collect_rooms(self):
        accessibles = self.level.geometries.accessible
        accessibles = assert_multipolygon(accessibles)
        for geometry in accessibles:
            room = GraphRoom(self, geometry)
            if not room.empty:
                self.rooms.append(room)

    def create_points(self):
        for room in self.rooms:
            room.create_points()

        doors = self.level.geometries.doors
        doors = assert_multipolygon(doors)
        for door in doors:
            polygon = door.buffer(0.01, join_style=JOIN_STYLE.mitre)
            center = door.centroid
            points = []
            for room in self.rooms:
                if polygon.intersects(room.geometry):
                    nearest_point = get_nearest_point(room.clear_geometry, center)
                    point = GraphPoint(room, *nearest_point.coords[0])
                    points.append(point)
                    room.points.append(point)

            if len(points) < 2:
                print('door with <2 rooms (%d) detected!' % len(points))

            for from_point, to_point in permutations(points, 2):
                from_point.connect_to(to_point)

        for room in self.rooms:
            room.connect_points()

    def draw_png(self):
        filename = os.path.join(settings.RENDER_ROOT, 'level-%s.base.png' % self.level.name)
        graph_filename = os.path.join(settings.RENDER_ROOT, 'level-%s.graph.png' % self.level.name)

        im = Image.open(filename)
        height = im.size[1]
        draw = ImageDraw.Draw(im)
        i = 0
        for room in self.rooms:
            for point in room.points:
                for otherpoint, connection in point.connections.items():
                    draw.line(_line_coords(point, otherpoint, height), fill=(255, 100, 100))

            for point in room.points:
                i += 1
                draw.ellipse(_ellipse_bbox(point.x, point.y, height), (200, 0, 0))

        print(i, 'points')

        im.save(graph_filename)
