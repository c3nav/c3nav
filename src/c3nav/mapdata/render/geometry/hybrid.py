import operator
from collections import deque
from dataclasses import dataclass, field
from functools import reduce
from itertools import chain
from typing import Literal, TypeVar

import numpy as np
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from c3nav.mapdata.render.geometry.mesh import Mesh
from c3nav.mapdata.utils.geometry import assert_multipolygon
from c3nav.mapdata.utils.mesh import triangulate_polygon


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
                          crop_ids=reduce(operator.or_, (other.crop_ids for other in geoms), frozenset()))


THybridGeometry = TypeVar("THybridGeometry", bound="HybridGeometry")


@dataclass(slots=True)
class HybridGeometry:
    """
    A geometry containing a mesh as well as a shapely geometry,
    so it can be used for different kinds of render engines.

    This object can be in 2 states:
    - 2d mesh state where faces refers to indizes of faces from an external list
    - 3d mesh state where faces refers to Mesh instances
    """
    geom: BaseGeometry
    faces: tuple[int, ...] | tuple[Mesh, ...]
    crop_ids: frozenset = field(default_factory=frozenset)  # todo: specify type more precisely
    add_faces: dict = field(default_factory=dict)  # todo: specify type more precisely

    @classmethod
    def create(cls, geom, face_centers: np.ndarray[tuple[int, Literal[2]], np.uint32]) -> THybridGeometry:
        """
        Create from existing facets and just select the ones that lie inside this polygon.
        """
        if isinstance(geom, (LineString, MultiLineString)):
            return HybridGeometry(geom, ())
        from c3nav.mapdata.utils.mpl import shapely_to_mpl  # moved in here to save memory
        faces = tuple(
            set(np.argwhere(shapely_to_mpl(subgeom).contains_points(face_centers)).flatten())
            for subgeom in assert_multipolygon(geom)
        )

        faces = tuple(reduce(operator.or_, faces, set()))
        return HybridGeometry(geom, faces)  # old code had wrong typing
        # return HybridGeometry(geom, tuple(f for f in faces if f))  # old code had wrong typing

    @classmethod
    def create_full(cls, geom: BaseGeometry,
                    vertices_offset: int, faces_offset: int) -> tuple[THybridGeometry,
                                                                      np.ndarray[tuple[int, Literal[2]], np.uint32],
                                                                      np.ndarray[tuple[int, Literal[3]], np.uint32]]:
        """
        Create by triangulating a polygon and adding the resulting facets to the total list.
        """
        if isinstance(geom, (LineString, MultiLineString, Point)):
            return HybridGeometry(geom, tuple()), np.empty((0, 2), dtype=np.int32), np.empty((0, 3), dtype=np.uint32)

        geom: Polygon | MultiPolygon | GeometryCollection

        vertices: deque = deque()
        faces: deque = deque()
        faces_i: deque = deque()
        for subgeom in assert_multipolygon(geom):
            new_vertices, new_faces = triangulate_polygon(subgeom)
            new_faces += vertices_offset
            vertices.append(new_vertices)
            faces.append(new_faces)
            faces_i.append(set(range(faces_offset, faces_offset+new_faces.shape[0])))
            vertices_offset += new_vertices.shape[0]
            faces_offset += new_faces.shape[0]

        if not vertices:
            return HybridGeometry(geom, tuple()), np.empty((0, 2), dtype=np.int32), np.empty((0, 3), dtype=np.uint32)

        vertices: np.ndarray[tuple[int, Literal[2]], np.uint32] = np.vstack(vertices)
        faces: np.ndarray[tuple[int, Literal[3]], np.uint32] = np.vstack(faces)

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
        """
        Fit this object (when it has minz=0 maxz=1) into a given minz, maxz range.
        """
        offset = np.array((0, 0, offset))
        scale = np.array((1, 1, scale))
        return HybridGeometry(geom=self.geom, crop_ids=self.crop_ids,
                              faces=tuple((faces*scale+offset) for faces in self.faces),
                              add_faces={crop_id: tuple((faces*scale+offset) for faces in self.faces)
                                         for crop_id, faces in self.add_faces})

    def filter(self, **kwargs):
        """
        Remove top, bottom or side facets.
        """
        return HybridGeometry(geom=self.geom, crop_ids=self.crop_ids,
                              faces=tuple(mesh.filter(**kwargs) for mesh in self.faces),
                              add_faces={crop_id: tuple(mesh.filter(**kwargs) for mesh in faces)
                                         for crop_id, faces in self.add_faces.items()})

    def remove_faces(self, faces):
        self.faces = tuple((subfaces-faces) for subfaces in self.faces)

    @property
    def is_empty(self):
        return self.geom.is_empty
        return not self.faces and not any(self.add_faces.values())

    def build_polyhedron(self, create_polyhedron, crops=None, **kwargs):
        """
        Create polyhedron using an externel function from this object,
        which means converting it from a flat mesh to a 3d mesh state.
        """
        remaining_faces = self.faces
        for crop, prep in crops or ():
            if prep.intersects(self.geom):
                crop_faces = set(chain(*crop.faces))
                crop_id = tuple(crop.crop_ids)[0]
                self.add_faces[crop_id] = create_polyhedron(tuple((faces & crop_faces)
                                                                  for faces in self.faces), **kwargs)
                remaining_faces = tuple((faces - crop_faces) for faces in self.faces)
        self.faces = create_polyhedron(remaining_faces, **kwargs)
