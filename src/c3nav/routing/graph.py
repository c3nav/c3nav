import os

from django.conf import settings
from django.utils.functional import cached_property
from PIL import Image, ImageDraw
from shapely.geometry import JOIN_STYLE, LineString, Polygon

from c3nav.mapdata.models import Level
from c3nav.routing.utils import get_coords_angles, polygon_to_mpl_path


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

        self.clear_geometry = geometry.buffer(-0.3, join_style=JOIN_STYLE.mitre)

        self.mpl_path = polygon_to_mpl_path(geometry)

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
            self._add_ring(polygon.exterior, want_left=False)

            for interior in polygon.interiors:
                self._add_ring(interior, want_left=True)

    def _add_ring(self, geom, want_left):
        """
        add the points of a ring, but only those that have a specific direction change.
        additionally removes unneeded points if the neighbors can be connected in self.clear_geometry
        :param geom: LinearRing
        :param want_left: True if the direction has to be left, False if it has to be right
        """
        coords = []
        skipped = False
        can_delete_last = False
        for coord, is_left in get_coords_angles(geom):
            if is_left != want_left:
                skipped = True
                continue

            if not skipped and can_delete_last and len(coords) >= 2:
                if LineString((coords[-2], coord)).within(self.clear_geometry):
                    coords[-1] = coord
                    continue

            coords.append(coord)
            can_delete_last = not skipped
            skipped = False

        if not skipped and can_delete_last and len(coords) >= 3:
            if LineString((coords[-2], coords[0])).within(self.clear_geometry):
                coords.pop()

        for coord in coords:
            self.points.append(GraphPoint(self, *coord))


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
