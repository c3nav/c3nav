import json
from itertools import chain

from shapely.geometry import mapping

from c3nav.mapdata.utils.geometry import assert_multipolygon


def polygon_scad(polygon):
    results = [_polygon_scad(polygon) for polygon in assert_multipolygon(polygon)]
    if not results:
        raise ValueError
    if len(results) == 1:
        return results[0]
    return '{ '+'; '.join(results)+'; }'


def _polygon_scad(polygon):
    coords = mapping(polygon)['coordinates']
    result = 'polygon(points='+json.dumps(tuple(chain(*coords)), separators=(',', ':'))
    if len(coords) > 1:
        paths = []
        start = 0
        for subcoords in coords:
            paths.append(tuple(range(start, len(subcoords))))
            start += len(subcoords)
        result += ', paths='+json.dumps(paths, separators=(',', ':'))
    result += ', convexity=20)'
    return result
