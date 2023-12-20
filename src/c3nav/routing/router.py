import logging
import operator
import pickle
from collections import deque, namedtuple
from functools import reduce
from itertools import chain
from typing import Optional

import numpy as np
from django.conf import settings
from django.core.cache import cache
from django.utils.functional import cached_property
from scipy.sparse.csgraph._shortest_path import shortest_path
from shapely import prepared
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from c3nav.mapdata.models import AltitudeArea, Area, GraphEdge, Level, LocationGroup, MapUpdate, Space, WayType
from c3nav.mapdata.models.geometry.space import POI, CrossDescription, LeaveDescription
from c3nav.mapdata.models.locations import CustomLocationProxyMixin
from c3nav.mapdata.utils.geometry import assert_multipolygon, get_rings, good_representative_point, unwrap_geom
from c3nav.mapdata.utils.locations import CustomLocation
from c3nav.routing.exceptions import LocationUnreachable, NoRouteFound, NotYetRoutable
from c3nav.routing.route import Route

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext

logger = logging.getLogger('c3nav')


class Router:
    filename = settings.CACHE_ROOT / 'router'

    def __init__(self, levels, spaces, areas, pois, groups, restrictions, nodes, edges, waytypes, graph):
        self.levels = levels
        self.spaces = spaces
        self.areas = areas
        self.pois = pois
        self.groups = groups
        self.restrictions = restrictions
        self.nodes = nodes
        self.edges = edges
        self.waytypes = waytypes
        self.graph = graph

    @staticmethod
    def get_altitude_in_areas(areas, point):
        return max(area.get_altitudes(point)[0] for area in areas if area.geometry_prep.intersects(point))

    @classmethod
    def rebuild(cls, update):
        levels_query = Level.objects.prefetch_related('buildings', 'spaces', 'altitudeareas', 'groups',
                                                      'spaces__holes', 'spaces__columns', 'spaces__groups',
                                                      'spaces__obstacles', 'spaces__lineobstacles',
                                                      'spaces__graphnodes', 'spaces__areas', 'spaces__areas__groups',
                                                      'spaces__pois',  'spaces__pois__groups')

        levels = {}
        spaces = {}
        areas = {}
        pois = {}
        groups = {}
        restrictions = {}
        nodes = deque()
        for level in levels_query:
            buildings_geom = unary_union(tuple(unwrap_geom(building.geometry) for building in level.buildings.all()))

            nodes_before_count = len(nodes)

            for group in level.groups.all():
                groups.setdefault(group.pk, {}).setdefault('levels', set()).add(level.pk)

            if level.access_restriction_id:
                restrictions.setdefault(level.access_restriction_id, RouterRestriction()).spaces.update(
                    space.pk for space in level.spaces.all()
                )

            for space in level.spaces.all():
                # create space geometries
                accessible_geom = space.geometry.difference(unary_union(
                    tuple(unwrap_geom(column.geometry)
                          for column in space.columns.all()
                          if column.access_restriction_id is None) +
                    tuple(unwrap_geom(hole.geometry) for hole in space.holes.all()) +
                    ((buildings_geom, ) if space.outside else ())
                ))
                obstacles_geom = unary_union(
                    tuple(unwrap_geom(obstacle.geometry) for obstacle in space.obstacles.all()) +
                    tuple(unwrap_geom(lineobstacle.buffered_geometry) for lineobstacle in space.lineobstacles.all())
                )
                clear_geom = unary_union(tuple(get_rings(accessible_geom.difference(obstacles_geom))))
                clear_geom_prep = prepared.prep(clear_geom)

                for group in space.groups.all():
                    groups.setdefault(group.pk, {}).setdefault('spaces', set()).add(space.pk)

                if space.access_restriction_id:
                    restrictions.setdefault(space.access_restriction_id, RouterRestriction()).spaces.add(space.pk)

                space_nodes = tuple(RouterNode.from_graph_node(node, i)
                                    for i, node in enumerate(space.graphnodes.all()))
                for i, node in enumerate(space_nodes, start=len(nodes)):
                    node.i = i
                nodes.extend(space_nodes)

                space_obj = space
                space = RouterSpace(space)
                space.nodes = set(node.i for node in space_nodes)

                for area in space_obj.areas.all():
                    for group in area.groups.all():
                        groups.setdefault(group.pk, {}).setdefault('areas', set()).add(area.pk)
                    area._prefetched_objects_cache = {}

                    area = RouterArea(area)
                    area_nodes = tuple(node for node in space_nodes if area.geometry_prep.intersects(node.point))
                    area.nodes = set(node.i for node in area_nodes)
                    for node in area_nodes:
                        node.areas.add(area.pk)
                    if not area.nodes and space_nodes:
                        nearest_node = min(space_nodes, key=lambda node: area.geometry.distance(node.point))
                        area.nodes.add(nearest_node.i)
                    areas[area.pk] = area
                    space.areas.add(area.pk)

                for area in level.altitudeareas.all():
                    if not space.geometry_prep.intersects(unwrap_geom(area.geometry)):
                        continue
                    for subgeom in assert_multipolygon(accessible_geom.intersection(unwrap_geom(area.geometry))):
                        if subgeom.is_empty:
                            continue
                        area_clear_geom = unary_union(tuple(get_rings(subgeom.difference(obstacles_geom))))
                        if area_clear_geom.is_empty:
                            continue
                        area = RouterAltitudeArea(subgeom, area_clear_geom,
                                                  area.altitude, area.altitude2, area.point1, area.point2)
                        area_nodes = tuple(node for node in space_nodes if area.geometry_prep.intersects(node.point))
                        area.nodes = set(node.i for node in area_nodes)
                        for node in area_nodes:
                            altitude = area.get_altitude(node)
                            if node.altitude is None or node.altitude < altitude:
                                node.altitude = altitude

                        space.altitudeareas.append(area)

                for node in space_nodes:
                    if node.altitude is not None:
                        continue
                    logger.warning('Node %d in space %d is not inside an altitude area' % (node.pk, space.pk))
                    node_altitudearea = min(space.altitudeareas,
                                            key=lambda a: a.geometry.distance(node.point), default=None)
                    if node_altitudearea:
                        node.altitude = node_altitudearea.get_altitude(node)
                    else:
                        node.altitude = float(level.base_altitude)
                        logger.info('Space %d has no altitude areas' % space.pk)

                for area in space.altitudeareas:
                    # create fallback nodes
                    if not area.nodes and space_nodes:
                        fallback_point = good_representative_point(area.clear_geometry)
                        fallback_node = RouterNode(None, None, fallback_point.x, fallback_point.y,
                                                   space.pk, area.get_altitude(fallback_point))
                        # todo: check waytypes here
                        for node in space_nodes:
                            line = LineString([(node.x, node.y), (fallback_node.x, fallback_node.y)])
                            if line.length < 5 and not clear_geom_prep.intersects(line):
                                area.fallback_nodes[node.i] = (
                                    fallback_node,
                                    RouterEdge(fallback_node, node, 0)
                                )
                        if not area.fallback_nodes:
                            nearest_node = min(space_nodes, key=lambda node: fallback_point.distance(node.point))
                            area.fallback_nodes[nearest_node.i] = (
                                fallback_node,
                                RouterEdge(fallback_node, nearest_node, 0)
                            )

                for poi in space_obj.pois.all():
                    for group in poi.groups.all():
                        groups.setdefault(group.pk, {}).setdefault('pois', set()).add(poi.pk)
                    poi._prefetched_objects_cache = {}

                    poi = RouterPoint(poi)
                    try:
                        altitudearea = space.altitudearea_for_point(poi.geometry)
                        poi.altitude = altitudearea.get_altitude(poi.geometry)
                        poi_nodes = altitudearea.nodes_for_point(poi.geometry, all_nodes=nodes)
                    except LocationUnreachable:
                        poi_nodes = {}
                    poi.nodes = set(i for i in poi_nodes.keys())
                    poi.nodes_addition = poi_nodes
                    pois[poi.pk] = poi
                    space.pois.add(poi.pk)

                for column in space_obj.columns.all():
                    if column.access_restriction_id is None:
                        continue
                    column.geometry_prep = prepared.prep(column.geometry)
                    column_nodes = tuple(node for node in space_nodes if column.geometry_prep.intersects(node.point))
                    column_nodes = set(node.i for node in column_nodes)
                    restrictions.setdefault(column.access_restriction_id,
                                            RouterRestriction()).additional_nodes.update(column_nodes)

                space_obj._prefetched_objects_cache = {}

                space.src.geometry = accessible_geom

                spaces[space.pk] = space

            level_spaces = set(space.pk for space in level.spaces.all())
            level._prefetched_objects_cache = {}

            level = RouterLevel(level, spaces=level_spaces)
            level.nodes = set(range(nodes_before_count, len(nodes)))
            levels[level.pk] = level

        # add graph descriptions
        for description in LeaveDescription.objects.all():
            spaces[description.space_id].leave_descriptions[description.target_space_id] = description.description

        for description in CrossDescription.objects.all():
            spaces[description.space_id].cross_descriptions[(description.origin_space_id,
                                                             description.target_space_id)] = description.description

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
                                 waytype=waytypes_lookup[edge.waytype_id],
                                 access_restriction=edge.access_restriction_id) for edge in GraphEdge.objects.all())
        edges = {(edge.from_node, edge.to_node): edge for edge in edges}

        # build graph matrix
        graph = np.full(shape=(len(nodes), len(nodes)), fill_value=np.inf, dtype=np.float32)
        for edge in edges.values():
            index = (edge.from_node, edge.to_node)
            graph[index] = edge.distance
            waytype = waytypes[edge.waytype]
            (waytype.upwards_indices if edge.rise > 0 else waytype.nonupwards_indices).append(index)
            if edge.access_restriction:
                restrictions.setdefault(edge.access_restriction, RouterRestriction()).edges.append(index)

        # respect slow_down_factor
        for area in areas.values():
            if area.slow_down_factor != 1:
                area_nodes = np.array(tuple(area.nodes), dtype=np.uint32)
                graph[area_nodes.reshape((-1, 1)), area_nodes] *= float(area.slow_down_factor)

        # finalize waytype matrixes
        for waytype in waytypes:
            waytype.upwards_indices = np.array(waytype.upwards_indices, dtype=np.uint32).reshape((-1, 2))
            waytype.nonupwards_indices = np.array(waytype.nonupwards_indices, dtype=np.uint32).reshape((-1, 2))

        # finalize restriction edge matrixes
        for restriction in restrictions.values():
            restriction.edges = np.array(restriction.edges, dtype=np.uint32).reshape((-1, 2))

        router = cls(levels, spaces, areas, pois, groups, restrictions, nodes, edges, waytypes, graph)
        pickle.dump(router, open(cls.build_filename(update), 'wb'))
        return router

    @classmethod
    def build_filename(cls, update):
        return settings.CACHE_ROOT / ('router_%s.pickle' % MapUpdate.build_cache_key(*update))

    @classmethod
    def load_nocache(cls, update):
        return pickle.load(open(cls.build_filename(update), 'rb'))

    cached = LocalContext()

    class NoUpdate:
        pass

    @classmethod
    def load(cls):
        from c3nav.mapdata.models import MapUpdate
        update = MapUpdate.last_processed_update()
        if getattr(cls.cached, 'update', cls.NoUpdate) != update:
            cls.cached.update = update
            cls.cached.data = cls.load_nocache(update)
        return cls.cached.data

    def get_locations(self, location, restrictions):
        locations = ()
        if isinstance(location, Level):
            if location.access_restriction_id not in restrictions:
                if location.pk not in self.levels:
                    raise NotYetRoutable
                locations = (self.levels[location.pk], )
        elif isinstance(location, Space):
            if location.pk not in restrictions.spaces:
                if location.pk not in self.spaces:
                    raise NotYetRoutable
                locations = (self.spaces[location.pk], )
        elif isinstance(location, Area):
            if location.space_id not in restrictions.spaces and location.access_restriction_id not in restrictions:
                if location.pk not in self.areas:
                    raise NotYetRoutable
                locations = (self.areas[location.pk], )
        elif isinstance(location, POI):
            if location.space_id not in restrictions.spaces and location.access_restriction_id not in restrictions:
                if location.pk not in self.pois:
                    raise NotYetRoutable
                locations = (self.pois[location.pk], )
        elif isinstance(location, LocationGroup):
            if location.pk not in self.groups:
                raise NotYetRoutable
            group = self.groups[location.pk]
            locations = tuple(chain(
                (level for level in (self.levels[pk] for pk in group.get('levels', ()))
                 if level.access_restriction_id not in restrictions),
                (space for space in (self.spaces[pk] for pk in group.get('spaces', ()))
                 if space.pk not in restrictions.spaces),
                (area for area in (self.areas[pk] for pk in group.get('areas', ()))
                 if area.space_id not in restrictions.spaces and area.access_restriction_id not in restrictions),
                (poi for poi in (self.pois[pk] for pk in group.get('pois', ()))
                 if poi.space_id not in restrictions.spaces and poi.access_restriction_id not in restrictions),
            ))
        elif isinstance(location, (CustomLocation, CustomLocationProxyMixin)):
            if isinstance(location, CustomLocationProxyMixin) and not location.available:
                raise LocationUnreachable
            point = Point(location.x, location.y)
            location = RouterPoint(location)
            space = self.space_for_point(location.level.pk, point, restrictions)
            if space is None:
                raise LocationUnreachable
            altitudearea = space.altitudearea_for_point(point)
            location.altitude = altitudearea.get_altitude(point)
            location_nodes = altitudearea.nodes_for_point(point, all_nodes=self.nodes)
            location.nodes = set(i for i in location_nodes.keys())
            location.nodes_addition = location_nodes
            locations = tuple((location, ))
        result = RouterLocation(locations)
        if not result.nodes:
            raise LocationUnreachable
        return result

    def space_for_point(self, level, point, restrictions) -> Optional['RouterSpace']:
        point = Point(point.x, point.y)
        level = self.levels[level]
        excluded_spaces = restrictions.spaces if restrictions else ()
        for space in level.spaces:
            if space in excluded_spaces:
                continue
            if self.spaces[space].geometry_prep.contains(point):
                return self.spaces[space]
        spaces = (self.spaces[space] for space in level.spaces if space not in excluded_spaces)
        spaces = ((space, space.geometry.distance(point)) for space in spaces)
        spaces = tuple((space, distance) for space, distance in spaces if distance < 20)
        if not spaces:
            return None
        return min(spaces, key=operator.itemgetter(1))[0]

    def altitude_for_point(self, space: int, point: Point) -> float:
        return self.spaces[space].altitudearea_for_point(point).get_altitude(point)

    def describe_custom_location(self, location):
        restrictions = self.get_restrictions(location.permissions)
        space = self.space_for_point(level=location.level.pk, point=location, restrictions=restrictions)
        if not space:
            return CustomLocationDescription(space=space, altitude=None, areas=(), near_area=None, near_poi=None,
                                             nearby=())
        try:
            altitude = space.altitudearea_for_point(location).get_altitude(location)
        except LocationUnreachable:
            altitude = None
        areas, near_area, nearby_areas = space.areas_for_point(
            areas=self.areas, point=location, restrictions=restrictions
        )
        near_poi, nearby_pois = space.poi_for_point(
            pois=self.pois, point=location, restrictions=restrictions
        )
        nearby = tuple(sorted(
            tuple(location for location in nearby_areas+nearby_pois if location[0].can_search),
            key=operator.itemgetter(1)
        ))
        # show all location within 5 meters, but at least 20
        min_i = len(nearby)+1
        for i, (location, distance) in enumerate(nearby):
            if distance > 5:
                min_i = i
        nearby = tuple(location for location, distance in nearby[:max(20, min_i)])
        return CustomLocationDescription(space=space, altitude=altitude,
                                         areas=areas, near_area=near_area, near_poi=near_poi, nearby=nearby)

    def shortest_path(self, restrictions, options):
        options_key = options.serialize_string()
        cache_key = 'router:shortest_path:%s:%s:%s' % (MapUpdate.current_processed_cache_key(),
                                                       restrictions.cache_key,
                                                       options_key)
        result = cache.get(cache_key)
        if result:
            distances, predecessors = result
            return (np.frombuffer(distances, dtype=np.float64).reshape(self.graph.shape),
                    np.frombuffer(predecessors, dtype=np.int32).reshape(self.graph.shape))

        graph = self.graph.copy()

        # speeds of waytypes, if relevant
        if options['mode'] == 'fastest':
            self.waytypes[0].speed = 1
            self.waytypes[0].speed_up = 1
            self.waytypes[0].extra_seconds = 0
            self.waytypes[0].walk = True

            for waytype in self.waytypes:
                speed = float(waytype.speed)
                speed_up = float(waytype.speed_up)
                if waytype.walk:
                    speed *= options.walk_factor
                    speed_up *= options.walk_factor

                for indices, dir_speed in ((waytype.nonupwards_indices, speed), (waytype.upwards_indices, speed_up)):
                    indices = tuple(indices.transpose().tolist())
                    values = graph[indices]
                    values /= dir_speed
                    if waytype.extra_seconds:
                        values += int(waytype.extra_seconds)
                    graph[indices] = values

        # avoid waytypes as specified in settings
        for waytype in self.waytypes[1:]:
            value = options.get('waytype_%s' % waytype.pk, 'allow')
            if value in ('avoid', 'avoid_up'):
                graph[tuple(waytype.upwards_indices.transpose().tolist())] *= 100000
            if value in ('avoid', 'avoid_down'):
                graph[tuple(waytype.nonupwards_indices.transpose().tolist())] *= 100000

        # prefer/avoid restrictions
        restrictions_setting = options.get("restrictions", "normal")
        if restrictions_setting != "normal":
            factor = 100000 if restrictions_setting == "avoid" else 1/100000
            all_restrictions = RouterRestrictionSet(self.restrictions.items())
            space_nodes = tuple(reduce(operator.or_, (self.spaces[space].nodes
                                                      for space in all_restrictions.spaces), set()))
            graph[space_nodes, :] *= factor
            graph[:, space_nodes] *= factor
            if restrictions.additional_nodes:
                graph[tuple(restrictions.additional_nodes), :] *= factor
                graph[:, tuple(restrictions.additional_nodes)] *= factor
            graph[tuple(restrictions.edges.transpose().tolist())] *= factor

        # exclude spaces and edges
        space_nodes = tuple(reduce(operator.or_, (self.spaces[space].nodes for space in restrictions.spaces), set()))
        graph[space_nodes, :] = np.inf
        graph[:, space_nodes] = np.inf
        if restrictions.additional_nodes:
            graph[tuple(restrictions.additional_nodes), :] = np.inf
            graph[:, tuple(restrictions.additional_nodes)] = np.inf
        graph[tuple(restrictions.edges.transpose().tolist())] = np.inf

        distances, predecessors = shortest_path(graph, directed=True, return_predecessors=True)
        cache.set(cache_key, (distances.astype(np.float64).tobytes(),
                              predecessors.astype(np.int32).tobytes()), 600)
        return distances, predecessors

    def get_restrictions(self, permissions):
        return RouterRestrictionSet({
            pk: restriction for pk, restriction in self.restrictions.items() if pk not in permissions
        })

    def get_route(self, origin, destination, permissions, options):
        restrictions = self.get_restrictions(permissions)

        # get possible origins and destinations
        origins = self.get_locations(origin, restrictions)
        destinations = self.get_locations(destination, restrictions)

        # calculate shortest path matrix
        distances, predecessors = self.shortest_path(restrictions, options=options)

        # find shortest path for our origins and destinations
        origin_nodes = np.array(tuple(origins.nodes))
        destination_nodes = np.array(tuple(destinations.nodes))
        origin_node, destination_node = np.unravel_index(
            distances[origin_nodes.reshape((-1, 1)), destination_nodes].argmin(),
            (len(origin_nodes), len(destination_nodes))
        )
        origin_node = origin_nodes[origin_node]
        destination_node = destination_nodes[destination_node]

        if distances[origin_node, destination_node] == np.inf:
            raise NoRouteFound

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

        origin_addition = origin.nodes_addition.get(origin_node)
        destination_addition = destination.nodes_addition.get(destination_node)

        # get additional distance at origin and destination
        origin_xyz = origin.xyz if isinstance(origin, RouterPoint) else None
        destination_xyz = destination.xyz if isinstance(destination, RouterPoint) else None

        return Route(self, origin, destination, path_nodes, options,
                     origin_addition, destination_addition, origin_xyz, destination_xyz)


CustomLocationDescription = namedtuple('CustomLocationDescription', ('space', 'altitude',
                                                                     'areas', 'near_area', 'near_poi', 'nearby'))


class BaseRouterProxy:
    def __init__(self, src):
        self.src = src
        self.nodes = set()
        self.nodes_addition = {}

    @cached_property
    def geometry_prep(self):
        return prepared.prep(unwrap_geom(self.src.geometry))

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
        self.areas = set()
        self.pois = set()
        self.altitudeareas = altitudeareas if altitudeareas else []
        self.leave_descriptions = {}
        self.cross_descriptions = {}

    def altitudearea_for_point(self, point):
        point = Point(point.x, point.y)
        if not self.altitudeareas:
            raise LocationUnreachable
        for area in self.altitudeareas:
            if area.geometry_prep.intersects(point):
                return area
        return min(self.altitudeareas, key=lambda area: area.geometry.distance(point))

    def areas_for_point(self, areas, point, restrictions):
        point = Point(point.x, point.y)
        areas = {pk: area for pk, area in areas.items()
                 if pk in self.areas and area.can_describe and area.access_restriction_id not in restrictions}

        nearby = ((area, area.geometry.distance(point)) for area in areas.values())
        nearby = tuple((area, distance) for area, distance in nearby if distance < 20)

        contained = tuple(area for area in areas.values() if area.geometry_prep.contains(point))
        if contained:
            return tuple(sorted(contained, key=lambda area: area.geometry.area)), None, nearby

        near = tuple((area, distance) for area, distance in nearby if distance < 5)
        if not near:
            return (), None, nearby
        return (), min(near, key=operator.itemgetter(1))[0], nearby

    def poi_for_point(self, pois, point, restrictions):
        point = Point(point.x, point.y)
        pois = {pk: poi for pk, poi in pois.items()
                if pk in self.pois and poi.can_describe and poi.access_restriction_id not in restrictions}

        nearby = ((poi, poi.geometry.distance(point)) for poi in pois.values())
        nearby = tuple((poi, distance) for poi, distance in nearby if distance < 20)

        near = tuple((poi, distance) for poi, distance in nearby if distance < 5)
        if not near:
            return None, nearby
        return min(near, key=operator.itemgetter(1))[0], nearby


class RouterArea(BaseRouterProxy):
    pass


class RouterPoint(BaseRouterProxy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.altitude = None

    @cached_property
    def xyz(self):
        return np.array((self.x, self.y, self.altitude))


class RouterAltitudeArea:
    def __init__(self, geometry, clear_geometry, altitude, altitude2, point1, point2):
        self.geometry = geometry
        self.clear_geometry = clear_geometry
        self.altitude = altitude
        self.altitude2 = altitude2
        self.point1 = point1
        self.point2 = point2
        self.nodes = frozenset()
        self.fallback_nodes = {}

    @cached_property
    def geometry_prep(self):
        return prepared.prep(self.geometry)

    @cached_property
    def clear_geometry_prep(self):
        return prepared.prep(self.clear_geometry)

    def get_altitude(self, point):
        # noinspection PyTypeChecker,PyCallByClass
        return AltitudeArea.get_altitudes(self, (point.x, point.y))[0]

    def nodes_for_point(self, point, all_nodes):
        point = Point(point.x, point.y)

        nodes = {}
        if self.nodes:
            for node in self.nodes:
                node = all_nodes[node]
                line = LineString([(node.x, node.y), (point.x, point.y)])
                if line.length < 10 and not self.clear_geometry_prep.intersects(line):
                    nodes[node.i] = (None, None)
            if not nodes:
                nearest_node = min(tuple(all_nodes[node] for node in self.nodes),
                                   key=lambda node: point.distance(node.point))
                nodes[nearest_node.i] = (None, None)
        else:
            nodes = self.fallback_nodes
        return nodes

    def __getstate__(self):
        result = self.__dict__.copy()
        result.pop('geometry_prep', None)
        result.pop('clear_geometry_prep', None)
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
    def __init__(self, from_node, to_node, waytype, access_restriction=None, rise=None, distance=None):
        self.from_node = from_node.i
        self.to_node = to_node.i
        self.waytype = waytype
        self.access_restriction = access_restriction
        if rise is not None:
            self.rise = rise
        elif to_node.altitude is None or from_node.altitude is None:
            self.rise = None
        else:
            self.rise = (to_node.altitude - from_node.altitude)
        self.distance = distance if distance is not None else np.linalg.norm(to_node.xyz - from_node.xyz)


class RouterWayType:
    def __init__(self, waytype):
        self.src = waytype
        self.upwards_indices = deque()
        self.nonupwards_indices = deque()

    def __getattr__(self, name):
        if name in ('__getstate__', '__setstate__'):
            raise AttributeError
        return getattr(self.src, name)

    def get_duration(self, edge, walk_factor):
        if edge.rise > 0:
            duration = edge.distance / (float(self.speed_up if self.src else 1) * walk_factor)
        else:
            duration = edge.distance / (float(self.speed if self.src else 1) * walk_factor)
        duration += self.extra_seconds if self.src else 0
        return duration


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


class RouterRestriction:
    def __init__(self, spaces=None):
        self.spaces = spaces if spaces else set()
        self.additional_nodes = set()
        self.edges = deque()


class RouterRestrictionSet:
    def __init__(self, restrictions):
        self.restrictions = restrictions

    @cached_property
    def spaces(self):
        return reduce(operator.or_, (restriction.spaces for restriction in self.restrictions.values()), frozenset())

    @cached_property
    def additional_nodes(self):
        return reduce(operator.or_, (restriction.additional_nodes
                                     for restriction in self.restrictions.values()), frozenset())

    @cached_property
    def edges(self):
        if not self.restrictions:
            return np.array((), dtype=np.uint32).reshape((-1, 2))
        return np.vstack(tuple(restriction.edges for restriction in self.restrictions.values()))

    @cached_property
    def cache_key(self):
        return '%s_%s' % ('-'.join(str(i) for i in self.spaces),
                          '-'.join(str(i) for i in self.edges.flatten().tolist()))

    def __contains__(self, pk):
        return pk in self.restrictions
