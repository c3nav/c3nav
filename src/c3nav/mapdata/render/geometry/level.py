import operator
import typing
from collections import Counter, deque
from functools import reduce
from itertools import chain

import numpy as np
from shapely import prepared
from shapely.geometry import GeometryCollection
from shapely.ops import unary_union

from c3nav.mapdata.render.geometry.altitudearea import AltitudeAreaGeometries
from c3nav.mapdata.render.geometry.hybrid import HybridGeometry
from c3nav.mapdata.render.geometry.mesh import Mesh
from c3nav.mapdata.utils.cache import AccessRestrictionAffected
from c3nav.mapdata.utils.geometry import get_rings, unwrap_geom
from c3nav.mapdata.utils.mesh import triangulate_rings

if typing.TYPE_CHECKING:
    from c3nav.mapdata.render.theme import ThemeColorManager

empty_geometry_collection = GeometryCollection()


class LevelGeometries:
    """
    Store geometries for a Level.
    """
    def __init__(self):
        self.buildings = None
        self.altitudeareas = []
        self.heightareas = []
        self.walls = None
        self.walls_extended = None
        self.all_walls = None
        self.short_walls = []
        self.doors = None
        self.doors_extended = None
        self.holes = None
        self.access_restriction_affected = None
        self.restricted_spaces_indoors = None
        self.restricted_spaces_outdoors = None
        self.affected_area = None
        self.ramps = []

        self.vertices = None
        self.faces = None

        self.walls_base = None
        self.walls_bottom = None

        self.pk = None
        self.on_top_of_id = None
        self.short_label = None
        self.base_altitude = None
        self.default_height = None
        self.door_height = None
        self.min_altitude = None
        self.max_altitude = None
        self.max_height = None

        self.lower_bound = None
        self.upper_bound = None

    def __repr__(self):
        return '<LevelGeometries for Level %s (#%d)>' % (self.short_label, self.pk)

    @classmethod
    def build_for_level(cls, level, color_manager: 'ThemeColorManager', altitudeareas_above):
        geoms = LevelGeometries()
        buildings_geom = unary_union([unwrap_geom(b.geometry) for b in level.buildings.all()])
        geoms.buildings = buildings_geom
        buildings_geom_prep = prepared.prep(buildings_geom)

        # remove columns and holes from space areas
        for space in level.spaces.all():
            subtract = []
            if space.outside:
                subtract.append(buildings_geom)
            columns = [c.geometry for c in space.columns.all() if c.access_restriction_id is None]
            if columns:
                subtract.extend(columns)
            if subtract:
                space.geometry = space.geometry.difference(unary_union([unwrap_geom(geom) for geom in subtract]))

            holes = tuple(h.geometry for h in space.holes.all())
            if holes:
                space.holes_geom = unary_union([unwrap_geom(h.geometry) for h in space.holes.all()])
                space.walkable_geom = space.geometry.difference(space.holes_geom)
                space.holes_geom = space.geometry.intersection(space.holes_geom)
            else:
                space.holes_geom = empty_geometry_collection
                space.walkable_geom = space.geometry

        spaces_geom = unary_union([unwrap_geom(s.geometry) for s in level.spaces.all()])
        doors_geom = unary_union([unwrap_geom(d.geometry) for d in level.doors.all()])
        doors_geom = doors_geom.intersection(buildings_geom)
        walkable_spaces_geom = unary_union([unwrap_geom(s.walkable_geom) for s in level.spaces.all()])
        geoms.doors = doors_geom.difference(walkable_spaces_geom)
        if level.on_top_of_id is None:
            geoms.holes = unary_union([s.holes_geom for s in level.spaces.all()])

        # keep track which areas are affected by access restrictions
        access_restriction_affected = {}

        # keep track wich spaces to hide
        restricted_spaces_indoors = {}
        restricted_spaces_outdoors = {}

        # go through spaces and their areas for access control, ground colors, height areas and obstacles
        colors = {}
        obstacles = {}
        heightareas = {}
        for space in level.spaces.all():
            buffered = space.geometry.buffer(0.01).union(unary_union(tuple(
                unwrap_geom(door.geometry)
                for door in level.doors.all() if door.geometry.intersects(unwrap_geom(space.geometry))
            )).difference(walkable_spaces_geom))
            intersects = buildings_geom_prep.intersects(buffered)

            access_restriction = space.access_restriction_id
            if access_restriction is not None:
                access_restriction_affected.setdefault(access_restriction, []).append(space.geometry)

                if intersects:
                    restricted_spaces_indoors.setdefault(access_restriction, []).append(
                        buffered.intersection(buildings_geom)
                    )
                if not intersects or not buildings_geom_prep.contains(buffered):
                    restricted_spaces_outdoors.setdefault(access_restriction, []).append(
                        buffered.difference(buildings_geom)
                    )

            colors.setdefault(space.get_color_sorted(color_manager), {}).setdefault(access_restriction, []).append(
                unwrap_geom(space.geometry)
            )

            for area in space.areas.all():
                access_restriction = area.access_restriction_id or space.access_restriction_id
                area.geometry = area.geometry.intersection(unwrap_geom(space.walkable_geom))
                if access_restriction is not None:
                    access_restriction_affected.setdefault(access_restriction, []).append(area.geometry)
                colors.setdefault(
                    area.get_color_sorted(color_manager), {}
                ).setdefault(access_restriction, []).append(area.geometry)

            for column in space.columns.all():
                access_restriction = column.access_restriction_id
                if access_restriction is None:
                    continue
                column.geometry = column.geometry.intersection(unwrap_geom(space.walkable_geom))
                buffered_column = column.geometry.buffer(0.01)
                if intersects:
                    restricted_spaces_indoors.setdefault(access_restriction, []).append(buffered_column)
                if not intersects or not buildings_geom_prep.contains(buffered):
                    restricted_spaces_outdoors.setdefault(access_restriction, []).append(buffered_column)
                access_restriction_affected.setdefault(access_restriction, []).append(column.geometry)

            for obstacle in sorted(space.obstacles.all(), key=lambda o: o.height+o.altitude):
                if not obstacle.height:
                    continue
                obstacles.setdefault(
                    int((obstacle.height+obstacle.altitude)*1000), {}
                ).setdefault(obstacle.get_color(color_manager), []).append(
                    obstacle.geometry.intersection(unwrap_geom(space.walkable_geom))
                )

            for lineobstacle in space.lineobstacles.all():
                if not lineobstacle.height:
                    continue
                obstacles.setdefault(int(lineobstacle.height*1000), {}).setdefault(
                    lineobstacle.get_color(color_manager), []
                ).append(
                    lineobstacle.buffered_geometry.intersection(unwrap_geom(space.walkable_geom))
                )

            geoms.ramps.extend(ramp.geometry for ramp in space.ramps.all())

            heightareas.setdefault(int((space.height or level.default_height)*1000), []).append(
                unwrap_geom(space.geometry)
            )
        colors.pop(None, None)

        # merge ground colors
        for color, color_group in colors.items():
            for access_restriction, areas in tuple(color_group.items()):
                color_group[access_restriction] = unary_union(areas)

        colors = {color: geometry for color, geometry in sorted(colors.items(), key=lambda v: v[0][0])}

        # add altitudegroup geometries and split ground colors into them
        for altitudearea in level.altitudeareas.all():
            altitudearea_prep = prepared.prep(unwrap_geom(altitudearea.geometry))
            altitudearea_colors = {color: {access_restriction: area.intersection(unwrap_geom(altitudearea.geometry))
                                           for access_restriction, area in areas.items()
                                           if altitudearea_prep.intersects(area)}
                                   for color, areas in colors.items()}
            altitudearea_colors = {color: areas for color, areas in altitudearea_colors.items() if areas}

            altitudearea_obstacles = {}
            for height, height_obstacles in obstacles.items():
                new_height_obstacles = {}
                for color, color_obstacles in height_obstacles.items():
                    new_color_obstacles = []
                    for obstacle in color_obstacles:
                        if altitudearea_prep.intersects(obstacle):
                            new_color_obstacles.append(obstacle.intersection(unwrap_geom(altitudearea.geometry)))
                    if new_color_obstacles:
                        new_height_obstacles[color] = new_color_obstacles
                if new_height_obstacles:
                    altitudearea_obstacles[height] = new_height_obstacles

            geoms.altitudeareas.append(AltitudeAreaGeometries(altitudearea,
                                                              altitudearea_colors,
                                                              altitudearea_obstacles))

        # merge height areas
        geoms.heightareas = tuple((unary_union(geoms), height)
                                  for height, geoms in sorted(heightareas.items(), key=operator.itemgetter(0)))

        # merge access restrictions
        geoms.access_restriction_affected = {access_restriction: unary_union([unwrap_geom(geom) for geom in areas])
                                             for access_restriction, areas in access_restriction_affected.items()}
        geoms.restricted_spaces_indoors = {access_restriction: unary_union(spaces)
                                           for access_restriction, spaces in restricted_spaces_indoors.items()}
        geoms.restricted_spaces_outdoors = {access_restriction: unary_union(spaces)
                                            for access_restriction, spaces in restricted_spaces_outdoors.items()}

        AccessRestrictionAffected.build(geoms.access_restriction_affected).save_level(level.pk, 'base')

        geoms.walls = buildings_geom.difference(unary_union((spaces_geom, doors_geom)))

        # shorten walls if there are altitudeareas above
        remaining = geoms.walls
        for altitudearea in altitudeareas_above:
            intersection = altitudearea.geometry.intersection(remaining).buffer(0)
            if intersection.is_empty:
                continue
            remaining = remaining.difference(unwrap_geom(altitudearea.geometry))
            geoms.short_walls.append((altitudearea, intersection))
        geoms.all_walls = geoms.walls
        geoms.walls = geoms.walls.difference(
            unary_union(tuple(unwrap_geom(altitudearea.geometry) for altitudearea in altitudeareas_above))
        )

        # general level infos
        geoms.pk = level.pk
        geoms.on_top_of_id = level.on_top_of_id
        geoms.short_label = level.short_label
        geoms.base_altitude = int(level.base_altitude * 1000)
        geoms.default_height = int(level.default_height * 1000)
        geoms.door_height = int(level.door_height * 1000)
        geoms.min_altitude = (min(area.altitude for area in geoms.altitudeareas)
                              if geoms.altitudeareas else geoms.base_altitude)
        geoms.max_altitude = (max(area.altitude for area in geoms.altitudeareas)
                              if geoms.altitudeareas else geoms.base_altitude)
        geoms.max_height = (min(height for area, height in geoms.heightareas)
                            if geoms.heightareas else geoms.default_height)
        geoms.lower_bound = geoms.min_altitude-700

        return geoms

    def get_geometries(self):
        # omit heightareas as these are never drawn
        return chain((area.geometry for area in self.altitudeareas), (self.walls, self.doors,),
                     self.restricted_spaces_indoors.values(), self.restricted_spaces_outdoors.values(), self.ramps,
                     (geom for altitude, geom in self.short_walls))

    def create_hybrid_geometries(self, face_centers):
        vertices_offset = self.vertices.shape[0]
        faces_offset = self.faces.shape[0]
        new_vertices = deque()
        new_faces = deque()
        for area in self.altitudeareas:
            area_vertices, area_faces = area.create_hybrid_geometries(face_centers, vertices_offset, faces_offset)
            vertices_offset += area_vertices.shape[0]
            faces_offset += area_faces.shape[0]
            new_vertices.append(area_vertices)
            new_faces.append(area_faces)
        if new_vertices:
            self.vertices = np.vstack((self.vertices, *new_vertices))
            self.faces = np.vstack((self.faces, *new_faces))

        self.heightareas = tuple((HybridGeometry.create(area, face_centers), height)
                                 for area, height in self.heightareas)
        self.walls = HybridGeometry.create(self.walls, face_centers)
        self.short_walls = tuple((altitudearea, HybridGeometry.create(geom, face_centers))
                                 for altitudearea, geom in self.short_walls)
        self.all_walls = HybridGeometry.create(self.all_walls, face_centers)
        self.doors = HybridGeometry.create(self.doors, face_centers)
        self.restricted_spaces_indoors = {key: HybridGeometry.create(geom, face_centers)
                                          for key, geom in self.restricted_spaces_indoors.items()}
        self.restricted_spaces_outdoors = {key: HybridGeometry.create(geom, face_centers)
                                           for key, geom in self.restricted_spaces_outdoors.items()}

    def _get_altitudearea_vertex_values(self, area, i_vertices):
        return area.get_altitudes(self.vertices[i_vertices])

    def _get_short_wall_vertex_values(self, item, i_vertices):
        return item[0].get_altitudes(self.vertices[i_vertices]) - int(0.7 * 1000)

    def _build_vertex_values(self, items, area_func, value_func):
        """
        Interpolate vertice with known altitudes to get altitudes for the remaining ones.
        """
        vertex_values = np.empty(self.vertices.shape[:1], dtype=np.int32)
        if not vertex_values.size:
            return vertex_values
        vertex_value_mask = np.full(self.vertices.shape[:1], fill_value=False, dtype=np.bool)

        for item in items:
            faces = area_func(item).faces
            if not faces:
                continue
            i_vertices = np.unique(self.faces[np.array(tuple(chain(*faces)))].flatten())
            vertex_values[i_vertices] = value_func(item, i_vertices)
            vertex_value_mask[i_vertices] = True

        from scipy.interpolate import NearestNDInterpolator  # moved in here to save memory

        if np.any(vertex_value_mask) and not np.all(vertex_value_mask):
            interpolate = NearestNDInterpolator(self.vertices[vertex_value_mask],
                                                vertex_values[vertex_value_mask])
            vertex_values[np.logical_not(vertex_value_mask)] = interpolate(
                *np.transpose(self.vertices[np.logical_not(vertex_value_mask)])
            )

        return vertex_values

    def _filter_faces(self, faces):
        """
        Filter faces so that no zero area faces remain.
        """
        return faces[np.all(np.any(faces[:, (0, 1, 2), :]-faces[:, (2, 0, 1), :], axis=2), axis=1)]

    def _create_polyhedron(self, faces, lower, upper, top=True, sides=True, bottom=True):
        """
        Callback function for HybridGeometry.create_polyhedron()
        """
        if not any(faces):
            return ()

        # collect rings/boundaries
        boundaries = deque()
        for subfaces in faces:
            if not subfaces:
                continue
            subfaces = self.faces[np.array(tuple(subfaces))]
            segments = subfaces[:, (0, 1, 1, 2, 2, 0)].reshape((-1, 2))
            edges = set(edge for edge, num in Counter(tuple(a) for a in np.sort(segments, axis=1)).items() if num == 1)
            new_edges = {}
            for a, b in segments:
                if (a, b) in edges or (b, a) in edges:
                    new_edges.setdefault(a, deque()).append(b)
            edges = new_edges
            double_points = set(a for a, bs in edges.items() if len(bs) > 1)
            while edges:
                new_ring = deque()
                if double_points:
                    start = double_points.pop()
                else:
                    start = next(iter(edges.keys()))
                last = edges[start].pop()
                if not edges[start]:
                    edges.pop(start)
                new_ring.append(start)
                while start != last:
                    new_ring.append(last)
                    double_points.discard(last)
                    new_last = edges[last].pop()
                    if not edges[last]:
                        edges.pop(last)
                    last = new_last
                new_ring = np.array(new_ring, dtype=np.uint32)
                boundaries.append(tuple(zip(chain((new_ring[-1], ), new_ring), new_ring)))
        boundaries = np.vstack(boundaries)

        geom_faces = self.faces[np.array(tuple(chain(*faces)))]

        if not isinstance(upper, np.ndarray):
            upper = np.full(self.vertices.shape[0], fill_value=upper, dtype=np.int32)
        else:
            upper = upper.flatten()

        if not isinstance(lower, np.ndarray):
            lower = np.full(self.vertices.shape[0], fill_value=lower, dtype=np.int32)
        else:
            lower = lower.flatten()

        # lower should always be lower or equal than upper
        lower = np.minimum(upper, lower)

        # remove faces that have identical upper and lower coordinates
        geom_faces = geom_faces[(upper[geom_faces]-lower[geom_faces]).any(axis=1)]

        # top faces
        if top:
            top = self._filter_faces(np.dstack((self.vertices[geom_faces], upper[geom_faces])))
        else:
            top = Mesh.empty_faces

        # side faces
        if sides:
            sides = self._filter_faces(np.vstack((
                # upper
                np.dstack((self.vertices[boundaries[:, (1, 0, 0)]],
                           np.hstack((upper[boundaries[:, (1, 0)]], lower[boundaries[:, (0,)]])))),
                # lower
                np.dstack((self.vertices[boundaries[:, (0, 1, 1)]],
                           np.hstack((lower[boundaries[:, (0, 1)]], upper[boundaries[:, (1,)]]))))
            )))
        else:
            sides = Mesh.empty_faces

        # bottom faces
        if bottom:
            bottom = self._filter_faces(
                np.flip(np.dstack((self.vertices[geom_faces], lower[geom_faces])), axis=1)
            )
        else:
            bottom = Mesh.empty_faces

        return tuple((Mesh(top, sides, bottom),))

    def build_mesh(self, interpolator=None):
        """
        Build the entire mesh
        """

        # first we triangulate most polygons in one go
        rings = tuple(chain(*(get_rings(geom) for geom in self.get_geometries())))
        self.vertices, self.faces = triangulate_rings(rings)
        self.create_hybrid_geometries(face_centers=self.vertices[self.faces].sum(axis=1) / 3000)

        # calculate altitudes
        vertex_altitudes = self._build_vertex_values(reversed(self.altitudeareas),
                                                     area_func=operator.attrgetter('geometry'),
                                                     value_func=self._get_altitudearea_vertex_values)
        vertex_heights = self._build_vertex_values(self.heightareas,
                                                   area_func=operator.itemgetter(0),
                                                   value_func=lambda a, i: a[1])
        vertex_wall_heights = vertex_altitudes + vertex_heights

        # remove altitude area faces inside walls
        for area in self.altitudeareas:
            area.remove_faces(reduce(operator.or_, self.walls.faces, set()))

        # create polyhedrons
        # we build the walls to often so we can extend them to create leveled 3d model bases.
        self.walls_base = HybridGeometry(self.all_walls.geom, self.all_walls.faces)
        self.walls_bottom = HybridGeometry(self.all_walls.geom, self.all_walls.faces)
        self.walls_extended = HybridGeometry(self.walls.geom, self.walls.faces)
        self.walls.build_polyhedron(self._create_polyhedron,
                                    lower=vertex_altitudes - int(0.7 * 1000),
                                    upper=vertex_wall_heights)

        for altitudearea, geom in self.short_walls:
            geom.build_polyhedron(self._create_polyhedron,
                                  lower=vertex_altitudes - int(0.7 * 1000),
                                  upper=self._build_vertex_values([(altitudearea, geom)],
                                                                  area_func=operator.itemgetter(1),
                                                                  value_func=self._get_short_wall_vertex_values))
        self.short_walls = tuple(geom for altitude, geom in self.short_walls)

        # make sure we are able to crop spaces when a access restriction is apply
        for key, geometry in self.restricted_spaces_indoors.items():
            geometry.crop_ids = frozenset(('in:%s' % key, ))
        for key, geometry in self.restricted_spaces_outdoors.items():
            geometry.crop_ids = frozenset(('out:%s' % key, ))
        crops = tuple((crop, prepared.prep(crop.geom)) for crop in chain(self.restricted_spaces_indoors.values(),
                                                                         self.restricted_spaces_outdoors.values()))

        self.doors_extended = HybridGeometry(self.doors.geom, self.doors.faces)
        self.doors.build_polyhedron(self._create_polyhedron,
                                    crops=crops,
                                    lower=vertex_altitudes + self.door_height,
                                    upper=vertex_wall_heights - 1)

        if interpolator is not None:
            upper = interpolator(*np.transpose(self.vertices)).astype(np.int32) - int(0.7 * 1000)
            self.walls_extended.build_polyhedron(self._create_polyhedron,
                                                 lower=vertex_wall_heights,
                                                 upper=upper,
                                                 bottom=False)
            self.doors_extended.build_polyhedron(self._create_polyhedron,
                                                 lower=vertex_wall_heights - 1,
                                                 upper=upper,
                                                 bottom=False)
        else:
            self.walls_extended = None
            self.doors_extended = None

        for area in self.altitudeareas:
            area.create_polyhedrons(self._create_polyhedron,
                                    area.get_altitudes(self.vertices),
                                    min_altitude=self.min_altitude,
                                    crops=crops)

        for key, geometry in self.restricted_spaces_indoors.items():
            geometry.build_polyhedron(self._create_polyhedron,
                                      lower=vertex_altitudes,
                                      upper=vertex_wall_heights,
                                      bottom=False)
        for key, geometry in self.restricted_spaces_outdoors.items():
            geometry.faces = ()  # todo: understand this

        self.walls_base.build_polyhedron(self._create_polyhedron,
                                         lower=self.min_altitude - int(0.7 * 1000),
                                         upper=vertex_altitudes - int(0.7 * 1000),
                                         top=False, bottom=False)
        self.walls_bottom.build_polyhedron(self._create_polyhedron, lower=0, upper=1, top=False)

        # unset heightareas, they are no loinger needed
        # self.all_walls = None # we don't remove all_walls because we use it for rendering tiles now
        self.ramps = None
        # self.heightareas = None
        self.vertices = None
        self.faces = None
