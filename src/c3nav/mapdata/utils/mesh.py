from collections import deque
from functools import lru_cache
from itertools import chain
from typing import Union

import numpy as np
from meshpy import triangle
from shapely.geometry import MultiPolygon, Polygon


@lru_cache()
def get_face_indizes(start, length):
    # noinspection PyTypeChecker
    indices = np.tile(np.arange(start, start + length).reshape((-1, 1)), 2).flatten()[1:-1].reshape((length - 1, 2))
    return np.vstack((indices, (indices[-1][-1], indices[0][0])))


def triangulate_rings(rings, holes=None):
    rings = tuple(
        tuple(tuple(vertex) for vertex in np.rint(np.array(ring.coords)*1000).astype(np.int32))
        for ring in rings
    )

    if not rings:
        return np.empty((0, 2), dtype=np.int32), np.empty((0, 3), dtype=np.uint32)

    vertices = tuple(set(chain(*rings)))
    vertices_lookup = {vertex: i for i, vertex in enumerate(vertices)}

    segments = set()
    for ring in rings:
        indices = tuple(vertices_lookup[vertex] for vertex in ring[:-1])
        segments.update(zip(indices, indices[1:]+indices[:1]))

    # noinspection PyArgumentList
    info = triangle.MeshInfo()
    info.set_points(np.array(vertices).tolist())
    info.set_facets(segments)

    if holes is not None:
        info.set_holes(holes)

    mesh = triangle.build(info, quality_meshing=False)
    return np.rint(np.array(mesh.points)).astype(np.int32), np.array(mesh.elements, dtype=np.uint32)


def _triangulate_polygon(polygon: Polygon, keep_holes=False):
    vertices = deque()
    segments = deque()

    offset = 0
    for ring in chain((polygon.exterior,), polygon.interiors):
        new_vertices = np.array(ring.coords)[:-1]
        vertices.append(new_vertices)
        segments.append(get_face_indizes(offset, len(new_vertices)))
        offset += len(new_vertices)

    # noinspection PyArgumentList
    info = triangle.MeshInfo()
    info.set_points(np.vstack(vertices))
    info.set_facets(np.vstack(segments).tolist())

    if not keep_holes:
        holes = np.array(tuple(
            Polygon(ring).representative_point().coords for ring in polygon.interiors
        ))
        if holes.size:
            info.set_holes(holes.reshape((holes.shape[0], -1)))

    mesh = triangle.build(info, quality_meshing=False)
    return np.array(mesh.points), np.array(mesh.elements)


def triangulate_polygon(geometry: Union[Polygon, MultiPolygon], keep_holes=False):
    if isinstance(geometry, Polygon):
        return _triangulate_polygon(geometry, keep_holes=keep_holes)

    vertices = deque()
    faces = deque()

    offset = 0
    for polygon in geometry.geoms:
        new_vertices, new_faces = _triangulate_polygon(polygon, keep_holes=keep_holes)
        vertices.append(new_vertices)
        faces.append(new_faces+offset if offset else new_faces)
        offset += len(new_vertices)

    return np.vstack(vertices), np.vstack(faces)
