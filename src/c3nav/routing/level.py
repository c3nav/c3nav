import os

import numpy as np
from django.conf import settings
from PIL import Image, ImageDraw
from shapely.geometry import JOIN_STYLE

from c3nav.mapdata.utils.geometry import assert_multipolygon
from c3nav.routing.point import GraphPoint
from c3nav.routing.room import GraphRoom
from c3nav.routing.utils.base import get_nearest_point
from c3nav.routing.utils.draw import _ellipse_bbox, _line_coords


class GraphLevel():
    def __init__(self, graph, level):
        self.graph = graph
        self.level = level
        self.rooms = []

        self.points = []
        self.room_transfer_points = None
        self.level_transfer_points = None

    def serialize(self):
        return (
            [room.serialize() for room in self.rooms],
            self.points,
            self.room_transfer_points,
            self.level_transfer_points,
        )

    def unserialize(self, data):
        rooms, self.points, self.room_transfer_points, self.level_transfer_points = data
        self.rooms = tuple(GraphRoom.unserialize(self, room) for room in rooms)

    # Building the Graph
    def build(self):
        print()
        print('Level %s:' % self.level.name)

        self._built_points = []
        self._built_room_transfer_points = []

        self.collect_rooms()
        print('%d rooms' % len(self.rooms))

        for room in self.rooms:
            room.build_areas()
            room.build_points()

        self.create_doors()
        self.create_levelconnectors()

        self._built_points = sum((room._built_points for room in self.rooms), [])
        self._built_points.extend(self._built_room_transfer_points)

        for room in self.rooms:
            room.build_connections()

        print('%d points' % len(self._built_points))
        print('%d room transfer points' % len(self._built_room_transfer_points))

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

    def finish_build(self):
        self.rooms = tuple(self.rooms)
        self.points = np.array(tuple(point.i for point in self._built_points))
        self.room_transfer_points = np.array(tuple(point.i for point in self._built_room_transfer_points))
        self.level_transfer_points = np.array(tuple(i for i in self.points if i in self.graph.level_transfer_points))

        for room in self.rooms:
            room.finish_build()

    # Drawing
    def draw_png(self, points=True, lines=True):
        filename = os.path.join(settings.RENDER_ROOT, 'level-%s.base.png' % self.level.name)
        graph_filename = os.path.join(settings.RENDER_ROOT, 'level-%s.graph.png' % self.level.name)

        im = Image.open(filename)
        height = im.size[1]
        draw = ImageDraw.Draw(im)
        if lines:
            for point in self.points:
                for otherpoint, connection in point.connections.items():
                    draw.line(_line_coords(point, otherpoint, height), fill=(255, 100, 100))

        if points:
            for point in self.points:
                draw.ellipse(_ellipse_bbox(point.x, point.y, height), (200, 0, 0))

        for point in self._built_room_transfer_points:
            draw.ellipse(_ellipse_bbox(point.x, point.y, height), (0, 0, 255))

        for point in self._built_room_transfer_points:
            for otherpoint, connection in point.connections.items():
                draw.line(_line_coords(point, otherpoint, height), fill=(0, 255, 255))

        im.save(graph_filename)

    # Routing
    def build_router(self):
        for room in self.rooms:
            room.build_router()
