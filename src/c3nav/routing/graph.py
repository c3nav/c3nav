# flake8: noqa
import os
import pickle
from collections import OrderedDict, namedtuple
from itertools import combinations

import numpy as np
from django.conf import settings
from scipy.sparse.csgraph._shortest_path import shortest_path
from scipy.sparse.csgraph._tools import csgraph_from_dense

from c3nav.mapdata.models.level import Level
from c3nav.mapdata.models.locations import Location, LocationGroup
from c3nav.routing.connection import GraphConnection
from c3nav.routing.exceptions import AlreadyThere, NoRouteFound, NotYetRoutable
from c3nav.routing.level import GraphLevel
from c3nav.routing.point import GraphPoint
from c3nav.routing.route import NoRoute, Route
from c3nav.routing.routesegments import (GraphRouteSegment, LevelRouteSegment, RoomRouteSegment, SegmentRoute,
                                         SegmentRouteWrapper)


class Graph:
    graph_cached = None
    graph_cached_mtime = None
    default_filename = os.path.join(settings.DATA_DIR, 'graph.pickle')

    def __init__(self, mtime=None):
        self.mtime = mtime
        self.levels = OrderedDict()
        for level in Level.objects.all():
            self.levels[level.name] = GraphLevel(self, level)

        self.points = []
        self.level_transfer_points = None
        self.elevatorlevel_points = None

    # Building the Graph
    def build(self):
        self._built_level_transfer_points = []
        self._built_levelconnector_points = {}

        self._built_elevatorlevel_points = {}

        for level in self.levels.values():
            level.build()

        # collect rooms and points
        rooms = sum((level.rooms for level in self.levels.values()), [])
        self.points = sum((level._built_points for level in self.levels.values()), [])

        # create connections between levels
        print()
        self.connect_levelconnectors()
        self.connect_elevators()

        # finishing build: creating numpy arrays and convert everything else to tuples
        self.points = tuple(set(self.points))

        for i, room in enumerate(rooms):
            room.i = i

        for i, point in enumerate(self.points):
            point.i = i

        self.level_transfer_points = tuple(point.i for point in self._built_level_transfer_points)

        for level in self.levels.values():
            level.finish_build()

        print()
        print('Total:')
        self.print_stats()

        print()
        print('Points per room:')
        for name, level in self.levels.items():
            print(('Level %s:' % name), *(sorted((len(room.points) for room in level.rooms), reverse=True)))

    def print_stats(self):
        print('%d points' % len(self.points))
        print('%d rooms' % sum(len(level.rooms) for level in self.levels.values()))
        print('%d level transfer points' % len(self.level_transfer_points))
        print('%d connections' % sum(level.connection_count() for level in self.levels.values()))

    def add_levelconnector_point(self, levelconnector, point):
        self._built_levelconnector_points.setdefault(levelconnector.name, []).append(point)

    def add_elevatorlevel_point(self, elevatorlevel, point):
        self._built_elevatorlevel_points[elevatorlevel.name] = point

    def connect_levelconnectors(self):
        from c3nav.mapdata.models.geometry import LevelConnector
        for levelconnector in LevelConnector.objects.all():
            center = levelconnector.geometry.centroid
            points = self._built_levelconnector_points.get(levelconnector.name, [])
            rooms = set(point.room for point in points if point.room is not None)
            connected_levels = set(room.level for room in rooms)

            should_levels = tuple(level.name for level in levelconnector.levels.all())
            missing_levels = set(should_levels) - set(level.level.name for level in connected_levels)

            if missing_levels:
                print('levelconnector %s on levels %s at (%.2f, %.2f) is not connected to levels %s!' %
                      (levelconnector.name, ', '.join(should_levels), center.x, center.y, ', '.join(missing_levels)))
                continue

            center_point = GraphPoint(center.x, center.y, None)
            self.points.append(center_point)
            self._built_level_transfer_points.append(center_point)

            for level in connected_levels:
                level._built_room_transfer_points.append(center_point)
                level._built_points.append(center_point)

            for room in rooms:
                room._built_points.append(center_point)

            for point in points:
                center_point.connect_to(point)
                point.connect_to(center_point)

    def connect_elevators(self):
        for elevator in Elevator.objects.all():  # noqa
            elevatorlevels = tuple(elevator.elevatorlevels.all())
            for level1, level2 in combinations(elevatorlevels, 2):
                point1 = self._built_elevatorlevel_points[level1.name]
                point2 = self._built_elevatorlevel_points[level2.name]

                center = GraphPoint((point1.x+point2.x)/2, (point1.y+point2.y)/2, None)
                self.points.append(center)
                self._built_level_transfer_points.append(center)

                for room in (point1.room, point2.room):
                    room._built_points.append(center)
                    room.level._built_room_transfer_points.append(center)
                    room.level._built_points.append(center)

                direction_up = level2.altitude > level1.altitude

                dist = abs(level2.altitude-level1.altitude)

                point1.connect_to(center, ctype=('elevator_up' if direction_up else 'elevator_down'), distance=dist)
                center.connect_to(point2, ctype=('elevator_up' if direction_up else 'elevator_down'), distance=dist)

                point2.connect_to(center, ctype=('elevator_down' if direction_up else 'elevator_up'), distance=dist)
                center.connect_to(point1, ctype=('elevator_down' if direction_up else 'elevator_up'), distance=dist)

    # Loading/Saving the Graph
    def serialize(self):
        return (
            {name: level.serialize() for name, level in self.levels.items()},
            [point.serialize() for point in self.points],
            self.level_transfer_points,
        )

    def save(self, filename=None):
        if filename is None:
            filename = self.default_filename
        with open(filename, 'wb') as f:
            pickle.dump(self.serialize(), f)

    @classmethod
    def unserialize(cls, data, mtime):
        levels, points, level_transfer_points = data

        graph = cls(mtime=mtime)

        for name, level in levels.items():
            graph.levels[name].unserialize(level)

        rooms = sum((level.rooms for level in graph.levels.values()), ())

        graph.points = tuple(GraphPoint(x, y, None if room is None else rooms[room]) for x, y, room in points)
        graph.level_transfer_points = level_transfer_points

        for i, room in enumerate(rooms):
            room.i = i

        for i, point in enumerate(graph.points):
            point.i = i

        return graph

    @classmethod
    def load(cls, filename=None):
        do_cache = False
        if filename is None:
            do_cache = True
            filename = cls.default_filename

        graph_mtime = None
        if do_cache:
            graph_mtime = os.path.getmtime(filename)
            if cls.graph_cached is not None:
                if cls.graph_cached_mtime == graph_mtime:
                    return cls.graph_cached

        with open(filename, 'rb') as f:
            graph = cls.unserialize(pickle.load(f), graph_mtime)

        if do_cache:
            cls.graph_cached_mtime = graph_mtime
            cls.graph_cached = graph

        graph.print_stats()
        return graph

    # Drawing
    def draw_pngs(self, points=True, lines=True):
        for level in self.levels.values():
            level.draw_png(points, lines)

    # Router
    def build_routers(self, allowed_ctypes, allow_nonpublic, avoid, include):
        routers = {}

        empty_distances = np.empty(shape=(len(self.level_transfer_points),) * 2, dtype=np.float16)
        empty_distances[:] = np.inf

        sparse_distances = empty_distances.copy()

        level_transfers = np.zeros(shape=(len(self.level_transfer_points),) * 2, dtype=np.int16)
        level_transfers[:] = -1

        for i, level in enumerate(self.levels.values()):
            routers.update(level.build_routers(allowed_ctypes, allow_nonpublic, avoid, include))
            router = routers[level]

            level_distances = empty_distances.copy()
            in_level_i = np.array(tuple(level.room_transfer_points.index(point)
                                        for point in level.level_transfer_points), dtype=int)
            in_graph_i = np.array(tuple(self.level_transfer_points.index(point)
                                        for point in level.level_transfer_points), dtype=int)
            level_distances[in_graph_i[:, None], in_graph_i] = router.shortest_paths[in_level_i[:, None], in_level_i]

            better = level_distances < sparse_distances
            sparse_distances[better] = level_distances[better]
            level_transfers[better] = i

        g_sparse = csgraph_from_dense(sparse_distances, null_value=np.inf)
        shortest_paths, predecessors = shortest_path(g_sparse, return_predecessors=True)

        routers[self] = GraphRouter(shortest_paths, predecessors, level_transfers)
        return routers

    def get_location_points(self, location: Location, mode):
        if isinstance(location, PointLocation):
            points = self.levels[location.section.name].connected_points(np.array((location.x, location.y)), mode)
            if not points:
                return (), None, None
            points, distances, ctypes = zip(*((point, distance, ctype) for point, (distance, ctype) in points.items()))
            distances = {points[i]: distance for i, distance in enumerate(distances)}
            points = np.array(points, dtype=np.int)
            return points, distances, ctypes
        try:
            if isinstance(location, AreaLocation):
                points = self.levels[location.level.name].arealocation_points[location.name]
                return points, None, None
            elif isinstance(location, LocationGroup):
                points = tuple(np.hstack(tuple(self.get_location_points(area, mode)[0]
                                         for area in location.arealocations.all())).astype(np.int))
                return points, None, None
        except KeyError:
            raise NotYetRoutable

    def _get_points_by_i(self, points):
        return tuple(self.points[i] for i in points)

    def _allowed_points_index(self, points, allowed_points_i):
        return np.array(tuple(i for i, point in enumerate(points) if point in allowed_points_i))

    def get_route(self, origin: Location, destination: Location,
                  allowed_ctypes, allow_nonpublic, avoid, include, visible_nonpublic_areas=None):
        orig_points_i, orig_distances, orig_ctypes = self.get_location_points(origin, 'orig')
        dest_points_i, dest_distances, dest_ctypes = self.get_location_points(destination, 'dest')

        if not len(orig_points_i) or not len(dest_points_i):
            raise NoRouteFound()

        if orig_distances is None and dest_distances is None:
            if set(dest_points_i) & set(orig_points_i):
                orig_points_i = tuple(set(orig_points_i) - set(dest_points_i))
            if set(dest_points_i) & set(orig_points_i):
                dest_points_i = tuple(set(dest_points_i) - set(orig_points_i))

            if not len(orig_points_i) or not len(dest_points_i):
                raise AlreadyThere()

        # if set(orig_points_i) & set(dest_points_i):
        #    raise AlreadyThere()

        add_orig_point = origin if isinstance(origin, PointLocation) else None
        add_dest_point = destination if isinstance(destination, PointLocation) else None

        orig_points = self._get_points_by_i(orig_points_i)
        dest_points = self._get_points_by_i(dest_points_i)
        common_points = tuple(set(orig_points) & set(dest_points))

        best_route = NoRoute

        # get routers
        routers = self.build_routers(allowed_ctypes, allow_nonpublic, avoid, include)

        # route within room
        orig_rooms = set(point.room for point in orig_points)
        dest_rooms = set(point.room for point in dest_points)
        common_rooms = orig_rooms & dest_rooms

        # rooms are directly connectable
        if add_orig_point and add_dest_point and common_rooms:
            room = tuple(common_rooms)[0]
            ctype = room.check_connection((add_orig_point.x, add_orig_point.y), (add_dest_point.x, add_dest_point.y))
            if ctype is not None:
                from_point = GraphPoint(add_orig_point.x, add_orig_point.y, room)
                to_point = GraphPoint(add_dest_point.x, add_dest_point.y, room)
                return Route((GraphConnection(from_point, to_point, ctype=ctype), ))

        if common_points:
            # same location
            if not add_orig_point and not add_dest_point:
                raise AlreadyThere()

            # points are connectable with only one via
            best_point = None
            best_distance = np.inf
            for point in common_points:
                distance = 0
                if add_orig_point:
                    distance += abs(np.linalg.norm(add_orig_point.xy - point.xy))
                if add_dest_point:
                    distance += abs(np.linalg.norm(add_dest_point.xy - point.xy))
                if distance < best_distance:
                    best_distance = distance
                    best_point = point

            connections = []
            if add_orig_point:
                from_point = GraphPoint(add_orig_point.x, add_orig_point.y, best_point.room)
                ctype = orig_ctypes[tuple(orig_points_i).index(best_point.i)]
                connections.append(GraphConnection(from_point, best_point, ctype=ctype))

            if add_dest_point:
                to_point = GraphPoint(add_dest_point.x, add_dest_point.y, best_point.room)
                ctype = dest_ctypes[tuple(dest_points_i).index(best_point.i)]
                connections.append(GraphConnection(best_point, to_point, ctype=ctype))

            return Route(connections)

        # get origin points for each room (points as point index within room)
        orig_room_points = {room: self._allowed_points_index(room.points, orig_points_i) for room in orig_rooms}
        dest_room_points = {room: self._allowed_points_index(room.points, dest_points_i) for room in dest_rooms}

        # add distances to room routers
        if orig_distances is not None:
            for room in orig_rooms:
                distances = np.array(tuple(orig_distances[room.points[i]] for i in orig_room_points[room]))
                routers[room].shortest_paths[orig_room_points[room], :] += distances[:, None]

        if dest_distances is not None:
            for room in dest_rooms:
                distances = np.array(tuple(dest_distances[room.points[i]] for i in dest_room_points[room]))
                routers[room].shortest_paths[:, dest_room_points[room]] += distances

        # if the points have common rooms, search for routes within those rooms
        if common_rooms:
            for room in common_rooms:
                shortest_paths = routers[room].shortest_paths[orig_room_points[room][:, None],
                                                              dest_room_points[room]]
                distance = shortest_paths.min()

                # Is this route better than the previous ones?
                if distance >= best_route.distance:
                    continue

                # noinspection PyTypeChecker
                from_point, to_point = np.argwhere(shortest_paths == distance)[0]
                from_point = orig_room_points[room][from_point]
                to_point = dest_room_points[room][to_point]
                best_route = RoomRouteSegment(room, routers, from_point, to_point).as_route()

        # get reachable room transfer points and their distance
        # as a dictionary: global transfer point index => RoomRouteSegment
        orig_room_transfers = self._room_transfers(orig_rooms, orig_room_points, routers, mode='orig')
        dest_room_transfers = self._room_transfers(dest_rooms, dest_room_points, routers, mode='dest')

        # route within level
        orig_levels = set(room.level for room in orig_rooms)
        dest_levels = set(room.level for room in dest_rooms)
        common_levels = orig_levels & dest_levels

        # get reachable roomtransfer points for each level (points as room transfer point index within level)
        orig_room_transfer_points = {level: self._allowed_points_index(level.room_transfer_points, orig_room_transfers)
                                     for level in orig_levels}
        dest_room_transfer_points = {level: self._allowed_points_index(level.room_transfer_points, dest_room_transfers)
                                     for level in dest_levels}

        # if the points have common levels, search for routes within those levels
        if common_levels:
            for level in common_levels:
                o_points = orig_room_transfer_points[level]
                d_points = dest_room_transfer_points[level]

                if not len(o_points) or not len(d_points):
                    continue

                shortest_paths = routers[level].shortest_paths[o_points[:, None], d_points]

                # add distances to the the room transfer points to the rows and columns
                shortest_paths += np.array(tuple(orig_room_transfers[level.room_transfer_points[in_level_i]].distance
                                                 for in_level_i in o_points))[:, None]
                shortest_paths += np.array(tuple(dest_room_transfers[level.room_transfer_points[in_level_i]].distance
                                                 for in_level_i in d_points))
                distance = shortest_paths.min()

                # Is this route better than the previous ones?
                if distance >= best_route.distance:
                    continue

                # noinspection PyTypeChecker
                from_point, to_point = np.argwhere(shortest_paths == distance)[0]
                from_point = o_points[from_point]
                to_point = d_points[to_point]
                best_route = SegmentRoute((orig_room_transfers[level.room_transfer_points[from_point]],
                                           LevelRouteSegment(level, routers, from_point, to_point),
                                           dest_room_transfers[level.room_transfer_points[to_point]]),
                                          distance=distance)

        # get reachable level transfer points and their distance
        # as a dictionary: global transfer point index => Route
        orig_level_transfers = self._level_transfers(orig_levels, orig_room_transfers, routers, mode='orig')
        dest_level_transfers = self._level_transfers(dest_levels, dest_room_transfers, routers, mode='dest')

        # get reachable leveltransfer points (points as level transfer point index within graph)
        orig_level_transfer_points = self._allowed_points_index(self.level_transfer_points, orig_level_transfers)
        dest_level_transfer_points = self._allowed_points_index(self.level_transfer_points, dest_level_transfers)

        # search a route within the whole graph
        o_points = orig_level_transfer_points
        d_points = dest_level_transfer_points
        if len(o_points) and len(d_points):
            shortest_paths = routers[self].shortest_paths[o_points[:, None], d_points]

            # add distances to the the room transfer points to the rows and columns
            shortest_paths += np.array(tuple(orig_level_transfers[self.level_transfer_points[in_graph_i]].distance
                                             for in_graph_i in o_points))[:, None]
            shortest_paths += np.array(tuple(dest_level_transfers[self.level_transfer_points[in_graph_i]].distance
                                             for in_graph_i in d_points))
            distance = shortest_paths.min()

            # Is this route better than the previous ones?
            if distance < best_route.distance:
                # noinspection PyTypeChecker
                from_point, to_point = np.argwhere(shortest_paths == distance)[0]
                from_point = o_points[from_point]
                to_point = d_points[to_point]
                best_route = SegmentRoute((orig_level_transfers[self.level_transfer_points[from_point]],
                                           GraphRouteSegment(self, routers, from_point, to_point),
                                           dest_level_transfers[self.level_transfer_points[to_point]]),
                                          distance=distance)

        if best_route is NoRoute:
            raise NoRouteFound()

        orig_ctype = orig_ctypes[tuple(orig_points_i).index(best_route.from_point)] if add_orig_point else None
        dest_ctype = dest_ctypes[tuple(dest_points_i).index(best_route.to_point)] if add_dest_point else None
        best_route = SegmentRouteWrapper(best_route, orig_point=add_orig_point, dest_point=add_dest_point,
                                         orig_ctype=orig_ctype, dest_ctype=dest_ctype)
        best_route = best_route.split()
        return best_route

    def _room_transfers(self, rooms, room_points, routers, mode):
        if mode not in ('orig', 'dest'):
            raise ValueError

        room_transfers = {}
        for room in rooms:
            room_transfer_points = np.array(tuple(room.points.index(point)
                                                  for point in room.room_transfer_points), dtype=int)

            points = room_points[room]
            if mode == 'orig':
                shortest_paths = routers[room].shortest_paths[points[:, None], room_transfer_points]
            else:
                shortest_paths = routers[room].shortest_paths[room_transfer_points[:, None], points]

            # noinspection PyTypeChecker
            for from_i, to_i in np.argwhere(shortest_paths != np.inf):
                distance = shortest_paths[from_i, to_i]
                from_i = points[from_i] if mode == 'orig' else room_transfer_points[from_i]
                to_i = room_transfer_points[to_i] if mode == 'orig' else points[to_i]

                transfer_i = room.points[to_i if mode == 'orig' else from_i]
                if transfer_i not in room_transfers or room_transfers[transfer_i].distance > distance:
                    room_transfers[transfer_i] = RoomRouteSegment(room, routers, from_i, to_i)

        return room_transfers

    def _level_transfers(self, levels, all_room_transfers, routers, mode):
        if mode not in ('orig', 'dest'):
            raise ValueError

        level_transfers = {}
        for level in levels:
            level_transfer_points = np.array(tuple(level.room_transfer_points.index(point)
                                                   for point in level.level_transfer_points), dtype=int)

            points, distances = zip(*(tuple((level.room_transfer_points.index(point), segment.distance)
                                            for point, segment in all_room_transfers.items()
                                            if point in level.room_transfer_points)))
            points = np.array(points)
            distances = np.array(distances)

            if mode == 'orig':
                shortest_paths = routers[level].shortest_paths[points[:, None], level_transfer_points]
                shortest_paths += distances[:, None]
            else:
                shortest_paths = routers[level].shortest_paths[level_transfer_points[:, None], points]
                shortest_paths += distances

            # noinspection PyTypeChecker
            for from_i, to_i in np.argwhere(shortest_paths != np.inf):
                distance = shortest_paths[from_i, to_i]
                from_i = points[from_i] if mode == 'orig' else level_transfer_points[from_i]
                to_i = level_transfer_points[to_i] if mode == 'orig' else points[to_i]

                transfer_i = level.room_transfer_points[to_i if mode == 'orig' else from_i]
                room_transfer_i = level.room_transfer_points[from_i if mode == 'orig' else to_i]
                if transfer_i not in level_transfers or level_transfers[transfer_i].distance > distance:
                    segments = [LevelRouteSegment(level, routers, from_i, to_i)]
                    if mode == 'orig':
                        segments.insert(0, all_room_transfers[room_transfer_i])
                    else:
                        segments.append(all_room_transfers[room_transfer_i])
                    level_transfers[transfer_i] = SegmentRoute(segments, distance)

        return level_transfers

    def get_nearest_point(self, level, x, y):
        return self.levels[level.name].nearest_point(np.array((x, y)), 'orig')


GraphRouter = namedtuple('GraphRouter', ('shortest_paths', 'predecessors', 'level_transfers', ))
