from itertools import combinations, permutations

import numpy as np
from matplotlib.path import Path
from shapely.geometry import JOIN_STYLE, LineString

from c3nav.mapdata.utils import assert_multipolygon
from c3nav.routing.graph.point import GraphPoint
from c3nav.routing.utils.coords import get_coords_angles
from c3nav.routing.utils.mpl import polygon_to_mpl_paths


class GraphRoom():
    def __init__(self, level, geometry):
        self.level = level
        self.geometry = geometry
        self.points = []

        self.clear_geometry = geometry.buffer(-0.3, join_style=JOIN_STYLE.mitre)
        self.empty = self.clear_geometry.is_empty

        if not self.empty:
            self.mpl_paths = polygon_to_mpl_paths(self.clear_geometry.buffer(0.01, join_style=JOIN_STYLE.mitre))

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

            points = []

            # overlaps to non-missing areas
            overlaps = assert_multipolygon(overlaps)
            for overlap in overlaps:
                points.append(self.add_point(overlap.centroid.coords[0]))

            points += self._add_ring(polygon.exterior, want_left=False)

            for interior in polygon.interiors:
                points += self._add_ring(interior, want_left=True)

            for from_point, to_point in permutations(points, 2):
                from_point.connect_to(to_point)

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
            points.append(self.add_point(coord))

        return points

    def add_point(self, coord):
        point = GraphPoint(self, *coord)
        self.points.append(point)
        return point

    def connect_points(self):
        room_paths = self.mpl_paths
        for point1, point2 in combinations(self.points, 2):
            path = Path(np.vstack((point1.xy, point2.xy)))
            for room_path in room_paths:
                if room_path.intersects_path(path, False):
                    break
            else:
                point1.connect_to(point2)
                point2.connect_to(point1)
