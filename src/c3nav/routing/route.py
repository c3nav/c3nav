import numpy as np
from django.utils.functional import cached_property

from c3nav.mapdata.utils.misc import get_dimensions


class Route:
    def __init__(self, connections, distance=None):
        self.connections = tuple(connections)
        self.distance = sum(connection.distance for connection in self.connections)
        self.from_point = connections[0].from_point
        self.to_point = connections[-1].to_point

    def __repr__(self):
        return ('<Route (\n    %s\n) distance=%f>' %
                ('\n    '.join(repr(connection) for connection in self.connections), self.distance))

    @cached_property
    def routeparts(self):
        routeparts = []
        connections = []
        add_connections = []
        level = self.connections[0].from_point.level

        for connection in self.connections:
            connections.append(connection)
            point = connection.to_point
            if point.level and point.level != level:
                if routeparts:
                    routeparts[-1].connections.extend(connections[:1])
                routeparts.append(RoutePart(level, add_connections+connections))
                level = point.level
                add_connections = connections[-3:]
                connections = []

        if connections:
            if routeparts:
                routeparts[-1].connections.extend(connections[:1])
            routeparts.append(RoutePart(level, add_connections+connections))

        routeparts = [routepart for routepart in routeparts if not routepart.level.intermediate]

        for routepart in routeparts:
            routepart.render_svg_coordinates()

        return tuple(routeparts)


class RoutePart:
    def __init__(self, graphlevel, connections):
        self.graphlevel = graphlevel
        self.level = graphlevel.level
        self.connections = connections

    def render_svg_coordinates(self):
        svg_width, svg_height = get_dimensions()

        points = (self.connections[0].from_point, ) + tuple(connection.to_point for connection in self.connections)
        for point in points:
            point.svg_x = point.x * 6
            point.svg_y = (svg_height - point.y) * 6

        x, y = zip(*((point.svg_x, point.svg_y) for point in points if point.level == self.graphlevel))

        self.distance = sum(connection.distance for connection in self.connections)

        # bounds for rendering
        self.svg_min_x = min(x) - 20
        self.svg_max_x = max(x) + 20
        self.svg_min_y = min(y) - 20
        self.svg_max_y = max(y) + 20

        svg_width = self.svg_max_x - self.svg_min_x
        svg_height = self.svg_max_y - self.svg_min_y

        if svg_width < 150:
            self.svg_min_x -= (10 - svg_width) / 2
            self.svg_max_x += (10 - svg_width) / 2

        if svg_height < 150:
            self.svg_min_y += (10 - svg_height) / 2
            self.svg_max_y -= (10 - svg_height) / 2

        self.svg_width = self.svg_max_x - self.svg_min_x
        self.svg_height = self.svg_max_y - self.svg_min_y

    def __str__(self):
        return repr(self.__dict__)


class RouteLine:
    def __init__(self, from_point, to_point, distance):
        self.from_point = from_point
        self.to_point = to_point
        self.distance = distance


class NoRoute:
    distance = np.inf
