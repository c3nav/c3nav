import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import shortest_path


class Router():
    def __init__(self):
        self.points = []
        self.points_pk = None

        self.transfer_points = set()
        self.shortest_paths = None
        self.predecessors = None

        self._built = False

    # noinspection PyTypeChecker
    def build(self, points, global_routing=False):
        if self._built:
            raise RuntimeError('already built.')
        self._built = True

        self.points = points
        self.points_pk = dict(zip(self.points, range(len(self.points))))
        matrix = np.zeros((len(self.points), len(self.points)))

        for point, pk in self.points_pk.items():
            for to_point, connection in point.connections.items():
                if to_point not in self.points_pk:
                    if not global_routing:
                        self.transfer_points.add(point)
                    continue
                matrix[pk, self.points_pk[to_point]] = connection.distance
            if global_routing:
                for to_point, distance in point.in_room_transfer_distances.items():
                    matrix[pk, self.points_pk[to_point]] = distance

        g_sparse = csr_matrix(np.ma.masked_values(np.fromstring(matrix).reshape(matrix.shape), 0))
        self.shortest_paths, self.predecessors = shortest_path(g_sparse, return_predecessors=True)

        if not global_routing:
            for from_point in self.transfer_points:
                from_point.in_room_transfer_distances = {}
                connections = self.shortest_paths[self.points_pk[from_point], ]
                for to_point_pk in np.argwhere(connections != np.inf).flatten():
                    to_point = self.points[to_point_pk]
                    if to_point not in self.transfer_points:
                        continue
                    from_point.in_room_transfer_distances[to_point] = connections[to_point_pk]

    def get_distance(self, from_point, to_point):
        return self.shortest_paths[self.points_pk[from_point], self.points_pk[from_point]]
