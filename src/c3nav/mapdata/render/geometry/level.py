import operator
import typing
from collections import Counter, deque
from dataclasses import dataclass
from functools import reduce
from itertools import chain

import numpy as np
from shapely import prepared, box
from shapely.geometry import GeometryCollection, Polygon, MultiPolygon
from shapely.ops import unary_union

from c3nav.mapdata.models import Space, Level, AltitudeArea, Source
from c3nav.mapdata.render.geometry.altitudearea import AltitudeAreaGeometries
from c3nav.mapdata.render.geometry.hybrid import HybridGeometry
from c3nav.mapdata.render.geometry.mesh import Mesh
from c3nav.mapdata.utils.cache import AccessRestrictionAffected
from c3nav.mapdata.utils.geometry import get_rings, unwrap_geom
from c3nav.mapdata.utils.mesh import triangulate_rings

if typing.TYPE_CHECKING:
    from c3nav.mapdata.render.theme import ThemeColorManager

empty_geometry_collection = GeometryCollection()


ZeroOrMorePolygons: typing.TypeAlias = GeometryCollection | Polygon | MultiPolygon


@dataclass
class BaseLevelGeometries:
    """
    Geometries for a Level.
    """
    # todo: split into the two versions of this
    buildings: ZeroOrMorePolygons
    altitudeareas: list[AltitudeAreaGeometries]
    heightareas: typing.Sequence[tuple[ZeroOrMorePolygons, float]]
    walls: ZeroOrMorePolygons
    all_walls: ZeroOrMorePolygons
    short_walls: list[tuple[AltitudeArea, ZeroOrMorePolygons]] | typing.Sequence[ZeroOrMorePolygons]
    doors: ZeroOrMorePolygons | None
    holes: ZeroOrMorePolygons | None
    restricted_spaces_indoors: dict[int, ZeroOrMorePolygons]
    restricted_spaces_outdoors: dict[int, ZeroOrMorePolygons]
    ramps: typing.Sequence[ZeroOrMorePolygons]

    pk: int
    on_top_of_id: int | None
    level_index: str
    short_label: str
    base_altitude: int
    default_height: int
    door_height: int
    min_altitude: int
    max_altitude: int
    max_height: int

    lower_bound: int

    def __repr__(self):
        return '<LevelGeometries for Level %s (#%d)>' % (self.short_label, self.pk)


@dataclass(slots=True)
class SingleLevelGeometries(BaseLevelGeometries):
    """
    Geometries for a level, base calculation on the way to LevelRenderData
    """
    access_restriction_affected: dict[int, ZeroOrMorePolygons]

    @dataclass
    class SpaceGeometries:
        geometry: ZeroOrMorePolygons
        holes_geom: ZeroOrMorePolygons
        walkable_geom: ZeroOrMorePolygons

        instance: Space

    @classmethod
    def spaces_for_level(cls, level: Level, buildings_geom: ZeroOrMorePolygons) -> list[SpaceGeometries]:
        spaces: list[cls.SpaceGeometries] = []
        for space in level.spaces.all():  # noqa
            geometry = space.geometry
            subtract = []
            if space.outside:
                subtract.append(buildings_geom)
            columns = [c.geometry for c in space.columns.all() if c.access_restriction_id is None]
            if columns:
                subtract.extend(columns)
            if subtract:
                geometry = geometry.difference(unary_union([unwrap_geom(geom) for geom in subtract]))

            holes = tuple(h.geometry for h in space.holes.all())
            if holes:
                holes_geom = unary_union([unwrap_geom(h.geometry) for h in space.holes.all()])
                walkable_geom = space.geometry.difference(holes_geom)
                holes_geom = space.geometry.intersection(holes_geom)
            else:
                holes_geom = empty_geometry_collection
                walkable_geom = geometry
            spaces.append(cls.SpaceGeometries(
                geometry=geometry,
                holes_geom=holes_geom,
                walkable_geom=walkable_geom,

                instance=space,
            ))
        return spaces

    @dataclass
    class Analysis:
        access_restriction_affected: dict[int, list[ZeroOrMorePolygons]]

        restricted_spaces_indoors: dict[int, list[ZeroOrMorePolygons]]
        restricted_spaces_outdoors: dict[int, list[ZeroOrMorePolygons]]

        colors: dict[tuple, dict[int, ZeroOrMorePolygons]]
        obstacles: dict[int, dict[str | None, list[ZeroOrMorePolygons]]]
        heightareas: dict[int, list[ZeroOrMorePolygons]]

        ramps: list[ZeroOrMorePolygons]

    @classmethod
    def analyze_spaces(cls, level: Level, spaces: list[SpaceGeometries], walkable_spaces_geom: ZeroOrMorePolygons,
                       buildings_geom: ZeroOrMorePolygons, color_manager: 'ThemeColorManager') -> Analysis:
        buildings_geom_prep = prepared.prep(buildings_geom)

        # keep track which areas are affected by access restrictions
        access_restriction_affected: dict[int, list[ZeroOrMorePolygons]] = {}

        # keep track wich spaces to hide
        restricted_spaces_indoors: dict[int, list[ZeroOrMorePolygons]] = {}
        restricted_spaces_outdoors: dict[int, list[ZeroOrMorePolygons]] = {}

        # go through spaces and their areas for access control, ground colors, height areas and obstacles
        colors: dict[tuple | None, dict[int, list[ZeroOrMorePolygons]]] = {}
        obstacles: dict[int, dict[str | None, list[ZeroOrMorePolygons]]] = {}
        heightareas: dict[int, list[ZeroOrMorePolygons]] = {}

        ramps: list[ZeroOrMorePolygons] = []

        for space in spaces:
            buffered = space.geometry.buffer(0.01).union(unary_union(tuple(
                unwrap_geom(door.geometry).buffer(0.02)
                for door in level.doors.all() if door.geometry.intersects(unwrap_geom(space.geometry))  # noqa
            )).difference(walkable_spaces_geom))
            intersects = buildings_geom_prep.intersects(buffered)

            access_restriction: int = space.instance.access_restriction_id  # noqa
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

            colors.setdefault(space.instance.get_color_sorted(color_manager), {}).setdefault(access_restriction,
                                                                                             []).append(
                unwrap_geom(space.geometry)
            )

            for area in space.instance.areas.all():  # noqa
                access_restriction = area.access_restriction_id or space.instance.access_restriction_id
                area.geometry = area.geometry.intersection(unwrap_geom(space.walkable_geom))
                if access_restriction is not None:
                    access_restriction_affected.setdefault(access_restriction, []).append(area.geometry)
                colors.setdefault(
                    area.get_color_sorted(color_manager), {}
                ).setdefault(access_restriction, []).append(area.geometry)

            for column in space.instance.columns.all():  # noqa
                access_restriction = column.access_restriction_id
                if access_restriction is None:
                    continue
                column.geometry = column.geometry.intersection(unwrap_geom(space.walkable_geom))
                buffered_column = column.geometry.buffer(0.02)
                if intersects:
                    restricted_spaces_indoors.setdefault(access_restriction, []).append(buffered_column)
                if not intersects or not buildings_geom_prep.contains(buffered):
                    restricted_spaces_outdoors.setdefault(access_restriction, []).append(buffered_column)
                access_restriction_affected.setdefault(access_restriction, []).append(column.geometry)

            for obstacle in sorted(space.instance.obstacles.all(), key=lambda o: o.height + o.altitude):  # noqa
                if not obstacle.height:
                    continue
                obstacles.setdefault(
                    int((obstacle.height + obstacle.altitude) * 1000), {}
                ).setdefault(obstacle.get_color(color_manager), []).append(
                    obstacle.geometry.intersection(unwrap_geom(space.walkable_geom))
                )

            for lineobstacle in space.instance.lineobstacles.all():  # noqa
                if not lineobstacle.height:
                    continue
                obstacles.setdefault(int(lineobstacle.height * 1000), {}).setdefault(
                    lineobstacle.get_color(color_manager), []
                ).append(
                    lineobstacle.buffered_geometry.intersection(unwrap_geom(space.walkable_geom))
                )

            ramps.extend(ramp.geometry for ramp in space.instance.ramps.all())  # noqa

            heightareas.setdefault(int((space.instance.height or level.default_height) * 1000), []).append(
                unwrap_geom(space.geometry)
            )
        colors.pop(None, None)

        new_colors: dict[tuple, dict[int, ZeroOrMorePolygons]] = {}

        # merge ground colors
        for color, color_group in colors.items():
            new_color_group = {}
            new_colors[color] = new_color_group
            for access_restriction, areas in tuple(color_group.items()):
                new_color_group[access_restriction] = unary_union(areas)

        new_colors = {color: geometry for color, geometry in sorted(new_colors.items(), key=lambda v: v[0][0])}

        return cls.Analysis(
            access_restriction_affected=access_restriction_affected,

            restricted_spaces_indoors=restricted_spaces_indoors,
            restricted_spaces_outdoors=restricted_spaces_outdoors,

            colors=new_colors,
            obstacles=obstacles,
            heightareas=heightareas,

            ramps=ramps,
        )
    
    @classmethod
    def build_altitudeareas(cls, level: Level, analysis: Analysis) -> list[AltitudeAreaGeometries]:
        # add altitudegroup geometries and split ground colors into them
        altitudearea_geoms: list[AltitudeAreaGeometries] = [] 
        for altitudearea in level.altitudeareas.all():  # noqa
            altitudearea.geometry = unwrap_geom(altitudearea.geometry).buffer(0)
            altitudearea_prep = prepared.prep(unwrap_geom(altitudearea.geometry))
            altitudearea_colors = {color: {access_restriction: area.intersection(unwrap_geom(altitudearea.geometry))
                                           for access_restriction, area in areas.items()
                                           if altitudearea_prep.intersects(area)}
                                   for color, areas in analysis.colors.items()}
            altitudearea_colors = {color: areas for color, areas in altitudearea_colors.items() if areas}

            altitudearea_obstacles = {}
            for height, height_obstacles in analysis.obstacles.items():
                new_height_obstacles = {}
                for color, color_obstacles in height_obstacles.items():
                    new_color_obstacles = []
                    for obstacle in color_obstacles:
                        obstacle = obstacle.buffer(0)
                        if altitudearea_prep.intersects(obstacle):
                            new_color_obstacles.append(obstacle.intersection(unwrap_geom(altitudearea.geometry)))
                    if new_color_obstacles:
                        new_height_obstacles[color] = new_color_obstacles
                if new_height_obstacles:
                    altitudearea_obstacles[height] = new_height_obstacles

            altitudearea_geoms.append(AltitudeAreaGeometries(
                altitudearea=altitudearea, 
                colors=altitudearea_colors, 
                obstacles=altitudearea_obstacles
            ))     
        return altitudearea_geoms
    
    @classmethod
    def build_short_walls(cls, altitudeareas_above,
                          walls_geom: ZeroOrMorePolygons) -> list[tuple[AltitudeArea, ZeroOrMorePolygons]]:
        remaining = walls_geom
        short_walls = []
        for altitudearea in altitudeareas_above:
            intersection = altitudearea.geometry.intersection(remaining).buffer(0)
            if intersection.is_empty:
                continue
            remaining = remaining.difference(unwrap_geom(altitudearea.geometry))
            short_walls.append((altitudearea, intersection))
        return short_walls

    @classmethod
    def build_for_level(cls, level: Level, color_manager: 'ThemeColorManager', altitudeareas_above):
        buildings_geom = unary_union([unwrap_geom(b.geometry) for b in level.buildings.all()])  # noqa

        # remove columns and holes from space areas
        spaces = cls.spaces_for_level(level, buildings_geom)

        spaces_geom = unary_union([unwrap_geom(space.geometry) for space in spaces])
        doors_geom = unary_union([unwrap_geom(d.geometry) for d in level.doors.all()])  # noqa
        doors_geom = doors_geom.intersection(buildings_geom)
        walkable_spaces_geom = unary_union([unwrap_geom(space.walkable_geom) for space in spaces])
        doors_geom = doors_geom.difference(walkable_spaces_geom)
        walls_geom = buildings_geom.difference(unary_union((spaces_geom, doors_geom.buffer(0.01))))
        if level.on_top_of_id is None:
            holes_geom = unary_union([s.holes_geom for s in spaces])

            if level.intermediate:
                holes_geom = unary_union([
                    holes_geom,
                    box(*chain(*Source.max_bounds())).difference(buildings_geom).difference(spaces_geom)
                ])

        else:
            holes_geom = None

        analysis = cls.analyze_spaces(
            level=level,
            spaces=spaces,
            walkable_spaces_geom=walkable_spaces_geom,
            buildings_geom=buildings_geom,
            color_manager=color_manager
        )

        altitudearea_geoms = cls.build_altitudeareas(level=level, analysis=analysis)
        heightareas_geom = tuple((unary_union(geoms), height) for height, geoms in
                                 sorted(analysis.heightareas.items(), key=operator.itemgetter(0)))

        base_altitude = int(level.base_altitude * 1000)
        default_height = int(level.default_height * 1000)
        door_height = int(level.door_height * 1000)

        min_altitude = (min(area.min_altitude for area in altitudearea_geoms) if altitudearea_geoms else base_altitude)

        # hybrid geometries

        geoms = cls(
            ramps=analysis.ramps,

            buildings=buildings_geom,
            doors=doors_geom,
            holes=holes_geom,

            altitudeareas=altitudearea_geoms,
            heightareas=heightareas_geom,

            # merge access restrictions
            access_restriction_affected={
                access_restriction: unary_union([unwrap_geom(geom) for geom in areas])
                for access_restriction, areas in analysis.access_restriction_affected.items()
            },
            restricted_spaces_indoors={
                access_restriction: unary_union(spaces)
                for access_restriction, spaces in analysis.restricted_spaces_indoors.items()
            },
            restricted_spaces_outdoors={
                access_restriction: unary_union(spaces)
                for access_restriction, spaces in analysis.restricted_spaces_outdoors.items()
            },

            # shorten walls if there are altitudeareas above
            short_walls=cls.build_short_walls(altitudeareas_above, walls_geom),

            all_walls=walls_geom,
            walls=walls_geom.difference(
                unary_union(tuple(unwrap_geom(altitudearea.geometry) for altitudearea in altitudeareas_above))
            ),

            # general level infos
            pk=level.pk,
            on_top_of_id=level.on_top_of_id,
            short_label=level.short_label,
            level_index=level.level_index,
            base_altitude=base_altitude,
            default_height=default_height,
            door_height=door_height,
            min_altitude=min_altitude,
            max_altitude=(max(area.max_altitude for area in altitudearea_geoms)
                          if altitudearea_geoms else base_altitude),
            max_height=(min(height for area, height in heightareas_geom)
                        if analysis.heightareas else default_height),
            lower_bound=min_altitude-700,
        )
        
        AccessRestrictionAffected.build(geoms.access_restriction_affected).save_level(level.pk, 'base')

        return geoms


@dataclass(slots=True)
class CompositeLevelGeometries(BaseLevelGeometries):
    """
    Geometries for a level, as a member of a composite level rendering, the final type in LevelRenderData
    """

    affected_area: ZeroOrMorePolygons
    doors_extended: HybridGeometry | None
    vertices: None | np.ndarray
    faces: None | np.ndarray
    upper_bound: int
    walls_base: None | HybridGeometry
    walls_bottom: None | HybridGeometry
    walls_extended: None | HybridGeometry

    def get_geometries(self):  # called on the final thing
        # omit heightareas as these are never drawn
        return chain((area.geometry for area in self.altitudeareas), (self.walls, self.doors,),
                     self.restricted_spaces_indoors.values(), self.restricted_spaces_outdoors.values(), self.ramps,
                     (geom for altitude, geom in self.short_walls))

    def create_hybrid_geometries(self, face_centers):  # called on the final thing
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
        vertex_value_mask = np.full(self.vertices.shape[:1], fill_value=False, dtype=bool)

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
