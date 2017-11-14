from itertools import chain

import numpy as np

from c3nav.mapdata.render.engines import register_engine
from c3nav.mapdata.render.engines.base3d import Base3DEngine


@register_engine
class STLEngine(Base3DEngine):
    filetype = 'stl'

    facet_template = (b'  facet normal %f %f %f\n'
                      b'    outer loop\n'
                      b'      vertex %.3f %.3f %.3f\n'
                      b'      vertex %.3f %.3f %.3f\n'
                      b'      vertex %.3f %.3f %.3f\n'
                      b'    endloop\n'
                      b'  endfacet')

    def _create_facet(self, facet) -> bytes:
        return self.facet_template % tuple(facet.flatten())

    def render(self, filename=None) -> bytes:
        facets = np.vstack(chain(*(chain(*v.values()) for v in self.vertices.values())))
        facets = np.hstack((np.cross(facets[:, 1]-facets[:, 0], facets[:, 2]-facets[:, 1]).reshape((-1, 1, 3)),
                            facets))
        return (b'solid c3nav_export\n' +
                b'\n'.join((self._create_facet(facet) for facet in facets)) +
                b'\nendsolid c3nav_export\n')
