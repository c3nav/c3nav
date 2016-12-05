import numpy as np


class GraphConnection():
    def __init__(self, graph, from_point, to_point, distance=None):
        self.graph = graph
        self.from_point = from_point
        self.to_point = to_point
        self.distance = distance if distance is not None else np.linalg.norm(from_point.xy - to_point.xy)

        if to_point in from_point.connections:
            self.graph.connections.remove(from_point.connections[to_point])

        from_point.connections[to_point] = self
        to_point.connections_in[from_point] = self
