import numpy as np

from c3nav.mapdata.render.engines import register_engine
from c3nav.mapdata.render.engines.base3d import Base3DEngine


@register_engine
class OpenSCADEngine(Base3DEngine):
    filetype = 'scad'

    def render(self) -> bytes:
        facets = np.vstack(self.vertices)
        vertices = tuple(set(tuple(vertex) for vertex in facets.reshape((-1, 3))))
        lookup = {vertex: i for i, vertex in enumerate(vertices)}

        return (b'polyhedron(\n' +
                b'  points = [\n' +
                b'\n'.join((b'    [%.3f, %.3f, %.3f],' % tuple(vertex)) for vertex in vertices) + b'\n' +
                b'  ],\n' +
                b'  faces = [\n' +
                b'\n'.join((b'    [%d, %d, %d],' % (lookup[tuple(a)], lookup[tuple(b)], lookup[tuple(c)]))
                           for a, b, c in facets) +
                b'  ],\n' +
                b'  convexity = 10\n' +
                b');\n')
