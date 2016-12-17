import numpy as np


class GraphConnection():
    def __init__(self, from_point, to_point, distance=None):
        self.from_point = from_point
        self.to_point = to_point
        self.distance = distance if distance is not None else abs(np.linalg.norm(from_point.xy - to_point.xy))

    def __repr__(self):
        return '<GraphConnection %r %r distance=%f>' % (self.from_point, self.to_point, self.distance)
