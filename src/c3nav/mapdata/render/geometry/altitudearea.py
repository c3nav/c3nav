from collections import deque
from itertools import chain

import numpy as np

from c3nav.mapdata.models import AltitudeArea
from c3nav.mapdata.render.geometry.hybrid import HybridGeometry


class AltitudeAreaGeometries:
    def __init__(self, altitudearea=None, colors=None, obstacles=None):
        if altitudearea is not None:
            self.geometry = altitudearea.geometry
            self.altitude = int(altitudearea.altitude * 1000)
            self.points = altitudearea.points
        else:
            self.geometry = None
            self.altitude = None
            self.points = None
        self.base = None
        self.bottom = None
        self.colors = colors
        self.obstacles = obstacles

    def get_altitudes(self, points):
        # noinspection PyCallByClass,PyTypeChecker
        return AltitudeArea.get_altitudes(self, points/1000).astype(np.int32)

    def create_hybrid_geometries(self, face_centers, vertices_offset, faces_offset):
        self.geometry = HybridGeometry.create(self.geometry, face_centers)

        vertices = deque()
        faces = deque()

        for color, areas in self.colors.items():
            for height in tuple(areas.keys()):
                faces_offset, vertices_offset = self._call_create_full(areas, height, faces, vertices,
                                                                       faces_offset, vertices_offset)

        for height_obstacles in self.obstacles.values():
            for color_obstacles in height_obstacles.values():
                for i in range(len(color_obstacles)):
                    faces_offset, vertices_offset = self._call_create_full(color_obstacles, i, faces, vertices,
                                                                           faces_offset, vertices_offset)

        if not vertices:
            return np.empty((0, 2), dtype=np.int32), np.empty((0, 3), dtype=np.uint32)
        return np.vstack(vertices), np.vstack(faces)

    def _call_create_full(self, mapping, key, faces, vertices, faces_offset, vertices_offset):
        geom = mapping[key]
        new_geom, new_vertices, new_faces = HybridGeometry.create_full(geom, vertices_offset, faces_offset)
        mapping[key] = new_geom
        vertices_offset += new_vertices.shape[0]
        faces_offset += new_faces.shape[0]
        vertices.append(new_vertices)
        faces.append(new_faces)
        return faces_offset, vertices_offset

    def remove_faces(self, faces):
        self.geometry.remove_faces(faces)
        for areas in self.colors.values():
            for area in areas.values():
                area.remove_faces(faces)

    def create_polyhedrons(self, create_polyhedron, altitudes, min_altitude, crops):
        if self.points is None:
            altitudes = self.altitude

        self.base = HybridGeometry(self.geometry.geom, self.geometry.faces)
        self.bottom = HybridGeometry(self.geometry.geom, self.geometry.faces)
        self.geometry.build_polyhedron(create_polyhedron,
                                       lower=altitudes - int(0.7 * 1000),
                                       upper=altitudes,
                                       crops=crops)
        self.base.build_polyhedron(create_polyhedron,
                                   lower=min_altitude - int(0.7 * 1000),
                                   upper=altitudes - int(0.7 * 1000),
                                   crops=crops,
                                   top=False, bottom=False)
        self.bottom.build_polyhedron(create_polyhedron,
                                     lower=0, upper=1,
                                     crops=crops,
                                     top=False)

        for geometry in chain(*(areas.values() for areas in self.colors.values())):
            geometry.build_polyhedron(create_polyhedron,
                                      lower=altitudes,
                                      upper=altitudes + int(0.001 * 1000),
                                      crops=crops)
        # todo: treat altitude properly
        for height, height_geometries in self.obstacles.items():
            for color, color_geometries in height_geometries.items():
                for geometry in color_geometries:
                    geometry.build_polyhedron(create_polyhedron,
                                              lower=altitudes,
                                              upper=altitudes + height,
                                              crops=crops)
