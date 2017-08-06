import json

from shapely.geometry import mapping


def polygon_scad(polygon):
    return 'polygon(points='+json.dumps(mapping(polygon)['coordinates'][0], separators=(',', ':'))+')'
