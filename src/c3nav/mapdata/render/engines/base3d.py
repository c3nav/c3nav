from collections import OrderedDict
from itertools import chain
from typing import Optional

import numpy as np

from c3nav.mapdata.render.data import HybridGeometry
from c3nav.mapdata.render.engines.base import FillAttribs, RenderEngine, StrokeAttribs


# noinspection PyAbstractClass
class Base3DEngine(RenderEngine):
    is_3d = True

    def __init__(self, *args, center=True, **kwargs):
        super().__init__(*args, **kwargs)

        self._current_group = None
        self.groups = OrderedDict()
        self.vertices = OrderedDict()
        self.colors = OrderedDict()

        self.np_scale = np.array((self.scale, self.scale, self.scale))
        self.np_offset = np.array((-self.minx * self.scale, -self.miny * self.scale, 0))

        if center:
            self.np_offset -= np.array(((self.maxx - self.minx) * self.scale / 2,
                                        (self.maxy - self.miny) * self.scale / 2,
                                        0))

    def add_group(self, group):
        self._current_group = group
        self.groups.setdefault(group, [])

    def _add_geometry(self, geometry, fill: Optional[FillAttribs], stroke: Optional[StrokeAttribs], category=None,
                      **kwargs):
        if fill is not None:
            key = '%s_%s' % (self._current_group, category)
            if key not in self.vertices:
                self.groups[self._current_group].append(key)
            self.vertices.setdefault(key, []).append(self._place_geometry(geometry))
            self.colors.setdefault(key, self.color_to_rgb(fill.color))

    @staticmethod
    def _append_to_vertices(vertices, append=None):
        if append is not None:
            append = np.array(append, dtype=np.float32).flatten()
            vertices = np.dstack((
                vertices,
                append.reshape(1, append.size).repeat(vertices.shape[0]*3, 0).reshape((-1, 3, append.size))
            ))
        return vertices

    def _place_geometry(self, geometry: HybridGeometry, append=None, offset=True):
        vertices = np.vstack(tuple(chain(*(
            mesh.tolist() for mesh in chain(geometry.faces, *geometry.add_faces.values())
        ))))
        if offset:
            vertices = vertices / 1000 * self.np_scale + self.np_offset
        else:
            vertices = vertices / 1000
        return self._append_to_vertices(vertices, append)
