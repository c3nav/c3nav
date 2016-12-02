import os
from math import atan2, pi, degrees

from PIL import Image
from PIL import ImageDraw
from django.conf import settings
from kombu.utils import cached_property
from shapely.geometry import JOIN_STYLE
from shapely.geometry import LineString
from shapely.geometry import MultiPolygon
from shapely.geometry import Point
from shapely.geometry import Polygon

from c3nav.mapdata.models import Level


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
        accessibles = [accessibles] if isinstance(accessibles, Polygon) else accessibles.geoms
        for geometry in accessibles:
            self.rooms.append(GraphRoom(self, geometry))

    def create_points(self):
        for room in self.rooms:
            room.create_points()

    def _ellipse_bbox(self, x, y, height):
        x *= settings.RENDER_SCALE
        y *= settings.RENDER_SCALE
        y = height-y
        return ((x - 2, y - 2), (x + 2, y + 2))

    def draw_png(self):
        filename = os.path.join(settings.RENDER_ROOT, 'level-%s.png' % self.level.name)
        graph_filename = os.path.join(settings.RENDER_ROOT, 'level-%s-graph.png' % self.level.name)

        im = Image.open(filename)
        height = im.size[1]
        draw = ImageDraw.Draw(im)
        i = 0
        for room in self.rooms:
            for point in room.points:
                i += 1
                draw.ellipse(self._ellipse_bbox(point.x, point.y, height), (255, 0, 0))
        print(i, 'points')

        im.save(graph_filename)


class GraphRoom():
    def __init__(self, level, geometry):
        self.level = level
        self.geometry = geometry
        self.points = []

    def cleanup_coords(self, coords):
        result = []
        last_coord = coords[-1]
        for coord in coords:
            if ((coord[0] - last_coord[0]) ** 2 + (coord[1] - last_coord[1]) ** 2) ** 0.5 >= 0.01:
                result.append(coord)
            last_coord = coord
        return result

    def coord_angle(self, coord1, coord2):
        return degrees(atan2(-(coord2[1] - coord1[1]), coord2[0] - coord1[0])) % 360

    def split_coords_by_angle(self, geom):
        coords = list(self.cleanup_coords(geom.coords))
        last_coords = coords[-2:]
        last_angle = self.coord_angle(last_coords[-2], last_coords[-1])
        left = []
        right = []
        for coord in coords:
            angle = self.coord_angle(last_coords[-1], coord)
            angle_diff = (last_angle-angle) % 360
            if angle_diff < 180:
                left.append(last_coords[-1])
            else:
                right.append(last_coords[-1])
            last_coords.append(coord)
            last_angle = angle

        if not geom.is_ccw:
            left, right = right, left

        return left, right

    def create_points(self):
        original_geometry = self.geometry
        geometry = original_geometry.buffer(-0.6, join_style=JOIN_STYLE.mitre)

        if geometry.is_empty:
            return

        if isinstance(geometry, Polygon):
            polygons = [geometry]
        else:
            polygons = geometry.geoms

        for polygon in polygons:
            left, right = self.split_coords_by_angle(polygon.exterior)
            for x, y in right:
                self.points.append(GraphPoint(self, x, y))

            for interior in polygon.interiors:
                left, right = self.split_coords_by_angle(interior)
                for x, y in left:
                    self.points.append(GraphPoint(self, x, y))


class GraphPoint():
    def __init__(self, room, x, y):
        self.room = room
        self.x = x
        self.y = y

    @cached_property
    def ellipse_bbox(self):
        x = self.x * settings.RENDER_SCALE
        y = self.y * settings.RENDER_SCALE
        return ((x-5, y-5), (x+5, y+5))


class Graph():
    def __init__(self):
        self.levels = {}

    def build(self):
        for level in Level.objects.all():
            self.levels[level.name] = GraphLevel(self, level)

        for level in self.levels.values():
            level.build()
            level.draw_png()


