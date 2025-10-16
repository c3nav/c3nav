import logging
import operator
import pickle
from collections import deque
from dataclasses import dataclass, field
from functools import reduce
from itertools import chain
from operator import itemgetter
from typing import Optional, Sequence, TypeAlias, ClassVar, NamedTuple, Union

import numpy as np
from django.conf import settings
from django.db.models.query import Prefetch
from django.utils.functional import cached_property, Promise
from shapely import prepared
from shapely.geometry import LineString, Point, Polygon, MultiPolygon
from shapely.ops import unary_union
from twisted.protocols.amp import Decimal

from c3nav.mapdata.locations import CustomLocation, LocationManager
from c3nav.mapdata.models import AltitudeArea, GraphEdge, Level, Space, WayType
from c3nav.mapdata.models.geometry.level import AltitudeAreaPoint
from c3nav.mapdata.models.geometry.space import POI, CrossDescription, LeaveDescription, Area
from c3nav.mapdata.models.locations import LocationTag
from c3nav.mapdata.permissions import active_map_permissions
from c3nav.mapdata.schemas.locations import LocationProtocol
from c3nav.mapdata.schemas.model_base import LocationPoint
from c3nav.mapdata.utils.cache.proxied import versioned_cache
from c3nav.mapdata.utils.cache.types import MapUpdateTuple
from c3nav.mapdata.utils.geometry.generaty import good_representative_point
from c3nav.mapdata.utils.geometry.inspect import assert_multipolygon, get_rings
from c3nav.mapdata.utils.geometry.wrapped import unwrap_geom
from c3nav.mapdata.utils.geometry.index import Index
from c3nav.routing.exceptions import LocationUnreachable, NoRouteFound, NotYetRoutable
from c3nav.routing.models import RouteOptions
from c3nav.routing.route import Route, RouteLocation

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext

logger = logging.getLogger('c3nav')


class RouterNodeAndEdge(NamedTuple):
    node: Optional["RouterNode"]
    edge: Optional["RouterEdge"]


NodeConnectionsByNode: TypeAlias = dict[int, RouterNodeAndEdge]
EdgeIndex: TypeAlias = tuple[int, int]


@dataclass
class Router:
    filename: ClassVar = settings.CACHE_ROOT / 'router'

    update: MapUpdateTuple
    levels: dict[int, "RouterLevel"]
    spaces: dict[int, "RouterSpace"]
    areas: dict[int, "RouterArea"]
    pois: dict[int, "RouterPOI"]
    locationtags: dict[int, Union["RouterLocation"]]
    restrictions: dict[int, "RouterRestriction"]
    nodes: tuple["RouterNode", ...]
    edges: dict[EdgeIndex, "RouterEdge"]
    waytypes: tuple["RouterWayType", ...]
    graph: np.ndarray

    @staticmethod
    def get_altitude_in_areas(areas, point):
        return max(area.get_altitudes(point)[0] for area in areas if area.geometry_prep.intersects(point))

    @classmethod
    def rebuild(cls, update: MapUpdateTuple):
        levels_query = Level.objects.prefetch_related('buildings', 'spaces', 'altitudeareas', 'spaces__graphnodes',
                                                      'spaces__holes', 'spaces__columns', 'spaces__tags', 'tags',
                                                      'spaces__obstacles', 'spaces__lineobstacles', 'spaces__areas',
                                                      'spaces__areas__tags', 'spaces__pois',  'spaces__pois__tags')

        levels: dict[int, RouterLevel] = {}
        spaces: dict[int, RouterSpace] = {}
        areas: dict[int, RouterArea] = {}
        pois: dict[int, RouterPOI] = {}
        locationtags: dict[int, RouterLocation] = {}
        restrictions: dict[int, RouterRestriction] = {}
        nodes: deque[RouterNode] = deque()
        for level in levels_query:
            buildings_geom = unary_union(tuple(unwrap_geom(building.geometry) for building in level.buildings.all()))

            nodes_before_count = len(nodes)

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

                if space.access_restriction_id:
                    restrictions.setdefault(space.access_restriction_id, RouterRestriction()).spaces.add(space.pk)

                space_nodes = tuple(RouterNode.from_graph_node(node, i)
                                    for i, node in enumerate(space.graphnodes.all()))
                for i, node in enumerate(space_nodes, start=len(nodes)):
                    node.i = i
                nodes.extend(space_nodes)

                space_obj = space
                routerspace = RouterSpace(space)
                routerspace.nodes = set(node.i for node in space_nodes)

                for area in space_obj.areas.all():

                    routerarea = RouterArea(area)
                    area_nodes = tuple(node for node in space_nodes if routerarea.geometry_prep.intersects(node.point))
                    routerarea.nodes = set(node.i for node in area_nodes)
                    for node in area_nodes:
                        node.areas.add(area.pk)
                    if not routerarea.nodes and space_nodes:
                        nearest_node = min(space_nodes, key=lambda node: area.geometry.distance(node.point))
                        routerarea.nodes.add(nearest_node.i)
                    areas[area.pk] = routerarea
                    routerspace.areas.add(area.pk)
                    for location in area.tags.all():
                        locationtags.setdefault(location.pk, RouterLocation(location)).targets.append(routerarea)

                for altitudearea in level.altitudeareas.all():
                    altitudearea.geometry = unwrap_geom(altitudearea.geometry).buffer(0)
                    if not routerspace.geometry_prep.intersects(unwrap_geom(altitudearea.geometry)):
                        continue
                    for subgeom in assert_multipolygon(accessible_geom.intersection(unwrap_geom(altitudearea.geometry))):
                        if subgeom.is_empty:
                            continue
                        area_clear_geom = unary_union(tuple(get_rings(subgeom.difference(obstacles_geom))))
                        if area_clear_geom.is_empty:
                            continue
                        routeraltitudearea = RouterAltitudeArea(
                            geometry=subgeom,
                            clear_geometry=area_clear_geom,
                            altitude=altitudearea.altitude,
                            points=altitudearea.points
                        )
                        area_nodes = tuple(node for node in space_nodes if routeraltitudearea.geometry_prep.intersects(node.point))
                        routeraltitudearea.nodes = frozenset(node.i for node in area_nodes)
                        for node in area_nodes:
                            altitude = routeraltitudearea.get_altitude(Point(node.xyz[:2]))
                            if node.altitude is None or node.altitude < altitude:
                                node.altitude = altitude

                        routerspace.altitudeareas.append(routeraltitudearea)

                for node in space_nodes:
                    if node.altitude is not None:
                        continue
                    logger.warning('Node %d in space %d is not inside an altitude area' % (node.pk, space.pk))
                    node_altitudearea = min(space.altitudeareas,
                                            key=lambda a: a.geometry.distance(node.point), default=None)
                    if node_altitudearea:
                        node.altitude = node_altitudearea.get_altitude(Point(node.xyz[:2]))
                    else:
                        node.altitude = float(level.base_altitude)
                        logger.info('Space %d has no altitude areas' % space.pk)

                for area in routerspace.altitudeareas:
                    # create fallback nodes
                    if not area.nodes and space_nodes:
                        fallback_point = good_representative_point(area.clear_geometry)
                        fallback_node = RouterNode(
                            i=None,
                            pk=None,
                            x=fallback_point.x,
                            y=fallback_point.y,
                            space=space.pk,
                            altitude=area.get_altitude(fallback_point)
                        )
                        # todo: check waytypes here
                        for node in space_nodes:
                            line = LineString([(node.x, node.y), (fallback_node.x, fallback_node.y)])
                            if line.length < 5 and not clear_geom_prep.intersects(line):
                                area.fallback_nodes[node.i] = RouterNodeAndEdge(
                                    node=fallback_node,
                                    edge=RouterEdge.create(from_node=fallback_node, to_node=node, waytype=0)
                                )
                        if not area.fallback_nodes:
                            nearest_node = min(space_nodes, key=lambda node: fallback_point.distance(node.point))
                            area.fallback_nodes[nearest_node.i] = RouterNodeAndEdge(
                                node=fallback_node,
                                edge=RouterEdge.create(from_node=fallback_node, to_node=nearest_node, waytype=0)
                            )

                for poi in space_obj.pois.all():
                    routerpoi = RouterPOI(poi)
                    try:
                        routeraltitudearea = routerspace.altitudearea_for_point(unwrap_geom(poi.geometry))
                        routerpoi.altitude = routeraltitudearea.get_altitude(poi.geometry)
                        poi_nodes = routeraltitudearea.nodes_for_point(poi.geometry, all_nodes=nodes)
                    except LocationUnreachable:
                        poi_nodes = {}
                    routerpoi.nodes = set(i for i in poi_nodes.keys())
                    routerpoi.nodes_addition = poi_nodes
                    pois[poi.pk] = routerpoi
                    routerspace.pois.add(poi.pk)
                    for location in poi.tags.all():
                        locationtags.setdefault(location.pk, RouterLocation(location)).targets.append(routerpoi)

                for column in space_obj.columns.all():
                    if column.access_restriction_id is None:
                        continue
                    column.geometry_prep = prepared.prep(unwrap_geom(column.geometry))
                    column_nodes = tuple(node for node in space_nodes if column.geometry_prep.intersects(node.point))
                    column_nodes = set(node.i for node in column_nodes)
                    restrictions.setdefault(column.access_restriction_id,
                                            RouterRestriction()).additional_nodes.update(column_nodes)

                routerspace.geometry = accessible_geom

                spaces[space.pk] = routerspace
                for location in space.tags.all():
                    locationtags.setdefault(location.pk, RouterLocation(location)).targets.append(routerspace)

            level_spaces = set(space.pk for space in level.spaces.all())

            routerlevel = RouterLevel(level)
            routerlevel.spaces = level_spaces
            routerlevel.nodes = set(range(nodes_before_count, len(nodes)))
            levels[level.pk] = routerlevel
            for location in level.tags.all():
                locationtags.setdefault(location.pk, RouterLocation(location)).targets.append(level)

        # add sublocations
        for location in LocationTag.objects.prefetch_related(
                Prefetch("calculated_descendants", LocationTag.objects.only("pk"))
        ):
            router_location = locationtags.setdefault(location.pk, RouterLocation(location))
            router_location.sublocations.update(sublocation.pk for sublocation in location.calculated_descendants.all())

        # add graph descriptions
        for description in LeaveDescription.objects.all():
            spaces[description.space_id].leave_descriptions[description.target_space_id] = description.description

        for description in CrossDescription.objects.all():
            spaces[description.space_id].cross_descriptions[(description.origin_space_id,
                                                             description.target_space_id)] = description.description

        # waytypes
        waytypes: deque[RouterWayType] = deque([RouterWayType(None)])
        waytypes_lookup = {None: 0}
        for i, waytype in enumerate(WayType.objects.all(), start=1):
            waytypes.append(RouterWayType(waytype))
            waytypes_lookup[waytype.pk] = i
        waytypes: tuple[RouterWayType, ...] = tuple(waytypes)

        # collect nodes
        nodes: tuple[RouterNode, ...] = tuple(nodes)
        nodes_lookup = {node.pk: node.i for node in nodes}

        # collect edges
        edges = tuple(
            RouterEdge.create(
                from_node=nodes[nodes_lookup[edge.from_node_id]],
                to_node=nodes[nodes_lookup[edge.to_node_id]],
                waytype=waytypes_lookup[edge.waytype_id],
                access_restriction=edge.access_restriction_id
            )
            for edge in GraphEdge.objects.all()
        )
        edges = {(edge.from_node, edge.to_node): edge for edge in edges}

        # build graph matrix
        build_waytype_indices = {i: (deque(), deque()) for i in range(len(waytypes))}
        graph = np.full(shape=(len(nodes), len(nodes)), fill_value=np.inf, dtype=np.float32)
        for edge in edges.values():
            index = (edge.from_node, edge.to_node)
            graph[index] = edge.distance
            build_waytype_indices[edge.waytype][0 if edge.rise > 0 else 1].append(index)
            if edge.access_restriction:
                restrictions.setdefault(edge.access_restriction, RouterRestriction()).edges.append(index)

        # respect slow_down_factor
        for routerarea in areas.values():
            if routerarea.slow_down_factor != 1:
                area_nodes = np.array(tuple(routerarea.nodes), dtype=np.uint32)
                graph[area_nodes.reshape((-1, 1)), area_nodes] *= float(routerarea.slow_down_factor)

        # finalize waytype matrixes
        for i, waytype in enumerate(waytypes):
            waytype.upwards_indices = np.array(build_waytype_indices[i][0], dtype=np.uint32).reshape((-1, 2))
            waytype.nonupwards_indices = np.array(build_waytype_indices[i][1], dtype=np.uint32).reshape((-1, 2))

        # finalize restriction edge matrixes
        for restriction in restrictions.values():
            restriction.edges = np.array(restriction.edges, dtype=np.uint32).reshape((-1, 2))

        router = cls(
            update=update,
            levels=levels,
            spaces=spaces,
            areas=areas,
            pois=pois,
            locationtags=locationtags,
            restrictions=restrictions,
            nodes=nodes,
            edges=edges,
            waytypes=waytypes,
            graph=graph
        )
        pickle.dump(router, open(cls.build_filename(update), 'wb'))
        return router

    def build_indexes(self):
        # can't be precalculated because of this bug: https://github.com/Toblerity/rtree/issues/87
        for level_id, level in self.levels.items():
            for space_id in level.spaces:
                space = self.spaces[space_id]
                level.space_index.insert(space_id, space.geometry)
                for area_id in space.areas:
                    space.areas_index.insert(area_id, self.areas[area_id].geometry)
                for poi_id in space.pois:
                    space.pois_index.insert(poi_id, self.pois[poi_id].geometry)
                for i, altitudearea in enumerate(space.altitudeareas):
                    space.altitudeareas_index.insert(i, altitudearea.geometry)

    @classmethod
    def build_filename(cls, update: MapUpdateTuple):
        return settings.CACHE_ROOT / update.folder_name / 'router.pickle'

    @classmethod
    def load_nocache(cls, update: MapUpdateTuple):
        router = pickle.load(open(cls.build_filename(update), 'rb'))
        router.build_indexes()
        return router

    cached = LocalContext()

    NoUpdate = (-1, -1)

    @classmethod
    def load(cls):
        from c3nav.mapdata.models import MapUpdate
        update = MapUpdate.last_update("routing.rebuild_router")
        if getattr(cls.cached, 'update', cls.NoUpdate) < update:
            cls.cached.data = cls.load_nocache(update)
        return cls.cached.data

    def locationpoint_to_routercoordinates(self, locationpoint: LocationPoint,
                                           restrictions: "RouterRestrictionSet") -> Optional["RouterCoordinates"]:
        point = Point(locationpoint[1:])
        routerpoint = RouterCoordinates(CustomLocation(*locationpoint))
        space = self.space_for_point(locationpoint[0], point, restrictions)
        if space is None:
            return None
        altitudearea = space.altitudearea_for_point(point)
        routerpoint.altitude = altitudearea.get_altitude(point)
        location_nodes = altitudearea.nodes_for_point(point, all_nodes=self.nodes)
        routerpoint.nodes = set(i for i in location_nodes.keys())
        routerpoint.nodes_addition = location_nodes
        return routerpoint

    def get_locations(self, location: LocationProtocol, restrictions: "RouterRestrictionSet") -> "RouterLocationSet":
        locations: tuple[RouterLocation, ...] = ()

        if isinstance(location, LocationTag):
            # locationtags… we just check if we know them
            if location.pk not in self.locationtags:
                raise NotYetRoutable
            locationtag = self.locationtags[location.pk]

            if locationtag.can_see(restrictions):  # todo: used to be run on the incoming object, do that again
                locations = (
                    locationtag,
                    *(sublocation for sublocation in (self.locationtags[pk] for pk in locationtag.sublocations)
                      if sublocation.can_see(restrictions))
                )

        else:
            # anything else… we just use what LocationProtocol provides
            locations = tuple(
                RouterLocation(location, targets=[routerpoint])
                for routerpoint in (self.locationpoint_to_routercoordinates(locationpoint, restrictions)
                                    for locationpoint in location.points)
                if routerpoint
            )

        # check dynamic state, any interesting things to route to?
        for sublocation in locations:
            dynamic_state = sublocation.dynamic_state
            if dynamic_state:
                sublocation.targets.extend(filter(None, (
                    self.locationpoint_to_routercoordinates(locationpoint, restrictions)
                    for locationpoint in dynamic_state.dynamic_points
                )))

        # if there's no targets, the location is unreachable
        if not any(sublocation.targets for sublocation in locations):
            raise LocationUnreachable

        result = RouterLocationSet(locations)
        if not result.get_nodes(restrictions):
            raise LocationUnreachable
        return result

    def space_for_point(self, level: int, point: Point, restrictions: "RouterRestrictionSet",
                        max_distance=20) -> Optional['RouterSpace']:
        # todo: way better caching here, and for the rest of custom location description stuff
        point = Point(point.x, point.y)
        level = self.levels[level]
        excluded_spaces = restrictions.spaces if restrictions else frozenset()
        print(level.space_index.__dict__)
        print(level.space_index.intersection(Point(point.x, point.y)))

        space_ids = (
            level.spaces if level.space_index is None else level.space_index.intersection(Point(point.x, point.y))
        ) - excluded_spaces
        print(space_ids)
        for space in space_ids:
            if self.spaces[space].geometry_prep.contains(point):
                return self.spaces[space]

        if level.space_index is not None:
            space_ids = (
                level.space_index.intersection(Point(point.x, point.y).buffer(max_distance))
            ) - excluded_spaces

        spaces = (self.spaces[space] for space in space_ids if space not in excluded_spaces)
        spaces = ((space, space.geometry.distance(point)) for space in spaces)
        spaces = tuple((space, distance) for space, distance in spaces if distance < max_distance)
        if not spaces:
            return None
        return min(spaces, key=operator.itemgetter(1))[0]

    def altitude_for_point(self, space: int, point: Point) -> float:
        return self.spaces[space].altitudearea_for_point(point).get_altitude(point)

    def level_id_for_xyz(self, xyz: tuple[float, float, float], restrictions: "RouterRestrictionSet", max_distance=50):
        xy = Point(xyz[0], xyz[1])
        z = xyz[2]
        possible_levels = {}
        for level_id, level in self.levels.items():
            space = self.space_for_point(level=level_id, point=xy,
                                         restrictions=restrictions, max_distance=max_distance)
            if space:
                possible_levels[level_id] = np.linalg.norm(
                    np.array((space.altitudearea_for_point(xy).get_altitude(xy)-z, space.geometry.distance(xy)))
                )
        if possible_levels:
            return min(possible_levels.items(), key=itemgetter(1))[0]

        return min(self.levels.items(), key=lambda a: abs(float(a[1].base_altitude)-z))[0]

    def describe_custom_location(self, location: CustomLocation):
        restrictions = self.get_restrictions(active_map_permissions.access_restrictions)

        point = Point(location.point[1:])
        space = self.space_for_point(level=location.level.pk, point=point, restrictions=restrictions)
        if not space:
            return CustomLocationDescription(
                space=space.get_location() if space else None, space_geometry=space,
                altitude=None, areas=(), near_area=None, near_poi=None, nearby=()
            )
        try:
            altitude = space.altitudearea_for_point(point).get_altitude(point)
        except LocationUnreachable:
            altitude = None
        areas, near_area, nearby_areas = space.areas_for_point(
            areas=self.areas, point=location, restrictions=restrictions
        )
        near_poi, nearby_pois = space.poi_for_point(
            pois=self.pois, point=location, restrictions=restrictions
        )
        nearby = tuple(sorted(
            tuple(nearby_areas+nearby_pois),
            key=operator.itemgetter(1)
        ))
        # show all location within 5 meters, but at least 20
        min_i = len(nearby)+1
        for i, (location, distance) in enumerate(nearby):
            if distance > 5:
                min_i = i
        nearby = tuple(location for location, distance in nearby[:max(20, min_i)])
        return CustomLocationDescription(
            space=space.get_location() if space else None,
            space_geometry=space,
            altitude=altitude,
            areas=tuple(filter(None, (area.get_location() for area in areas))),
            near_area=near_area.get_location() if near_area else None,
            near_poi=near_poi.get_location() if near_poi else None,
            nearby=tuple(filter(None, (n.get_location() for n in nearby)))
        )

    @cached_property
    def shortest_path_func(self):
        # this is effectively a lazy import to save memory… todo: do we need that?
        from scipy.sparse.csgraph import shortest_path
        return shortest_path

    def shortest_path(self, restrictions: "RouterRestrictionSet", options):
        options_key = options.serialize_string()
        cache_key = f"router:shortest_path:{restrictions.cache_key}:{options_key}"
        result = versioned_cache.get(self.update, cache_key)
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
            if restrictions_setting == "avoid":
                factor = 100000
            else:
                graph *= 100000
                factor = 1/100000
            all_restrictions = RouterRestrictionSet(self.restrictions)
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

        distances, predecessors = self.shortest_path_func(graph, directed=True, return_predecessors=True)
        versioned_cache.set(self.update, cache_key, (distances.astype(np.float64).tobytes(),
                                                     predecessors.astype(np.int32).tobytes()), 600)
        return distances, predecessors

    def get_restrictions(self, permissions: set[int]) -> "RouterRestrictionSet":
        return RouterRestrictionSet({
            pk: restriction for pk, restriction in self.restrictions.items() if pk not in permissions
        })

    def get_route(self, origin: LocationProtocol, destination: LocationProtocol, options: RouteOptions):
        restrictions = self.get_restrictions(active_map_permissions.access_restrictions)

        # get possible origins and destinations
        origins = self.get_locations(origin, restrictions)
        destinations = self.get_locations(destination, restrictions)

        # calculate shortest path matrix
        distances, predecessors = self.shortest_path(restrictions, options=options)

        # find shortest path for our origins and destinations
        origin_nodes = np.array(tuple(origins.get_nodes(restrictions)))
        destination_nodes = np.array(tuple(destinations.get_nodes(restrictions)))
        origin_node, destination_node = np.unravel_index(
            distances[origin_nodes.reshape((-1, 1)), destination_nodes].argmin(),
            (len(origin_nodes), len(destination_nodes))
        )
        origin_node = origin_nodes[origin_node]
        destination_node = destination_nodes[destination_node]

        if distances[origin_node, destination_node] == np.inf:
            raise NoRouteFound

        # get best origin and destination
        final_origin = origins.get_location_for_node(origin_node, restrictions=restrictions)
        final_destination = destinations.get_location_for_node(destination_node, restrictions=restrictions)

        if final_origin is None or final_destination is None:
            raise ValueError

        # recreate path
        path_nodes = deque((destination_node, ))
        last_node = destination_node
        while last_node != origin_node:
            last_node = predecessors[origin_node, last_node]
            path_nodes.appendleft(last_node)

        return Route(
            router=self,
            origin=RouteLocation(
                location=final_origin.location.get_actual_location(),
                point=final_origin.point,
                dotted=bool(final_origin.get_nodes_addition(restrictions).get(origin_node))
            ),
            destination=RouteLocation(
                location=final_destination.location.get_actual_location(),
                point=final_destination.point,
                dotted=bool(final_destination.get_nodes_addition(restrictions).get(destination_node))
            ),
            path_nodes=tuple(path_nodes),
            options=options,
            origin_addition=final_origin.get_nodes_addition(restrictions).get(origin_node),
            destination_addition=final_destination.get_nodes_addition(restrictions).get(destination_node),
            origin_xyz=final_origin.xyz,
            destination_xyz=final_destination.xyz,
        )


class CustomLocationDescription(NamedTuple):
    # todo: space and space_geometry? this could clearly be much better
    space: Optional[LocationTag]
    space_geometry: Optional["RouterSpace"]
    altitude: Optional[float]
    areas: Sequence[LocationTag]
    near_area: Optional[LocationTag]
    near_poi: Optional[LocationTag]
    nearby: Sequence[LocationTag]


@dataclass
class BaseRouterTarget:
    def __init__(self, src):
        self.point = getattr(src, "point", None)
        self.nodes: set[int] = set()
        self.nodes_addition: NodeConnectionsByNode = {}
        self.access_restriction_id: int | None = src.access_restriction_id

    def can_see(self, restrictions: "RouterRestrictionSet") -> bool:
        raise NotImplementedError


@dataclass
class BaseRouterDatabaseTarget(BaseRouterTarget):
    def __init__(self, src):
        super().__init__(src)
        self.id = src.id
        self.sorted_tags: list[int] = [location.pk for location in src.sorted_tags]

    @property
    def pk(self):
        return self.id

    def get_location(self) -> LocationTag | None:
        # todo: do this nicer eventually
        visible_locations = LocationManager.get_visible()
        return next(iter(chain(
            filter(None, (visible_locations.get(pk, None) for pk in self.sorted_tags)),
            (None, )
        )))

    @property
    def title(self):
        location = self.get_location()
        if location:
            return location.title
        # todo: fix this, make this nicer, in the functions that cal this
        return '(no title)'


@dataclass
class BaseRouterGeometryTarget(BaseRouterDatabaseTarget):
    def __init__(self, src):
        super().__init__(src)
        self.geometry = src.geometry

    @cached_property
    def geometry_prep(self):
        return prepared.prep(unwrap_geom(self.geometry))

    def __getstate__(self):
        result = self.__dict__.copy()
        result.pop('geometry_prep', None)
        return result


@dataclass
class RouterLevel(BaseRouterDatabaseTarget):
    def __init__(self, src: Level):
        # todo: use dataclasses propertly here
        super().__init__(src)
        self.on_top_of_id: int | None = src.on_top_of_id
        self.short_label: str = src.short_label
        self.spaces: set[int] = set()
        self.space_index = Index()

    def can_see(self, restrictions: "RouterRestrictionSet") -> bool:
        return self.access_restriction_id not in restrictions


@dataclass
class RouterSpace(BaseRouterGeometryTarget):
    def __init__(self, src: Space):
        super().__init__(src)
        self.level_id = src.level_id
        self.enter_description: str | None = src.enter_description
        self.areas: set[int] = set()
        self.pois: set[int] = set()
        self.altitudeareas: list[RouterAltitudeArea] = []
        self.leave_descriptions: dict[int, Promise] = {}
        self.cross_descriptions: dict[tuple[int, int], Promise] = {}

    areas_index: Index = field(default_factory=Index)
    pois_index: Index = field(default_factory=Index)
    altitudeareas_index: Index = field(default_factory=Index)

    def can_see(self, restrictions: "RouterRestrictionSet") -> bool:
        return self.pk not in restrictions.spaces

    def altitudearea_for_point(self, point: Point):
        if not self.altitudeareas:
            raise LocationUnreachable
        altitudeareas = tuple(self.altitudeareas[i] for i in self.altitudeareas_index.intersection(point))
        for area in altitudeareas:
            if area.geometry_prep.intersects(point):
                return area
        altitudeareas = tuple(
            self.altitudeareas[i] for i in self.altitudeareas_index.intersection(point.buffer(20))
        )
        if altitudeareas:
            return min(altitudeareas, key=lambda area: area.geometry.distance(point))
        return self.altitudeareas[0]

    def areas_for_point(self, areas, point, restrictions: "RouterRestrictionSet"):
        # todo: areas is redundant as a parameter, same for pois_for_point further down
        point = Point(point.x, point.y)
        areas = {pk: area for pk, area in areas.items()
                 if pk in self.areas and area.can_see(restrictions)}

        contained_area_ids = self.areas_index.intersection(point)
        nearby_area_ids = self.areas_index.intersection(point.buffer(20))

        nearby = ((area, area.geometry.distance(point)) for area in areas.values()
                  if area.pk in nearby_area_ids)
        nearby = tuple((area, distance) for area, distance in nearby if distance < 20)

        contained = tuple(area for area in areas.values() if area.geometry_prep.contains(point)
                          if area.pk in contained_area_ids)
        if contained:
            return tuple(sorted(contained, key=lambda area: area.geometry.area)), None, nearby

        near = tuple((area, distance) for area, distance in nearby if distance < 5)
        if not near:
            return (), None, nearby
        return (), min(near, key=operator.itemgetter(1))[0], nearby

    def poi_for_point(self, pois, point, restrictions: "RouterRestrictionSet"):
        point = Point(point.x, point.y)
        pois = {pk: poi for pk, poi in pois.items()
                if pk in self.pois and poi.can_see(restrictions)}

        nearby_poi_ids = self.pois_index.intersection(point.buffer(20))

        nearby = ((poi, poi.geometry.distance(point)) for poi in pois.values()
                  if poi.pk in nearby_poi_ids)
        nearby = tuple((poi, distance) for poi, distance in nearby if distance < 20)

        near = tuple((poi, distance) for poi, distance in nearby if distance < 5)
        if not near:
            return None, nearby
        return min(near, key=operator.itemgetter(1))[0], nearby


@dataclass
class RouterArea(BaseRouterGeometryTarget):
    def __init__(self, src: Area):
        super().__init__(src)
        self.space_id: int = src.space_id
        self.slow_down_factor: Decimal = src.slow_down_factor

    def can_see(self, restrictions: "RouterRestrictionSet") -> bool:
        return self.space_id not in restrictions.spaces and self.access_restriction_id not in restrictions


@dataclass
class RouterPOI(BaseRouterGeometryTarget):
    def __init__(self, src: POI):
        super().__init__(src)
        self.space_id: int = src.space_id
        self.x = src.x
        self.y = src.y
        self.altitude: float | None = None

    def can_see(self, restrictions: "RouterRestrictionSet") -> bool:
        return self.space_id not in restrictions.spaces and self.access_restriction_id not in restrictions

    @cached_property
    def xyz(self):
        return np.array((self.x, self.y, self.altitude))


@dataclass
class RouterCoordinates(BaseRouterTarget):
    def __init__(self, src: CustomLocation):
        super().__init__(src)
        self.x = src.x
        self.y = src.y
        self.altitude: float | None = None

    def can_see(self, restrictions: "RouterRestrictionSet") -> bool:
        return True

    @cached_property
    def xyz(self):
        return np.array((self.x, self.y, self.altitude))


RouterTarget: TypeAlias = Union["RouterLevel", "RouterSpace", "RouterArea", "RouterPOI", "RouterCoordinates"]


@dataclass
class RouterLocation:
    src: LocationProtocol
    sublocations: set[int] = field(default_factory=set)
    targets: list[RouterTarget] = field(default_factory=list)

    def can_see(self, restrictions: "RouterRestrictionSet") -> bool:
        # todo: implement this differently, obviously
        return (
            (
                not self.effective_access_restrictions
                or not any((restriction in restrictions) for restriction in self.effective_access_restrictions)
            ) and (
                not self.targets
                or any(target.can_see(restrictions) for target in self.targets)
            )
        )

    def __getattr__(self, name):
        if name == '__setstate__':
            raise AttributeError
        return getattr(self.src, name)

    def get_nodes(self, restrictions: "RouterRestrictionSet"):
        return reduce(
            operator.or_,
            (target.nodes for target in self.targets if target.can_see(restrictions)),
            set()
        )

    def get_target_for_node(self, node, restrictions: "RouterRestrictionSet") -> RouterTarget | None:
        for target in self.targets:
            if target.can_see(restrictions) and node in target.nodes:
                return target
        return None

    def get_nodes_addition(self, restrictions: "RouterRestrictionSet"):
        # todo: minimum per node?
        return reduce(
            operator.or_,
            (target.nodes_addition for target in self.targets if target.can_see(restrictions)),
            {}
        )

    def get_actual_location(self):
        # todo: we want to get rid of src at some point
        return self.src


@dataclass
class RouterAltitudeArea:
    geometry: Polygon | MultiPolygon
    clear_geometry: Polygon | MultiPolygon
    altitude: Decimal
    points: Sequence[AltitudeAreaPoint]
    nodes: frozenset[int] = field(default_factory=frozenset)
    fallback_nodes: NodeConnectionsByNode = field(default_factory=dict)

    @cached_property
    def geometry_prep(self):
        return prepared.prep(self.geometry)

    @cached_property
    def clear_geometry_prep(self):
        return prepared.prep(self.clear_geometry)

    def get_altitude(self, point: Point):
        # noinspection PyTypeChecker,PyCallByClass
        return AltitudeArea.get_altitudes(self, (point.x, point.y))[0]

    def nodes_for_point(self, point: Point, all_nodes) -> NodeConnectionsByNode:
        point = Point(point.x, point.y)

        nodes = {}
        if self.nodes:
            for node in self.nodes:
                node = all_nodes[node]
                line = LineString([(node.x, node.y), (point.x, point.y)])
                if line.length < 10 and not self.clear_geometry_prep.intersects(line):
                    nodes[node.i] = RouterNodeAndEdge(node=None, edge=None)
            if not nodes:
                nearest_node = min(tuple(all_nodes[node] for node in self.nodes),
                                   key=lambda node: point.distance(node.point))
                nodes[nearest_node.i] = RouterNodeAndEdge(node=None, edge=None)
        else:
            nodes = self.fallback_nodes
        return nodes

    def __getstate__(self):
        result = self.__dict__.copy()
        result.pop('geometry_prep', None)
        result.pop('clear_geometry_prep', None)
        return result


@dataclass
class RouterNode:
    i: int | None
    pk: int | None
    x: float
    y: float
    space: int
    altitude: float
    areas: set[int] = field(default_factory=set)

    @classmethod
    def from_graph_node(cls, node, i):
        return cls(
            i=i,
            pk=node.pk,
            x=node.geometry.x,
            y=node.geometry.y,
            space=node.space_id,
            altitude=0,
        )

    @cached_property
    def point(self):
        return Point(self.x, self.y)

    @cached_property
    def xyz(self):
        return np.array((self.x, self.y, self.altitude))


@dataclass
class RouterEdge:
    from_node: int
    to_node: int
    waytype: int
    access_restriction: int
    rise: float | None
    distance: float

    @classmethod
    def create(cls, from_node: "RouterNode", to_node: "RouterNode", waytype: int,
               access_restriction: int | None = None):
        return cls(
            from_node=from_node.i,
            to_node=to_node.i,
            waytype=waytype,
            access_restriction=access_restriction,
            rise=(None if to_node.altitude is None or from_node.altitude is None
                  else (to_node.altitude - from_node.altitude)),
            distance=np.linalg.norm(to_node.xyz - from_node.xyz),
        )


@dataclass
class RouterWayType:
    src: WayType | None
    upwards_indices: np.typing.NDArray = field(default_factory=lambda: np.array(()))
    nonupwards_indices: np.typing.NDArray = field(default_factory=lambda: np.array(()))

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


@dataclass
class RouterLocationWithTarget:
    location: RouterLocation
    target: RouterTarget

    @property
    def point(self) -> LocationPoint:
        return self.target.point

    @property
    def xyz(self) -> tuple[float, float, float] | None:
        return getattr(self.target, 'xyz', None)

    def get_nodes_addition(self, restrictions: "RouterRestrictionSet"):
        return self.location.get_nodes_addition(restrictions)


@dataclass
class RouterLocationSet:
    """
    Describes a Location selected as an origin or destination for a route. This might match multiple locations,
    for example if we route to a location with descendants, we select the nearest/best descendant.
    """
    locations: tuple[RouterLocation, ...]

    def get_nodes(self, restrictions: "RouterRestrictionSet") -> frozenset[int]:
        return reduce(
            operator.or_,
            (location.get_nodes(restrictions)
             for location in self.locations if location.can_see(restrictions)),
            frozenset()
        )

    def get_location_for_node(self, node, restrictions: "RouterRestrictionSet") -> RouterLocationWithTarget | None:
        for location in self.locations:
            if location.can_see(restrictions):
                target = location.get_target_for_node(node, restrictions=restrictions)
                if target:
                    return RouterLocationWithTarget(location, target)
        return None


@dataclass
class RouterRestriction:
    spaces: set[int] = field(default_factory=set)
    additional_nodes: set[int] = field(default_factory=set)
    edges: deque[EdgeIndex] = field(default_factory=deque)


@dataclass
class RouterRestrictionSet:
    restrictions: dict[int, RouterRestriction]

    @cached_property
    def spaces(self) -> frozenset[int]:
        return reduce(operator.or_, (restriction.spaces for restriction in self.restrictions.values()), frozenset())

    @cached_property
    def additional_nodes(self) -> frozenset[int]:
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
