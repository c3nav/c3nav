import re

from shapely.affinity import scale
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from c3nav.mapdata.render.engines import register_engine
from c3nav.mapdata.render.engines.base3d import Base3DEngine
from c3nav.mapdata.render.utils import get_full_levels, get_min_altitude
from c3nav.mapdata.utils.geometry import assert_multipolygon


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
                bpy.ops.mesh.normals_make_consistent()
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
                    tuple(zip(indices, indices[1:]+(0, ))),
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
                    tuple(zip(indices, indices[1:]+(0, ))),
                    (indices, ),
                )

                # add ring to scene
                obj = bpy.data.objects.new(name, mesh)
                scene = bpy.context.scene
                scene.objects.link(obj)

                ## extrude it
                extrude_object(obj, extrude)
                return obj

            polygons_for_join = []
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

    def custom_render(self, level_render_data, bbox, access_permissions):
        levels = get_full_levels(level_render_data)
        min_altitude = get_min_altitude(levels, default=level_render_data.base_altitude)

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

            for altitudearea in geoms.altitudeareas:
                name = 'Level %s Altitudearea %s' % (geoms.short_label, altitudearea.altitude)
                if altitudearea.altitude2 is not None:
                    min_slope_altitude = min(altitudearea.altitude, altitudearea.altitude2)
                    max_slope_altitude = max(altitudearea.altitude, altitudearea.altitude2)
                    self._add_polygon(name, altitudearea.geometry.geom, min_slope_altitude, max_slope_altitude)
                    bounds = altitudearea.geometry.geom.bounds
                    self._add_slope(bounds, altitudearea.altitude, altitudearea.altitude2,
                                    altitudearea.point1, altitudearea.point2)
                    self._subtract_slope()
                    self._collect_last_polygon_for_join()
                    self._add_polygon(name, altitudearea.geometry.geom, min_altitude-700, min_slope_altitude)
                    self._collect_last_polygon_for_join()
                    self._join_polygons()
                else:
                    self._add_polygon(name, altitudearea.geometry.geom, min_altitude-700, altitudearea.altitude)

            break

    def _add_polygon(self, name, geometry, minz, maxz):
        geometry = geometry.buffer(0)
        for polygon in assert_multipolygon(geometry):
            self._add_python(
                'last_polygon = add_polygon(name=%(name)r, exterior=%(exterior)r, interiors=%(interiors)r, '
                'minz=%(minz)f, maxz=%(maxz)f)' % {
                    'name': name,
                    'exterior': tuple(polygon.exterior.coords),
                    'interiors': tuple(tuple(interior.coords) for interior in polygon.interiors),
                    'minz': minz/1000,
                    'maxz': maxz/1000,
                }
            )

    def _add_slope(self, bounds, altitude1, altitude2, point1, point2):
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

        self._add_python(
            'last_slope = add_polygon_3d(name=%(name)r, coords=%(coords)r, extrude=%(extrude)f)' % {
                'name': 'tmpslope',
                'coords': tuple(points_3d),
                'extrude': abs(altitude1-altitude2)/1000+1,
            }
        )

    def _subtract_slope(self):
        self._add_python('subtract_object(last_polygon, last_slope, delete_after=True)')

    def _collect_last_polygon_for_join(self):
        self._add_python('polygons_for_join.append(last_polygon)')

    def _clear_polygons_for_join(self):
        self._add_python('polygons_for_join = []')

    def _join_polygons(self):
        self._add_python('join_objects(polygons_for_join)')
        self._add_python('last_polygon = polygons_for_join[0]')
        self._clear_polygons_for_join()

    def render(self, filename=None):
        return self.result.encode()
