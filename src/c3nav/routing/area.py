from itertools import combinations

import numpy as np
from matplotlib.path import Path

from c3nav.routing.utils.coords import coord_angle


class GraphArea():
    def __init__(self, room, mpl_clear, mpl_stairs, escalators, points=None):
        self.room = room
        self.graph = room.graph

        self.mpl_clear = mpl_clear
        self.mpl_stairs = mpl_stairs
        self.escalators = escalators

        self.points = points

    def serialize(self):
        return (
            self.mpl_clear,
            self.mpl_stairs,
            self.escalators,
            self.points,
        )

    def prepare_build(self):
        self._built_points = []

    def build_connections(self):
        for point1, point2 in combinations(self._built_points, 2):

            there, back, distance = self.check_connection(point1.xy, point2.xy)

            if there is not None:
                point1.connect_to(point2, distance=distance, ctype=there)

            if back is not None:
                point2.connect_to(point1, distance=distance, ctype=back)

    def check_connection(self, point1, point2):
        path = Path(np.vstack((point1, point2)))
        distance = abs(np.linalg.norm(point1 - point2))

        # lies within room
        if self.mpl_clear.intersects_path(path):
            return None, None, None

        if self.room.stuffedareas.intersects_path(path, filled=True):
            distance *= 2.5

        # stair checker
        angle = coord_angle(point1, point2)
        stair_direction_up = None
        for stair_path, stair_angle in self.mpl_stairs:
            if not path.intersects_path(stair_path):
                continue

            angle_diff = ((stair_angle - angle + 180) % 360) - 180

            new_direction_up = (angle_diff > 0)
            if stair_direction_up is None:
                stair_direction_up = new_direction_up
            elif stair_direction_up != new_direction_up:
                return None, None, None

            if not (40 < abs(angle_diff) < 150):
                return None, None, None

        # escalator checker
        angle = coord_angle(point1, point2)
        escalator_direction_up = None
        escalator_swap_direction = False
        for escalator in self.escalators:
            if not escalator.mpl_geom.intersects_path(path, filled=True):
                continue

            if escalator_direction_up is not None:
                # only one escalator per connection
                return None, None, None

            angle_diff = ((escalator.angle - angle + 180) % 360) - 180

            escalator_direction_up = (angle_diff > 0)
            escalator_swap_direction = (escalator_direction_up != escalator.direction_up)

        if stair_direction_up is not None:
            return (
                ('stairs_up' if stair_direction_up else 'stairs_down'),
                ('stairs_down' if stair_direction_up else 'stairs_up'),
                distance,
            )
        elif escalator_direction_up is not None:
            if not escalator_swap_direction:
                return ('escalator_up' if escalator_direction_up else 'escalator_down'), None, distance
            else:
                return None, ('escalator_down' if escalator_direction_up else 'escalator_up'), distance

        return '', '', distance

    def add_point(self, point):
        if not self.mpl_clear.contains_point(point.xy):
            return False
        self._built_points.append(point)
        return True

    def finish_build(self):
        self.points = np.array(tuple(point.i for point in self._built_points))

        set_points = set(self.points)
        if len(self.points) != len(set_points):
            print('ERROR: POINTS DOUBLE-ADDED (AREA)', len(self.points), len(set_points))

    def contains_point(self, point):
        return self.mpl_clear.contains_point(point)

    def connected_points(self, point, mode):
        connections = {}
        for point_i in self.points:
            other_point = self.graph.points[point_i]

            there, back, distance = self.check_connection(point, other_point.xy)
            ctype = there if mode == 'orig' else back
            if ctype is not None:
                connections[point_i] = (distance, ctype)
        return connections
