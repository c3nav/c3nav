from abc import ABC

import numpy as np
from django.utils.functional import cached_property


class RouteSegment(ABC):
    def __init__(self, router, from_point, to_point):
        """
        :param router: a Router (RoomRouter, GraphRouter, …)
        :param from_point: in-router index of first point
        :param to_point: in-router index of last point
        """
        self.router = router
        self.from_point = int(from_point)
        self.to_point = int(to_point)

    def as_route(self):
        return Route([self])

    @cached_property
    def distance(self):
        return self.router.shortest_paths[self.from_point, self.to_point]


class RoomRouteSegment(RouteSegment):
    def __init__(self, room, router, from_point, to_point):
        """
        Route segment within a Room
        :param room: GraphRoom
        :param router: RoomRouter
        :param from_point: in-room index of first point
        :param to_point: in-room index of last point
        """
        super().__init__(router, from_point, to_point)
        self.room = room
        self.global_from_point = room.points[from_point]
        self.global_to_point = room.points[to_point]

    def __repr__(self):
        return ('<RoomRouteSegment in %r from points %d to %d with distance %f>' %
                (self.room, self.from_point, self.to_point, self.distance))


class LevelRouteSegment(RouteSegment):
    def __init__(self, level, router, from_point, to_point):
        """
        Route segment within a Level (from room transfer point to room transfer point)
        :param level: GraphLevel
        """
        super().__init__(router, from_point, to_point)
        self.level = level
        self.global_from_point = level.room_transfer_points[from_point]
        self.global_to_point = level.room_transfer_points[to_point]

    def __repr__(self):
        return ('<LevelRouteSegment in %r from points %d to %d with distance %f>' %
                (self.level, self.from_point, self.to_point, self.distance))


class GraphRouteSegment(RouteSegment):
    def __init__(self, graph, router, from_point, to_point):
        """
        Route segment within a Graph (from level transfer point to level transfer point)
        :param graph: Graph
        """
        super().__init__(router, from_point, to_point)
        self.graph = graph
        self.global_from_point = graph.level_transfer_points[from_point]
        self.global_to_point = graph.level_transfer_points[to_point]

    def __repr__(self):
        return ('<GraphRouteSegment in %r from points %d to %d with distance %f>' %
                (self.graph, self.from_point, self.to_point, self.distance))


class Route:
    def __init__(self, segments, distance=None):
        self.segments = sum(((item.segments if isinstance(item, Route) else (item, )) for item in segments), ())
        self.distance = sum(segment.distance for segment in self.segments)

    def __repr__(self):
        return ('<Route (\n    %s\n) distance=%f>' %
                ('\n    '.join(repr(segment) for segment in self.segments), self.distance))


class NoRoute:
    distance = np.inf
