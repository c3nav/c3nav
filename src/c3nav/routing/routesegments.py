from abc import ABC, abstractmethod

from django.utils.functional import cached_property

from c3nav.routing.connection import GraphConnection
from c3nav.routing.point import GraphPoint
from c3nav.routing.route import Route


class RouteSegment(ABC):
    def __init__(self, routers, router, from_point, to_point):
        """
        :param router: a Router (RoomRouter, GraphRouter, …)
        :param from_point: in-router index of first point
        :param to_point: in-router index of last point
        """
        self.routers = routers
        self.router = router
        self.from_point = int(from_point)
        self.to_point = int(to_point)

    def as_route(self):
        return SegmentRoute([self])

    def _get_points(self):
        points = [self.to_point]
        first = self.from_point
        current = self.to_point
        while current != first:
            current = self.router.predecessors[first, current]
            points.append(current)
        return tuple(reversed(points))

    @abstractmethod
    def get_connections(self):
        pass

    @cached_property
    def distance(self):
        return self.router.shortest_paths[self.from_point, self.to_point]


class RoomRouteSegment(RouteSegment):
    def __init__(self, room, routers, from_point, to_point):
        """
        Route segment within a Room
        :param room: GraphRoom
        """
        super().__init__(routers, routers[room], from_point, to_point)
        self.room = room
        self.global_from_point = room.points[from_point]
        self.global_to_point = room.points[to_point]

    def get_connections(self):
        points = self._get_points()
        return tuple(self.room.get_connection(from_point, to_point)
                     for from_point, to_point in zip(points[:-1], points[1:]))

    def __repr__(self):
        return ('<RoomRouteSegment in %r from points %d to %d with distance %f>' %
                (self.room, self.from_point, self.to_point, self.distance))


class LevelRouteSegment(RouteSegment):
    def __init__(self, level, routers, from_point, to_point):
        """
        Route segment within a Level (from room transfer point to room transfer point)
        :param level: GraphLevel
        """
        super().__init__(routers, routers[level], from_point, to_point)
        self.level = level
        self.global_from_point = level.room_transfer_points[from_point]
        self.global_to_point = level.room_transfer_points[to_point]

    def split(self):
        segments = []
        points = self._get_points()
        for from_point, to_point in zip(points[:-1], points[1:]):
            room = self.level.rooms[self.router.room_transfers[from_point, to_point]]
            global_from_point = self.level.room_transfer_points[from_point]
            global_to_point = self.level.room_transfer_points[to_point]
            segments.append(RoomRouteSegment(room, self.routers,
                                             from_point=room.points.index(global_from_point),
                                             to_point=room.points.index(global_to_point)))
        return tuple(segments)

    def get_connections(self):
        return sum((segment.get_connections() for segment in self.split()), ())

    def __repr__(self):
        return ('<LevelRouteSegment in %r from points %d to %d with distance %f>' %
                (self.level, self.from_point, self.to_point, self.distance))


class GraphRouteSegment(RouteSegment):
    def __init__(self, graph, routers, from_point, to_point):
        """
        Route segment within a Graph (from level transfer point to level transfer point)
        :param graph: Graph
        """
        super().__init__(routers, routers[graph], from_point, to_point)
        self.graph = graph
        self.global_from_point = graph.level_transfer_points[from_point]
        self.global_to_point = graph.level_transfer_points[to_point]

    def split(self):
        segments = []
        points = self._get_points()
        for from_point, to_point in zip(points[:-1], points[1:]):
            level = tuple(self.graph.levels.values())[self.router.level_transfers[from_point, to_point]]
            global_from_point = self.graph.level_transfer_points[from_point]
            global_to_point = self.graph.level_transfer_points[to_point]
            segments.append(LevelRouteSegment(level, self.routers,
                                              from_point=level.room_transfer_points.index(global_from_point),
                                              to_point=level.room_transfer_points.index(global_to_point)))
        return tuple(segments)

    def get_connections(self):
        return sum((segment.get_connections() for segment in self.split()), ())

    def __repr__(self):
        return ('<GraphRouteSegment in %r from points %d to %d with distance %f>' %
                (self.graph, self.from_point, self.to_point, self.distance))


class SegmentRoute:
    def __init__(self, segments, distance=None):
        self.segments = sum(((item.segments if isinstance(item, SegmentRoute) else (item,))
                             for item in segments if item.from_point != item.to_point), ())
        self.distance = sum(segment.distance for segment in self.segments)
        self.from_point = segments[0].global_from_point
        self.to_point = segments[-1].global_to_point
        self.global_from_point = self.from_point
        self.global_to_point = self.to_point

    def __repr__(self):
        return ('<SegmentedRoute (\n    %s\n) distance=%f>' %
                ('\n    '.join(repr(segment) for segment in self.segments), self.distance))

    def rawsplit(self):
        return sum((segment.get_connections() for segment in self.segments), ())

    def split(self):
        return Route(self.rawsplit())


class SegmentRouteWrapper:
    def __init__(self, segmentroute: SegmentRoute, orig_point, dest_point, orig_ctype, dest_ctype):
        self.segmentroute = segmentroute
        self.orig_point = orig_point
        self.dest_point = dest_point
        self.orig_ctype = orig_ctype
        self.dest_ctype = dest_ctype

    def __repr__(self):
        return ('<SegmentedRouteWrapper %s, add_orig_point=%s, add_dest_point=%s>' %
                (repr(self.segmentroute), repr(self.orig_point), repr(self.dest_point)))

    def split(self):
        connections = self.segmentroute.rawsplit()

        if self.orig_point:
            first_point = connections[0].from_point
            orig_point = GraphPoint(self.orig_point.x, self.orig_point.y, first_point.room)
            connections = (GraphConnection(orig_point, first_point, ctype=self.orig_ctype),) + connections

        if self.dest_point:
            last_point = connections[-1].to_point
            dest_point = GraphPoint(self.dest_point.x, self.dest_point.y, last_point.room)
            connections = connections + (GraphConnection(last_point, dest_point, ctype=self.dest_ctype), )

        return Route(connections)
