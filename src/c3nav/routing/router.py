import operator
import os
import pickle
from collections import deque
from functools import reduce
from itertools import chain

import numpy as np
from django.conf import settings
from django.utils.functional import cached_property
from scipy.sparse.csgraph._shortest_path import shortest_path
from shapely import prepared
from shapely.geometry import Point
from shapely.ops import unary_union

from c3nav.mapdata.models import AltitudeArea, Area, GraphEdge, Level, LocationGroup, Space, WayType
from c3nav.routing.route import Route


class Router:
    filename = os.path.join(settings.CACHE_ROOT, 'router')

    def __init__(self, levels, spaces, areas, groups, nodes, edges, waytypes, graph):
        self.levels = levels
        self.spaces = spaces
        self.areas = areas
        self.groups = groups
        self.nodes = nodes
        self.edges = edges
        self.waytypes = waytypes
        self.graph = graph

    @staticmethod
    def get_altitude_in_areas(areas, point):
        return max(area.get_altitudes(point)[0] for area in areas if area.geometry_prep.intersects(point))

    @classmethod
    def rebuild(cls):
        levels_query = Level.objects.prefetch_related('buildings', 'spaces', 'altitudeareas', 'groups',
                                                      'spaces__holes', 'spaces__columns', 'spaces__groups',
                                                      'spaces__obstacles', 'spaces__lineobstacles',
                                                      'spaces__graphnodes', 'spaces__areas', 'spaces__areas__groups')

        levels = {}
        spaces = {}
        areas = {}
        groups = {}
        nodes = deque()
        for level in levels_query:
            buildings_geom = unary_union(tuple(building.geometry for building in level.buildings.all()))

            nodes_before_count = len(nodes)

            for group in level.groups.all():
                groups.setdefault(group.pk, {}).setdefault('levels', set()).add(level.pk)

            for space in level.spaces.all():
                # create space geometries
                accessible_geom = space.geometry.difference(unary_union(
                    tuple(column.geometry for column in space.columns.all()) +
                    tuple(hole.geometry for hole in space.holes.all()) +
                    ((buildings_geom, ) if space.outside else ())
                ))
                obstacles_geom = unary_union(  # noqa
                    tuple(obstacle.geometry for obstacle in space.obstacles.all()) +
                    tuple(lineobstacle.buffered_geometry for lineobstacle in space.lineobstacles.all())
                )
                # todo: do something with this, then remove #noqa

                for group in space.groups.all():
                    groups.setdefault(group.pk, {}).setdefault('spaces', set()).add(space.pk)

                space_nodes = tuple(RouterNode.from_graph_node(node, i)
                                    for i, node in enumerate(space.graphnodes.all()))
                for i, node in enumerate(space_nodes, start=len(nodes)):
                    node.i = i
                nodes.extend(space_nodes)

                for area in space.areas.all():
                    for group in area.groups.all():
                        groups.setdefault(group.pk, {}).setdefault('areas', set()).add(area.pk)
                    area._prefetched_objects_cache = {}

                    area = RouterArea(area)
                    area_nodes = tuple(node for node in space_nodes if area.geometry_prep.intersects(node.point))
                    area.nodes = set(node.i for node in area_nodes)
                    for node in area_nodes:
                        node.areas.add(area.pk)
                    areas[area.pk] = area

                space._prefetched_objects_cache = {}
                space = RouterSpace(space)
                space.nodes = set(node.i for node in space_nodes)

                for area in level.altitudeareas.all():
                    if not space.geometry_prep.intersects(area.geometry):
                        continue
                    area = RouterAltitudeArea(accessible_geom.intersection(area.geometry),
                                              area.altitude, area.altitude2, area.point1, area.point2)
                    area_nodes = tuple(node for node in space_nodes if area.geometry_prep.intersects(node.point))
                    area.nodes = set(node.i for node in area_nodes)
                    for node in area_nodes:
                        altitude = area.get_altitude(node)
                        if node.altitude is None or node.altitude < altitude:
                            node.altitude = altitude
                    space.altitudeareas.append(area)

                spaces[space.pk] = space

            level_spaces = set(space.pk for space in level.spaces.all())
            level._prefetched_objects_cache = {}

            level = RouterLevel(level, spaces=level_spaces)
            level.nodes = set(range(nodes_before_count, len(nodes)))
            levels[level.pk] = level

        # waytypes
        waytypes = deque([RouterWayType(None)])
        waytypes_lookup = {None: 0}
        for i, waytype in enumerate(WayType.objects.all(), start=1):
            waytypes.append(RouterWayType(waytype))
            waytypes_lookup[waytype.pk] = i
        waytypes = tuple(waytypes)

        # collect nodes
        nodes = tuple(nodes)
        nodes_lookup = {node.pk: node.i for node in nodes}

        # collect edges
        edges = tuple(RouterEdge(from_node=nodes[nodes_lookup[edge.from_node_id]],
                                 to_node=nodes[nodes_lookup[edge.to_node_id]],
                                 waytype=waytypes_lookup[edge.waytype_id]) for edge in GraphEdge.objects.all())
        edges = {(edge.from_node.i, edge.to_node.i): edge for edge in edges}

        # build graph matrix
        graph = np.full(shape=(len(nodes), len(nodes)), fill_value=np.inf, dtype=np.float32)
        for edge in edges.values():
            index = (edge.from_node.i, edge.to_node.i)
            graph[index] = edge.distance
            waytype = waytypes[edge.waytype]
            (waytype.upwards_indices if edge.rise > 0 else waytype.nonupwards_indices).append(index)

        # finalize waytype matrixes
        for waytype in waytypes:
            waytype.upwards_indices = np.array(waytype.upwards_indices, dtype=np.uint32).reshape((-1, 2))
            waytype.nonupwards_indices = np.array(waytype.nonupwards_indices, dtype=np.uint32).reshape((-1, 2))

        router = cls(levels, spaces, areas, groups, nodes, edges, waytypes, graph)
        pickle.dump(router, open(cls.filename, 'wb'))
        return router

    @classmethod
    def load(cls):
        return pickle.load(open(cls.filename, 'rb'))

    def get_locations(self, location, permissions=frozenset()):
        locations = ()
        if isinstance(location, Level):
            locations = (self.levels.get(location.pk), )
        elif isinstance(location, Space):
            locations = (self.spaces.get(location.pk), )
        elif isinstance(location, Area):
            locations = (self.areas.get(location.pk), )
        elif isinstance(location, LocationGroup):
            group = self.groups.get(location.pk)
            locations = tuple(chain(
                (self.levels[pk] for pk in group.get('levels', ())),
                (self.spaces[pk] for pk in group.get('spaces', ())),
                (self.areas[pk] for pk in group.get('areas', ()))
            ))
        # todo: route from/to POI or custom location
        return RouterLocation(tuple(location for location in locations
                                    if location is not None and (location.access_restriction_id is None or
                                                                 location.access_restriction_id in permissions)))

    def get_route(self, origin, destination, permissions=frozenset()):
        # get possible origins and destinations
        origins = self.get_locations(origin, permissions=permissions)
        destinations = self.get_locations(destination, permissions=permissions)

        # todo: throw error if route is impossible

        # calculate shortest path matrix
        distances, predecessors = shortest_path(self.graph, directed=True, return_predecessors=True)

        # find shortest path for our origins and destinations
        origin_nodes = np.array(tuple(origins.nodes))
        destination_nodes = np.array(tuple(destinations.nodes))
        origin_node, destination_node = np.unravel_index(
            distances[origin_nodes.reshape((-1, 1)), destination_nodes].argmin(),
            (len(origin_nodes), len(destination_nodes))
        )
        origin_node = origin_nodes[origin_node]
        destination_node = destination_nodes[destination_node]

        # get best origin and destination
        origin = origins.get_location_for_node(origin_node)
        destination = destinations.get_location_for_node(destination_node)

        # recreate path
        path_nodes = deque((destination_node, ))
        last_node = destination_node
        while last_node != origin_node:
            last_node = predecessors[origin_node, last_node]
            path_nodes.appendleft(last_node)
        path_nodes = tuple(path_nodes)

        return Route(self, origin, destination, distances[origin_node, destination_node], path_nodes)


class BaseRouterProxy:
    def __init__(self, src):
        self.src = src
        self.nodes = set()

    @cached_property
    def geometry_prep(self):
        return prepared.prep(self.src.geometry)

    def __getstate__(self):
        result = self.__dict__.copy()
        result.pop('geometry_prep', None)
        return result

    def __getattr__(self, name):
        if name == '__setstate__':
            raise AttributeError
        return getattr(self.src, name)


class RouterLevel(BaseRouterProxy):
    def __init__(self, level, spaces=None):
        super().__init__(level)
        self.spaces = spaces if spaces else set()


class RouterSpace(BaseRouterProxy):
    def __init__(self, space, altitudeareas=None):
        super().__init__(space)
        self.altitudeareas = altitudeareas if altitudeareas else []


class RouterArea(BaseRouterProxy):
    pass


class RouterAltitudeArea:
    def __init__(self, geometry, altitude, altitude2, point1, point2):
        self.geometry = geometry
        self.altitude = altitude
        self.altitude2 = altitude2
        self.point1 = point1
        self.point2 = point2

    @cached_property
    def geometry_prep(self):
        return prepared.prep(self.geometry)

    def get_altitude(self, point):
        # noinspection PyTypeChecker,PyCallByClass
        return AltitudeArea.get_altitudes(self, (point.x, point.y))[0]

    def __getstate__(self):
        result = self.__dict__.copy()
        result.pop('geometry_prep', None)
        return result


class RouterNode:
    def __init__(self, i, pk, x, y, space, altitude=None, areas=None):
        self.i = i
        self.pk = pk
        self.x = x
        self.y = y
        self.space = space
        self.altitude = altitude
        self.areas = areas if areas else set()

    @classmethod
    def from_graph_node(cls, node, i):
        return cls(i, node.pk, node.geometry.x, node.geometry.y, node.space_id)

    @cached_property
    def point(self):
        return Point(self.x, self.y)

    @cached_property
    def xyz(self):
        return np.array((self.x, self.y, self.altitude))


class RouterEdge:
    def __init__(self, from_node, to_node, waytype, rise=None, distance=None):
        self.from_node = from_node
        self.to_node = to_node
        self.waytype = waytype
        self.rise = rise if rise is not None else (self.to_node.altitude - self.from_node.altitude)
        self.distance = distance if distance is not None else np.linalg.norm(to_node.xyz - from_node.xyz)


class RouterWayType:
    def __init__(self, waytype):
        self.src = waytype
        self.upwards_indices = deque()
        self.nonupwards_indices = deque()

    def __getattr__(self, name):
        if name == '__setstate__':
            raise AttributeError
        return getattr(self.src, name)


class RouterLocation:
    def __init__(self, locations=()):
        self.locations = locations

    @cached_property
    def nodes(self):
        return reduce(operator.or_, (location.nodes for location in self.locations), frozenset())

    def get_location_for_node(self, node):
        for location in self.locations:
            if node in location.nodes:
                return location
        return None
