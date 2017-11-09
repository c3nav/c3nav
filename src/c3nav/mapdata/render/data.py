import operator
import pickle
import threading
from collections import Counter, deque
from functools import reduce
from itertools import chain

import numpy as np
from django.db import transaction
from scipy.interpolate import NearestNDInterpolator
from shapely import prepared
from shapely.geometry import GeometryCollection, LineString, MultiLineString
from shapely.ops import unary_union

from c3nav.mapdata.cache import MapHistory
from c3nav.mapdata.models import Level, MapUpdate
from c3nav.mapdata.utils.geometry import assert_multipolygon, get_rings
from c3nav.mapdata.utils.mesh import triangulate_rings
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

    def fit(self, bottom, top):
        offset = np.array((0, 0, bottom))
        scale = np.array((1, 1, top-bottom))
        return HybridGeometry(geom=self.geom, crop_ids=self.crop_ids,
                              faces=tuple((faces*scale+offset) for faces in self.faces),
                              add_faces={crop_id: tuple((faces*scale+offset) for faces in self.faces)
                                         for crop_id, faces in self.add_faces})

    @property
    def is_empty(self):
        return not self.faces and not any(self.add_faces.values())

    def build_polyhedron(self, create_polyhedron, bottom, top, crops=None):
        remaining_faces = self.faces
        for crop, prep in crops or ():
            if prep.intersects(self.geom):
                crop_faces = set(chain(*crop.faces))
                crop_id = tuple(crop.crop_ids)[0]
                self.add_faces[crop_id] = create_polyhedron(tuple((faces & crop_faces) for faces in self.faces),
                                                            bottom=bottom, top=top)
                remaining_faces = tuple((faces - crop_faces) for faces in self.faces)
        self.faces = create_polyhedron(remaining_faces, bottom=bottom, top=top)


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

    def create_polyhedrons(self, create_polyhedron, crops):
        altitude = float(self.altitude)
        self.geometry.build_polyhedron(create_polyhedron, bottom=altitude-0.7, top=altitude, crops=crops)
        for geometry in chain(*(areas.values() for areas in self.colors.values())):
            geometry.build_polyhedron(create_polyhedron, bottom=altitude-0.1, top=altitude+0.001, crops=crops)


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

                    if crop_to.is_empty:
                        break

            render_data = LevelRenderData()
            render_data.access_restriction_affected = {}

            for sublevel in sublevels:
                try:
                    crop_to = level_crop_to[sublevel.pk]
                except KeyError:
                    break

                old_geoms = single_level_geoms[sublevel.pk]

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

                new_geoms.level_base = unary_union((new_geoms.walls,
                                                    *(area.geometry for area in new_geoms.altitudeareas)))

                new_geoms.pk = old_geoms.pk
                new_geoms.on_top_of_id = old_geoms.on_top_of_id
                new_geoms.base_altitude = old_geoms.base_altitude
                new_geoms.default_height = old_geoms.default_height
                new_geoms.min_altitude = float(min(area.altitude for area in new_geoms.altitudeareas)
                                               if new_geoms.altitudeareas else new_geoms.base_altitude)

                new_geoms.build_mesh()

                render_data.levels.append(new_geoms)

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

        self.level_base = None
        self.optional_base = None

        self.pk = None
        self.on_top_of_id = None
        self.base_altitude = None
        self.default_height = None
        self.min_altitude = None

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

        # general level infos
        geoms.pk = level.pk
        geoms.on_top_of_id = level.on_top_of_id
        geoms.base_altititude = level.base_altitude
        geoms.default_height = level.default_height
        geoms.min_altitude = float(min(area.altitude for area in geoms.altitudeareas)
                                   if geoms.altitudeareas else level.base_altitude)

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
        self.level_base = HybridGeometry.create(self.level_base, face_centers)

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

    def _create_polyhedron(self, faces, bottom=None, top=None, crops=None):
        if not any(faces):
            return

        # collect rings/boundaries
        boundaries = deque()
        for subfaces in faces:
            if not subfaces:
                continue
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

        new_faces = deque()
        geom_faces = self.faces[np.array(tuple(chain(*faces)))]

        if not isinstance(top, np.ndarray):
            top = np.full(self.vertices.shape[0], fill_value=top)

        if not isinstance(bottom, np.ndarray):
            bottom = np.full(self.vertices.shape[0], fill_value=bottom)

        # upper faces
        new_faces.append(np.dstack((self.vertices[geom_faces], top[geom_faces])))

        # side faces (upper)
        new_faces.append(np.dstack((self.vertices[boundaries[:, (1, 0, 0)]],
                                    np.hstack((top[boundaries[:, (1, 0)]], bottom[boundaries[:, (0,)]])))))

        # side faces (lower)
        new_faces.append(np.dstack((self.vertices[boundaries[:, (0, 1, 1)]],
                                    np.hstack((bottom[boundaries[:, (0, 1)]], top[boundaries[:, (1,)]])))))

        # lower faces
        new_faces.append(np.dstack((self.vertices[np.flip(geom_faces, axis=1)], bottom[geom_faces])))

        return (np.vstack(new_faces), )

    def build_mesh(self):
        rings = tuple(chain(*(get_rings(geom) for geom in self.get_geometries())))
        self.vertices, self.faces = triangulate_rings(rings)
        self.create_hybrid_geometries(face_centers=self.vertices[self.faces].sum(axis=1) / 3)

        # calculate altitudes
        vertex_altitudes = self._build_vertex_values((area.geometry, int(area.altitude*100))
                                                     for area in reversed(self.altitudeareas))/100
        vertex_heights = self._build_vertex_values((area, int(height*100))
                                                   for area, height in self.heightareas)/100
        vertex_wall_heights = vertex_altitudes + vertex_heights

        # create polyhedrons
        self.walls.build_polyhedron(self._create_polyhedron, bottom=vertex_altitudes-0.7, top=vertex_wall_heights)

        for key, geometry in self.restricted_spaces_indoors.items():
            geometry.crop_ids = frozenset(('in:%s' % key, ))
        for key, geometry in self.restricted_spaces_outdoors.items():
            geometry.crop_ids = frozenset(('out:%s' % key, ))
        crops = tuple((crop, prepared.prep(crop.geom)) for crop in chain(self.restricted_spaces_indoors.values(),
                                                                         self.restricted_spaces_outdoors.values()))

        self.doors.build_polyhedron(self._create_polyhedron, crops=crops,
                                    bottom=vertex_wall_heights-1, top=vertex_wall_heights)

        for area in self.altitudeareas:
            area.create_polyhedrons(self._create_polyhedron, crops=crops)

        for key, geometry in self.restricted_spaces_indoors.items():
            geometry.build_polyhedron(self._create_polyhedron, bottom=vertex_altitudes-0.7, top=vertex_wall_heights)
        for key, geometry in self.restricted_spaces_outdoors.items():
            geometry.faces = None

        self.optional_base = HybridGeometry(self.level_base.geom, self.level_base.faces)
        self.level_base.build_polyhedron(self._create_polyhedron,
                                         bottom=self.min_altitude-0.8, top=vertex_altitudes-0.6)
        self.optional_base.build_polyhedron(self._create_polyhedron, bottom=0, top=1)

        # unset heightareas, they are no loinger needed
        self.heightareas = None
        self.vertices = None
        self.faces = None
