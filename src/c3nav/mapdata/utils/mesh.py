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
    return (
        np.zeros((0, 2), dtype=np.uint32),
        np.zeros((0, 3), dtype=np.uint32),
    )

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
        segments.update(tuple(sorted((a, b))) for a, b in zip(indices, indices[1:]+indices[:1]) if a != b)

    if len(segments) < 3:
        return np.empty((0, 2), dtype=np.int32), np.empty((0, 3), dtype=np.uint32)

    # noinspection PyArgumentList
    info = triangle.MeshInfo()
    info.set_points(np.array(vertices).tolist())
    info.set_facets(segments)

    if holes is not None:
        info.set_holes(np.rint(np.array(holes)*1000))

    mesh = triangle.build(info, quality_meshing=False)

    mesh_points = np.rint(np.array(mesh.points)).astype(np.int32)
    mesh_elements = np.array(mesh.elements, dtype=np.uint32)

    # remove triangles with no area
    facets = np.dstack((np.zeros(mesh_elements.shape), mesh_points[mesh_elements]))
    ok_index = np.cross(facets[:, 1] - facets[:, 0], facets[:, 2] - facets[:, 1]).max(axis=1) != 0
    mesh_elements = mesh_elements[ok_index]

    return mesh_points, mesh_elements


def _triangulate_polygon(polygon: Polygon, keep_holes=False):
    holes = None
    if not keep_holes:
        holes = np.array(tuple(
            Polygon(ring).representative_point().coords for ring in polygon.buffer(0.02).interiors
        ))
        holes = holes.reshape((-1, 2)) if holes.size else None

    return triangulate_rings((polygon.exterior, *polygon.interiors), holes)


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


def triangulate_gapless_mesh_from_polygons(geometries):
    rings = []
    for polygon in geometries:
        polygon = polygon.buffer(0)
        rings.append(polygon.exterior)
        rings.extend(polygon.interiors)
    return triangulate_rings(rings)
