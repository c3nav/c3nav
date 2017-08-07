import json
from decimal import Decimal

from shapely.geometry import mapping

from c3nav.mapdata.utils.geometry import assert_multipolygon


def polygon_scad(polygon, height):
    results = [_polygon_scad(polygon, height=height) for polygon in assert_multipolygon(polygon)]
    if not results:
        raise ValueError
    if len(results) == 1:
        return results[0]
    return 'union() {\n'+add_indent(''.join(results))+'}\n'


def _polygon_scad(polygon, height):
    coords = mapping(polygon.simplify(0.001))['coordinates']

    exterior = coords[0]
    interiors = coords[1:]
    result = 'linear_extrude(height=%.2f, center=false, convexity=20) ' % height
    result += _ring_scad(exterior)
    if interiors:
        result = 'difference() {\n'+add_indent(result)
        result += '    translate([0, 0, -0.01]) {\n'
        for ring in interiors:
            result += '        linear_extrude(height=%.2f, center=false, convexity=20) ' % (height+Decimal('0.02'))
            result += _ring_scad(ring)
        result += '    }\n'
        result += '}\n'
    return result


def _ring_scad(coords):
    return 'polygon(points='+json.dumps(coords[:-1], separators=(',', ':'))+', convexity=20);\n'


def add_indent(text):
    return '    '+text.replace('\n', '\n    ')[:(-4 if text.endswith('\n') else None)]
