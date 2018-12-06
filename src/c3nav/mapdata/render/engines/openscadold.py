import numpy as np

from c3nav.mapdata.render.engines import register_engine
from c3nav.mapdata.render.engines.base3d import Base3DEngine


@register_engine
class OldOpenSCADEngine(Base3DEngine):
    filetype = 'old.scad'

    def _create_polyhedron(self, vertices):
        facets = np.vstack(vertices)
        vertices = tuple(set(tuple(vertex) for vertex in facets.reshape((-1, 3))))
        lookup = {vertex: i for i, vertex in enumerate(vertices)}

        # from collections import Counter
        # print(Counter(Counter([tuple(sorted((tuple(a), tuple(b))))
        #                        for a, b in facets[:, (0, 1, 1, 2, 2, 0), :].reshape((-1, 2, 3))]).values()))

        return (b'  polyhedron(\n' +
                b'    points = [\n' +
                b'\n'.join((b'      [%.3f, %.3f, %.3f],' % tuple(vertex)) for vertex in vertices) + b'\n' +
                b'    ],\n' +
                b'    faces = [\n' +
                b'\n'.join((b'      [%d, %d, %d],' % (lookup[tuple(a)], lookup[tuple(b)], lookup[tuple(c)]))
                           for a, b, c in facets) + b'\n' +
                b'    ],\n' +
                b'    convexity = 10\n' +
                b'  );')

    def render(self, filename=None) -> bytes:
        result = (b'c3nav_export();\n\n' +
                  b'module c3nav_export() {\n' +
                  b'\n'.join((b'  %s();' % group.replace('-', 'minus').encode())
                             for group in self.groups.keys()) + b'\n' +
                  b'}\n\n')
        for group, subgroups in self.groups.items():
            # noinspection PyStringFormat
            result += (b'module ' + group.replace('-', 'minus').encode() + b'() {\n' +
                       b'\n'.join((b'  color([%.2f, %.2f, %.2f]) %s();' %
                                   (*self.colors[subgroup][:3], subgroup.replace('-', 'minus').encode()))
                                  for subgroup in subgroups) + b'\n' +
                       b'}\n')
        result += b'\n'
        for group, vertices in self.vertices.items():
            result += (b'module ' + group.replace('-', 'minus').encode() + b'() {\n' +
                       b'\n'.join(self._create_polyhedron(v) for v in vertices.values()) +
                       b'}\n')
        return result
