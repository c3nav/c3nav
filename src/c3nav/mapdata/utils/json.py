import json

from django.core.serializers.json import DjangoJSONEncoder


def _preencode(data, magic_marker, in_coords=False, in_groups=False):
    if isinstance(data, dict):
        data = data.copy()
        for name, value in tuple(data.items()):
            if name in ('bounds', 'point', 'locations') and isinstance(value, (tuple, list)):
                data[name] = magic_marker+json.dumps(value, cls=DjangoJSONEncoder)+magic_marker
            else:
                data[name] = _preencode(value, magic_marker,
                                        in_coords=(name == 'coordinates'), in_groups=(name == 'groups'))
        return data
    elif isinstance(data, (tuple, list)):
        if (in_coords and data and isinstance(data[0], (int, float))) or in_groups:
            return magic_marker+json.dumps(data, cls=DjangoJSONEncoder)+magic_marker
        else:
            return tuple(_preencode(value, magic_marker, in_coords) for value in data)
    else:
        return data


def json_encoder_reindent(method, data, *args, **kwargs):
    magic_marker = '***JSON_MAGIC_MARKER***'
    test_encode = json.dumps(data, cls=DjangoJSONEncoder)
    while magic_marker in test_encode:
        magic_marker += '*'
    result = method(_preencode(data, magic_marker), *args, **kwargs)
    if type(result) == str:
        return result.replace('"'+magic_marker, '').replace(magic_marker+'"', '')
    else:
        magic_marker = magic_marker.encode()
        return result.replace(b'"'+magic_marker, b'').replace(magic_marker+b'"', b'')


def format_geojson(data):
    # todo: get rid of all of this
    coordinates = data.get('coordinates', None)
    if coordinates is not None:
        if data['type'] == 'Point':
            pass
        elif data['type'] == 'LineString' or data['type'] == 'MultiPoint':
            pass
        elif data['type'] == 'MultiLineString':
            pass
        elif data['type'] == 'Polygon':
            if not coordinates:
                data['type'] = 'MultiPolygon'
        elif data['type'] == 'MultiPolygon':
            pass
        else:
            raise ValueError('Unknown geojson type: %s' % data['type'])
        return {
            'type': data['type'],
            'coordinates': coordinates,
        }
    return {
        'type': data['type'],
        'geometries': [format_geojson(geometry) for geometry in data['geometries']],
    }


