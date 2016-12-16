import os
import pickle
from collections import OrderedDict, namedtuple

import numpy as np
from django.conf import settings
from scipy.sparse.csgraph._shortest_path import shortest_path
from scipy.sparse.csgraph._tools import csgraph_from_dense

from c3nav.mapdata.models import Level
from c3nav.mapdata.models.geometry import LevelConnector
from c3nav.mapdata.models.locations import AreaLocation, Location, LocationGroup, PointLocation
from c3nav.routing.level import GraphLevel
from c3nav.routing.point import GraphPoint


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

    # Building the Graph
    def build(self):
        self._built_level_transfer_points = []
        self._built_levelconnector_points = {}

        for level in self.levels.values():
            level.build()

        # collect rooms and points
        rooms = sum((level.rooms for level in self.levels.values()), [])
        self.points = sum((level._built_points for level in self.levels.values()), [])

        # create connections between levels
        print()
        self.connect_levelconnectors()

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

    def connect_levelconnectors(self):
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
    def build_routers(self):
        level_routers = {}
        room_routers = {}

        empty_distances = np.empty(shape=(len(self.level_transfer_points),) * 2, dtype=np.float16)
        empty_distances[:] = np.inf

        sparse_distances = empty_distances.copy()

        sparse_levels = np.zeros(shape=(len(self.level_transfer_points),) * 2, dtype=np.int16)
        sparse_levels[:] = -1

        for i, level in enumerate(self.levels.values()):
            router, add_room_routers = level.build_routers()
            level_routers[level] = router
            room_routers.update(add_room_routers)

            level_distances = empty_distances.copy()
            in_level_i = np.array(tuple(level.room_transfer_points.index(point)
                                        for point in level.level_transfer_points))
            in_graph_i = np.array(tuple(self.level_transfer_points.index(point)
                                        for point in level.level_transfer_points))
            level_distances[in_graph_i[:, None], in_graph_i] = router.shortest_paths[in_level_i[:, None], in_level_i]

            better = level_distances < sparse_distances
            sparse_distances[better.transpose()] = level_distances[better.transpose()]
            sparse_levels[better.transpose()] = i

        g_sparse = csgraph_from_dense(sparse_distances, null_value=np.inf)
        shortest_paths, predecessors = shortest_path(g_sparse, return_predecessors=True)
        return GraphRouter(shortest_paths, predecessors), level_routers, room_routers

    def get_location_points(self, location: Location):
        if isinstance(location, PointLocation):
            return 'bla'
        elif isinstance(location, AreaLocation):
            return self.levels[location.level.name].arealocation_points[location.name]
        elif isinstance(location, LocationGroup):
            return np.hstack(tuple(self.get_location_points(area) for area in location.locationareas))

    def _get_points_by_i(self, points):
        return tuple(self.points[i] for i in points)

    def _get_index_of_allowed_points(self, points, allowed_points_i):
        return np.array(tuple(i for i, point in enumerate(points) if point in allowed_points_i))

    def get_route(self, origin: Location, destination: Location):
        orig_points_i = set(self.get_location_points(origin))
        dest_points_i = set(self.get_location_points(destination))

        orig_points = self._get_points_by_i(orig_points_i)
        dest_points = self._get_points_by_i(dest_points_i)

        best_route_distance = float('inf')
        best_route = None

        # get routers
        graph_router, level_routers, room_routers = self.build_routers()

        # route within room
        orig_rooms = set(point.room for point in orig_points)
        dest_rooms = set(point.room for point in dest_points)
        common_rooms = orig_rooms & dest_rooms

        # get origin points for each room (points as point index within room)
        orig_room_points = {room: self._get_index_of_allowed_points(room.points, orig_points_i) for room in orig_rooms}
        dest_room_points = {room: self._get_index_of_allowed_points(room.points, dest_points_i) for room in dest_rooms}

        # if the points have common rooms, search for routes within those rooms
        if common_rooms:
            for room in common_rooms:
                shortest_paths = room_routers[room].shortest_paths[orig_room_points[room][:, None],
                                                                   dest_room_points[room]]
                distance = shortest_paths.min()

                # Is this route better than the previous ones?
                if distance >= best_route_distance:
                    continue

                # noinspection PyTypeChecker
                best_route = ('room', room, np.argwhere(shortest_paths == distance)[0])
                best_route_distance = distance

        # get reachable room transfer points and their distance
        # as a dictionary: global transfer point index => (global index of closest location point, distance)
        orig_room_transfers = self._room_transfers(orig_rooms, orig_room_points, room_routers, mode='orig')
        dest_room_transfers = self._room_transfers(dest_rooms, dest_room_points, room_routers, mode='dest')

        # route within level
        orig_levels = set(room.level for room in orig_rooms)
        dest_levels = set(room.level for room in dest_rooms)
        common_levels = orig_levels & dest_levels

        # get reachable roomtransfer points for each level (points as room transfer point index within level)
        orig_level_points = {level: self._get_index_of_allowed_points(level.room_transfer_points, orig_room_transfers)
                             for level in orig_levels}
        dest_level_points = {level: self._get_index_of_allowed_points(level.room_transfer_points, dest_room_transfers)
                             for level in dest_levels}

        if common_levels:
            for level in common_levels:
                o_points = orig_level_points[level]
                d_points = dest_level_points[level]
                shortest_paths = level_routers[level].shortest_paths[o_points[:, None], d_points]
                shortest_paths += np.array(tuple(orig_room_transfers[level.room_transfer_points[in_level_i]][1]
                                                 for in_level_i in o_points))[:, None]
                shortest_paths += np.array(tuple(dest_room_transfers[level.room_transfer_points[in_level_i]][1]
                                                 for in_level_i in d_points))
                distance = shortest_paths.min()

                # Is this route better than the previous ones?
                if distance >= best_route_distance:
                    continue

                # noinspection PyTypeChecker
                best_route = ('level', level, np.argwhere(shortest_paths == distance)[0])
                best_route_distance = distance

        return best_route

    def _room_transfers(self, rooms, room_points, room_routers, mode):
        if mode not in ('orig', 'dest'):
            raise ValueError

        room_transfers = {}
        for room in rooms:
            room_transfer_points = np.array(tuple(room.points.index(point) for point in room.room_transfer_points))

            points = room_points[room]
            if mode == 'orig':
                shortest_paths = room_routers[room].shortest_paths[points[:, None], room_transfer_points]
            else:
                shortest_paths = room_routers[room].shortest_paths[room_transfer_points[:, None], points]

            # noinspection PyTypeChecker
            for from_i, to_i in np.argwhere(shortest_paths != np.inf):
                distance = shortest_paths[from_i, to_i]
                location_i, transfer_i = (from_i, to_i) if mode == 'orig' else (to_i, from_i)
                location_i = room.points[points[location_i]]
                transfer_i = room.points[room_transfer_points[transfer_i]]
                if transfer_i not in room_transfers or room_transfers[transfer_i][1] < distance:
                    room_transfers[transfer_i] = (location_i, distance)

        return room_transfers


GraphRouter = namedtuple('GraphRouter', ('shortest_paths', 'predecessors', ))
