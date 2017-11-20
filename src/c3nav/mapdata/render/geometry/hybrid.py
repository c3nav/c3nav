import operator
from collections import deque
from functools import reduce
from itertools import chain

import numpy as np
from shapely.geometry import GeometryCollection, LineString, MultiLineString
from shapely.ops import unary_union

from c3nav.mapdata.utils.geometry import assert_multipolygon
from c3nav.mapdata.utils.mesh import triangulate_polygon
from c3nav.mapdata.utils.mpl import shapely_to_mpl


def hybrid_union(geoms):
    if not geoms:
        return HybridGeometry(GeometryCollection(), ())
    if len(geoms) == 1:
        return geoms[0]
    add_faces = {}
    for other in geoms:
        for crop_id, faces in other.add_faces.items():
            add_faces[crop_id] = add_faces.get(crop_id, ()) + faces
    return HybridGeometry(geom=unary_union(tuple(geom.geom for geom in geoms)),
                          faces=tuple(chain(*(geom.faces for geom in geoms))),
                          add_faces=add_faces,
                          crop_ids=reduce(operator.or_, (other.crop_ids for other in geoms), set()))


class HybridGeometry:
    __slots__ = ('geom', 'faces', 'crop_ids', 'add_faces')

    def __init__(self, geom, faces, crop_ids=frozenset(), add_faces=None):
        self.geom = geom
        self.faces = faces
        self.add_faces = add_faces or {}
        self.crop_ids = crop_ids

    @classmethod
    def create(cls, geom, face_centers):
        if isinstance(geom, (LineString, MultiLineString)):
            return HybridGeometry(geom, set())
        faces = tuple(
            set(np.argwhere(shapely_to_mpl(subgeom).contains_points(face_centers)).flatten())
            for subgeom in assert_multipolygon(geom)
        )
        return HybridGeometry(geom, tuple(f for f in faces if f))

    @classmethod
    def create_full(cls, geom, vertices_offset, faces_offset):
        if isinstance(geom, (LineString, MultiLineString)):
            return HybridGeometry(geom, set()), np.empty((0, 2), dtype=np.int32), np.empty((0, 3), dtype=np.uint32)

        vertices = deque()
        faces = deque()
        faces_i = deque()
        for subgeom in assert_multipolygon(geom):
            new_vertices, new_faces = triangulate_polygon(subgeom)
            new_faces += vertices_offset
            vertices.append(new_vertices)
            faces.append(new_faces)
            faces_i.append(set(range(faces_offset, faces_offset+new_faces.shape[0])))
            vertices_offset += new_vertices.shape[0]
            faces_offset += new_faces.shape[0]

        vertices = np.vstack(vertices)
        faces = np.vstack(faces)

        return HybridGeometry(geom, tuple(faces_i)), vertices, faces

    def union(self, other):
        add_faces = self.add_faces
        for crop_id, faces in other.add_faces.items():
            add_faces[crop_id] = add_faces.get(crop_id, ())+faces
        return HybridGeometry(geom=self.geom.union(other.geom), faces=self.faces+other.faces, add_faces=add_faces,
                              crop_ids=self.crop_ids | other.crop_ids)

    def difference(self, other):
        return HybridGeometry(geom=self.geom.difference(other.geom), faces=self.faces,
                              add_faces={crop_id: faces for crop_id, faces in self.add_faces.items()
                                         if crop_id not in other.crop_ids},
                              crop_ids=self.crop_ids - other.crop_ids)

    def fit(self, scale, offset):
        offset = np.array((0, 0, offset))
        scale = np.array((1, 1, scale))
        return HybridGeometry(geom=self.geom, crop_ids=self.crop_ids,
                              faces=tuple((faces*scale+offset) for faces in self.faces),
                              add_faces={crop_id: tuple((faces*scale+offset) for faces in self.faces)
                                         for crop_id, faces in self.add_faces})

    def filter(self, **kwargs):
        return HybridGeometry(geom=self.geom, crop_ids=self.crop_ids,
                              faces=tuple(mesh.filter(**kwargs) for mesh in self.faces),
                              add_faces={crop_id: tuple(mesh.filter(**kwargs) for mesh in faces)
                                         for crop_id, faces in self.add_faces.items()})

    def remove_faces(self, faces):
        self.faces = tuple((subfaces-faces) for subfaces in self.faces)

    @property
    def is_empty(self):
        return not self.faces and not any(self.add_faces.values())

    def build_polyhedron(self, create_polyhedron, crops=None, **kwargs):
        remaining_faces = self.faces
        for crop, prep in crops or ():
            if prep.intersects(self.geom):
                crop_faces = set(chain(*crop.faces))
                crop_id = tuple(crop.crop_ids)[0]
                self.add_faces[crop_id] = create_polyhedron(tuple((faces & crop_faces)
                                                                  for faces in self.faces), **kwargs)
                remaining_faces = tuple((faces - crop_faces) for faces in self.faces)
        self.faces = create_polyhedron(remaining_faces, **kwargs)
