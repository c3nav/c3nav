import json
from collections import OrderedDict

from shapely.geometry import Polygon


def _preencode(data, magic_marker, in_coords=False):
    if isinstance(data, dict):
        data = data.copy()
        for name, value in tuple(data.items()):
            if name in ('bounds', ):
                data[name] = magic_marker+json.dumps(value)+magic_marker
            else:
                data[name] = _preencode(value, magic_marker, in_coords=(name == 'coordinates'))
        return data
    elif isinstance(data, (tuple, list)):
        if in_coords and len(data) == 2 and isinstance(data[0], (int, float)) and isinstance(data[1], (int, float)):
            return magic_marker+json.dumps(data)+magic_marker
        else:
            return tuple(_preencode(value, magic_marker, in_coords) for value in data)
    else:
        return data


def json_encoder_reindent(method, data, *args, **kwargs):
    magic_marker = '***JSON_MAGIC_MARKER***'
    test_encode = json.dumps(data)
    while magic_marker in test_encode:
        magic_marker += '*'
    result = method(_preencode(data, magic_marker), *args, **kwargs)
    if type(result) == str:
        return result.replace('"'+magic_marker, '').replace(magic_marker+'"', '')
    else:
        magic_marker = magic_marker.encode()
        return result.replace(b'"'+magic_marker, b'').replace(magic_marker+b'"', b'')


def format_geojson(data, round=True):
    return OrderedDict((
        ('type', data['type']),
        ('coordinates', round_coordinates(data['coordinates']) if round else data['coordinates']),
    ))


def round_coordinates(data):
    if isinstance(data, (list, tuple)):
        return tuple(round_coordinates(item) for item in data)
    else:
        return round(data, 2)


def clean_geometry(geometry):
    """
    if the given geometry is a Polygon and invalid, try to make it valid if it results in a Polygon (not MultiPolygon)
    """
    if geometry.is_valid:
        return geometry

    if isinstance(geometry, Polygon):
        p = Polygon(list(geometry.exterior.coords))
        for interior in geometry.interiors:
            p = p.difference(Polygon(list(interior.coords)))

        if isinstance(p, Polygon) and p.is_valid:
            return p

    return geometry
