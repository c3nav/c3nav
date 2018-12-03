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
            def add_polygon(exterior, interiors, minz, maxz):
                add_ring(exterior, minz, maxz)

            def add_ring(coords, minz, maxz):
                if coords[0] == coords[-1]:
                    coords = coords[:-1]
                if len(coords) < 3:
                    raise ValueError('Ring with less than 3 points.')
                indices = tuple(range(len(coords)))
                mesh = bpy.data.meshes.new(name='Test')
                mesh.from_pydata(
                    tuple((x, y, minz) for x, y in coords),
                    tuple(zip(indices, indices[1:]+(0, ))),
                    (indices, ),
                )
                obj = bpy.data.objects.new('Test', mesh)
                scene = bpy.context.scene
                scene.objects.link(obj)
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
        print(min_altitude)
        for level in levels:
            print(level)

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
                self._add_polygon(altitudearea.geometry.geom)
                break

            break

    def _add_polygon(self, geometry):
        for polygon in assert_multipolygon(geometry):
            self._add_python('add_polygon(exterior=%(exterior)r, interiors=%(interiors)r, minz=0, maxz=1)' % {
                'exterior': tuple(polygon.exterior.coords),
                'interiors': tuple(tuple(interior.coords) for interior in polygon.interiors),
            })
            continue

    def render(self, filename=None):
        return self.result.encode()
