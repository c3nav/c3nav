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
            path = Path(np.vstack((point1.xy, point2.xy)))

            # lies within room
            if self.mpl_clear.intersects_path(path):
                continue

            # stair checker
            angle = coord_angle(point1.xy, point2.xy)
            valid = True
            stair_direction_up = None
            for stair_path, stair_angle in self.mpl_stairs:
                if not path.intersects_path(stair_path):
                    continue

                angle_diff = ((stair_angle - angle + 180) % 360) - 180

                new_direction_up = (angle_diff > 0)
                if stair_direction_up is None:
                    stair_direction_up = new_direction_up
                elif stair_direction_up != new_direction_up:
                    valid = False
                    break

                if not (40 < abs(angle_diff) < 150):
                    valid = False
                    break

            if not valid:
                continue

            # escalator checker
            angle = coord_angle(point1.xy, point2.xy)
            valid = True
            escalator_direction_up = None
            escalator_swap_direction = False
            for escalator in self.escalators:
                if not escalator.mpl_geom.intersects_path(path, filled=True):
                    continue

                if escalator_direction_up is not None:
                    # only one escalator per connection
                    valid = False
                    break

                angle_diff = ((escalator.angle - angle + 180) % 360) - 180

                escalator_direction_up = (angle_diff > 0)
                escalator_swap_direction = (escalator_direction_up != escalator.direction_up)

            if not valid:
                continue

            if stair_direction_up is not None:
                point1.connect_to(point2, ctype=('steps_up' if stair_direction_up else 'steps_down'))
                point2.connect_to(point1, ctype=('steps_down' if stair_direction_up else 'steps_up'))
            elif escalator_direction_up is not None:
                if not escalator_swap_direction:
                    point1.connect_to(point2, ctype=('escalator_up' if escalator_direction_up else 'escalator_down'))
                else:
                    point2.connect_to(point1, ctype=('escalator_down' if escalator_direction_up else 'escalator_up'))
            else:
                point1.connect_to(point2)
                point2.connect_to(point1)

    def add_point(self, point):
        if not self.mpl_clear.contains_point(point.xy):
            return False
        self._built_points.append(point)
        return True

    def finish_build(self):
        self.points = np.array(tuple(point.i for point in self._built_points))
