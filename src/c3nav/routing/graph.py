import os
from itertools import permutations

from django.conf import settings
from django.utils.functional import cached_property
from PIL import Image, ImageDraw
from shapely.geometry import JOIN_STYLE, LineString, Polygon

from c3nav.mapdata.models import Level
from c3nav.routing.utils import assert_multipolygon, get_coords_angles, get_nearest_point, polygon_to_mpl_path


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
                print('waaaah')

            for from_point, to_point in permutations(points, 2):
                from_point.connect_to(to_point)

    def _ellipse_bbox(self, x, y, height):
        x *= settings.RENDER_SCALE
        y *= settings.RENDER_SCALE
        y = height-y
        return ((x - 2, y - 2), (x + 2, y + 2))

    def _line_coords(self, from_point, to_point, height):
        return (from_point.x * settings.RENDER_SCALE, height - (from_point.y * settings.RENDER_SCALE),
                to_point.x * settings.RENDER_SCALE, height - (to_point.y * settings.RENDER_SCALE))

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
                for otherpoint, connection in point.connections.items():
                    draw.line(self._line_coords(point, otherpoint, height), fill=(255, 0, 0))
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

        # points with 60cm distance to borders
        polygons = assert_multipolygon(geometry)
        for polygon in polygons:
            self._add_ring(polygon.exterior, want_left=False)

            for interior in polygon.interiors:
                self._add_ring(interior, want_left=True)

        # now fill in missing doorways or similar
        missing_geometry = self.clear_geometry.difference(geometry.buffer(0.61, join_style=JOIN_STYLE.mitre))
        polygons = assert_multipolygon(missing_geometry)
        for polygon in polygons:
            overlaps = polygon.buffer(0.62).intersection(geometry)
            if overlaps.is_empty:
                continue
            overlaps = assert_multipolygon(overlaps)
            for overlap in overlaps:
                self.points.append(GraphPoint(self, *overlap.centroid.coords[0]))

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
        self.connections = {}
        self.connections_in = {}

    @cached_property
    def ellipse_bbox(self):
        x = self.x * settings.RENDER_SCALE
        y = self.y * settings.RENDER_SCALE
        return ((x-5, y-5), (x+5, y+5))

    def connect_to(self, to_point):
        self.room.level.graph.add_connection(self, to_point)


class GraphConnection():
    def __init__(self, graph, from_point, to_point):
        if to_point in from_point.connections:
            raise ValueError('already connected')

        self.graph = graph
        from_point.connections[to_point] = self
        to_point.connections_in[from_point] = self


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
