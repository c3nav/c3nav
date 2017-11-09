import operator
import pickle
import threading
from collections import Counter, deque, namedtuple
from functools import reduce
from itertools import chain

import numpy as np
from django.db import transaction
from django.utils.functional import cached_property
from scipy.interpolate import NearestNDInterpolator
from shapely.geometry import GeometryCollection, LineString, MultiLineString
from shapely.ops import unary_union

from c3nav.mapdata.cache import MapHistory
from c3nav.mapdata.models import Level, MapUpdate
from c3nav.mapdata.utils.geometry import assert_multipolygon, get_rings
from c3nav.mapdata.utils.mesh import triangulate_rings
from c3nav.mapdata.utils.mpl import shapely_to_mpl


def hybrid_union(geoms):
    if not geoms:
        return HybridGeometry(GeometryCollection(), set())
    if len(geoms) == 1:
        return geoms[0]
    return HybridGeometry(unary_union(tuple(geom.geom for geom in geoms)),
                          reduce(operator.or_, (geom.faces for geom in geoms), set()))


class HybridGeometry(namedtuple('HybridGeometry', ('geom', 'faces'))):
    @classmethod
    def create(cls, geom, face_centers):
        if isinstance(geom, (LineString, MultiLineString)):
            return HybridGeometry(geom, set())
        faces = tuple(
            set(np.argwhere(shapely_to_mpl(subgeom).contains_points(face_centers)).flatten())
            for subgeom in assert_multipolygon(geom)
        )
        return HybridGeometry(geom, tuple(f for f in faces if f))

    def union(self, geom):
        return HybridGeometry(self.geom.union(geom.geom), self.faces | geom.faces)

    def difference(self, geom):
        return HybridGeometry(self.geom.difference(geom.geom), self.faces - geom.faces)

    @cached_property
    def is_empty(self):
        return not self.faces


class AltitudeAreaGeometries:
    def __init__(self, altitudearea=None, colors=None):
        if altitudearea is not None:
            self.geometry = altitudearea.geometry
            self.altitude = altitudearea.altitude
        else:
            self.geometry = None
            self.altitude = None
        self.colors = colors

    def get_geometries(self):
        return chain((self.geometry,), chain(*(areas.values() for areas in self.colors.values())))

    def create_hybrid_geometries(self, face_centers):
        self.geometry = HybridGeometry.create(self.geometry, face_centers)
        self.colors = {color: {key: HybridGeometry.create(geom, face_centers) for key, geom in areas.items()}
                       for color, areas in self.colors.items()}


class FakeCropper:
    @staticmethod
    def intersection(other):
        return other


class LevelRenderData:
    def __init__(self):
        self.levels = []
        self.access_restriction_affected = None

    @staticmethod
    def rebuild():
        levels = tuple(Level.objects.prefetch_related('altitudeareas', 'buildings', 'doors', 'spaces',
                                                      'spaces__holes', 'spaces__columns', 'spaces__locationgroups'))

        single_level_geoms = {level.pk: LevelGeometries.build_for_level(level) for level in levels}

        for i, level in enumerate(levels):
            if level.on_top_of_id is not None:
                continue

            map_history = MapHistory.open_level(level.pk, 'base')

            sublevels = tuple(sublevel for sublevel in levels
                              if sublevel.on_top_of_id == level.pk or sublevel.base_altitude <= level.base_altitude)

            level_crop_to = {}

            # choose a crop area for each level. non-intermediate levels (not on_top_of) below the one that we are
            # currently rendering will be cropped to only render content that is visible through holes indoors in the
            # levels above them.
            crop_to = None
            primary_level_count = 0
            for sublevel in reversed(sublevels):
                geoms = single_level_geoms[sublevel.pk]

                if geoms.holes is not None:
                    primary_level_count += 1

                # set crop area if we area on the second primary layer from top or below
                level_crop_to[sublevel.pk] = crop_to if primary_level_count > 1 else FakeCropper

                if geoms.holes is not None:
                    if crop_to is None:
                        crop_to = geoms.holes
                    else:
                        crop_to = crop_to.intersection(geoms.holes)

            render_data = LevelRenderData()
            render_data.access_restriction_affected = {}

            for sublevel in sublevels:
                old_geoms = single_level_geoms[sublevel.pk]
                crop_to = level_crop_to[sublevel.pk]

                if crop_to is not FakeCropper:
                    map_history.composite(MapHistory.open_level(sublevel.pk, 'base'), crop_to)

                new_geoms = LevelGeometries()
                new_geoms.doors = crop_to.intersection(old_geoms.doors)
                new_geoms.walls = crop_to.intersection(old_geoms.walls)

                for altitudearea in old_geoms.altitudeareas:
                    new_geometry = crop_to.intersection(altitudearea.geometry)
                    if new_geometry.is_empty:
                        continue

                    new_altitudearea = AltitudeAreaGeometries()
                    new_altitudearea.geometry = new_geometry
                    new_altitudearea.altitude = altitudearea.altitude

                    new_colors = {}
                    for color, areas in altitudearea.colors.items():
                        new_areas = {}
                        for access_restriction, area in areas.items():
                            new_area = new_geometry.intersection(area)
                            if not new_area.is_empty:
                                new_areas[access_restriction] = new_area
                        if new_areas:
                            new_colors[color] = new_areas

                    new_altitudearea.colors = new_colors
                    new_geoms.altitudeareas.append(new_altitudearea)

                if new_geoms.walls.is_empty and not new_geoms.altitudeareas:
                    continue

                new_geoms.heightareas = tuple(
                    (area, height) for area, height in ((crop_to.intersection(area), height)
                                                        for area, height in old_geoms.heightareas)
                    if not area.is_empty
                )

                new_geoms.affected_area = unary_union((
                    *(altitudearea.geometry for altitudearea in new_geoms.altitudeareas),
                    crop_to.intersection(new_geoms.walls.buffer(1))
                ))

                for access_restriction, area in old_geoms.restricted_spaces_indoors.items():
                    new_area = crop_to.intersection(area)
                    if not new_area.is_empty:
                        render_data.access_restriction_affected.setdefault(access_restriction, []).append(new_area)

                new_geoms.restricted_spaces_indoors = {}
                for access_restriction, area in old_geoms.restricted_spaces_indoors.items():
                    new_area = crop_to.intersection(area)
                    if not new_area.is_empty:
                        new_geoms.restricted_spaces_indoors[access_restriction] = new_area

                new_geoms.restricted_spaces_outdoors = {}
                for access_restriction, area in old_geoms.restricted_spaces_outdoors.items():
                    new_area = crop_to.intersection(area)
                    if not new_area.is_empty:
                        new_geoms.restricted_spaces_outdoors[access_restriction] = new_area

                new_geoms.build_mesh()

                render_data.levels.append((new_geoms, sublevel.default_height))

            render_data.access_restriction_affected = {
                access_restriction: unary_union(areas)
                for access_restriction, areas in render_data.access_restriction_affected.items()
            }

            level.render_data = pickle.dumps(render_data)

            map_history.save(MapHistory.level_filename(level.pk, 'render'))

        with transaction.atomic():
            for level in levels:
                level.save()

    cached = {}
    cache_key = None
    cache_lock = threading.Lock()

    @classmethod
    def get(cls, level):
        with cls.cache_lock:
            cache_key = MapUpdate.current_cache_key()
            level_pk = str(level.pk if isinstance(level, Level) else level)
            if cls.cache_key != cache_key:
                cls.cache_key = cache_key
                cls.cached = {}
            else:
                result = cls.cached.get(level_pk, None)
                if result is not None:
                    return result

            if isinstance(level, Level):
                result = pickle.loads(level.render_data)
            else:
                result = pickle.loads(Level.objects.filter(pk=level).values_list('render_data', flat=True)[0])

            cls.cached[level_pk] = result
            return result


class LevelGeometries:
    def __init__(self):
        self.altitudeareas = []
        self.heightareas = []
        self.walls = None
        self.doors = None
        self.holes = None
        self.access_restriction_affected = None
        self.restricted_spaces_indoors = None
        self.restricted_spaces_outdoors = None
        self.affected_area = None

        self.vertices = None
        self.faces = None
        self.vertex_altitudes = None
        self.vertex_heights = None

    @staticmethod
    def build_for_level(level):
        geoms = LevelGeometries()
        buildings_geom = unary_union([b.geometry for b in level.buildings.all()])

        # remove columns and holes from space areas
        for space in level.spaces.all():
            if space.outside:
                space.geometry = space.geometry.difference(buildings_geom)
            space.geometry = space.geometry.difference(unary_union([c.geometry for c in space.columns.all()]))
            space.holes_geom = unary_union([h.geometry for h in space.holes.all()])
            space.walkable_geom = space.geometry.difference(space.holes_geom)

        spaces_geom = unary_union([s.geometry for s in level.spaces.all()])
        doors_geom = unary_union([d.geometry for d in level.doors.all()])
        walkable_spaces_geom = unary_union([s.walkable_geom for s in level.spaces.all()])
        geoms.doors = doors_geom.difference(walkable_spaces_geom)
        walkable_geom = walkable_spaces_geom.union(geoms.doors)
        if level.on_top_of_id is None:
            geoms.holes = spaces_geom.difference(walkable_geom)

        # keep track which areas are affected by access restrictions
        access_restriction_affected = {}

        # keep track wich spaces to hide
        restricted_spaces_indoors = {}
        restricted_spaces_outdoors = {}

        # go through spaces and their areas for access control, ground colors and height areas
        colors = {}
        heightareas = {}
        for space in level.spaces.all():
            access_restriction = space.access_restriction_id
            if access_restriction is not None:
                access_restriction_affected.setdefault(access_restriction, []).append(space.geometry)
                buffered = space.geometry.buffer(0.01).union(unary_union(
                    tuple(door.geometry for door in level.doors.all() if door.geometry.intersects(space.geometry))
                ).difference(walkable_spaces_geom))
                if buffered.intersects(buildings_geom):
                    restricted_spaces_indoors.setdefault(access_restriction, []).append(
                        buffered.intersection(buildings_geom)
                    )
                if not buffered.within(buildings_geom):
                    restricted_spaces_outdoors.setdefault(access_restriction, []).append(
                        buffered.difference(buildings_geom)
                    )

            colors.setdefault(space.get_color(), {}).setdefault(access_restriction, []).append(space.geometry)

            for area in space.areas.all():
                access_restriction = area.access_restriction_id or space.access_restriction_id
                if access_restriction is not None:
                    access_restriction_affected.setdefault(access_restriction, []).append(area.geometry)
                colors.setdefault(area.get_color(), {}).setdefault(access_restriction, []).append(area.geometry)

            heightareas.setdefault(space.height or level.default_height, []).append(space.geometry)
        colors.pop(None, None)

        # merge ground colors
        for color, color_group in colors.items():
            for access_restriction, areas in tuple(color_group.items()):
                color_group[access_restriction] = unary_union(areas)

        # add altitudegroup geometries and split ground colors into them
        for altitudearea in level.altitudeareas.all():
            altitudearea_colors = {color: {access_restriction: area.intersection(altitudearea.geometry)
                                           for access_restriction, area in areas.items()
                                           if area.intersects(altitudearea.geometry)}
                                   for color, areas in colors.items()}
            altitudearea_colors = {color: areas for color, areas in altitudearea_colors.items() if areas}
            geoms.altitudeareas.append(AltitudeAreaGeometries(altitudearea, altitudearea_colors))

        # merge height areas
        geoms.heightareas = tuple((unary_union(geoms), height)
                                  for height, geoms in sorted(heightareas.items(), key=operator.itemgetter(0)))

        # merge access restrictions
        geoms.access_restriction_affected = {access_restriction: unary_union(areas)
                                             for access_restriction, areas in access_restriction_affected.items()}
        geoms.restricted_spaces_indoors = {access_restriction: unary_union(spaces)
                                           for access_restriction, spaces in restricted_spaces_indoors.items()}
        geoms.restricted_spaces_outdoors = {access_restriction: unary_union(spaces)
                                            for access_restriction, spaces in restricted_spaces_outdoors.items()}

        geoms.walls = buildings_geom.difference(spaces_geom).difference(doors_geom)

        return geoms

    def get_geometries(self):
        # omit heightareas as these are never drawn
        return chain(chain(*(area.get_geometries() for area in self.altitudeareas)), (self.walls, self.doors,),
                     self.restricted_spaces_indoors.values(), self.restricted_spaces_outdoors.values())

    def create_hybrid_geometries(self, face_centers):
        for area in self.altitudeareas:
            area.create_hybrid_geometries(face_centers)
        self.heightareas = tuple((HybridGeometry.create(area, face_centers), height)
                                 for area, height in self.heightareas)
        self.walls = HybridGeometry.create(self.walls, face_centers)
        self.doors = HybridGeometry.create(self.doors, face_centers)
        self.restricted_spaces_indoors = {key: HybridGeometry.create(geom, face_centers)
                                          for key, geom in self.restricted_spaces_indoors.items()}
        self.restricted_spaces_outdoors = {key: HybridGeometry.create(geom, face_centers)
                                           for key, geom in self.restricted_spaces_outdoors.items()}

    def _build_vertex_values(self, area_values):
        vertex_values = np.empty(self.vertices.shape[:1], dtype=np.int32)
        vertex_value_mask = np.full(self.vertices.shape[:1], fill_value=False, dtype=np.bool)

        for area, value in area_values:
            i_vertices = np.unique(self.faces[np.array(tuple(chain(*area.faces)))].flatten())
            vertex_values[i_vertices] = value
            vertex_value_mask[i_vertices] = True

        if not np.all(vertex_value_mask):
            interpolate = NearestNDInterpolator(self.vertices[vertex_value_mask],
                                                vertex_values[vertex_value_mask])
            vertex_values[np.logical_not(vertex_value_mask)] = interpolate(
                *np.transpose(self.vertices[np.logical_not(vertex_value_mask)])
            )

        return vertex_values

    def _create_polyhedron(self, geometry, bottom=None, top=None):
        if geometry.is_empty:
            return

        # collect rings/boundaries
        boundaries = deque()
        for subfaces in geometry.faces:
            subfaces = self.faces[np.array(tuple(subfaces))]
            segments = subfaces[:, (0, 1, 1, 2, 2, 0)].reshape((-1, 2))
            edges = set(edge for edge, num in Counter(tuple(a) for a in np.sort(segments, axis=1)).items() if num == 1)
            edges = {a: b for a, b in segments if (a, b) in edges or (b, a) in edges}
            while edges:
                new_ring = deque()
                start, last = next(iter(edges.items()))
                edges.pop(start)
                new_ring.append(start)
                while start != last:
                    new_ring.append(last)
                    last = edges.pop(last)
                new_ring = np.array(new_ring, dtype=np.int64)
                boundaries.append(tuple(zip(chain((new_ring[-1], ), new_ring), new_ring)))
        boundaries = np.vstack(boundaries)

        faces = deque()
        geom_faces = self.faces[np.array(tuple(chain(*geometry.faces)))]

        if not isinstance(top, np.ndarray):
            top = np.full(self.vertices.shape[0], fill_value=top)

        if not isinstance(bottom, np.ndarray):
            bottom = np.full(self.vertices.shape[0], fill_value=bottom)

        # upper faces
        faces.append(np.dstack((self.vertices[geom_faces], top[geom_faces])))

        # side faces (upper)
        faces.append(np.dstack((self.vertices[boundaries[:, (1, 0, 0)]],
                                np.hstack((top[boundaries[:, (1, 0)]], bottom[boundaries[:, (0,)]])))))

        # side faces (lower)
        faces.append(np.dstack((self.vertices[boundaries[:, (0, 1, 1)]],
                                np.hstack((bottom[boundaries[:, (0, 1)]], top[boundaries[:, (1,)]])))))

        # lower faces
        faces.append(np.dstack((self.vertices[np.flip(geom_faces, axis=1)], bottom[geom_faces])))

        return np.vstack(faces)

    def build_mesh(self):
        rings = tuple(chain(*(get_rings(geom) for geom in self.get_geometries())))
        self.vertices, self.faces = triangulate_rings(rings)
        self.create_hybrid_geometries(face_centers=self.vertices[self.faces].sum(axis=1) / 3)

        # calculate altitudes
        self.vertex_altitudes = self._build_vertex_values((area.geometry, int(area.altitude*100))
                                                          for area in reversed(self.altitudeareas))/100
        self.vertex_heights = self._build_vertex_values((area, int(height*100))
                                                        for area, height in self.heightareas)/100
        self.vertex_wall_heights = self.vertex_altitudes+self.vertex_heights

        # create polyhedrons
        self._create_polyhedron(self.walls, bottom=self.vertex_altitudes, top=self.vertex_wall_heights)

        # unset heightareas, they are no loinger needed
        self.heightareas = None
