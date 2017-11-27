import os
import pickle
from collections import deque

import numpy as np
from django.conf import settings
from django.utils.functional import cached_property
from shapely import prepared
from shapely.geometry import Point
from shapely.ops import unary_union

from c3nav.mapdata.models import AltitudeArea, GraphEdge, Level, WayType


class Router:
    filename = os.path.join(settings.CACHE_ROOT, 'router')

    def __init__(self, levels, spaces, areas, nodes, waytypes, graph):
        self.levels = levels
        self.spaces = spaces
        self.areas = areas
        self.nodes = nodes
        self.waytypes = waytypes
        self.graph = graph

    @staticmethod
    def get_altitude_in_areas(areas, point):
        return max(area.get_altitudes(point)[0] for area in areas if area.geometry_prep.intersects(point))

    @classmethod
    def build(cls):
        levels_query = Level.objects.prefetch_related('buildings', 'spaces', 'altitudeareas',
                                                      'spaces__holes', 'spaces__columns',
                                                      'spaces__obstacles', 'spaces__lineobstacles',
                                                      'spaces__areas', 'spaces__graphnodes')

        levels = {}
        spaces = {}
        areas = {}
        nodes = deque()
        for level in levels_query:
            buildings_geom = unary_union(tuple(building.geometry for building in level.buildings.all()))

            nodes_before_count = len(nodes)

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

                space_nodes = tuple(RouterNode.from_graph_node(node) for node in space.graphnodes.all())
                for i, node in enumerate(space_nodes, start=len(nodes)):
                    node.i = i
                nodes.extend(space_nodes)

                for area in space.areas.all():
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
        nodes_coords = np.array(tuple((node.x*100, node.y*100) for node in nodes), dtype=np.uint32)  # noqa
        # todo: remove #noqa when we're ready

        # collect edges
        edges = tuple(RouterEdge(from_node=nodes[nodes_lookup[edge.from_node_id]],
                                 to_node=nodes[nodes_lookup[edge.to_node_id]],
                                 waytype=waytypes_lookup[edge.waytype_id]) for edge in GraphEdge.objects.all())
        edges_lookup = {(edge.from_node.i, edge.to_node.i): edge for edge in edges}  # noqa
        # todo: remove #noqa when we're ready

        # build graph matrix
        graph = np.full(shape=(len(nodes), len(nodes)), fill_value=np.inf, dtype=np.float32)
        for edge in edges:
            index = (edge.from_node.i, edge.to_node.i)
            graph[index] = edge.distance
            waytype = waytypes[edge.waytype]
            (waytype.upwards_indices if edge.rise > 0 else waytype.nonupwards_indices).append(index)

        # finalize waytype matrixes
        for waytype in waytypes:
            waytype.upwards_indices = np.array(waytype.upwards_indices, dtype=np.uint32).reshape((-1, 2))
            waytype.nonupwards_indices = np.array(waytype.nonupwards_indices, dtype=np.uint32).reshape((-1, 2))

        router = cls(levels, spaces, areas, nodes, waytypes, graph)
        pickle.dump(router, open(cls.filename, 'wb'))
        return router

    @classmethod
    def load(cls):
        return pickle.load(open(cls.filename, 'rb'))


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
    def __init__(self, pk, x, y, space, altitude=None, areas=None):
        self.pk = pk
        self.x = x
        self.y = y
        self.space = space
        self.altitude = altitude
        self.areas = areas if areas else set()

    @classmethod
    def from_graph_node(cls, node):
        return cls(node.pk, node.geometry.x, node.geometry.y, node.space_id)

    @cached_property
    def point(self):
        return Point(self.x, self.y)

    @cached_property
    def xy(self):
        return np.array((self.x, self.y))


class RouterEdge:
    def __init__(self, from_node, to_node, waytype, rise=None, distance=None):
        self.from_node = from_node
        self.to_node = to_node
        self.waytype = waytype
        self.rise = rise if rise is not None else (self.to_node.altitude - self.from_node.altitude)
        self.distance = distance if distance is not None else np.linalg.norm(to_node.xy - from_node.xy)


class RouterWayType:
    def __init__(self, waytype):
        self.waytype = waytype
        self.upwards_indices = deque()
        self.nonupwards_indices = deque()
