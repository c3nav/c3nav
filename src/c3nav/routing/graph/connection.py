class GraphConnection():
    def __init__(self, graph, from_point, to_point):
        self.graph = graph

        if to_point in from_point.connections:
            self.graph.connections.remove(from_point.connections[to_point])

        from_point.connections[to_point] = self
        to_point.connections_in[from_point] = self
