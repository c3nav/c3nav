import re

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
                bpy.ops.object.mode_set(mode='OBJECT')

            def subtract_object(obj, other_obj):
                select_object(obj)
                bpy.ops.object.modifier_add(type='BOOLEAN')
                mod = obj.modifiers
                mod[0].name = 'Difference'
                mod[0].operation = 'DIFFERENCE'
                mod[0].object = other_obj
                bpy.ops.object.modifier_apply(apply_as='DATA', modifier=mod[0].name)

            def delete_object(obj):
                select_object(obj)
                bpy.ops.object.delete()

            def add_polygon(name, exterior, interiors, minz, maxz):
                if bpy.context.object:
                    bpy.ops.object.mode_set(mode='OBJECT')
                deselect_all()
                exterior = add_ring(name, exterior, minz, maxz)
                for i, interior_coords in enumerate(interiors):
                    interior = add_ring('%s interior %d' % (name, i), interior_coords, minz-1, maxz+1)
                    subtract_object(exterior, interior)
                    delete_object(interior)

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
                self._add_polygon(name, altitudearea.geometry.geom, min_altitude-1, altitudearea.altitude)

            break

    def _add_polygon(self, name, geometry, minz, maxz):
        for polygon in assert_multipolygon(geometry):
            self._add_python(
                'add_polygon(name=%(name)r, exterior=%(exterior)r, interiors=%(interiors)r, '
                'minz=%(minz)f, maxz=%(maxz)f)' % {
                    'name': name,
                    'exterior': tuple(polygon.exterior.coords),
                    'interiors': tuple(tuple(interior.coords) for interior in polygon.interiors),
                    'minz': minz/1000,
                    'maxz': maxz/1000,
                }
            )

    def render(self, filename=None):
        return self.result.encode()
