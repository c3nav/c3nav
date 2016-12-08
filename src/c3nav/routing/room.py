from itertools import combinations, permutations

import numpy as np
from matplotlib.path import Path
from shapely.geometry import CAP_STYLE, JOIN_STYLE, LineString

from c3nav.mapdata.utils.geometry import assert_multilinestring, assert_multipolygon
from c3nav.routing.point import GraphPoint
from c3nav.routing.router import Router
from c3nav.routing.utils.coords import coord_angle, get_coords_angles
from c3nav.routing.utils.mpl import shapely_to_mpl


class GraphRoom():
    def __init__(self, level, geometry, mpl_clear=None):
        self.level = level
        self.graph = level.graph

        self.geometry = geometry
        self.points = []

        self.clear_geometry = geometry.buffer(-0.3, join_style=JOIN_STYLE.mitre)
        self.empty = self.clear_geometry.is_empty

        self.router = Router()

        if not self.empty:
            self.level.rooms.append(self)
            self.graph.rooms.append(self)

        self.mpl_clear = mpl_clear

    def prepare_build(self):
        self.mpl_clear = shapely_to_mpl(self.clear_geometry.buffer(0.01, join_style=JOIN_STYLE.mitre))
        self.mpl_stairs = ()
        for stair_line in self.level.level.geometries.stairs:
            coords = tuple(stair_line.coords)
            self.mpl_stairs += tuple((Path(part), coord_angle(*part)) for part in zip(coords[:-1], coords[1:]))

    def build_points(self):
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

            for from_point, to_point in permutations(points, 2):
                from_point.connect_to(to_point)

        # points around steps
        stairs_areas = self.level.level.geometries.stairs
        stairs_areas = stairs_areas.buffer(0.3, join_style=JOIN_STYLE.mitre, cap_style=CAP_STYLE.flat)
        stairs_areas = assert_multipolygon(stairs_areas.intersection(self.geometry))
        for polygon in stairs_areas:
            for ring in (polygon.exterior, )+tuple(polygon.interiors):
                print('#')
                for linestring in assert_multilinestring(ring.intersection(self.clear_geometry)):
                    print(' -')
                    coords = tuple(linestring.coords)
                    start = 1
                    for segment in zip(coords[:-1], coords[1:]):
                        print('  .')
                        path = Path(segment)
                        length = abs(np.linalg.norm(path.vertices[0] - path.vertices[1]))
                        for coord in tuple(path.interpolated(max(int(length / 1.0), 1)).vertices)[start:-1]:
                            self.add_point(coord)
                        start = 0

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
        return [point]

    def build_connections(self):
        i = 0
        for point1, point2 in combinations(self.points, 2):
            path = Path(np.vstack((point1.xy, point2.xy)))

            # lies within room
            if self.mpl_clear.intersects_path(path):
                continue

            # stair checker
            angle = coord_angle(point1.xy, point2.xy)
            valid = True
            for stair_path, stair_angle in self.mpl_stairs:
                if not path.intersects_path(stair_path):
                    continue

                angle_diff = ((stair_angle - angle + 180) % 360) - 180
                up = angle_diff < 0  # noqa
                if not (70 < abs(angle_diff) < 110):
                    valid = False
                    break

            if not valid:
                continue

            point1.connect_to(point2)
            point2.connect_to(point1)
            i += 1

    def build_router(self):
        self.router.build(self.points)
