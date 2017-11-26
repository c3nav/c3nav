import os
from itertools import chain

import numpy as np

from c3nav.mapdata.render.engines import register_engine
from c3nav.mapdata.render.engines.base3d import Base3DEngine


@register_engine
class WavefrontEngine(Base3DEngine):
    filetype = 'obj'

    def _normal_normal(self, normal):
        return normal / (np.absolute(normal).max())

    def render(self, filename=None):
        facets = np.vstack(chain(*(chain(*v.values()) for v in self.vertices.values())))
        vertices = tuple(set(tuple(vertex) for vertex in facets.reshape((-1, 3))))
        vertices_lookup = {vertex: i for i, vertex in enumerate(vertices, start=1)}

        normals = np.cross(facets[:, 1] - facets[:, 0], facets[:, 2] - facets[:, 1]).reshape((-1, 3))
        normals = normals / np.maximum(1, np.amax(np.absolute(normals), axis=1)).reshape((-1, 1))
        normals = tuple(set(tuple(normal) for normal in normals))
        normals_lookup = {normal: i for i, normal in enumerate(normals, start=1)}

        materials = b''
        materials_filename = filename + '.mtl'
        for name, color in self.colors.items():
            materials += ((b'newmtl %s\n' % name.encode()) +
                          (b'Ka %.2f %.2f %.2f\n' % color[:3]) +
                          (b'Kd %.2f %.2f %.2f\n' % color[:3]) +
                          b'Ks 0.00 0.00 0.00\n' +
                          (b'd %.2f\n' % color[3]) +
                          b'illum 2\n')

        result = b'mtllib %s\n' % os.path.split(materials_filename)[-1].encode()
        result += b'o c3navExport\n'
        result += b''.join((b'v %.3f %.3f %.3f\n' % vertex) for vertex in vertices)
        result += b''.join((b'vn %.6f %.6f %.6f\n' % normal) for normal in normals)

        for group, subgroups in self.groups.items():
            result += b'\n# ' + group.encode() + b'\n'
            for subgroup in subgroups:
                result += b'\n# ' + subgroup.encode() + b'\n'
                for i, vertices in enumerate(self.vertices[subgroup].values()):
                    if not vertices:
                        continue
                    for j, facets in enumerate(vertices):
                        if not facets.size:
                            continue
                        normals = np.cross(facets[:, 1] - facets[:, 0], facets[:, 2] - facets[:, 1]).reshape((-1, 3))
                        normals = normals / np.maximum(1, np.amax(np.absolute(normals), axis=1)).reshape((-1, 1))
                        normals = tuple(normals_lookup[tuple(normal)] for normal in normals)
                        result += ((b'g %s_%d_%d\n' % (subgroup.encode(), i, j)) +
                                   (b'usemtl %s\n' % subgroup.encode()) +
                                   b's off\n' +
                                   b''.join((b'f %d//%d %d//%d %d//%d\n' % (vertices_lookup[tuple(a)], normals[k],
                                                                            vertices_lookup[tuple(b)], normals[k],
                                                                            vertices_lookup[tuple(c)], normals[k],)
                                            for k, (a, b, c) in enumerate(facets)))
                                   )
        return result, (materials_filename, materials)
