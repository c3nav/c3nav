import numpy as np
from matplotlib.path import Path
from shapely.geometry import CAP_STYLE, JOIN_STYLE, LineString

from c3nav.mapdata.utils.geometry import assert_multilinestring, assert_multipolygon
from c3nav.routing.area import GraphArea
from c3nav.routing.point import GraphPoint
from c3nav.routing.router import Router
from c3nav.routing.utils.coords import coord_angle, get_coords_angles
from c3nav.routing.utils.mpl import shapely_to_mpl


class GraphRoom():
    def __init__(self, level):
        self.level = level
        self.graph = level.graph

        self.mpl_clear = None

        self.areas = []
        self.points = None
        self.room_transfer_points = None
        self.distances = np.zeros((1, ))

    def serialize(self):
        return (
            self.mpl_clear,
            [area.serialize() for area in self.areas],
            self.points,
            self.room_transfer_points,
            self.distances,
        )

    @classmethod
    def unserialize(cls, level, data):
        room = cls(level)
        room.mpl_clear, areas, room.points, room.room_transfer_points, room.distances = data
        room.areas = tuple(GraphArea(room, *area) for area in areas)
        return room

    # Building the Graph
    def prepare_build(self, geometry):
        self._built_geometry = geometry
        self.clear_geometry = self._built_geometry.buffer(-0.3, join_style=JOIN_STYLE.mitre)

        if self.clear_geometry.is_empty:
            return False

        self._built_points = []

        self.mpl_clear = shapely_to_mpl(self.clear_geometry.buffer(0.01, join_style=JOIN_STYLE.mitre))
        self.mpl_stairs = ()
        for stair_line in assert_multilinestring(self.level.level.geometries.stairs):
            coords = tuple(stair_line.coords)
            self.mpl_stairs += tuple((Path(part), coord_angle(*part)) for part in zip(coords[:-1], coords[1:]))

        self.isolated_areas = []
        return True

    def build_areas(self):
        stairs_areas = self.level.level.geometries.stairs
        stairs_areas = stairs_areas.buffer(0.3, join_style=JOIN_STYLE.mitre, cap_style=CAP_STYLE.flat)
        stairs_areas = stairs_areas.intersection(self._built_geometry)
        self.stairs_areas = assert_multipolygon(stairs_areas)

        isolated_areas = tuple(assert_multipolygon(stairs_areas.intersection(self.clear_geometry)))
        isolated_areas += tuple(assert_multipolygon(self.clear_geometry.difference(stairs_areas)))

        for isolated_area in isolated_areas:
            mpl_clear = shapely_to_mpl(isolated_area.buffer(0.01, join_style=JOIN_STYLE.mitre))
            mpl_stairs = tuple((stair, angle) for stair, angle in self.mpl_stairs
                               if mpl_clear.intersects_path(stair, filled=True))
            area = GraphArea(self, mpl_clear, mpl_stairs)
            area.prepare_build()
            self.areas.append(area)

    def build_points(self):
        narrowed_geometry = self._built_geometry.buffer(-0.6, join_style=JOIN_STYLE.mitre)
        geometry = narrowed_geometry.buffer(0.31, join_style=JOIN_STYLE.mitre).intersection(self.clear_geometry)

        if geometry.is_empty:
            return

        # points with 60cm distance to borders
        polygons = assert_multipolygon(geometry)
        for polygon in polygons:
            self._add_ring(polygon.exterior, want_left=False)

            for interior in polygon.interiors:
                self._add_ring(interior, want_left=True)

        # now fill in missing doorways or similar
        accessible_clear_geometry = geometry.buffer(0.31, join_style=JOIN_STYLE.mitre)
        missing_geometry = self.clear_geometry.difference(accessible_clear_geometry)
        polygons = assert_multipolygon(missing_geometry)
        for polygon in polygons:
            overlaps = polygon.buffer(0.02).intersection(accessible_clear_geometry)
            if overlaps.is_empty:
                continue

            points = []

            # overlaps to non-missing areas
            overlaps = assert_multipolygon(overlaps)
            for overlap in overlaps:
                points += self.add_point(overlap.centroid.coords[0])

            points += self._add_ring(polygon.exterior, want_left=False)

            for interior in polygon.interiors:
                points += self._add_ring(interior, want_left=True)

        # points around steps
        for polygon in self.stairs_areas:
            for ring in (polygon.exterior, )+tuple(polygon.interiors):
                for linestring in assert_multilinestring(ring.intersection(self.clear_geometry)):
                    coords = tuple(linestring.coords)
                    if len(coords) == 2:
                        path = Path(coords)
                        length = abs(np.linalg.norm(path.vertices[0] - path.vertices[1]))
                        for coord in tuple(path.interpolated(int(length / 1.0 + 1)).vertices):
                            self.add_point(coord)
                        continue

                    start = 0
                    for segment in zip(coords[:-1], coords[1:]):
                        path = Path(segment)
                        length = abs(np.linalg.norm(path.vertices[0] - path.vertices[1]))
                        if length < 1.0:
                            coords = (path.vertices[1 if start == 0 else 0], )
                        else:
                            coords = tuple(path.interpolated(int(length / 1.0 + 0.5)).vertices)[start:]
                        for coord in coords:
                            self.add_point(coord)
                        start = 1

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

        points = []
        for coord in coords:
            points += self.add_point(coord)

        return points

    def add_point(self, coord):
        if not self.mpl_clear.contains_point(coord):
            return []
        point = GraphPoint(coord[0], coord[1], self)
        self._built_points.append(point)
        for area in self.areas:
            area.add_point(point)
        return [point]

    def build_connections(self):
        for area in self.areas:
            pass  # area.build_connections()

    def connection_count(self):
        # print(np.count_nonzero(self.distances != np.inf))
        return np.count_nonzero(self.distances != np.inf)

    def finish_build(self):
        self.areas = tuple(self.areas)
        self.points = np.array(tuple(point.i for point in self._built_points))
        self.room_transfer_points = np.array(tuple(i for i in self.points if i in self.level.room_transfer_points))

        mapping = {from_i: to_i for to_i, from_i in enumerate(self.points)}

        self.distances = np.empty(shape=(len(self.points), len(self.points)), dtype=np.float16)
        self.distances[:] = np.inf

        for from_point in self._built_points:
            for to_point, connection in from_point.connections.items():
                if to_point.i in mapping:
                    self.distances[mapping[from_point.i], mapping[to_point.i]] = connection.distance

        for area in self.areas:
            area.finish_build()

    # Routing
    def build_router(self):
        self.router = Router()
        self.router.build(self._built_points)
