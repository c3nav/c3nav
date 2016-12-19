import numpy as np
from django.utils.functional import cached_property

from c3nav.routing.utils.coords import coord_angle


class GraphConnection():
    def __init__(self, from_point, to_point, distance=None, ctype=''):
        self.from_point = from_point
        self.to_point = to_point
        self.distance = distance if distance is not None else abs(np.linalg.norm(from_point.xy - to_point.xy))
        self.ctype = ctype

    @cached_property
    def angle(self):
        return coord_angle(self.from_point.xy, self.to_point.xy)

    def __repr__(self):
        return ('<GraphConnection %r %r distance=%f ctype=%s>' %
                (self.from_point, self.to_point, self.distance, self.ctype))
