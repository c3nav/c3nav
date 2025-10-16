import re
from operator import attrgetter

from shapely import prepared
from shapely.affinity import scale
from shapely.geometry import JOIN_STYLE, LineString, Point
from shapely.ops import unary_union

from c3nav.mapdata.render.engines import register_engine
from c3nav.mapdata.render.engines.base3d import Base3DEngine
from c3nav.mapdata.render.utils import get_full_levels, get_main_levels
from c3nav.mapdata.utils.geometry.inspect import assert_multipolygon


@register_engine
class BlenderEngine(Base3DEngine):
    filetype = 'blend.py'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.result = ''
        self._add_python('''
            import bpy
            import bmesh

            def deselect_all():
                bpy.ops.object.select_all(action='DESELECT')

            def select_object(obj):
                deselect_all()
                obj.select = True
                bpy.context.scene.objects.active = obj

            def triangulate_object(obj):
                me = obj.data
                bm = bmesh.from_edit_mesh(me)
                bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method=0, ngon_method=0)
                bmesh.update_edit_mesh(me, True)

            def clone_object(obj):
                new_obj = obj.copy()
                new_obj.data = obj.data.copy()
                scene = bpy.context.scene
                scene.objects.link(new_obj)
                return new_obj

            def extrude_object(obj, height):
                select_object(obj)
                bpy.ops.object.mode_set(mode='EDIT')
                triangulate_object(obj)
                bpy.ops.mesh.select_mode(type='FACE')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.extrude_region_move(
                    TRANSFORM_OT_translate={'value': (0, 0, height)}
                )
                triangulate_object(obj)
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.normals_make_consistent(inside=False)
                bpy.ops.object.mode_set(mode='OBJECT')

            def subtract_object(obj, other_obj, delete_after=False):
                select_object(obj)
                bpy.ops.object.modifier_add(type='BOOLEAN')
                mod = obj.modifiers
                mod[0].name = 'Difference'
                mod[0].operation = 'DIFFERENCE'
                mod[0].object = other_obj
                mod[0].solver = 'CARVE'
                bpy.ops.object.modifier_apply(apply_as='DATA', modifier=mod[0].name)
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.normals_make_consistent()
                bpy.ops.mesh.dissolve_limited()
                triangulate_object(obj)
                bpy.ops.object.mode_set(mode='OBJECT')
                if delete_after:
                    delete_object(other_obj)

            def join_objects(objs):
                obj = objs[0]
                other_objs = objs[1:]
                for other_obj in other_objs:
                    select_object(obj)
                    bpy.ops.object.modifier_add(type='BOOLEAN')
                    mod = obj.modifiers
                    mod[0].name = 'Union'
                    mod[0].operation = 'UNION'
                    mod[0].object = other_obj
                    mod[0].solver = 'CARVE'
                    bpy.ops.object.modifier_apply(apply_as='DATA', modifier=mod[0].name)
                    delete_object(other_obj)
                return obj

            def delete_object(obj):
                select_object(obj)
                bpy.ops.object.delete()

            def add_polygon(name, exterior, interiors, minz, maxz):
                if bpy.context.object:
                    bpy.ops.object.mode_set(mode='OBJECT')
                deselect_all()
                exterior = add_ring(name, exterior, minz, maxz)
                all_interiors = []
                for i, interior_coords in enumerate(interiors):
                    interior = add_ring('%s interior %d' % (name, i), interior_coords, minz-1, maxz+1)
                    all_interiors.append(interior)
                if all_interiors:
                    joined_interiors = join_objects(all_interiors)
                    subtract_object(exterior, joined_interiors, delete_after=True)
                return exterior

            def add_ring(name, coords, minz, maxz):
                if coords[0] == coords[-1]:
                    coords = coords[:-1]
                if len(coords) < 3:
                    raise ValueError('Ring with less than 3 points.')

                # create ring
                indices = tuple(range(len(coords)))
                mesh = bpy.data.meshes.new(name=name)
                mesh.from_pydata(
                    tuple((x, y, minz) for x, y in coords),
                    (),
                    (indices, ),
                )

                # add ring to scene
                obj = bpy.data.objects.new(name, mesh)
                scene = bpy.context.scene
                scene.objects.link(obj)

                # extrude it
                extrude_object(obj, maxz-minz)

                return obj

            def add_polygon_3d(name, coords, extrude):
                if coords[0] == coords[-1]:
                    coords = coords[:-1]
                if len(coords) < 3:
                    raise ValueError('Ring with less than 3 points.')

                if bpy.context.object:
                    bpy.ops.object.mode_set(mode='OBJECT')
                deselect_all()

                # create ring
                indices = tuple(range(len(coords)))
                mesh = bpy.data.meshes.new(name=name)
                mesh.from_pydata(
                    coords,
                    (),
                    (indices, ),
                )

                # add ring to scene
                obj = bpy.data.objects.new(name, mesh)
                scene = bpy.context.scene
                scene.objects.link(obj)

                ## extrude it
                extrude_object(obj, extrude)
                return obj

            def add_mesh(name, vertices, faces):
                # create mesh
                mesh = bpy.data.meshes.new(name=name)
                mesh.from_pydata(
                    vertices,
                    (),
                    faces,
                )

                # add mesh to scene
                obj = bpy.data.objects.new(name, mesh)
                scene = bpy.context.scene
                scene.objects.link(obj)
                return obj

            def cut_using_mesh_planes(obj, bottom_mesh_plane, top_mesh_plane, height):
                height = abs(height)
                bottom_obj = clone_object(bottom_mesh_plane)
                extrude_object(bottom_obj, -height)
                subtract_object(obj, bottom_obj, delete_after=True)
                top_obj = clone_object(top_mesh_plane)
                extrude_object(top_obj, height)
                subtract_object(obj, top_obj, delete_after=True)

            main_object = None
            polygons_for_join = []
            last_mesh_plane = None
            current_mesh_plane = None
        ''')

    def _clean_python(self, code):
        if '\t' in code:
            raise ValueError('Tabulators in code')
        code = re.sub(r'^( *\n)*', '', code)
        whitespaces = re.match('^ *', code)
        code = re.sub(r'^%s' % whitespaces.group(0), '', code, flags=re.MULTILINE)
        code = re.sub(r'^ +$', '', code, flags=re.MULTILINE)
        code = re.sub(r' +$', '', code)
        return code

    def _add_python(self, code):
        self.result += self._clean_python(code)+'\n'

    def custom_render(self, level_render_data, access_permissions, full_levels):
        if full_levels:
            levels = get_full_levels(level_render_data)
        else:
            levels = get_main_levels(level_render_data)

        buildings = None

        last_lower_bound = None
        for geoms in reversed(levels):
            if geoms.on_top_of_id is not None:
                continue

            altitudes = [geoms.base_altitude]
            for altitudearea in geoms.altitudeareas:
                altitudes.append(altitudearea.altitude)
                if altitudearea.altitude2 is not None:
                    altitudes.append(altitudearea.altitude2)

            if last_lower_bound is None:
                altitude = max(altitudes)
                height = max((height for (geometry, height) in geoms.heightareas), default=geoms.default_height)
                last_lower_bound = altitude+height

            geoms.upper_bound = last_lower_bound
            geoms.lower_bound = min(altitudes)-700
            last_lower_bound = geoms.lower_bound

        current_upper_bound = last_lower_bound
        for geoms in levels:
            # hide indoor and outdoor rooms if their access restriction was not unlocked
            restricted_spaces_indoors = unary_union(
                tuple(area.geom for access_restriction, area in geoms.restricted_spaces_indoors.items()
                      if access_restriction not in access_permissions)
            )
            restricted_spaces_outdoors = unary_union(
                tuple(area.geom for access_restriction, area in geoms.restricted_spaces_outdoors.items()
                      if access_restriction not in access_permissions)
            )
            restricted_spaces = unary_union((restricted_spaces_indoors, restricted_spaces_outdoors))  # noqa

            # crop altitudeareas
            for altitudearea in geoms.altitudeareas:
                altitudearea.geometry = altitudearea.geometry.geom.difference(restricted_spaces)
                altitudearea.geometry_prep = prepared.prep(altitudearea.geometry)

            # crop heightareas
            new_heightareas = []
            for geometry, height in geoms.heightareas:
                geometry = geometry.geom.difference(restricted_spaces)
                geometry_prep = prepared.prep(geometry)
                new_heightareas.append((geometry, geometry_prep, height))
            geoms.heightareas = new_heightareas

            if geoms.on_top_of_id is None:
                buildings = geoms.buildings
                current_upper_bound = geoms.upper_bound

                holes = geoms.holes.difference(restricted_spaces)
                buildings = buildings.difference(holes)

                self._add_polygon('Level %s' % geoms.level_index, buildings,
                                  geoms.lower_bound, geoms.upper_bound)
                self._set_last_polygon_to_main()

            for altitudearea in sorted(geoms.altitudeareas, key=attrgetter('altitude')):
                name = 'Level %s Altitudearea %s' % (geoms.short_label, altitudearea.altitude)
                geometry = altitudearea.geometry.buffer(0)
                inside_geometry = geometry.intersection(buildings).buffer(0).buffer(0.01, join_style=JOIN_STYLE.mitre)
                outside_geometry = geometry.difference(buildings).buffer(0).buffer(0.01, join_style=JOIN_STYLE.mitre)

                if not inside_geometry.is_empty:
                    if altitudearea.altitude2 is not None:
                        self._debug('slope start')
                        min_slope_altitude = min(altitudearea.altitude, altitudearea.altitude2)
                        self._add_polygon(name, inside_geometry, min_slope_altitude-10, current_upper_bound+1000)
                        bounds = inside_geometry.bounds
                        self._add_slope(bounds, altitudearea.altitude-10, altitudearea.altitude2-10,
                                        altitudearea.point1, altitudearea.point2, bottom=True)
                        self._subtract_slope()
                        self._debug('slope continue')
                        self._subtract_last_polygon_from_main()
                        self._debug('slope end')
                    else:
                        if altitudearea.altitude < current_upper_bound:
                            self._add_polygon(name, inside_geometry,
                                              altitudearea.altitude, current_upper_bound+1000)
                            self._subtract_last_polygon_from_main()

                if not outside_geometry.is_empty:
                    if altitudearea.altitude2 is not None:
                        pass  # todo
                    else:
                        if altitudearea.altitude > current_upper_bound:
                            lower = altitudearea.altitude-700
                            if lower == current_upper_bound:
                                lower -= 10
                            self._add_polygon(name, outside_geometry,
                                              lower, altitudearea.altitude)

        self._add_python('''
            if last_mesh_plane:
                delete_object(last_mesh_plane)
            if current_mesh_plane:
                delete_object(current_mesh_plane)''')

    def _add_polygon(self, name, geometry, minz, maxz):
        geometry = geometry.buffer(0)
        self._add_python('sub_polygons = []')
        for polygon in assert_multipolygon(geometry):
            self._add_python(
                'sub_polygons.append(add_polygon(name=%(name)r, exterior=%(exterior)r, interiors=%(interiors)r, '
                'minz=%(minz)f, maxz=%(maxz)f))' % {
                    'name': name,
                    'exterior': tuple(polygon.exterior.coords),
                    'interiors': tuple(tuple(interior.coords) for interior in polygon.interiors),
                    'minz': minz/1000,
                    'maxz': maxz/1000,
                }
            )
        self._add_python('last_polygon = sub_polygons[0]')
        self._add_python('join_objects(sub_polygons)')

    def _add_slope(self, bounds, altitude1, altitude2, point1, point2, bottom=False):
        altitude_diff = altitude2-altitude1
        altitude_middle = (altitude1+altitude2)/2
        altitude_halfdiff = altitude_diff/2
        altitude_base = altitude1
        line = LineString([point1, point2])

        minx, miny, maxx, maxy = bounds
        points_2d = [(minx-100, miny-100), (maxx+100, miny-100), (maxx+100, maxy+100), (minx-100, maxy+100)]
        points_3d = []
        for i, (x, y) in enumerate(points_2d):
            point = Point((x, y))
            pos = line.project(point)
            while pos <= 0 or pos >= line.length-1:
                line = scale(line, xfact=2, yfact=2, zfact=2)
                altitude_diff *= 2
                altitude_halfdiff *= 2
                altitude_base = altitude_middle-altitude_halfdiff
                pos = line.project(point)
            z = ((pos/line.length)*altitude_diff)+altitude_base
            points_3d.append((x, y, z/1000))

        extrude = abs(altitude1-altitude2)/1000+100
        if bottom:
            extrude = -extrude
        self._add_python(
            'last_slope = add_polygon_3d(name=%(name)r, coords=%(coords)r, extrude=%(extrude)f)' % {
                'name': 'tmpslope',
                'coords': tuple(points_3d),
                'extrude': extrude,
            }
        )

    def _add_mesh_plane(self, name, vertices, faces):
        self._add_python('''
            if last_mesh_plane:
                delete_object(last_mesh_plane)''')
        self._add_python('last_mesh_plane = current_mesh_plane')
        self._add_python(
            'current_mesh_plane = add_mesh(name=%(name)r, vertices=%(vertices)r, faces=%(faces)r)' % {
                'name': name,
                'vertices': vertices.tolist(),
                'faces': faces.tolist(),
            }
        )

    def _cut_last_poly_with_mesh_planes(self, minz, maxz):
        height = maxz-minz
        self._add_python('cut_using_mesh_planes(last_polygon, last_mesh_plane, current_mesh_plane, %f)' % (height/1000))

    def _subtract_slope(self):
        self._add_python('subtract_object(last_polygon, last_slope, delete_after=True)')

    def _set_last_polygon_to_main(self):
        self._add_python('main_object = last_polygon')

    def _subtract_last_polygon_from_main(self):
        self._add_python('subtract_object(main_object, last_polygon, delete_after=True)')
        self._add_python('last_polygon = main_object')

    def _collect_last_polygon_for_join(self):
        self._add_python('polygons_for_join.append(last_polygon)')

    def _clear_polygons_for_join(self):
        self._add_python('polygons_for_join = []')

    def _join_polygons(self):
        self._add_python('join_objects(polygons_for_join)')
        self._add_python('last_polygon = polygons_for_join[0]')
        self._clear_polygons_for_join()

    def _debug(self, message):
        self._add_python('print(%r)' % message)

    def render(self, filename=None):
        return self.result.encode()
